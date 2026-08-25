{-# LANGUAGE DeriveGeneric #-}

module Amendment where

import           Data.Aeson        (ToJSON)
import           Data.Function     ((&))
import           Data.List         (isInfixOf, isPrefixOf, isSubsequenceOf, nub, sort)
import           Data.Maybe        (isNothing)
import           Data.String.Utils (split, splitWs)
import           Data.Time         (Day, defaultTimeLocale, parseTimeM)
import           GHC.Generics
import           Provenance
import           StringOps
import           Text.Read         (readMaybe)
import           Text.Regex.TDFA

data Amendment = Amendment { affectedSections ∷ ChangeSet, bill ∷ Bill, chapter ∷ Integer, summary ∷ Maybe String, effectiveDate ∷ Day, year ∷ Integer, validation ∷ Validation, provenance ∷ Provenance } deriving (Show, Generic)
data ChangeSet = ChangeSet { amended ∷ [SectionNumber], repealed ∷ [SectionNumber] } deriving (Eq, Show, Generic)
data ChangeAction = AmendmentAction | RepealAction deriving (Eq, Show, Generic)
data EvidenceSource = TitleEvidence | OperativeBodyEvidence deriving (Eq, Show, Generic)
data SectionEvidence = SectionEvidence { evidenceSectionNumber ∷ SectionNumber, evidenceAction ∷ ChangeAction, evidenceSource ∷ EvidenceSource, evidenceSectionClause ∷ Maybe String, evidenceText ∷ String } deriving (Eq, Show, Generic)
data ValidationStatus = Verified | ParsedUnverified | Conflict | Incomplete deriving (Eq, Show, Generic)
data Validation = Validation { validationStatus ∷ ValidationStatus, titleBodyMatch ∷ Bool, titleSections ∷ ChangeSet, bodySections ∷ ChangeSet, sectionEvidence ∷ [SectionEvidence] } deriving (Eq, Show, Generic)
data ParseErrorCode = MissingCitation | InvalidCitation | MissingYear | MissingChapter | MissingEffectiveDate | ExtractionFailed deriving (Eq, Show, Generic)
data ParseError = ParseError { parseErrorCode ∷ ParseErrorCode, parseErrorField ∷ Maybe String, parseErrorMessage ∷ String } deriving (Eq, Show, Generic)
type SectionNumber = String
data Bill = Bill { billType ∷ BillType, billNumber ∷ Integer } deriving (Show, Eq, Generic)
data BillType = HB | SB deriving (Read, Show, Eq, Generic)

instance ToJSON Amendment
instance ToJSON Bill
instance ToJSON BillType
instance ToJSON ChangeSet
instance ToJSON ChangeAction
instance ToJSON EvidenceSource
instance ToJSON SectionEvidence
instance ToJSON Validation
instance ToJSON ValidationStatus
instance ToJSON ParseError
instance ToJSON ParseErrorCode

emptyChangeSet ∷ ChangeSet
emptyChangeSet = ChangeSet { amended = [], repealed = [] }

makeBill ∷ String → Maybe Bill
makeBill citation = case splitWs citation of
  [chamber, number] -> do parsedType ← readMaybe chamber; parsedNumber ← readMaybe number; pure Bill { billType = parsedType, billNumber = parsedNumber }
  _ -> Nothing

findCitation ∷ [String] → Maybe String
findCitation phrases = phrases & join & firstMatch "(HB|SB) [0-9]+"

findYear ∷ [String] → Maybe Integer
findYear input = do
  matched ← input & join & firstMatch "(OREGON LAWS|Oregon Laws) [0-9]{4}"
  case splitWs matched of [] -> Nothing; xs -> readMaybe (last xs)

findChapter ∷ [String] → Maybe Integer
findChapter phrases = do
  matched ← phrases & join & firstMatch "(Chap\\.|Chapter) [0-9]{1,4}"
  case splitWs matched of [] -> Nothing; xs -> readMaybe (last xs)

findEffectiveDate ∷ [String] → Maybe Day
findEffectiveDate input = do
  matched ← input & join & firstMatch "Effective[[:space:]]+date[[:space:]]+[A-Za-z]+[[:space:]]+[0-9]{1,2},[[:space:]]+[0-9]{4}"
  parseTimeM True defaultTimeLocale "Effective date %B %-d, %Y" (unwords (splitWs matched))

findSummary ∷ [String] → Maybe String
findSummary phrases = case filter isSummary phrases of [aSummary] → Just (cleanUp aSummary); _ → Nothing
isSummary ∷ String → Bool
isSummary sentence = "Relating to" `isPrefixOf` sentence

findSectionNumbers ∷ [String] → [SectionNumber]
findSectionNumbers phrases = phrases & map sectionNumbers & concat & nub & sort

findChangedStatutes ∷ String → ChangeSet
findChangedStatutes title = changeSetFromEvidence (findTitleEvidence title)

findTitleEvidence ∷ String → [SectionEvidence]
findTitleEvidence title =
  let clauses = split "; " title
      evidenceFor action needle clause | needle `isSubsequenceOf` clause = map (\section -> SectionEvidence section action TitleEvidence Nothing clause) (findSectionNumbers [clause]) | otherwise = []
  in concatMap (\clause -> evidenceFor AmendmentAction "amending" clause ++ evidenceFor RepealAction "repealing" clause) clauses

findBodyChangedStatutes ∷ [String] → ChangeSet
findBodyChangedStatutes = changeSetFromEvidence . findBodyEvidence

findBodyEvidence ∷ [String] → [SectionEvidence]
findBodyEvidence phrases = let document = join phrases; sectionBlocks = drop 1 (split "SECTION " document) in concatMap evidenceFromBlock sectionBlocks

evidenceFromBlock ∷ String → [SectionEvidence]
evidenceFromBlock block = nub (primaryEvidence block ++ subsectionEvidence block)

primaryEvidence ∷ String → [SectionEvidence]
primaryEvidence block = case operativeMarker block of
  Just (action, marker) ->
    let prefix = beforeMarker marker block
        clause = firstMatch "^[0-9]+[A-Za-z]?" prefix
        excerpt = prefix ++ marker
        directOrsTarget = case firstMatch "^[0-9]+[A-Za-z]?\\.[[:space:]]*(\\([0-9]+\\)[[:space:]]*)?ORS[[:space:]]" prefix of Just _ -> True; Nothing -> False
    in if directOrsTarget then map (\section -> SectionEvidence section action OperativeBodyEvidence clause excerpt) (sectionNumbers prefix) else []
  Nothing -> []

-- Some SECTION blocks contain multiple numbered operative subclauses, e.g.
-- (1) ORS x is repealed. (2) ORS y is repealed. Parse each explicit
-- subsection target independently instead of stopping at the first marker.
subsectionEvidence ∷ String → [SectionEvidence]
subsectionEvidence block = concatMap evidenceFromSubsection (drop 1 (split ") ORS " block))
  where
    evidenceFromSubsection fragment =
      let candidate = "ORS " ++ fragment
      in case operativeMarker candidate of
          Just (action, marker) ->
            let prefix = beforeMarker marker candidate
                excerpt = prefix ++ marker
                clause = firstMatch "^[0-9]+[A-Za-z]?" block
            in map (\section -> SectionEvidence section action OperativeBodyEvidence clause excerpt) (sectionNumbers prefix)
          Nothing -> []

operativeMarker ∷ String → Maybe (ChangeAction, String)
operativeMarker block = firstMatching
  [ (AmendmentAction, " is amended to read"), (AmendmentAction, " are amended to read"), (RepealAction, " is repealed"), (RepealAction, " are repealed") ]
  where firstMatching [] = Nothing; firstMatching ((action, marker):rest) | marker `isInfixOf` block = Just (action, marker) | otherwise = firstMatching rest

changeSetFromEvidence ∷ [SectionEvidence] → ChangeSet
changeSetFromEvidence evidence = ChangeSet
  { amended = evidence & filter ((== AmendmentAction) . evidenceAction) & map evidenceSectionNumber & nub & sort
  , repealed = evidence & filter ((== RepealAction) . evidenceAction) & map evidenceSectionNumber & nub & sort }

beforeMarker ∷ String → String → String
beforeMarker marker input = case split marker input of (prefix:_) -> prefix; [] -> input

reconcileChangeSets ∷ ChangeSet → ChangeSet → Validation
reconcileChangeSets titleChanges bodyChanges = reconcileChangeSetsWithEvidence titleChanges bodyChanges []

reconcileChangeSetsWithEvidence ∷ ChangeSet → ChangeSet → [SectionEvidence] → Validation
reconcileChangeSetsWithEvidence titleChanges bodyChanges evidence =
  let same = titleChanges == bodyChanges; bothEmpty = titleChanges == emptyChangeSet && bodyChanges == emptyChangeSet
      status | bothEmpty = Incomplete | same = Verified | bodyChanges == emptyChangeSet = ParsedUnverified | otherwise = Conflict
  in Validation { validationStatus = status, titleBodyMatch = same, titleSections = titleChanges, bodySections = bodyChanges, sectionEvidence = evidence }

selectBestChangeSet ∷ ChangeSet → ChangeSet → ChangeSet
selectBestChangeSet titleChanges bodyChanges | bodyChanges == emptyChangeSet = titleChanges | otherwise = bodyChanges

parseAmendment ∷ Provenance → [String] → Either [ParseError] Amendment
parseAmendment sourceProvenance phrases =
  let citation = findCitation phrases; parsedBill = citation >>= makeBill; parsedYear = findYear phrases; parsedChapter = findChapter phrases; parsedEffectiveDate = findEffectiveDate phrases
      summaryText = findSummary phrases; titleEvidence = maybe [] findTitleEvidence summaryText; bodyEvidence = findBodyEvidence phrases
      titleChanges = changeSetFromEvidence titleEvidence; bodyChanges = changeSetFromEvidence bodyEvidence; allEvidence = titleEvidence ++ bodyEvidence
      errors = concat [ missingError MissingCitation "bill" "Could not find an HB/SB citation" (isNothing citation), invalidCitationError citation parsedBill, missingError MissingYear "year" "Could not find the Oregon Laws year" (isNothing parsedYear), missingError MissingChapter "chapter" "Could not find the Oregon Laws chapter" (isNothing parsedChapter), missingError MissingEffectiveDate "effectiveDate" "Could not parse the effective date" (isNothing parsedEffectiveDate) ]
  in case (parsedBill, parsedYear, parsedEffectiveDate, parsedChapter) of
    (Just billValue, Just yearValue, Just effectiveDateValue, Just chapterValue) | null errors -> Right Amendment { bill = billValue, summary = summaryText, affectedSections = selectBestChangeSet titleChanges bodyChanges, year = yearValue, effectiveDate = effectiveDateValue, chapter = chapterValue, validation = reconcileChangeSetsWithEvidence titleChanges bodyChanges allEvidence, provenance = sourceProvenance }
    _ -> Left errors

missingError ∷ ParseErrorCode → String → String → Bool → [ParseError]
missingError code field message isMissing | isMissing = [ParseError code (Just field) message] | otherwise = []
invalidCitationError ∷ Maybe String → Maybe Bill → [ParseError]
invalidCitationError (Just citation) Nothing = [ParseError InvalidCitation (Just "bill") ("Could not parse citation: " ++ citation)]
invalidCitationError _ _ = []

sectionNumbers ∷ String → [String]
sectionNumbers phrase = getAllTextMatches (phrase =~ "[0-9]{1,3}[A-Z]?\\.[0-9]{3}")
