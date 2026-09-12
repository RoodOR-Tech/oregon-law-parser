# Key-term / synonym search database

`build_synonym_db.py` is a standalone module that builds a search-quality
layer on top of ORS statutory text: it extracts explicit statutory
definitions, optionally expands each statute into layperson questions and
colloquial synonyms via an LLM, and persists everything into a small
relational schema (`statutes`, `definitions`, `synonyms_and_keys`) so a
hybrid search system can bridge everyday phrasing and legal terms of art.

This is a separate, best-effort downstream layer, not part of the
certified stdlib-only `ors/` relational pipeline: it depends on SQLAlchemy
and (optionally) an LLM SDK, and it does not modify anything under
`analyze/`, `tools/`, `gold/`, `operations/`, `validation/`, `fixtures/` or
`ors/`. It can consume `body_text` from `ors/tools/parse_ors_chapter.py`'s
own output, or any other plain-text/XML statutory chunks.

## Install

```bash
pip install -r search/requirements.txt
# plus, if you plan to call a real LLM:
pip install anthropic   # or: pip install openai
```

## Run the demo

No API key or input data required — runs against a small bundled sample
using a deterministic offline mock LLM client:

```bash
python3 search/build_synonym_db.py
```

## Run against the real ORS relational pipeline

The most direct path: parse real chapters with the existing `ors/`
pipeline, then hand its rows straight to this module.

```bash
python3 ors/tools/acquire_ors_chapters.py \
  --chapters-file ors/sample/chapters.json \
  --output-dir ors-sources --report ors-acquisition.json
python3 ors/tools/parse_ors_chapter.py \
  --acquisition-report ors-acquisition.json \
  --report ors-parse.json --rows ors-rows.json

python3 search/build_synonym_db.py \
  --ors-rows-file ors-rows.json \
  --db-url sqlite:///ors_synonym_db.sqlite3 \
  --llm-provider anthropic
```

`--ors-rows-file` reads `ors-rows.json`'s `sections` array directly
(`sectionNumber`, `catchline`, `bodyText`), filtered to `status:
"operative"` by default -- a repealed/renumbered/reserved/note_only stub
carries no live text to extract definitions from. This is a
one-directional, data-only read of that pipeline's output file; this
module still does not import any of its code, and the `ors/` pipeline
does not know this module exists.

## Run against ad hoc statute chunks

```bash
python3 search/build_synonym_db.py \
  --input-dir path/to/statute-chunks \
  --db-url sqlite:///ors_synonym_db.sqlite3 \
  --llm-provider anthropic
```

`--input-dir` should contain `.txt` files (optional `CITATION:`/`TITLE:`
header lines, statute body after) and/or `.xml` files
(`<statute citation="..." title="..."><body>...</body></statute>`).
`--input-dir` and `--ors-rows-file` are mutually exclusive. `--db-url`
accepts any SQLAlchemy URL, including PostgreSQL
(`postgresql+psycopg2://...`).

## Using it from another program

```python
from search.build_synonym_db import get_engine, get_session_factory, expand_user_query

engine = get_engine("sqlite:///ors_synonym_db.sqlite3")
with get_session_factory(engine)() as session:
    result = expand_user_query("who has to hand over government records", session)
    # result["ors_citations"], result["matched_canonical_terms"], result["alternative_phrases"]
```
