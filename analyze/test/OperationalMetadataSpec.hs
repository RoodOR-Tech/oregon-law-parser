module OperationalMetadataSpec where

import           Amendment
import           Data.Time   (UTCTime(..), fromGregorian)
import           Provenance
import           Test.Hspec

spec :: Spec
spec = do
  describe "operational citation metadata" $ do
    it "parses ballot measure citations without weakening HB/SB parsing" $ do
      findCitation ["The Act set forth above (Ballot Measure No. 114) was proposed by initiative petition"]
        `shouldBe` Just "Ballot Measure No. 114"
      makeBill "Ballot Measure No. 114"
        `shouldBe` Just (Bill { billType = BallotMeasure, billNumber = 114 })

  describe "operational chapter metadata" $ do
    let source = Provenance
          { sourcePath = "../session-fixtures/2009orlaw0091.html"
          , sourceUrl = Just "https://www.oregonlegislature.gov/bills_laws/lawsstatutes/2009orLaw0091.html"
          , sourceSha256 = "1640001eeaf6f7ef40b9ebda01bf64590f381ddcd29c371c76bbe5b8fcbab985"
          , processedAt = UTCTime (fromGregorian 2009 5 21) 0
          }

    it "uses the authoritative source identifier when legacy HTML omits the numeric chapter heading" $ do
      findChapter ["Chapter Oregon Laws 2009"] `shouldBe` Nothing
      findChapterWithProvenance source ["Chapter Oregon Laws 2009"] `shouldBe` Just 91

    it "keeps document chapter text authoritative when it is present" $ do
      findChapterWithProvenance source ["Chapter 92 Oregon Laws 2009"] `shouldBe` Just 92

  describe "operational effective-date metadata" $ do
    it "parses a referred act effective date from the Legislative Counsel note" $ do
      let ps =
            [ "NOTE: The Act set forth above (chapter 220, Oregon Laws 2023 (Enrolled House Bill 2004)) was referred to the voters of the State of Oregon at the November 5, 2024, general election."
            , "If approved, the Act takes effect 30 days after the election (i.e., on December 5, 2024)."
            ]
      findEffectiveDate ps `shouldBe` Just (fromGregorian 2024 12 5)

    it "parses an initiative effective date from the Governor proclamation note" $ do
      let ps =
            [ "The Act set forth above (Ballot Measure No. 114) was proposed by initiative petition and was approved by the voters at the regular general election on November 8, 2022."
            , "By proclamation of the Governor dated December 8, 2022, the Act was declared to have received an affirmative majority of the total number of votes cast thereon and to be in full force and effect as provided in Article IV, section 1, of the Oregon Constitution."
            ]
      findEffectiveDate ps `shouldBe` Just (fromGregorian 2022 12 8)