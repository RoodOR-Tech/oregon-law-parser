{-# LANGUAGE OverloadedStrings #-}

module Main where

import           Amendment
import           Control.Monad            (when)
import           Data.Aeson               (object, (.=))
import           Data.Aeson.Encode.Pretty (encodePretty)
import qualified Data.ByteString.Lazy     as B
import           Data.Eq.Unicode
import           GHC.IO.Exception
import           System.Exit              (exitFailure)
import           Cli
import           Provenance               (makeProvenance)
import           Tika

main ∷ IO ()
main = do
  options ← getOptions
  sourceProvenance ← makeProvenance (inputFilePath options) (sourceUrl options)
  (errCode, rawHTML, stderr') ← runTika options

  when (errCode ≠ ExitSuccess) $ do
    emitFailure sourceProvenance
      [ParseError ExtractionFailed Nothing stderr']
    exitFailure

  case parseAmendment sourceProvenance (paragraphs rawHTML) of
    Right amendment → B.putStr (encodePretty amendment)
    Left errors → do
      emitFailure sourceProvenance errors
      exitFailure

emitFailure provenanceValue errors =
  B.putStr (encodePretty (object
    [ "errors" .= errors
    , "provenance" .= provenanceValue
    ]))
