# Oregon law parser

Build queryable ORS editions and session-law actions with Python 3.10+:

```sh
python -m pip install -e ".[test,parquet]"
python -m parser.cli run --year 2023 --output ./dist/ors_data.db
```

The portable pipeline uses pdfplumber and SQLite; it does not require Haskell,
Java, Tika, or an external database. It emits `editions`, `chapters`, `sections`,
`amendments`, and `pending_changes`, plus source provenance, styled amendment
tokens and review diagnostics. Add `--parquet-dir dist/parquet` for Parquet.
Downloads are cached and hash-checked; `--manifest ... --offline` replays pinned
sources. Full discovery can take considerable time. For a small real-source run,
add `--chapters 1 --session-limit 2`.

See [portable pipeline usage, schema, queries and validation scope](PORTABLE_PIPELINE.md).
Export a searchable website from the generated database:

```sh
python -m parser.cli explorer --database ./dist/ors_data.db --output ./dist/explorer
python -m http.server 8000 --directory ./dist/explorer
```

Open `http://localhost:8000`. Search exact words across printed versions, browse
chapters, compare versions, inspect additions/deletions, and follow original
PDF sources. The export is static and can be served without a Python backend.
Use a fresh output directory when changing datasets. See [explorer and review
scope](EXPLORER.md) for search semantics and review classifications.

The first printed section version is the publication view; alternate texts and
their timing notes remain queryable in `section_versions`. Inspect `diagnostics`
for session-law clauses that need review. See the [audit](PIPELINE_AUDIT.md) for
the integration decisions and validation boundaries.
Run all Python tests with `python -m pytest -q`. The established
[ORS relational schema](ors/SCHEMA.md) and reviewed preview tools remain available.

```python
import sqlite3
with sqlite3.connect("dist/ors_data.db") as db:
    rows = db.execute("""
        SELECT ors_section, catchline FROM sections
        WHERE edition_year = ? AND chapter_number = ? ORDER BY ors_section
    """, (2023, "161")).fetchall()
```

## Legacy session-law parser

The original Haskell parser and its certification workflows are retained below
for comparison. Their certification does not automatically apply to the new
Python extraction pipeline.

A command line app, `analyze`, which pulls in [an Oregon session law in PDF format](https://www.oregonlegislature.gov/bills_laws/lawsstatutes/2016orLaw0001.pdf):

![image](https://raw.githubusercontent.com/dogweather/analyze-ors-amendment-haskell/master/fixtures/typical-pdf.png)

and produces this metadata in JSON:


```bash
$ analyze 2016orLaw0001.pdf

{
    "summary": "Relating to speed limits on highways that traverse state lines; creating new provisions; amending ORS 811.111; and declaring an emergency.",
    "bill": {
        "billNumber": 4047,
        "billType": "HB"
    }, 
    "effectiveDate": "2016-03-01",
    "year": 2016,
    "affectedSections": {
        "repealed": [],
        "amended": [
            "811.111"
        ]
    }
}
```

A web app can easily import this and display it:

<img width="586" alt="Screenshot 2023-10-10 at 8 32 32 PM" src="https://github.com/public-law/oregon-law-parser/assets/150670/29ebe973-53e7-48b9-9f5f-52cef04e8b0f">


See [Main.hs](https://github.com/dogweather/analyze-ors-amendment-haskell/blob/master/analyze/src/Main.hs) for the top-level code.


# Improving flexibility via this intermediate step

In the past, this kind of coding was in the same project as the rest of the application. E.g., here, it'd be a Ruby rake task because the app is in Rails.

But this new, separate repo decouples the data import process: instead of writing more Ruby code for my Rails app, the JSON data is a go-between format. In this way I can, e.g. use with other languages like Haskell when appropriate.
