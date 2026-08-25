{-# LANGUAGE DeriveGeneric #-}

module Amendment where

import           Data.Aeson        (ToJSON)
import           Data.Function     ((&))
import           Data.List         (isInfixOf, isPrefixOf, isSubsequenceOf, nub, sort)
import           Data.Maybe        (isNothing)
import           Data.String.Utils (split, splitWs)
import           Data.Time         (Day, defaultTimeLocale, parseTimeM)
import           GHC.Generics
import           Prelude.Unicode
import           Provenance
import           StringOps
import           Text.Read         (readMaybe)
import           Text.Regex.TDFA

data Amendment =
  Amendment {
    affectedSections ∷ ChangeSet,
    bill             ∷ Bill,
    chapter          ∷ Integer,
    summary          ∷ Maybe String,
    effectiveDate    ∷ Day,
    year             ∷ Integer,
    validation       ∷ Validation,
    provenance       ∷ Provenance
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
  | Incomplete
  deriving (Eq, Show, Generic)

data Validation =
  Validation {
    validationStatus ∷ ValidationStatus,
    titleBodyMatch   ∷ Bool,
    titleSections    ∷ ChangeSet,
    bodySections     ∷ ChangeSet
  } deriving (Eq, Show, Generic)

data ParseErrorCode
  = MissingCitation
  | InvalidCitation
  | MissingYear
  | MissingChapter
  | MissingEffectiveDate
  | ExtractionFailed
  deriving (Eq, Show, Generic)

data ParseError =
  ParseError {
    parseErrorCode    ∷ ParseErrorCode,
    parseErrorField   ∷ Maybe String,
    parseErrorMessage ∷ String
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
instance ToJSON ParseError
instance ToJSON ParseErrorCode

emptyChangeSet ∷ ChangeSet
emptyChangeSet = ChangeSet { amended = [], repealed = [] }

makeBill ∷ String → Maybe Bill
makeBill citation =
  case splitWs citation of
    [chamber, number] -> do
      parsedType ← readMaybe chamber
      parsedNumber ← readMaybe number
      pure Bill { billType = parsedType, billNumber = parsedNumber }
    _ -> Nothing

findCitation ∷ [String] → Maybe String
findCitation phrases =
  phrases
    & join
    & firstMatch "(HB|SB) [0-9]+"

findYear ∷ [String] → Maybe Integer
findYear input = do
  matched ← input
    & join
    & firstMatch "OREGON LAWS [0-9]{4}"
  case splitWs matched of
    [] -> Nothing
    xs -> readMaybe (last xs)

findChapter ∷ [String] → Maybe Integer
findChapter phrases = do
  matched ← phrases
    & join
    & firstMatch "Chap. [0-9]{1,3}"
  case splitWs matched of
    [] -> Nothing
    xs -> readMaybe (last xs)

findEffectiveDate ∷ [String] → Maybe Day
findEffectiveDate input = do
  matched ← input
    & join
    & firstMatch "Effective date .+ [0-9]+, [0-9]{4}"
  parseTimeM True defaultTimeLocale "Effective date %B %-d, %Y" matched

findSummary ∷ [String] → Maybe String
findSummary phrases =
  case filter isSummary phrases of
    [aSummary] → Just (cleanUp aSummary)
    _          → Nothing

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
    Just marker -> sectionNumbers (beforeMarker marker block)
    Nothing     -> []

firstPresentMarker ∷ [String] → String → Maybe String
firstPresentMarker [] _ = Nothing
firstPresentMarker (marker:rest) input
  | marker `isInfixOf` input = Just marker
  | otherwise                = firstPresentMarker rest input

beforeMarker ∷ String → String → String
beforeMarker marker input =
  case split marker input of
    (prefix:_) -> prefix
    []         -> input

-- Reconcile independent title and operative-body parsers.
reconcileChangeSets ∷ ChangeSet → ChangeSet → Validation
reconcileChangeSets titleChanges bodyChanges =
  let same = titleChanges == bodyChanges
      bothEmpty = titleChanges == emptyChangeSet && bodyChanges == emptyChangeSet
      status
        | bothEmpty = Incomplete
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

parseAmendment ∷ Provenance → [String] → Either [ParseError] Amendment
parseAmendment sourceProvenance phrases =
  let citation = findCitation phrases
      parsedBill = citation >>= makeBill
      parsedYear = findYear phrases
      parsedChapter = findChapter phrases
      parsedEffectiveDate = findEffectiveDate phrases
      summaryText = findSummary phrases
      titleChanges = maybe emptyChangeSet findChangedStatutes summaryText
      bodyChanges = findBodyChangedStatutes phrases
      errors =
        concat
          [ missingError MissingCitation "bill" "Could not find an HB/SB citation" (isNothing citation)
          , invalidCitationError citation parsedBill
          , missingError MissingYear "year" "Could not find the Oregon Laws year" (isNothing parsedYear)
          , missingError MissingChapter "chapter" "Could not find the Oregon Laws chapter" (isNothing parsedChapter)
          , missingError MissingEffectiveDate "effectiveDate" "Could not parse the effective date" (isNothing parsedEffectiveDate)
          ]
  in case (parsedBill, parsedYear, parsedEffectiveDate, parsedChapter) of
    (Just billValue, Just yearValue, Just effectiveDateValue, Just chapterValue)
      | null errors -> Right Amendment {
          bill = billValue,
          summary = summaryText,
          affectedSections = selectBestChangeSet titleChanges bodyChanges,
          year = yearValue,
          effectiveDate = effectiveDateValue,
          chapter = chapterValue,
          validation = reconcileChangeSets titleChanges bodyChanges,
          provenance = sourceProvenance
        }
    _ -> Left errors

missingError ∷ ParseErrorCode → String → String → Bool → [ParseError]
missingError code field message isMissing
  | isMissing = [ParseError code (Just field) message]
  | otherwise = []

invalidCitationError ∷ Maybe String → Maybe Bill → [ParseError]
invalidCitationError (Just citation) Nothing =
  [ParseError InvalidCitation (Just "bill") ("Could not parse citation: " ++ citation)]
invalidCitationError _ _ = []

sectionNumbers ∷ String → [String]
sectionNumbers phrase =
  -- Match ORS section numbers like 40.230, 743A.144, and 475C.770.
  getAllTextMatches (phrase =~ "[0-9]{1,3}[A-Z]?\\.[0-9]{3}")

flatten = concat
unique = nub
