module StringOpsSpec where

import           StringOps
import           Test.Hspec


main :: IO ()
main = hspec spec

spec :: Spec
spec = do
  describe "fixHyphenation" $ do
    it "rejoins a parser-critical word split across a line" $ do
      fixHyphenation "re-\npealed" `shouldBe` "repealed"

    it "preserves an ordinary hyphen followed by a space" $ do
      fixHyphenation "well- formed" `shouldBe` "well- formed"

    it "preserves a hard hyphen when a hyphenated word wraps across a line" $ do
      fixHyphenation "well-\nformed" `shouldBe` "well-formed"

    it "handles CRLF extraction boundaries" $ do
      fixHyphenation "sec-\r\ntion" `shouldBe` "section"

  describe "fixWhitespace" $ do
    it "changes a newline to a space" $ do
      fixWhitespace "and\nthe story" `shouldBe` "and the story"

  describe "join" $ do
    it "normalizes line-wrap hyphenation before parser matching" $ do
      join ["SECTION 9. ORS 316.417 and 317.504 are re-\npealed."]
        `shouldBe` "SECTION 9. ORS 316.417 and 317.504 are repealed."

    it "preserves legitimate hyphenated text across an extraction line break" $ do
      join ["The well-\nformed application is accepted."]
        `shouldBe` "The well-formed application is accepted."

    it "removes PDF extraction control artifacts inside words" $ do
      join ["SECTION 4. ORS 305.280, as amended by sec\x0002tion 34, is amended to read:"]
        `shouldBe` "SECTION 4. ORS 305.280, as amended by section 34, is amended to read:"

  describe "cleanUp" $ do
    it "handles extra text" $ do
      let input = "Relating to the state transient lodging tax; creating\nnew provisions; amending ORS 284.131 and\n320.305; prescribing an effective date; and pro-\nviding for revenue raising that requires approval\nby a three-fifths majority.\nWhereas Enrolled House Bill 2267 (chapter 818,"
      cleanUp input `shouldBe` "Relating to the state transient lodging tax; creating new provisions; amending ORS 284.131 and 320.305; prescribing an effective date; and providing for revenue raising that requires approval by a three-fifths majority."
