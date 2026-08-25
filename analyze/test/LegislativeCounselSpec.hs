module LegislativeCounselSpec where

import           Amendment
import           LegislativeCounsel
import           Test.Hspec

main :: IO ()
main = hspec spec

spec :: Spec
spec = do
  describe "lcChangeSetForChapter" $ do
    it "selects amendments and repeals for the requested Oregon Laws year and chapter" $ do
      let rows =
            [ LCRecord "455.628" LCAmended 2026 108 "16"
            , LCRecord "456.648 to 456.828" LCAddedTo 2026 91 "1"
            , LCRecord "90.100" LCAmended 2026 23 "4"
            , LCRecord "90.999" LCRepealed 2026 108 "21"
            ]
      lcChangeSetForChapter 2026 108 rows `shouldBe`
        ChangeSet { amended = ["455.628"], repealed = ["90.999"] }

    it "does not combine the same chapter number across Oregon Laws years" $ do
      let rows =
            [ LCRecord "455.628" LCAmended 2026 108 "16"
            , LCRecord "455.999" LCAmended 2025 108 "3"
            ]
      lcChangeSetForChapter 2026 108 rows `shouldBe`
        ChangeSet { amended = ["455.628"], repealed = [] }

  describe "reconcileWithLegislativeCounsel" $ do
    it "verifies when parser and Legislative Counsel agree" $ do
      let parsed = ChangeSet { amended = ["455.628"], repealed = [] }
          rows = [LCRecord "455.628" LCAmended 2026 108 "16"]
      lcValidationStatus (reconcileWithLegislativeCounsel 2026 108 parsed rows)
        `shouldBe` LCVerified

    it "reports conflict when Legislative Counsel disagrees" $ do
      let parsed = ChangeSet { amended = ["455.628"], repealed = [] }
          rows = [LCRecord "455.629" LCAmended 2026 108 "16"]
      lcValidationStatus (reconcileWithLegislativeCounsel 2026 108 parsed rows)
        `shouldBe` LCConflict

    it "reports no evidence when the table has no records for the year and chapter" $ do
      let parsed = ChangeSet { amended = ["455.628"], repealed = [] }
          rows = [LCRecord "455.628" LCAmended 2025 108 "16"]
      lcValidationStatus (reconcileWithLegislativeCounsel 2026 108 parsed rows)
        `shouldBe` LCNoEvidence
