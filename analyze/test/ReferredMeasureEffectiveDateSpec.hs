module ReferredMeasureEffectiveDateSpec where

import Amendment
import Data.Time (fromGregorian)
import Test.Hspec

main :: IO ()
main = hspec spec

spec :: Spec
spec = do
  describe "findEffectiveDate for legislatively referred measures" $ do
    it "derives the constitutional 30-day effective date from an explicit election date" $ do
      let ps =
            [ "providing that this Act shall be referred to the people for their approval or rejection"
            , "SECTION 10. This 2002 fifth special session Act shall be submitted to the people for their approval or rejection at a special election held throughout this state on January 28, 2003."
            ]
      findEffectiveDate ps `shouldBe` Just (fromGregorian 2003 2 27)

    it "does not infer an election-based effective date unless the Act is referred or submitted to the people" $ do
      findEffectiveDate ["A special election is held on January 28, 2003."] `shouldBe` Nothing
