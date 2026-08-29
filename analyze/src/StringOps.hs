module StringOps(cleanUp, firstMatch, join, fixHyphenation, fixWhitespace) where

import Control.Arrow.Unicode ( (⋙) )
import Data.Char             (isAlpha, toLower)
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


-- Rejoin extraction-induced word breaks only when the original text contains
-- an actual line boundary. For parser-critical vocabulary, remove the inserted
-- hyphen; for every other word, preserve the hyphen while removing the line
-- break so a legitimate hard hyphen is never silently destroyed.
--
-- This is deliberately a single pass. The earlier implementation enumerated
-- every possible split of every parser-critical word and repeatedly scanned the
-- complete document for each form. That was correct on small fixtures but made
-- large session laws exceed the operational parser timeout.
fixHyphenation ∷ String → String
fixHyphenation = repairLineBreakHyphens


parserCriticalWords ∷ [String]
parserCriticalWords =
  [ "amend"
  , "amended"
  , "amending"
  , "amendment"
  , "amendments"
  , "chapter"
  , "chapters"
  , "effective"
  , "providing"
  , "provision"
  , "provisions"
  , "repeal"
  , "repealed"
  , "repealing"
  , "section"
  , "sections"
  , "statute"
  , "statutes"
  ]


repairLineBreakHyphens ∷ String → String
repairLineBreakHyphens = reverse ⋙ go []
  where
    -- Work from left to right while keeping the emitted prefix reversed. When a
    -- hyphen is immediately followed by an extraction line break, inspect the
    -- alphabetic fragments on each side without rescanning the full document.
    go acc [] = acc
    go acc ('-':rest) =
      case consumeLineBreak rest of
        Nothing -> go ('-':acc) rest
        Just afterBreak ->
          let (rightWord, remainder) = span isAlpha afterBreak
              (leftReversed, _) = span isAlpha acc
              combined = map toLower (reverse leftReversed ++ rightWord)
              emitted
                | combined `elem` parserCriticalWords = reverse rightWord ++ acc
                | otherwise = reverse rightWord ++ ('-':acc)
          in go emitted remainder
    go acc (c:rest) = go (c:acc) rest


consumeLineBreak ∷ String → Maybe String
consumeLineBreak (' ':'\r':'\n':rest) = Just rest
consumeLineBreak (' ':'\n':rest) = Just rest
consumeLineBreak (' ':'\r':rest) = Just rest
consumeLineBreak ('\r':'\n':rest) = Just rest
consumeLineBreak ('\n':rest) = Just rest
consumeLineBreak ('\r':rest) = Just rest
consumeLineBreak _ = Nothing


stripExtractionArtifacts ∷ String → String
stripExtractionArtifacts = filter (\c -> c /= '\x00ad' && c /= '\x0002')


normalizeExtraction ∷ String → String
normalizeExtraction =
  stripExtractionArtifacts
  ⋙ fixHyphenation
  ⋙ fixWhitespace


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
