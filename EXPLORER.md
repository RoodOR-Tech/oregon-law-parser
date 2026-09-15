# Oregon Law Explorer

The `explorer` command publishes static HTML, CSS, JavaScript, and JSON from a
database built with parser 0.3.0 or later. No server-side database, account,
JavaScript package installation, or build system is required to run it locally.
Serve the directory over HTTP; opening `index.html` directly with a file URL
does not permit the JSON fetches used by the application.

The search index includes section identifiers, catchlines, and the body text
of every printed version. Search terms are case-insensitive ASCII letters and
digits, matched as exact words with AND semantics across those versions.
An exact ORS identifier opens the matching result. This is not phrase,
semantic, fuzzy, or stemmed search. Notes and amendment bodies are not in the
statutory text index. The changes view searches action metadata; the review
view searches diagnostic text. Chapter filtering uses the direct ORS target;
uncodified ADD actions have no assigned ORS chapter and appear under All chapters.

Data is split into chapter documents, individual action documents, and word
index shards. The initial load contains the section roster and action/review
metadata; bodies and search shards load on demand. Once exported, the local
site can run without internet except when opening an original source PDF.
The dataset checksum is visible in the footer. Export into a new directory
for each dataset so obsolete assets are not retained.

## Review outcome for the 2023 corpus

The original 326 diagnostics included 13 conditional direct ORS amendments,
one conditional ORS repeal, and one numbered direct ORS repeal. The corrected
parser extracts these 15 additional actions, producing 2,313 actions in total.
The numbered repeal also contains a session-law sunset, retained as a separate
diagnostic. The remaining 312 diagnostic records are classified as:

| Category | Records | Meaning |
| --- | ---: | --- |
| Session-law provision | 294 | Acts on an Act section rather than a directly identified ORS target |
| Series membership | 15 | Makes existing sections part of a series without creating their text |
| Incidental repeal reference | 3 | Continuity, severability, or reporting language referring to repeal |

Classification is conservative and rule-based. Unrecognized forms remain
`review_required`; no evidence is deleted or converted into a guessed ORS
target. Zero unclassified diagnostics in this corpus is not proof of complete
amendment recall or legal effect. Uncodified actions and temporal linking are
still outside the direct-ORS action model.

Two additive tables preserve the new evidence:

- `amendment_context(amendment_id, condition_text, operative_text)` retains
  the complete operative instruction and any recognized enactment contingency.
  Conditions are not resolved. Repealing an earlier *amending Act section*
  does not by itself mean the underlying ORS section is repealed.
- `diagnostic_reviews(diagnostic_id, category, disposition, explanation)`
  records the deterministic classification alongside the original diagnostic.

The section view remains the printed edition, not an as-of-date consolidation.
Side-by-side comparison shows printed versions, not a computed legal redline.
Action redlines use source typography and deletion brackets. All 284 alternate
versions, 1,024 pending/publication notices, source links, and original flags
remain available. Source PDFs remain the evidence for interpretation.

The optional WebMCP search tool uses the same visible search flow when the
browser supports it. It is not required to use the explorer.
