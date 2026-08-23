module Main where

import           Amendment
import           Control.Arrow.Unicode
import           Control.Monad
import           Data.Aeson.Encode.Pretty (encodePretty)
import qualified Data.ByteString.Lazy     as B
import           Data.Eq.Unicode
import           Data.Function            ((&))
import           GHC.IO.Exception
import           Cli
import           Tika

main ∷ IO ()
main = do
  (errCode, rawHTML, stderr') ← runTika =<< getOptions
  when (errCode ≠ ExitSuccess)
    (fail stderr')

  B.putStr (tikaOutputToJson rawHTML)

tikaOutputToJson ∷ String → B.ByteString
tikaOutputToJson = paragraphs ⋙ makeAmendment ⋙ encodePretty

makeAmendment ∷ [String] → Amendment
makeAmendment phrases =
  let summaryText = phrases |> findSummary
      titleChanges = summaryText |> findChangedStatutes
      bodyChanges = phrases |> findBodyChangedStatutes
  in Amendment {
    bill             = phrases |> findCitation |> makeBill,
    summary          = summaryText,
    affectedSections = selectBestChangeSet titleChanges bodyChanges,
    year             = phrases |> findYear,
    effectiveDate    = phrases |> findEffectiveDate,
    chapter          = phrases |> findChapter,
    validation       = reconcileChangeSets titleChanges bodyChanges
  }

-- Function application operator from Elm, F#, and Elixir
(|>) = (&)
