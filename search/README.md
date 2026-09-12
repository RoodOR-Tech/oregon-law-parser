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

## Run against real ORS chunks

```bash
python3 search/build_synonym_db.py \
  --input-dir path/to/statute-chunks \
  --db-url sqlite:///ors_synonym_db.sqlite3 \
  --llm-provider anthropic
```

`--input-dir` should contain `.txt` files (optional `CITATION:`/`TITLE:`
header lines, statute body after) and/or `.xml` files
(`<statute citation="..." title="..."><body>...</body></statute>`).
`--db-url` accepts any SQLAlchemy URL, including PostgreSQL
(`postgresql+psycopg2://...`).

## Using it from another program

```python
from search.build_synonym_db import get_engine, get_session_factory, expand_user_query

engine = get_engine("sqlite:///ors_synonym_db.sqlite3")
with get_session_factory(engine)() as session:
    result = expand_user_query("who has to hand over government records", session)
    # result["ors_citations"], result["matched_canonical_terms"], result["alternative_phrases"]
```
