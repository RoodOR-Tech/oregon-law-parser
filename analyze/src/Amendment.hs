{-# LANGUAGE DeriveGeneric #-}

module Amendment where

import           Data.Aeson        (ToJSON)
import           Data.Function     ((&))
import           Data.List         (isInfixOf, isPrefixOf, isSubsequenceOf, nub, sort)
import           Data.String.Utils (split, splitWs)
import           Data.Time         (Day, defaultTimeLocale, parseTimeOrError)
import           GHC.Generics
import           Prelude.Unicode
import           StringOps
import           Text.Regex.TDFA

data Amendment =
  Amendment {
    affectedSections ∷ ChangeSet,
    bill             ∷ Bill,
    chapter          ∷ Integer,
    summary          ∷ String,
    effectiveDate    ∷ Day,
    year             ∷ Integer,
    validation       ∷ Validation
  } deriving (Show, Generic)

data ChangeSet =
  ChangeSet {
    amended  ∷ [SectionNumber],
    repealed ∷ [SectionNumber]
  } deriving (Eq, Show, Generic)

data ValidationStatus
  = Verified
  | ParsedUnverified
  | Conflict
  deriving (Eq, Show, Generic)

data Validation =
  Validation {
    validationStatus ∷ ValidationStatus,
    titleBodyMatch   ∷ Bool,
    titleSections    ∷ ChangeSet,
    bodySections     ∷ ChangeSet
  } deriving (Eq, Show, Generic)

type SectionNumber = String

data Bill =
  Bill {
    billType   ∷ BillType,
    billNumber ∷ Integer
  } deriving (Show, Eq, Generic)

data BillType = HB | SB
  deriving (Read, Show, Eq, Generic)

instance ToJSON Amendment
instance ToJSON Bill
instance ToJSON BillType
instance ToJSON ChangeSet
instance ToJSON Validation
instance ToJSON ValidationStatus

emptyChangeSet ∷ ChangeSet
emptyChangeSet = ChangeSet { amended = [], repealed = [] }

makeBill ∷ String → Bill
makeBill citation =
  let [chamber, number] = splitWs citation
  in  Bill { billType = read chamber, billNumber = read number }

findCitation ∷ [String] → String
findCitation phrases =
  let maybeMatch = phrases
        & join
        & firstMatch "(HB|SB) [0-9]+"
  in case maybeMatch of
    Just s -> s
    Nothing -> error "Could not find a citation"

findYear ∷ [String] → Integer
findYear input =
  let maybeMatch = input
        & join
        & firstMatch "OREGON LAWS [0-9]{4}"
  in case maybeMatch of
    Just s -> s
              & splitWs
              & last
              & read
    Nothing -> error "Could not find the year"

findChapter ∷ [String] → Integer
findChapter phrases =
  let maybeMatch =
        phrases
        & join
        & firstMatch "Chap. [0-9]{1,3}"
  in case maybeMatch of
    Just s -> s
              & splitWs
              & last
              & read
    Nothing -> error "Could not find the Chapter"

findEffectiveDate ∷ [String] → Day
findEffectiveDate paragraphs =
  let maybeMatch =
        paragraphs
        & join
        & firstMatch "Effective date .+ [0-9]+, [0-9]{4}"
  in case maybeMatch of
    Just s -> parseTimeOrError True defaultTimeLocale "Effective date %B %-d, %Y" s
    Nothing -> error "Could not find the Effective Date"

findSummary ∷ [String] → String
findSummary phrases =
  case filter isSummary phrases of
    [aSummary] → cleanUp aSummary
    _          → "(Summary is not available)"

isSummary ∷ String → Bool
isSummary sentence =
  "Relating to" `isPrefixOf` sentence

findSectionNumbers ∷ [String] → [SectionNumber]
findSectionNumbers phrases =
  phrases
    & map sectionNumbers
    & flatten
    & unique
    & sort

-- Parse the title/summary declaration. Kept as a secondary source of evidence.
findChangedStatutes ∷ String → ChangeSet
findChangedStatutes title =
  let clauses = split "; " title
      extractFrom section = findSectionNumbers ∘ filter (\c → section `isSubsequenceOf` c) $ clauses
  in ChangeSet {
    amended  = extractFrom "amending",
    repealed = extractFrom "repealing"
  }

-- Parse operative SECTION clauses in the enrolled/session law body.
-- Only text before the operative marker is considered, preventing ORS references
-- inside the amended statutory text from being mistaken for affected sections.
findBodyChangedStatutes ∷ [String] → ChangeSet
findBodyChangedStatutes phrases =
  let document = join phrases
      sectionBlocks = drop 1 (split "SECTION " document)
      amendedSections = extractOperativeSections [" is amended to read", " are amended to read"] sectionBlocks
      repealedSections = extractOperativeSections [" is repealed", " are repealed"] sectionBlocks
  in ChangeSet {
    amended = amendedSections,
    repealed = repealedSections
  }

extractOperativeSections ∷ [String] → [String] → [SectionNumber]
extractOperativeSections markers blocks =
  blocks
    & map (extractBlock markers)
    & flatten
    & unique
    & sort

extractBlock ∷ [String] → String → [SectionNumber]
extractBlock markers block =
  case firstPresentMarker markers block of
    Just marker -> sectionNumbers (before marker block)
    Nothing     -> []

firstPresentMarker ∷ [String] → String → Maybe String
firstPresentMarker [] _ = Nothing
firstPresentMarker (marker:rest) input
  | marker `isInfixOf` input = Just marker
  | otherwise                = firstPresentMarker rest input

before ∷ String → String → String
before marker input =
  case split marker input of
    (prefix:_) -> prefix
    []         -> input

-- Reconcile independent title and operative-body parsers.
reconcileChangeSets ∷ ChangeSet → ChangeSet → Validation
reconcileChangeSets titleChanges bodyChanges =
  let same = titleChanges == bodyChanges
      status
        | same = Verified
        | bodyChanges == emptyChangeSet = ParsedUnverified
        | otherwise = Conflict
  in Validation {
    validationStatus = status,
    titleBodyMatch = same,
    titleSections = titleChanges,
    bodySections = bodyChanges
  }

-- Prefer operative text whenever it produces evidence. The title remains a fallback
-- for legacy documents/layouts that the body parser cannot yet recognize.
selectBestChangeSet ∷ ChangeSet → ChangeSet → ChangeSet
selectBestChangeSet titleChanges bodyChanges
  | bodyChanges == emptyChangeSet = titleChanges
  | otherwise = bodyChanges

sectionNumbers ∷ String → [String]
sectionNumbers phrase =
  -- Match ORS section numbers like 40.230, 743A.144, and 475C.770.
  getAllTextMatches (phrase =~ "[0-9]{1,3}[A-Z]?\\.[0-9]{3}")

flatten = concat
unique = nub
