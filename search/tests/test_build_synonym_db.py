"""Regression tests for search/build_synonym_db.py.

Each `extract_definitions` case below is a minimal, synthetic snippet
reproducing one real structural form found while measuring the extractor
against the actual ORS chapter 1/90/161/174/192/279A/646A sample text --
see the two commits that fixed these gaps for the real citations each
form came from. The point of freezing them here is that a future change
to the regex can't silently regress one of these without a test failing.
"""

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build_synonym_db import (  # noqa: E402
    MockLLMClient,
    StatuteChunk,
    build_database,
    expand_definitions_with_llm,
    expand_user_query,
    extract_definitions,
    get_engine,
    get_session_factory,
    ingest_statute,
    load_statute_chunks,
)


class ExtractDefinitionsTests(unittest.TestCase):
    def test_flat_numbered_entries(self):
        text = (
            "As used in ORS 192.311 to 192.478, unless the context requires otherwise:\n"
            '(1) "Attorney fees" means the reasonable attorney fees incurred.\n'
            '(2) "Custodian" means the public body that has custody of a record.'
        )
        defs = extract_definitions(text, "192.311")
        self.assertEqual([d.defined_term for d in defs], ["Attorney fees", "Custodian"])
        self.assertEqual(defs[0].definition_text, "the reasonable attorney fees incurred.")

    def test_no_scope_phrase_returns_empty(self):
        text = "Every person has a right to inspect any public record of a public body."
        self.assertEqual(extract_definitions(text, "192.420"), [])

    def test_compound_lettered_anchor(self):
        # ORS 646A.005: a numbered entry whose first sentence is itself split
        # into lettered subparts before the next numbered entry begins.
        text = (
            "As used in this section:\n"
            '(1) "Animal" means a live, nonhuman vertebrate.\n'
            '(2)(a) "Cosmetic" means a product applied to the human body.\n'
            '(b) "Cosmetic" does not include soap.\n'
            '(3) "Supplier" means a person that supplies an ingredient.'
        )
        defs = extract_definitions(text, "646A.005")
        terms = [d.defined_term for d in defs]
        self.assertEqual(terms, ["Animal", "Cosmetic", "Supplier"])
        self.assertIn("a product applied", defs[1].definition_text)

    def test_qualifier_clause_before_verb(self):
        # ORS 646A.725: a clause citing another ORS section (with its own
        # decimal point) sits between the term and "means".
        text = (
            "As used in this section:\n"
            '(5) "Equity purchaser," except as provided in ORS 646A.730, means '
            "a person that enters into an equity conveyance."
        )
        defs = extract_definitions(text, "646A.725")
        self.assertEqual(len(defs), 1)
        self.assertEqual(defs[0].defined_term, "Equity purchaser,")
        self.assertIn("a person that enters into", defs[0].definition_text)

    def test_verb_has_meaning_given(self):
        text = (
            "As used in this section:\n"
            '(6) "Public body" has the meaning given that term in ORS 174.109.'
        )
        defs = extract_definitions(text, "192.820")
        self.assertEqual(len(defs), 1)
        self.assertTrue(defs[0].definition_text.startswith("has the meaning given"))

    def test_verb_is_cross_reference(self):
        text = 'As used in this section:\n(4) "Service contract" is a contract described in ORS 646A.154.'
        defs = extract_definitions(text, "646A.152")
        self.assertEqual(len(defs), 1)
        self.assertTrue(defs[0].definition_text.startswith("is a contract described"))

    def test_two_name_alias_produces_two_rows(self):
        text = (
            "As used in this section:\n"
            '(5) "Service contract holder" or "contract holder" means a person '
            "that purchases or holds a service contract."
        )
        defs = extract_definitions(text, "646A.152")
        terms = sorted(d.defined_term for d in defs)
        self.assertEqual(terms, ["Service contract holder", "contract holder"])
        self.assertEqual(defs[0].definition_text, defs[1].definition_text)

    def test_bare_colon_pushes_verb_down_a_level(self):
        # ORS 192.005: the term is followed only by a colon; the real verb
        # ("Means"/"Does not include") is on the lettered sub-item below it.
        text = (
            "As used in this section:\n"
            '(5) "Public record":\n'
            "(a) Means any information prepared by a state agency.\n"
            "(b) Does not include records of the Legislative Assembly.\n"
            '(6) "State agency" means any state officer or board.'
        )
        defs = extract_definitions(text, "192.005")
        self.assertEqual([d.defined_term for d in defs], ["Public record", "State agency"])
        self.assertIn("Means any information", defs[0].definition_text)

    def test_negative_definition_does_not_mean(self):
        text = (
            "As used in this section:\n"
            '(2) "Business day" does not mean a Saturday or a legal holiday.'
        )
        defs = extract_definitions(text, "646A.725")
        self.assertEqual(len(defs), 1)
        self.assertTrue(defs[0].definition_text.startswith("does not mean"))

    def test_scope_phrase_variants(self):
        variants = [
            "As used in chapter 743, Oregon Laws 1971, and ORS 166.635, unless the "
            'context requires otherwise:\n(1) "Act" means a bodily movement.',
            "As used in the statute laws of this state, unless the context or a "
            'specially applicable definition requires otherwise:\n(1) "City" includes '
            "any incorporated village or town.",
            'As used in this chapter, unless the context otherwise requires:\n'
            '(1) "Tenant" means a person entitled to occupy a dwelling unit.',
        ]
        for text in variants:
            with self.subTest(text=text[:40]):
                defs = extract_definitions(text, "test")
                self.assertEqual(len(defs), 1)


class QueryExpansionMiddlewareTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "test.sqlite3"
        self.engine = get_engine(f"sqlite:///{db_path}")
        self.session_factory = get_session_factory(self.engine)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_ingest_and_expand_user_query(self):
        # Ingest directly so this test is independent of the LLM pipeline.
        chunk = StatuteChunk(citation="192.311", title="Definitions", text_content="text")
        from build_synonym_db import QueryExpansion

        expansion = QueryExpansion(
            citation="192.311",
            layperson_questions=["Who has to hand over government records?"],
            colloquial_synonyms={"Public body": ["government agency", "state office"]},
            legal_terms_of_art=["Public body", "Custodian"],
        )
        with self.session_factory() as session:
            ingest_statute(session, chunk, [], expansion)

        with self.session_factory() as session:
            result = expand_user_query("government agency", session)
            self.assertIn("192.311", result["ors_citations"])
            self.assertIn("Public body", result["matched_canonical_terms"])

            result_empty = expand_user_query("zzz_no_match_zzz", session)
            self.assertEqual(result_empty["matches"], [])

            result_blank = expand_user_query("   ", session)
            self.assertEqual(result_blank["matches"], [])

    def test_reingesting_same_citation_replaces_rows_not_duplicates(self):
        chunk = StatuteChunk(citation="1.001", title="T", text_content="body one")
        with self.session_factory() as session:
            ingest_statute(session, chunk, [], None)

        chunk2 = StatuteChunk(citation="1.001", title="T", text_content="body two")
        with self.session_factory() as session:
            ingest_statute(session, chunk2, [], None)

        from sqlalchemy import func, select

        from build_synonym_db import Statute

        with self.session_factory() as session:
            count = session.scalar(select(func.count()).select_from(Statute))
            self.assertEqual(count, 1)
            statute = session.execute(select(Statute)).scalar_one()
            self.assertEqual(statute.text_content, "body two")


class BuildDatabaseEndToEndTests(unittest.TestCase):
    def test_full_pipeline_with_mock_llm(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "e2e.sqlite3"
            engine = get_engine(f"sqlite:///{db_path}")
            chunk = StatuteChunk(
                citation="192.311",
                title="Definitions",
                text_content=(
                    "As used in ORS 192.311 to 192.478:\n"
                    '(1) "Public body" means every state officer, agency or board.'
                ),
            )
            asyncio.run(build_database([chunk], engine, llm_client=MockLLMClient()))

            from sqlalchemy import func, select

            from build_synonym_db import Definition, Statute, SynonymKey

            session_factory = get_session_factory(engine)
            with session_factory() as session:
                self.assertEqual(session.scalar(select(func.count()).select_from(Statute)), 1)
                self.assertGreaterEqual(session.scalar(select(func.count()).select_from(Definition)), 1)
                self.assertGreater(session.scalar(select(func.count()).select_from(SynonymKey)), 0)

                result = expand_user_query("public body", session)
                self.assertIn("192.311", result["ors_citations"])


class LoadStatuteChunksTests(unittest.TestCase):
    def test_text_and_xml_chunks_load_malformed_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "167.007.txt").write_text(
                "CITATION: 167.007\nTITLE: Definitions\nAs used in this section:\n"
                '(1) "Sexual conduct" means human contact.'
            )
            (root / "999.999.xml").write_text(
                '<statute citation="999.999" title="Made up">'
                "<body>As used in this section: (1) “Widget” means a device.</body>"
                "</statute>"
            )
            (root / "broken.xml").write_text('<statute citation="broken"><body>unterminated')

            chunks = load_statute_chunks(root)
            citations = sorted(c.citation for c in chunks)
            self.assertEqual(citations, ["167.007", "999.999"])


class LLMExpansionTests(unittest.TestCase):
    def test_expand_definitions_with_mock_llm_batch(self):
        chunk = StatuteChunk(citation="1.001", title="T", text_content="text")
        defs = extract_definitions(
            'As used in this section:\n(1) "Widget" means a device.', "1.001"
        )
        results = asyncio.run(
            expand_definitions_with_llm([(chunk, defs)], MockLLMClient(), concurrency=2)
        )
        self.assertEqual(len(results), 1)
        self.assertGreaterEqual(len(results[0].layperson_questions), 1)


if __name__ == "__main__":
    unittest.main()
