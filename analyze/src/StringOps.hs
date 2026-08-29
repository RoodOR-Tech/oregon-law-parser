module StringOps(cleanUp, firstMatch, join, fixHyphenation, fixWhitespace) where

import Control.Arrow.Unicode ( (⋙) )
import Data.List             (foldl', isSuffixOf)
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
fixHyphenation ∷ String → String
fixHyphenation =
  repairKnownLineBreakWords
  ⋙ preserveUnknownLineBreakHyphens


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


repairKnownLineBreakWords ∷ String → String
repairKnownLineBreakWords input =
  foldl' (flip repairWord) input parserCriticalWords


repairWord ∷ String → String → String
repairWord word input =
  foldl' repairAt input [1 .. length word - 1]
  where
    repairAt text index =
      let (left, right) = splitAt index word
          brokenForms =
            [ left ++ "-\n" ++ right
            , left ++ "-\r\n" ++ right
            , left ++ "-\r" ++ right
            , left ++ "- \n" ++ right
            , left ++ "- \r\n" ++ right
            , left ++ "- \r" ++ right
            ]
      in foldl' (\result broken -> replace broken word result) text brokenForms


preserveUnknownLineBreakHyphens ∷ String → String
preserveUnknownLineBreakHyphens =
  replace "- \r\n" "-"
  ⋙ replace "- \n" "-"
  ⋙ replace "- \r" "-"
  ⋙ replace "-\r\n" "-"
  ⋙ replace "-\n" "-"
  ⋙ replace "-\r" "-"


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
