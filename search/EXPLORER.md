# Oregon Law Explorer integration

The Explorer combines existing text results with PR #90's actual
`expand_user_query(query, session)` results using reciprocal-rank fusion.
Python, SQLAlchemy and SQLite run in a module Web Worker using a pinned,
self-hosted Pyodide runtime. No API key or LLM call runs in the browser.
This is text plus term/synonym search; it does not use vector embeddings.
Exact citations remain first, filters apply to both result sources, and
runtime failures leave ordinary text search available.

## Build and review

From the repository root, install `pip install -e '.[search-openai]'`
(or `.[search-anthropic]`). Configure the chosen provider's API key in
the environment. Use an explicit model supported by that account.

```sh
python -m search.explorer_bridge build --ors-db dist/ors_data.db --output dist/definitions.sqlite3
python -m search.explorer_bridge build --ors-db dist/ors_data.db --base-db dist/definitions.sqlite3 --output dist/review.sqlite3 --llm-provider openai --llm-model MODEL --llm-citations 192.311,90.100,161.015,646A.602
python -m search.browser_runtime --output dist/runtime
```

The first command builds definitions and literal term keys for primary
operative printed texts. The second reuses that verified build and calls
the real provider for only the listed statutes. The existing ORS rows
adapter is reused; no ORS parser code is imported. Output paths must be new.

Read every prompt and raw response in `dist/review.audit/`. Check JSON
validity, whether phrases express the statutory definitions, and whether
questions misstate or broaden the law. Malformed responses are retained
and fail the build. After reviewing all responses, set `manually_reviewed`
to true and record the reviewer, model, citations and findings in
`review_note` in `dist/review.build.json`. Do not approve a mock or
definitions-only run. The export checks source, database, module, audit
and runtime hashes and rejects incomplete review.

Generate the normal Explorer with `python -m parser.cli explorer --help`
for its options, then attach the reviewed layer:

```sh
python -m search.explorer_bridge export --database dist/review.sqlite3 --explorer dist/explorer --runtime dist/runtime
```

Publish that static directory using the target's hosting workflow. The UI
shows the number of sections with reviewed LLM phrases; a four-section
trial is not full-corpus LLM coverage. Keep the full search database and
audit alongside build records. The published query copy omits statute body
text, which the normal Explorer data already supplies.

## Verification and current limits

```sh
python -m unittest discover -s search/tests -v
python -m pytest -q
node search/tests/test_hybrid_rank.mjs
python -m search.browser_runtime --output dist/runtime --verify-only
```

For a real Postgres check, install `psycopg2-binary`, configure `DATABASE_URL`,
and run `python -m search.verify_postgres --ors-rows-file SAMPLE.json
--report postgres-report.json`. The probe creates and removes a uniquely
named schema, checks Unicode, query expansion, reingestion and rollback.
It does not require or claim LLM output. Explorer production uses static
SQLite rather than Postgres.

As of this integration's local verification, PostgreSQL 17.11 round-trips
passed; the real browser Python query and Explorer UI search passed using
literal keys. The full build contains 38,763 operative statutes, 10,708
definitions and 10,696 literal keys. **Real-provider output review and
production publication remain pending an API key.** Automated mock tests
do not close that requirement. PR #90's extraction regex and public
function signatures are preserved; the rows reader has a tested UTF-8
portability fix for Windows.
