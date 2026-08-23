module LegislativeCounselSpec where

import           Amendment
import           LegislativeCounsel
import           Test.Hspec

main :: IO ()
main = hspec spec

spec :: Spec
spec = do
  describe "lcChangeSetForChapter" $ do
    it "selects amendments and repeals for the requested Oregon Laws chapter" $ do
      let rows =
            [ LCRecord "455.628" LCAmended 108 "16"
            , LCRecord "456.648 to 456.828" LCAddedTo 91 "1"
            , LCRecord "90.100" LCAmended 23 "4"
            , LCRecord "90.999" LCRepealed 108 "21"
            ]
      lcChangeSetForChapter 108 rows `shouldBe`
        ChangeSet { amended = ["455.628"], repealed = ["90.999"] }

  describe "reconcileWithLegislativeCounsel" $ do
    it "verifies when parser and Legislative Counsel agree" $ do
      let parsed = ChangeSet { amended = ["455.628"], repealed = [] }
          rows = [LCRecord "455.628" LCAmended 108 "16"]
      lcValidationStatus (reconcileWithLegislativeCounsel 108 parsed rows)
        `shouldBe` LCVerified

    it "reports conflict when Legislative Counsel disagrees" $ do
      let parsed = ChangeSet { amended = ["455.628"], repealed = [] }
          rows = [LCRecord "455.629" LCAmended 108 "16"]
      lcValidationStatus (reconcileWithLegislativeCounsel 108 parsed rows)
        `shouldBe` LCConflict

    it "reports no evidence when the table has no records for the chapter" $ do
      let parsed = ChangeSet { amended = ["455.628"], repealed = [] }
          rows = [LCRecord "455.628" LCAmended 107 "16"]
      lcValidationStatus (reconcileWithLegislativeCounsel 108 parsed rows)
        `shouldBe` LCNoEvidence
