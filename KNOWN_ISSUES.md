# Known Issues

This file tracks known parser limitations that are intentionally not hidden by changing independently reviewed gold expectations.

## ORS 697.612 amendment missed in Oregon Laws 2009 chapter 604

- **Gold document:** `2009orlaw0604`
- **Bill:** HB 2191
- **Expected action:** amended
- **ORS section:** `697.612`
- **Authoritative source:** Oregon Laws 2009 chapter 604
- **Status:** open parser defect
- **Certification impact:** one false negative in the frozen 50-law certification corpus

The independently reviewed gold expectation remains unchanged. CI #100 on the 50-law certification candidate reported section precision 1.000, section recall 0.9981, and metadata exact match 1.000, which is above the configured recall target of 0.995 and therefore release-certifying.

A future parser fix should make this section detectable from the operative amendment text without introducing false positives or weakening provenance/conflict diagnostics. The frozen benchmark should then demonstrate 1.000 recall if no other regressions are introduced.

## Issue-handling rule

Known parser misses must be fixed in parser behavior or extraction logic. Do not edit independently reviewed gold labels merely to make CI pass. If a gold expectation is later found to be wrong, correct it only after explicit authoritative-source re-review and preserve the review/provenance record.
