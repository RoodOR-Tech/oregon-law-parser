module Legacy2001Spec where

import           Amendment
import           Data.Time   (UTCTime(..), fromGregorian)
import           Provenance
import           Test.Hspec

spec :: Spec
spec = do
  describe "legacy 2001 metadata" $ do
    it "accepts ballot-measure citations without No." $ do
      findCitation ["The Act set forth above (Ballot Measure 5) was proposed by initiative petition"]
        `shouldBe` Just "Ballot Measure 5"
      makeBill "Ballot Measure 5"
        `shouldBe` Just (Bill { billType = BallotMeasure, billNumber = 5 })

    it "uses authoritative provenance year when text contains no year candidate" $ do
      findYearWithProvenance provenance2001 ["AN ACT HB 2001"] `shouldBe` Just 2001

    it "does not let provenance override a conflicting textual year" $ do
      findYearWithProvenance provenance2001 ["OREGON LAWS 2003"] `shouldBe` Just 2003

    it "uses the ORS 171.022 default date only for legislative acts" $ do
      findEffectiveDateWithContext provenance2001 (Just (Bill HB 2001)) ["AN ACT HB 2001"]
        `shouldBe` Just (fromGregorian 2002 1 1)
      findEffectiveDateWithContext provenance2001 (Just (Bill BallotMeasure 5)) ["Ballot Measure 5"]
        `shouldBe` Nothing

    it "still prefers an explicit effective date over the legislative default" $ do
      findEffectiveDateWithContext provenance2001 (Just (Bill SB 10)) ["Effective date July 1, 2001"]
        `shouldBe` Just (fromGregorian 2001 7 1)

provenance2001 :: Provenance
provenance2001 = Provenance
  { sourcePath = "2001orlaw0188.html"
  , sourceUrl = Just "https://www.oregonlegislature.gov/bills_laws/lawsstatutes/2001orLaw0188ses.html"
  , sourceSha256 = replicate 64 'a'
  , processedAt = UTCTime (fromGregorian 2026 8 29) 0
  }
