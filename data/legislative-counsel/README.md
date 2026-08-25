# Oregon Legislative Counsel validation data

This directory defines the normalized input contract for independent validation against Oregon Legislative Counsel (LC) ORS update tables.

## Why this exists

The session-law parser and the LC tables are independent representations of the same legal changes. Production-quality output should reconcile the parser's extracted ORS amendments/repeals against LC records for the same Oregon Laws chapter.

LC publishes update tables by ORS volume. Table 1 identifies ORS sections amended, repealed, or "added to" and provides the corresponding Oregon Laws chapter and section.

Authoritative index:
https://www.oregonlegislature.gov/lc/Pages/ORSupdate.aspx

## Normalized CSV schema

```text
ors_section,action,oregon_laws_chapter,oregon_laws_section,source_url,source_year,source_volume
```

### Fields

- `ors_section`: ORS section or range exactly as represented by LC.
- `action`: `amended`, `repealed`, or `added_to`.
- `oregon_laws_chapter`: Oregon Laws chapter number.
- `oregon_laws_section`: Oregon Laws section value; stored as text because LC can use non-simple values.
- `source_url`: LC document URL.
- `source_year`: session/update year.
- `source_volume`: ORS volume number.

## Reconciliation rules

1. Match LC rows to a parsed document by Oregon Laws year and chapter.
2. Compare `amended` and `repealed` rows against the parser's operative-body `ChangeSet`.
3. Do **not** treat `added_to` as an amendment or repeal; retain it as separate evidence.
4. If parser and LC amendment/repeal sets match exactly, status is `LCVerified`.
5. If LC has evidence for the chapter but differs from the parser, status is `LCConflict` and the record requires review.
6. If LC contains no amendment/repeal evidence for that chapter, status is `LCNoEvidence`; absence is not proof that the parser is correct.
7. Preserve source URL and, in production ingestion, a SHA-256 hash of the downloaded LC document.

## Sample

`2026-sample.csv` contains a few representative rows transcribed from LC's 2026 update tables solely to exercise the normalized format. It is not a complete 2026 dataset.
