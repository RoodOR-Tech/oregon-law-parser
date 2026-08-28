module Legacy2008Spec where

import           Amendment
import           Data.Time  (fromGregorian)
import           Test.Hspec

main :: IO ()
main = hspec spec

spec :: Spec
spec = do
  describe "2008 referred-act effective dates" $ do
    it "derives the effective date 30 days after the stated election" $ do
      let ps =
            [ "Chapter 14 Oregon Laws 2008 Special Session"
            , "NOTE: Chapter 14, Oregon Laws 2008 (Enrolled Senate Bill 1087), was referred to the people at the regular general election on November 4, 2008. If approved, the Act takes effect 30 days after the election."
            ]
      findEffectiveDate ps `shouldBe` Just (fromGregorian 2008 12 4)
