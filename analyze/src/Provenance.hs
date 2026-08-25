{-# LANGUAGE DeriveGeneric #-}

module Provenance
  ( Provenance(..)
  , makeProvenance
  ) where

import           Crypto.Hash            (Digest, SHA256, hashlazy)
import           Data.Aeson             (ToJSON)
import qualified Data.ByteString.Lazy   as B
import           Data.Time              (UTCTime, getCurrentTime)
import           GHC.Generics


data Provenance =
  Provenance {
    sourcePath   ∷ FilePath,
    sourceUrl    ∷ Maybe String,
    sourceSha256 ∷ String,
    processedAt  ∷ UTCTime
  } deriving (Eq, Show, Generic)

instance ToJSON Provenance

makeProvenance ∷ FilePath → Maybe String → IO Provenance
makeProvenance path url = do
  bytes ← B.readFile path
  now ← getCurrentTime
  let digest = show (hashlazy bytes ∷ Digest SHA256)
  pure Provenance {
    sourcePath = path,
    sourceUrl = url,
    sourceSha256 = digest,
    processedAt = now
  }
