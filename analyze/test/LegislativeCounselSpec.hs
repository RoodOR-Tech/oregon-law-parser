module LegislativeCounselSpec where

import           Amendment
import qualified Data.ByteString.Lazy.Char8 as BL
import           LegislativeCounsel
import           Test.Hspec

main :: IO ()
main = hspec spec

spec :: Spec
spec = do
  describe "decodeLCRecords" $ do
    it "loads normalized Legislative Counsel rows with source provenance" $ do
      let csv = BL.pack $ unlines
            [ "ors_section,action,oregon_laws_chapter,oregon_laws_section,source_url,source_year,source_volume"
            , "455.628,amended,108,16,https://example.test/Volume13.pdf,2026,13"
            , "90.999,repealed,108,21,https://example.test/Volume01.pdf,2026,1"
            ]
      case decodeLCRecords csv of
        Right rows -> do
          length rows `shouldBe` 2
          lcOrsSection (head rows) `shouldBe` "455.628"
          lcAction (head rows) `shouldBe` LCAmended
          lcSourceYear (head rows) `shouldBe` 2026
          lcSourceUrl (head rows) `shouldBe` "https://example.test/Volume13.pdf"
          lcSourceVolume (head rows) `shouldBe` 13
        Left err -> expectationFailure err

    it "fails closed on unsupported action values" $ do
      let csv = BL.pack $ unlines
            [ "ors_section,action,oregon_laws_chapter,oregon_laws_section,source_url,source_year,source_volume"
            , "455.628,changed,108,16,https://example.test/Volume13.pdf,2026,13"
            ]
      decodeLCRecords csv `shouldSatisfy` isLeft

  describe "lcChangeSetForChapter" $ do
    it "selects amendments and repeals for the requested Oregon Laws year and chapter" $ do
      let rows =
            [ mkRecord "455.628" LCAmended 2026 108 "16"
            , mkRecord "456.648 to 456.828" LCAddedTo 2026 91 "1"
            , mkRecord "90.100" LCAmended 2026 23 "4"
            , mkRecord "90.999" LCRepealed 2026 108 "21"
            ]
      lcChangeSetForChapter 2026 108 rows `shouldBe`
        ChangeSet { amended = ["455.628"], repealed = ["90.999"] }

    it "does not combine the same chapter number across Oregon Laws years" $ do
      let rows =
            [ mkRecord "455.628" LCAmended 2026 108 "16"
            , mkRecord "455.999" LCAmended 2025 108 "3"
            ]
      lcChangeSetForChapter 2026 108 rows `shouldBe`
        ChangeSet { amended = ["455.628"], repealed = [] }

  describe "reconcileWithLegislativeCounsel" $ do
    it "verifies when parser and Legislative Counsel agree and retains LC evidence" $ do
      let parsed = ChangeSet { amended = ["455.628"], repealed = [] }
          rows = [mkRecord "455.628" LCAmended 2026 108 "16"]
          validation = reconcileWithLegislativeCounsel 2026 108 parsed rows
      lcValidationStatus validation `shouldBe` LCVerified
      counselEvidence validation `shouldBe` rows

    it "reports conflict when Legislative Counsel disagrees" $ do
      let parsed = ChangeSet { amended = ["455.628"], repealed = [] }
          rows = [mkRecord "455.629" LCAmended 2026 108 "16"]
      lcValidationStatus (reconcileWithLegislativeCounsel 2026 108 parsed rows)
        `shouldBe` LCConflict

    it "reports no evidence when the table has no records for the year and chapter" $ do
      let parsed = ChangeSet { amended = ["455.628"], repealed = [] }
          rows = [mkRecord "455.628" LCAmended 2025 108 "16"]
      lcValidationStatus (reconcileWithLegislativeCounsel 2026 108 parsed rows)
        `shouldBe` LCNoEvidence

    it "does not treat added-to-only rows as amendment/repeal evidence" $ do
      let parsed = emptyChangeSet
          rows = [mkRecord "456.648 to 456.828" LCAddedTo 2026 91 "1"]
          validation = reconcileWithLegislativeCounsel 2026 91 parsed rows
      lcValidationStatus validation `shouldBe` LCNoEvidence
      counselEvidence validation `shouldBe` rows

mkRecord :: String -> LCAction -> Integer -> Integer -> String -> LCRecord
mkRecord ors action sourceYear chapterNumber lawsSection = LCRecord
  { lcOrsSection = ors
  , lcAction = action
  , lcSourceYear = sourceYear
  , lcOregonLawsChapter = chapterNumber
  , lcOregonLawsSection = lawsSection
  , lcSourceUrl = "https://example.test/Volume13.pdf"
  , lcSourceVolume = 13
  }

isLeft :: Either a b -> Bool
isLeft (Left _) = True
isLeft _ = False
