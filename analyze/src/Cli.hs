module Cli
  ( Options(..)
  , getOptions
  ) where

import           Options.Applicative
import           Data.Semigroup      ((<>))


data Options =
  Options {
    inputFilePath  ∷ FilePath,
    tikaJarPath    ∷ Maybe FilePath,
    javaExecutable ∷ String,
    sourceUrl      ∷ Maybe String
  } deriving (Show)


getOptions ∷ IO Options
getOptions = execParser cli


cli ∷ ParserInfo Options
cli = info (optionsP <**> helper)
   ( fullDesc
  <> progDesc "Extracts Oregon session law metadata."
  <> header   "A command line app, which pulls in an Oregon session law\
              \ in PDF format and extracts this metadata to JSON." )


optionsP ∷ Parser Options
optionsP =
  Options
  <$> argument str
     ( metavar "FILENAME"
    <> help    "Path to .PDF file" )
  <*> optional
     ( strOption
        ( short   't'
       <> long    "tika-jar"
       <> metavar "PATH_TO_JAR"
       <> help    "Path to Tika's .JAR file" ) )
  <*> strOption
     ( short   'j'
    <> long    "java-executable"
    <> value   "java"
    <> metavar "JAVA_EXECUTABLE"
    <> help    "Name of Java executable" )
  <*> optional
     ( strOption
        ( long    "source-url"
       <> metavar "URL"
       <> help    "Canonical source URL for provenance" ) )
