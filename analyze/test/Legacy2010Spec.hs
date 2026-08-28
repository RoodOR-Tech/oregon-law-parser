module Legacy2010Spec where

import Amendment
import Test.Hspec

spec :: Spec
spec = do
  describe "legacy 2010 Oregon Laws HTML" $ do
    it "normalizes leading extraction whitespace before identifying the act title" $ do
      findSummary
        [ "\t   Relating to prudently incurred costs associated with compliance with a renewable portfolio standard; amending ORS 469A.120 and 757.370; and declaring an emergency."
        ] `shouldBe` Just "Relating to prudently incurred costs associated with compliance with a renewable portfolio standard; amending ORS 469A.120 and 757.370; and declaring an emergency."

    it "prefers the operative act year over a stale Oregon Laws heading" $ do
      findYear
        [ "Chapter 79 Oregon Laws 2009"
        , "SECTION 3. This 2010 Act being necessary for the immediate preservation of the public peace, health and safety, an emergency is declared to exist."
        ] `shouldBe` Just 2010

    it "does not let prior-act references override the current session year" $ do
      findYear
        [ "Chapter 30 Oregon Laws 2010 Special Session"
        , "SECTION 1. Section 4 of this 2007 Act is amended."
        , "SECTION 8. This 2010 Act takes effect on passage."
        ] `shouldBe` Just 2010
