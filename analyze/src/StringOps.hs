module StringOps(cleanUp, firstMatch, join, fixHyphenation, fixWhitespace) where

import Control.Arrow.Unicode ( (⋙) )
import Data.List             (isSuffixOf)
import Data.String.Utils     (replace, split)
import Text.Regex.TDFA       ( (=~) )


cleanUp ∷ String → String
cleanUp a_string =
  let sentences =
        normalizeExtraction
        ⋙  splitIntoSentences
  in case sentences a_string of
    (x:_) -> x
    []      -> ""


fixWhitespace ∷ String → String
fixWhitespace = replace "\n" " " ⋙ replace "\r" " " ⋙ replace "\t" " "


fixHyphenation ∷ String → String
fixHyphenation = replace "- " ""


stripExtractionArtifacts ∷ String → String
stripExtractionArtifacts = filter (\c -> c /= '\x00ad' && c /= '\x0002')


normalizeExtraction ∷ String → String
normalizeExtraction =
  fixWhitespace
  ⋙ fixHyphenation
  ⋙ stripExtractionArtifacts


splitIntoSentences ∷ String → [String]
splitIntoSentences = split ". " ⋙  map ensureEndsWithPeriod


ensureEndsWithPeriod :: String → String
ensureEndsWithPeriod sentence =
  sentence ++ (if "." `isSuffixOf` sentence then "" else ".")


--
-- Regex helpers
--
firstMatch ∷ String → String → Maybe String
firstMatch regex input =
  case (input =~ regex :: String) of
    "" -> Nothing
    x -> Just x



--
-- More-conventional function names
--
join ∷ [String] → String
join = unwords ⋙ normalizeExtraction
