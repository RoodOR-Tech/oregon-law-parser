{-# LANGUAGE DeriveGeneric #-}

module Amendment where

import           Data.Aeson        (ToJSON)
import           Data.Function     ((&))
import           Data.List         (isInfixOf, isPrefixOf, minimumBy, nub, sort)
import           Data.Maybe        (isNothing)
import           Data.Ord          (comparing)
import           Data.String.Utils (split, splitWs)
import           Data.Time         (Day, addDays, defaultTimeLocale, parseTimeM)
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
data BillType = HB | SB | BallotMeasure deriving (Read, Show, Eq, Generic)

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
  ["Ballot", "Measure", "No.", number] -> do parsedNumber ← readMaybe number; pure Bill { billType = BallotMeasure, billNumber = parsedNumber }
  _ -> Nothing

findCitation ∷ [String] → Maybe String
findCitation phrases = phrases & join & firstMatch "(HB|SB) [0-9]+|Ballot Measure No\\. [0-9]+"

yearCandidates ∷ [String] → [Integer]
yearCandidates input =
  let document = join input
      headingMatches = getAllTextMatches (document =~ "(OREGON LAWS|Oregon Laws) [0-9]{4}")
      actMatches = getAllTextMatches (document =~ "(This|this) [0-9]{4} Act")
      headingYears = [yearValue | matched <- headingMatches, let tokens = splitWs matched, not (null tokens), Just yearValue <- [readMaybe (last tokens)]]
      actYears = [yearValue | matched <- actMatches, let tokens = splitWs matched, length tokens == 3, Just yearValue <- [readMaybe (tokens !! 1)]]
  in nub (headingYears ++ actYears)

findYear ∷ [String] → Maybe Integer
findYear input = case yearCandidates input of [] -> Nothing; years -> Just (maximum years)

findSourceYear ∷ Provenance → Maybe Integer
findSourceYear sourceProvenance =
  let location = case sourceUrl sourceProvenance of Just url -> url; Nothing -> sourcePath sourceProvenance
  in do
    matched ← firstMatch "[0-9]{4}([Ss][0-9]+)?[Oo][Rr][Ll]aw|[0-9]{4}adv" location
    yearText ← firstMatch "[0-9]{4}" matched
    readMaybe yearText

findYearWithProvenance ∷ Provenance → [String] → Maybe Integer
findYearWithProvenance sourceProvenance input =
  let candidates = yearCandidates input
  in case findSourceYear sourceProvenance of
      Just sourceYear | sourceYear `elem` candidates -> Just sourceYear
      _ -> case candidates of [] -> Nothing; years -> Just (maximum years)

findChapter ∷ [String] → Maybe Integer
findChapter phrases = do
  matched ← phrases & join & firstMatch "(Chap\\.|Chapter) [0-9]{1,4}"
  case splitWs matched of [] -> Nothing; xs -> readMaybe (last xs)

findSourceChapter ∷ Provenance → Maybe Integer
findSourceChapter sourceProvenance =
  let location = case sourceUrl sourceProvenance of Just url -> url; Nothing -> sourcePath sourceProvenance
  in do
    matched ← firstMatch "([Oo][Rr][Ll]aw|[Ss][0-9]+[Oo][Rr][Ll]aw|adv)[0-9]{4}" location
    chapterText ← firstMatch "[0-9]{4}" matched
    readMaybe chapterText

findChapterWithProvenance ∷ Provenance → [String] → Maybe Integer
findChapterWithProvenance sourceProvenance phrases = case findChapter phrases of
  Just chapterValue -> Just chapterValue
  Nothing -> findSourceChapter sourceProvenance

parseNamedDate ∷ String → Maybe Day
parseNamedDate matched = parseTimeM True defaultTimeLocale "%B %-d, %Y" (unwords (splitWs matched))

findDateAfter ∷ String → String → Maybe Day
findDateAfter marker document = case drop 1 (split marker document) of
  (suffix:_) -> firstMatch "[A-Za-z]+[[:space:]]+[0-9]{1,2},[[:space:]]+[0-9]{4}" suffix >>= parseNamedDate
  [] -> Nothing

findEffectiveDate ∷ [String] → Maybe Day
findEffectiveDate input =
  let document = join input
      ordinary = do
        matched ← firstMatch "Effective[[:space:]]+date[[:space:]]+[A-Za-z]+[[:space:]]+[0-9]{1,2},[[:space:]]+[0-9]{4}" document
        dateText ← firstMatch "[A-Za-z]+[[:space:]]+[0-9]{1,2},[[:space:]]+[0-9]{4}" matched
        parseNamedDate dateText
      referredAct = findDateAfter "Act takes effect" document
      referredElection = if "referred to the people" `isInfixOf` document || "submitted to the people" `isInfixOf` document
        then addDays 30 <$> findDateAfter "election" document
        else Nothing
      initiative = if "Ballot Measure No." `isInfixOf` document && "full force and effect" `isInfixOf` document
        then findDateAfter "Governor dated" document
        else Nothing
  in case ordinary of
      Just dateValue -> Just dateValue
      Nothing -> case referredAct of
        Just dateValue -> Just dateValue
        Nothing -> case referredElection of
          Just dateValue -> Just dateValue
          Nothing -> initiative

findSummary ∷ [String] → Maybe String
findSummary phrases =
  let normalized = map (unwords . splitWs . cleanUp) phrases
  in case filter isSummary normalized of [aSummary] → Just aSummary; _ → Nothing
isSummary ∷ String → Bool
isSummary sentence = "Relating to" `isPrefixOf` unwords (splitWs sentence)

findSectionNumbers ∷ [String] → [SectionNumber]
findSectionNumbers phrases = phrases & map sectionNumbers & concat & nub & sort

findChangedStatutes ∷ String → ChangeSet
findChangedStatutes title = changeSetFromEvidence (findTitleEvidence title)

findTitleEvidence ∷ String → [SectionEvidence]
findTitleEvidence title =
  let clauses = split "; " title
      evidenceFor action needle clause | needle `isInfixOf` clause = map (\section -> SectionEvidence section action TitleEvidence Nothing clause) (findSectionNumbers [clause]) | otherwise = []
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
    in if directTargetPrefix True prefix then map (\section -> SectionEvidence section action OperativeBodyEvidence clause excerpt) (sectionNumbers prefix) else []
  Nothing -> []

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
            in if directTargetPrefix False prefix then map (\section -> SectionEvidence section action OperativeBodyEvidence clause excerpt) (sectionNumbers prefix) else []
          Nothing -> []

directTargetPrefix ∷ Bool → String → Bool
directTargetPrefix includeSectionClause prefix =
  let sectionStart = if includeSectionClause then "^[0-9]+[A-Za-z]?\\.[[:space:]]*(Repeals\\.[[:space:]]*)?(\\([0-9]+\\)[[:space:]]*)?" else "^"
      conditionalPrefix = "(If[[:space:]]+[^,]+[[:space:]]+becomes[[:space:]]+law,[[:space:]]*)?"
      orsNumber = "[0-9]{1,3}[A-Z]?\\.[0-9]{3,4}"
      separator = "[[:space:]]*(,[[:space:]]*|[[:space:]]+and[[:space:]]+)(ORS[[:space:]]+)?"
      directTargets = "ORS[[:space:]]+" ++ orsNumber ++ "(" ++ separator ++ orsNumber ++ ")*"
      uncodifiedTail = "([[:space:]]+and[[:space:]]+sections?[[:space:]]+[0-9A-Za-z]+([[:space:]]*,[[:space:]]*[0-9A-Za-z]+)*([[:space:]]+and[[:space:]]+[0-9A-Za-z]+)?,[[:space:]]+chapter[[:space:]]+[0-9]+,[[:space:]]+Oregon Laws[[:space:]]+[0-9]{4}([[:space:]]*\\([^)]*\\))?)?"
      amendedByQualifier = "([[:space:]]*,[[:space:]]*as amended by .*)?"
      patternText = sectionStart ++ conditionalPrefix ++ directTargets ++ uncodifiedTail ++ amendedByQualifier ++ "[[:space:]]*,?[[:space:]]*$"
  in prefix =~ patternText

operativeMarker ∷ String → Maybe (ChangeAction, String)
operativeMarker block =
  let candidates = filter (\(_, marker) -> marker `isInfixOf` block)
        [ (AmendmentAction, " is amended to read")
        , (AmendmentAction, " are amended to read")
        , (RepealAction, " is repealed")
        , (RepealAction, " are repealed")
        ]
  in case candidates of
      [] -> Nothing
      _ -> Just (minimumBy (comparing (\(_, marker) -> length (beforeMarker marker block))) candidates)

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
  let citation = findCitation phrases; parsedBill = citation >>= makeBill; parsedYear = findYearWithProvenance sourceProvenance phrases; parsedChapter = findChapterWithProvenance sourceProvenance phrases; parsedEffectiveDate = findEffectiveDate phrases
      summaryText = findSummary phrases; titleEvidence = maybe [] findTitleEvidence summaryText; bodyEvidence = findBodyEvidence phrases
      titleChanges = changeSetFromEvidence titleEvidence; bodyChanges = changeSetFromEvidence bodyEvidence; allEvidence = titleEvidence ++ bodyEvidence
      errors = concat [ missingError MissingCitation "bill" "Could not find an HB/SB or ballot-measure citation" (isNothing citation), invalidCitationError citation parsedBill, missingError MissingYear "year" "Could not find the Oregon Laws year" (isNothing parsedYear), missingError MissingChapter "chapter" "Could not find the Oregon Laws chapter" (isNothing parsedChapter), missingError MissingEffectiveDate "effectiveDate" "Could not parse the effective date" (isNothing parsedEffectiveDate) ]
  in case (parsedBill, parsedYear, parsedEffectiveDate, parsedChapter) of
    (Just billValue, Just yearValue, Just effectiveDateValue, Just chapterValue) | null errors -> Right Amendment { bill = billValue, summary = summaryText, affectedSections = selectBestChangeSet titleChanges bodyChanges, year = yearValue, effectiveDate = effectiveDateValue, chapter = chapterValue, validation = reconcileChangeSetsWithEvidence titleChanges bodyChanges allEvidence, provenance = sourceProvenance }
    _ -> Left errors

missingError ∷ ParseErrorCode → String → String → Bool → [ParseError]
missingError code field message isMissing | isMissing = [ParseError code (Just field) message] | otherwise = []
invalidCitationError ∷ Maybe String → Maybe Bill → [ParseError]
invalidCitationError (Just citation) Nothing = [ParseError InvalidCitation (Just "bill") ("Could not parse citation: " ++ citation)]
invalidCitationError _ _ = []

sectionNumbers ∷ String → [String]
sectionNumbers phrase = getAllTextMatches (phrase =~ "[0-9]{1,3}[A-Z]?\\.[0-9]{3,4}")