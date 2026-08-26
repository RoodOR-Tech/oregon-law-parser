module AmendmentSpec where

import           Amendment
import           Data.Time   (UTCTime(..), fromGregorian)
import           Provenance
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
      makeBill "HB 4047" `shouldBe` Just (Bill { billType = HB, billNumber = 4047 })

    it "can parse a typical senate bill" $ do
      makeBill "SB 1532" `shouldBe` Just (Bill { billType = SB, billNumber = 1532 })

    it "returns Nothing for malformed citations" $ do
      makeBill "HB nope" `shouldBe` Nothing

  describe "findCitation" $ do
    it "can find it in an HB title" $ do
      findCitation ["AN ACT HB 4047"] `shouldBe` Just "HB 4047"

    it "can find it in an SB title" $ do
      findCitation ["AN ACT SB 1234"] `shouldBe` Just "SB 1234"

    it "returns Nothing when a citation is absent" $ do
      findCitation ["AN ACT"] `shouldBe` Nothing

  describe "findYear" $ do
    it "returns just the year" $ do
      findYear ["OREGON LAWS 2016", "Some junk"] `shouldBe` Just 2016

    it "parses the mixed-case legacy HTML chapter heading" $ do
      findYear ["Chapter 23 Oregon Laws 2010 Special Session"] `shouldBe` Just 2010

  describe "findChapter" $ do
    it "can find it" $ do
      findChapter ["Chap. 102"] `shouldBe` Just 102

    it "parses the legacy HTML chapter heading" $ do
      findChapter ["Chapter 23 Oregon Laws 2010 Special Session"] `shouldBe` Just 23

  describe "findEffectiveDate" $ do
    it "picks out the right one" $ do
      let ps = ["Nope.", "Approved by the Governor March 3, 2016 Filed in the office of Secretary of State March 3, 2016 Effective date January 17, 2017"]
      findEffectiveDate ps `shouldBe` Just (fromGregorian 2017 1 17)

    it "tolerates irregular PDF spacing in a special-session footer" $ do
      let ps = ["Filed in the office of Secretary of State November 10, 2025", "Effective   date   December  31,  2025"]
      findEffectiveDate ps `shouldBe` Just (fromGregorian 2025 12 31)

    it "returns Nothing when the effective date is absent" $ do
      findEffectiveDate ["No effective date here"] `shouldBe` Nothing

  describe "findSummary" $ do
    it "uses Nothing instead of a sentinel string when unavailable" $ do
      findSummary ["AN ACT HB 1"] `shouldBe` Nothing

  describe "findChangedStatutes" $ do
    it "picks out the amended and repealed correctly" $ do
      let title = "Relating to student safety; creating new provisions; amending ORS 165.570 and sections 1 and 2, chapter 93, Oregon Laws 2014; repealing ORS 180.650 and 180.660; and declaring an emergency."
      findChangedStatutes title `shouldBe` ChangeSet { amended = ["165.570"], repealed = ["180.650", "180.660"] }

    it "doesn't get fooled by 'and'" $ do
      let title = "Relating to criminal impersonation; creating new provisions; and amending ORS 161.005 and 162.365."
      findChangedStatutes title `shouldBe` ChangeSet { amended = ["161.005", "162.365"], repealed = [] }

    it "does not treat an amending clause as a repeal by subsequence" $ do
      let title = "Relating to state financial administration; amending ORS 92.365, 92.415, 100.670 and 336.221 and sections 3 and 4, chapter 441, Oregon Laws 2023; repealing sections 3, 11 and 12, chapter 4, Oregon Laws 2013; and declaring an emergency."
      findChangedStatutes title `shouldBe` ChangeSet { amended = ["100.670", "336.221", "92.365", "92.415"], repealed = [] }

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

    it "allows an as-amended-by qualifier before an operative amendment" $ do
      let ps = ["SECTION 4. ORS 659A.885, as amended by section 3, chapter 102, Oregon Laws 2010, is amended to read:"]
      findBodyChangedStatutes ps `shouldBe` ChangeSet { amended = ["659A.885"], repealed = [] }

    it "extracts ORS targets from a mixed ORS and Oregon Laws repeal clause" $ do
      let ps = ["SECTION 1. (1) ORS 455.612, 455.614, 476.390, 476.394, 477.027, 477.161 and 477.490 and sections 12a, 12b and 29, chapter 592, Oregon Laws 2021, are repealed."]
      findBodyChangedStatutes ps `shouldBe` ChangeSet { amended = [], repealed = ["455.612", "455.614", "476.390", "476.394", "477.027", "477.161", "477.490"] }

    it "accepts a conditional becomes-law prefix on a direct ORS amendment" $ do
      let ps = ["SECTION 41. If House Bill 2191 becomes law, ORS 697.612, as amended by section 2, chapter 604, Oregon Laws 2009 (Enrolled House Bill 2191), is amended to read:"]
      findBodyChangedStatutes ps `shouldBe` ChangeSet { amended = ["697.612"], repealed = [] }

    it "does not infer a current repeal from historical narrative" $ do
      let ps = ["SECTION 5. (1) ORS 458.620 (1)(f) (2019 Edition) and 458.667 (2019 Edition) established an account. (2) The account was abolished by prior law and the repeal of ORS 458.667 by prior law. (3) The repeal of ORS 458.667 by section 6 of this 2023 Act confirms the result. SECTION 6. ORS 458.667 is repealed."]
      findBodyChangedStatutes ps `shouldBe` ChangeSet { amended = [], repealed = ["458.667"] }

  describe "section evidence" $ do
    it "retains operative SECTION number, action, source, and evidence text" $ do
      let evidence = findBodyEvidence ["SECTION 12. ORS 475C.770 is amended to read:"]
      evidence `shouldBe`
        [ SectionEvidence
            { evidenceSectionNumber = "475C.770"
            , evidenceAction = AmendmentAction
            , evidenceSource = OperativeBodyEvidence
            , evidenceSectionClause = Just "12"
            , evidenceText = "12. ORS 475C.770 is amended to read"
            }
        ]

    it "retains title evidence independently from operative evidence" $ do
      let evidence = findTitleEvidence "Relating to safety; amending ORS 811.111; repealing ORS 811.112."
      map evidenceSource evidence `shouldBe` [TitleEvidence, TitleEvidence]
      map evidenceSectionNumber evidence `shouldBe` ["811.111", "811.112"]

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

  describe "parseAmendment" $ do
    it "returns all missing required-field errors instead of throwing" $ do
      let result = parseAmendment testProvenance ["OREGON LAWS 2026"]
      case result of
        Left errors -> do
          map parseErrorCode errors `shouldContain` [MissingCitation]
          map parseErrorCode errors `shouldContain` [MissingChapter]
          map parseErrorCode errors `shouldContain` [MissingEffectiveDate]
        Right _ -> expectationFailure "Expected structured parse errors"

    it "preserves provenance and section evidence on successful parses" $ do
      let ps =
            [ "OREGON LAWS 2026 Chap. 12 AN ACT HB 4047"
            , "Relating to speed limits; amending ORS 811.111."
            , "SECTION 1. ORS 811.111 is amended to read:"
            , "Effective date January 17, 2027"
            ]
      case parseAmendment testProvenance ps of
        Right amendment -> do
          provenance amendment `shouldBe` testProvenance
          length (sectionEvidence (validation amendment)) `shouldBe` 2
          map evidenceSource (sectionEvidence (validation amendment))
            `shouldContain` [OperativeBodyEvidence]
        Left errors -> expectationFailure ("Unexpected parse failure: " ++ show errors)

    it "parses legacy Oregon Laws HTML chapter metadata" $ do
      let ps =
            [ "Chapter 23 Oregon Laws 2010 Special Session"
            , "AN ACT SB 993"
            , "Relating to consumer lending; amending ORS 725.010; and declaring an emergency."
            , "SECTION 29. ORS 725.010 is amended to read:"
            , "Effective date March 4, 2010"
            ]
      case parseAmendment testProvenance ps of
        Right amendment -> do
          year amendment `shouldBe` 2010
          chapter amendment `shouldBe` 23
          bill amendment `shouldBe` Bill { billType = SB, billNumber = 993 }
          effectiveDate amendment `shouldBe` fromGregorian 2010 3 4
        Left errors -> expectationFailure ("Unexpected legacy HTML parse failure: " ++ show errors)

testProvenance :: Provenance
testProvenance = Provenance
  { sourcePath = "fixture.pdf"
  , sourceUrl = Just "https://example.test/fixture.pdf"
  , sourceSha256 = replicate 64 'a'
  , processedAt = UTCTime (fromGregorian 2026 1 1) 0
  }
