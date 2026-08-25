module AmendmentSpec where

import           Amendment
import           Data.Time  (fromGregorian)
import           Test.Hspec

main :: IO ()
main = hspec spec

spec :: Spec
spec = do
  describe "isSummary" $ do
    it "is true for a valid summary" $ do
      let summary_hb_4047 = "Relating to speed limits on highways that traverse state lines; creating new provisions; amending ORS 811.111; and declaring an emergency."
      isSummary summary_hb_4047 `shouldBe` True

  describe "makeBill" $ do
    it "can parse a typical house bill" $ do
      makeBill "HB 4047" `shouldBe` Bill { billType = HB, billNumber = 4047 }

    it "can parse a typical senate bill" $ do
      makeBill "SB 1532" `shouldBe` Bill { billType = SB, billNumber = 1532 }

  describe "findCitation" $ do
    it "can find it in an HB title" $ do
      findCitation ["AN ACT HB 4047"] `shouldBe` "HB 4047"

    it "can find it in an SB title" $ do
      findCitation ["AN ACT SB 1234"] `shouldBe` "SB 1234"

  describe "findYear" $ do
    it "returns just the year" $ do
      findYear ["OREGON LAWS 2016", "Some junk"] `shouldBe` 2016

  describe "findChapter" $ do
    it "can find it" $ do
      findChapter ["Chap. 102"] `shouldBe` 102

  describe "findEffectiveDate" $ do
    it "picks out the right one" $ do
      let ps = ["Nope.", "Approved by the Governor March 3, 2016 Filed in the office of Secretary of State March 3, 2016 Effective date January 17, 2017"]
      findEffectiveDate ps `shouldBe` fromGregorian 2017 1 17

  describe "findChangedStatutes" $ do
    it "picks out the amended and repealed correctly" $ do
      let title = "Relating to student safety; creating new provisions; amending ORS 165.570 and sections 1 and 2, chapter 93, Oregon Laws 2014; repealing ORS 180.650 and 180.660; and declaring an emergency."
      findChangedStatutes title `shouldBe` ChangeSet { amended = ["165.570"], repealed = ["180.650", "180.660"] }

    it "doesn't get fooled by 'and'" $ do
      let title = "Relating to criminal impersonation; creating new provisions; and amending ORS 161.005 and 162.365."
      findChangedStatutes title `shouldBe` ChangeSet { amended = ["161.005", "162.365"], repealed = [] }

  describe "findBodyChangedStatutes" $ do
    it "uses the operative amendment clause" $ do
      let ps = ["SECTION 2. ORS 811.111 is amended to read:", "811.111. A later body reference to ORS 999.999 must not be treated as another amended statute."]
      findBodyChangedStatutes ps `shouldBe` ChangeSet { amended = ["811.111"], repealed = [] }

    it "finds multiple statutes in an operative repeal clause" $ do
      let ps = ["SECTION 5. ORS 180.650 and 180.660 are repealed."]
      findBodyChangedStatutes ps `shouldBe` ChangeSet { amended = [], repealed = ["180.650", "180.660"] }

    it "supports lettered ORS chapters beyond A-C" $ do
      let ps = ["SECTION 7. ORS 475C.770 is amended to read:"]
      findBodyChangedStatutes ps `shouldBe` ChangeSet { amended = ["475C.770"], repealed = [] }

  describe "reconcileChangeSets" $ do
    it "marks matching independent parses as verified" $ do
      let changes = ChangeSet { amended = ["811.111"], repealed = [] }
      validationStatus (reconcileChangeSets changes changes) `shouldBe` Verified

    it "marks a body/title disagreement as a conflict" $ do
      let titleChanges = ChangeSet { amended = ["811.111"], repealed = [] }
          bodyChanges = ChangeSet { amended = ["811.112"], repealed = [] }
      validationStatus (reconcileChangeSets titleChanges bodyChanges) `shouldBe` Conflict

    it "retains title extraction as a fallback when body parsing has no evidence" $ do
      let titleChanges = ChangeSet { amended = ["811.111"], repealed = [] }
      selectBestChangeSet titleChanges emptyChangeSet `shouldBe` titleChanges
      validationStatus (reconcileChangeSets titleChanges emptyChangeSet) `shouldBe` ParsedUnverified

    it "marks a complete lack of parser evidence as incomplete" $ do
      let validation = reconcileChangeSets emptyChangeSet emptyChangeSet
      validationStatus validation `shouldBe` Incomplete
      titleBodyMatch validation `shouldBe` True
