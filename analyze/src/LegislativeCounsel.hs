{-# LANGUAGE DeriveGeneric #-}
{-# LANGUAGE OverloadedStrings #-}

module LegislativeCounsel where

import           Amendment
import           Data.Aeson            (ToJSON)
import qualified Data.ByteString.Char8 as BS
import qualified Data.ByteString.Lazy  as BL
import           Data.Csv
import           Data.List             (nub, sort)
import qualified Data.Vector           as V
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
    lcOregonLawsSection ∷ String,
    lcSourceUrl         ∷ String,
    lcSourceVolume      ∷ Integer
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
    counselSections    ∷ ChangeSet,
    counselEvidence    ∷ [LCRecord]
  } deriving (Eq, Show, Generic)

instance ToJSON LCAction
instance ToJSON LCRecord
instance ToJSON LCValidationStatus
instance ToJSON LCValidation

instance FromField LCAction where
  parseField raw =
    case BS.unpack raw of
      "amended"  -> pure LCAmended
      "repealed" -> pure LCRepealed
      "added_to" -> pure LCAddedTo
      other       -> fail ("Unsupported Legislative Counsel action: " ++ other)

instance FromNamedRecord LCRecord where
  parseNamedRecord record =
    LCRecord
      <$> record .: "ors_section"
      <*> record .: "action"
      <*> record .: "source_year"
      <*> record .: "oregon_laws_chapter"
      <*> record .: "oregon_laws_section"
      <*> record .: "source_url"
      <*> record .: "source_volume"

-- Load a normalized Legislative Counsel CSV. Cassava handles quoted fields,
-- embedded commas, and row-level type validation so malformed source data fails
-- closed instead of silently entering the validation dataset.
loadLCRecords ∷ FilePath → IO (Either String [LCRecord])
loadLCRecords path = decodeLCRecords <$> BL.readFile path

decodeLCRecords ∷ BL.ByteString → Either String [LCRecord]
decodeLCRecords bytes =
  case decodeByName bytes of
    Left err -> Left err
    Right (_, rows) -> Right (V.toList rows)

lcRecordsForChapter ∷ Integer → Integer → [LCRecord] → [LCRecord]
lcRecordsForChapter sourceYear chapterNumber =
  filter (\record ->
    lcSourceYear record == sourceYear
      && lcOregonLawsChapter record == chapterNumber)

lcChangeSetForChapter ∷ Integer → Integer → [LCRecord] → ChangeSet
lcChangeSetForChapter sourceYear chapterNumber records =
  let matching = lcRecordsForChapter sourceYear chapterNumber records
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
  let evidence = lcRecordsForChapter sourceYear chapterNumber records
      counsel = lcChangeSetForChapter sourceYear chapterNumber records
      hasEvidence = not (null evidence)
      status
        | not hasEvidence = LCNoEvidence
        | counsel == parsed = LCVerified
        | otherwise = LCConflict
  in LCValidation {
    lcValidationStatus = status,
    parserSections = parsed,
    counselSections = counsel,
    counselEvidence = evidence
  }

(|>) ∷ a → (a → b) → b
x |> f = f x
