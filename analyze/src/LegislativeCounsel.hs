{-# LANGUAGE DeriveGeneric #-}

module LegislativeCounsel where

import           Amendment
import           Data.Aeson    (ToJSON)
import           Data.List     (nub, sort)
import           GHC.Generics

data LCAction
  = LCAmended
  | LCRepealed
  | LCAddedTo
  deriving (Eq, Show, Generic)

data LCRecord =
  LCRecord {
    lcOrsSection        ∷ SectionNumber,
    lcAction            ∷ LCAction,
    lcSourceYear        ∷ Integer,
    lcOregonLawsChapter ∷ Integer,
    lcOregonLawsSection ∷ String
  } deriving (Eq, Show, Generic)

data LCValidationStatus
  = LCVerified
  | LCConflict
  | LCNoEvidence
  deriving (Eq, Show, Generic)

data LCValidation =
  LCValidation {
    lcValidationStatus ∷ LCValidationStatus,
    parserSections     ∷ ChangeSet,
    counselSections    ∷ ChangeSet
  } deriving (Eq, Show, Generic)

instance ToJSON LCAction
instance ToJSON LCRecord
instance ToJSON LCValidationStatus
instance ToJSON LCValidation

-- Convert Legislative Counsel table records for one Oregon Laws year and chapter
-- into the same ChangeSet representation used by the session-law parser. Oregon
-- Laws chapter numbers repeat across years, so both values are required. "Added
-- To" records are deliberately excluded because they do not represent amendments
-- or repeals of an existing ORS section.
lcChangeSetForChapter ∷ Integer → Integer → [LCRecord] → ChangeSet
lcChangeSetForChapter sourceYear chapterNumber records =
  let matching = filter matchesSource records
      matchesSource record =
        lcSourceYear record == sourceYear
          && lcOregonLawsChapter record == chapterNumber
      sectionsFor action =
        matching
          |> filter ((== action) . lcAction)
          |> map lcOrsSection
          |> nub
          |> sort
  in ChangeSet {
    amended = sectionsFor LCAmended,
    repealed = sectionsFor LCRepealed
  }

reconcileWithLegislativeCounsel ∷ Integer → Integer → ChangeSet → [LCRecord] → LCValidation
reconcileWithLegislativeCounsel sourceYear chapterNumber parsed records =
  let counsel = lcChangeSetForChapter sourceYear chapterNumber records
      hasEvidence = counsel /= emptyChangeSet
      status
        | not hasEvidence = LCNoEvidence
        | counsel == parsed = LCVerified
        | otherwise = LCConflict
  in LCValidation {
    lcValidationStatus = status,
    parserSections = parsed,
    counselSections = counsel
  }

(|>) ∷ a → (a → b) → b
x |> f = f x
