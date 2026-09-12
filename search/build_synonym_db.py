#!/usr/bin/env python3
"""Build a key-term / synonym database from ORS text to power hybrid search.

Pipeline: parse statutory text chunks -> extract statutory definitions ->
optionally expand each statute into layperson questions, colloquial
synonyms and terms of art via an LLM -> persist everything into a
relational schema (SQLite by default, any SQLAlchemy-supported database,
including PostgreSQL, via --db-url) -> expand incoming user search
queries against that table at query time.

This module is independent of, and does not modify, the certified
stdlib-only ORS relational pipeline under ``ors/``. It is a downstream,
best-effort search-quality layer: it can consume plain-text or XML
statutory chunks produced by any source, including ``ors/tools/
parse_ors_chapter.py``'s own ``body_text`` output, but does not require
it.

Run standalone with no arguments to see it work end to end against a
small bundled sample using a deterministic mock LLM client (no API key
required):

    python3 search/build_synonym_db.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import re
import sys
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from sqlalchemy import (
    ForeignKey,
    String,
    Text,
    create_engine,
    func,
    or_,
    select,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

logger = logging.getLogger("ors_synonym_db")


# ---------------------------------------------------------------------------
# 1. Statutory chunk loading
# ---------------------------------------------------------------------------


@dataclass
class StatuteChunk:
    """One statute (or statutory excerpt) ready for parsing."""

    citation: str
    title: Optional[str]
    text_content: str
    source_path: Optional[str] = None


def load_statute_chunks(input_dir: Path) -> List[StatuteChunk]:
    """Load every ``.txt`` and ``.xml`` statute chunk under ``input_dir``.

    A malformed file is logged and skipped rather than aborting the whole
    run -- one bad chunk should not block the rest of the corpus.
    """
    chunks: List[StatuteChunk] = []
    if not input_dir.exists():
        raise FileNotFoundError(f"input directory does not exist: {input_dir}")

    for path in sorted(input_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            if path.suffix.lower() == ".xml":
                chunk = _parse_xml_chunk(path)
            elif path.suffix.lower() == ".txt":
                chunk = _parse_text_chunk(path)
            else:
                continue
        except (OSError, UnicodeDecodeError, ET.ParseError) as exc:
            logger.warning("skipping unreadable chunk %s: %s", path, exc)
            continue
        if chunk is None:
            logger.warning("skipping %s: no citation could be determined", path)
            continue
        chunks.append(chunk)
    return chunks


def _parse_xml_chunk(path: Path) -> Optional[StatuteChunk]:
    """Parse ``<statute citation="..." title="...">text</statute>``."""
    root = ET.parse(path).getroot()
    citation = root.attrib.get("citation") or root.findtext("citation")
    title = root.attrib.get("title") or root.findtext("title")
    text_content = (root.text or "").strip()
    body_el = root.find("body")
    if body_el is not None and body_el.text:
        text_content = body_el.text.strip()
    if not citation or not text_content:
        return None
    return StatuteChunk(citation=citation.strip(), title=(title or "").strip() or None,
                         text_content=text_content, source_path=str(path))


_CITATION_LINE = re.compile(r"^CITATION:\s*(?P<citation>.+)$", re.IGNORECASE)
_TITLE_LINE = re.compile(r"^TITLE:\s*(?P<title>.+)$", re.IGNORECASE)


def _parse_text_chunk(path: Path) -> Optional[StatuteChunk]:
    """Parse a plain-text chunk with optional ``CITATION:``/``TITLE:`` header lines.

    Falls back to scanning the body for an inline ``ORS 192.311`` style
    citation when no header is present.
    """
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    citation: Optional[str] = None
    title: Optional[str] = None
    body_start = 0

    for i, line in enumerate(lines[:5]):
        cm = _CITATION_LINE.match(line)
        tm = _TITLE_LINE.match(line)
        if cm:
            citation = cm.group("citation").strip()
            body_start = i + 1
        elif tm:
            title = tm.group("title").strip()
            body_start = i + 1

    text_content = "\n".join(lines[body_start:]).strip()

    if citation is None:
        m = re.search(r"\bORS\s+(\d{1,4}[A-Z]?\.\d{3,4})\b", raw)
        if m:
            citation = m.group(1)

    if not citation or not text_content:
        return None
    return StatuteChunk(citation=citation, title=title, text_content=text_content,
                         source_path=str(path))


# ---------------------------------------------------------------------------
# 2. Statutory definition extraction
# ---------------------------------------------------------------------------


@dataclass
class ExtractedDefinition:
    """One ``"term" means ...`` entry pulled out of a definitions section."""

    citation: str
    defined_term: str
    definition_text: str


# Scoping phrases that introduce a definitions block. Real ORS text varies
# a great deal after "As used in" -- "this chapter", "ORS 192.311 to
# 192.478", "chapter 743, Oregon Laws 1971, and ORS 166.635", "the statute
# laws of this state" -- and the trailing qualifier varies too ("unless the
# context requires otherwise" vs. "unless the context otherwise requires").
# Matching is deliberately loose (anything up to the line's own colon)
# since this only gates whether a definitions block is present at all; the
# entry pattern below does the real extraction.
_SCOPE_PATTERN = re.compile(r"As used in[^\n:]{0,200}:", re.IGNORECASE)

# A single numbered definition entry: (1) "Term" means the rest of the
# sentence, up to the next numbered entry or the end of the text. Also
# matches ORS's compound form where the first entry under a number carries
# a lettered subpart, e.g. (2)(a) "Term" means ...; a bare lettered
# continuation like "(b) ..." has no digit so it never itself matches as a
# new entry, and stays folded into the (2)(a) entry's own text. A second
# aliased name joined by "or" -- (5) "Service contract holder" or
# "contract holder" means ... -- becomes two rows sharing one definition.
# The verb is deliberately widened past "means"/"includes" to "has" (has
# the meaning given that term in ORS ...) and "is" (is a contract described
# in ORS ...), both real cross-reference definition forms.
_DEFINITION_ENTRY_PATTERN = re.compile(
    r"""\(\s*(?P<num>\d+)\s*\)(?:\([a-z]\))?\s*
        [“"'](?P<term>[^”"']{1,160})[”"']
        (?:\s*or\s*[“"'](?P<term2>[^”"']{1,160})[”"'])?
        \s*
        (?P<verb>means|includes|has|is)[,\s]+
        (?P<definition>.*?)
        (?=(?:\n?\s*\(\d+\)(?:\([a-z]\))?\s*[“"'])|\Z)""",
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)

# A "Definitions" catchline with no leading "As used in ..." scope phrase.
_DEFINITIONS_HEADING_PATTERN = re.compile(r"^\s*Definitions\b", re.IGNORECASE)

_VERBS_KEPT_IN_TEXT = {"includes", "has", "is"}


def extract_definitions(statute_text: str, citation: str) -> List[ExtractedDefinition]:
    """Find explicit statutory definitions inside ``statute_text``.

    Recognizes ORS's two common forms: a scoping sentence ("As used in
    this chapter...") followed by numbered ``"term" means ...`` entries,
    and a bare "Definitions" catchline followed by the same entry shape.
    Returns an empty list -- not an error -- for text with no definitions
    section, which is the normal case for most statutes.
    """
    has_scope = bool(_SCOPE_PATTERN.search(statute_text)) or bool(
        _DEFINITIONS_HEADING_PATTERN.match(statute_text)
    )
    if not has_scope:
        return []

    definitions: List[ExtractedDefinition] = []
    for match in _DEFINITION_ENTRY_PATTERN.finditer(statute_text):
        body = _normalize_whitespace(match.group("definition")).rstrip(".")
        verb = match.group("verb").lower()
        definition_text = f"{verb} {body}." if verb in _VERBS_KEPT_IN_TEXT else f"{body}."
        if not definition_text.strip("."):
            continue
        for group_name in ("term", "term2"):
            raw_term = match.group(group_name)
            if raw_term is None:
                continue
            term = _normalize_whitespace(raw_term)
            if not term:
                continue
            definitions.append(
                ExtractedDefinition(citation=citation, defined_term=term, definition_text=definition_text)
            )
    return definitions


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# 3. LLM-assisted synthetic query expansion
# ---------------------------------------------------------------------------


@dataclass
class QueryExpansion:
    """The synthetic search-training payload generated for one statute."""

    citation: str
    layperson_questions: List[str] = field(default_factory=list)
    colloquial_synonyms: Dict[str, List[str]] = field(default_factory=dict)
    legal_terms_of_art: List[str] = field(default_factory=list)


class LLMRateLimitError(Exception):
    """Raised by an ``LLMClient`` when the provider signals a rate limit."""


class LLMClient(ABC):
    """Minimal async interface every provider adapter implements."""

    @abstractmethod
    async def complete(self, prompt: str) -> str:
        """Return the raw text completion for ``prompt``."""


def _build_expansion_prompt(chunk: StatuteChunk, definitions: Sequence[ExtractedDefinition]) -> str:
    definition_context = ""
    if definitions:
        rendered = "\n".join(f'- "{d.defined_term}": {d.definition_text}' for d in definitions)
        definition_context = f"Formal statutory definitions already extracted:\n{rendered}\n"

    return f"""You are a legal research assistant helping laypeople find Oregon statutes
using everyday language instead of legal terms of art.

ORS Citation: {chunk.citation}
Statute Title: {chunk.title or "(untitled)"}
Statutory Text:
\"\"\"
{chunk.text_content}
\"\"\"
{definition_context}
Respond with ONLY a JSON object (no markdown fences, no commentary) in exactly
this shape:
{{
  "layperson_questions": ["...", "...", "..."],
  "colloquial_synonyms": {{"<legal term>": ["<synonym1>", "<synonym2>"]}},
  "legal_terms_of_art": ["...", "..."]
}}

Generate 3 to 5 "layperson_questions" -- natural search queries a
non-lawyer might type. "colloquial_synonyms" should map each legal term
of art you identify to one or more everyday alternative phrasings.
"""


_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(?P<body>.*?)\s*```", re.DOTALL)


def _parse_llm_response(raw_text: str, citation: str) -> QueryExpansion:
    """Parse an LLM's JSON reply into a ``QueryExpansion``, tolerating fences."""
    fenced = _JSON_FENCE_PATTERN.search(raw_text)
    payload = fenced.group("body") if fenced else raw_text
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"could not parse LLM response for {citation} as JSON: {exc}") from exc

    return QueryExpansion(
        citation=citation,
        layperson_questions=[str(q) for q in data.get("layperson_questions", [])],
        colloquial_synonyms={
            str(term): [str(s) for s in syns]
            for term, syns in dict(data.get("colloquial_synonyms", {})).items()
        },
        legal_terms_of_art=[str(t) for t in data.get("legal_terms_of_art", [])],
    )


async def _with_retries(coro_factory, *, max_retries: int, base_delay: float = 1.0):
    """Run an async call, retrying with exponential backoff + jitter on rate limits."""
    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except LLMRateLimitError:
            if attempt == max_retries:
                raise
            delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
            logger.warning("rate limited, retrying in %.1fs (attempt %d/%d)", delay, attempt + 1, max_retries)
            await asyncio.sleep(delay)


class AnthropicLLMClient(LLMClient):
    """Adapter for the Anthropic Messages API (``pip install anthropic``)."""

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-5", max_retries: int = 5) -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - exercised only without the dep
            raise RuntimeError("AnthropicLLMClient requires 'pip install anthropic'") from exc
        self._anthropic = anthropic
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model
        self.max_retries = max_retries

    async def complete(self, prompt: str) -> str:
        async def _call() -> str:
            try:
                response = await self._client.messages.create(
                    model=self.model,
                    max_tokens=1024,
                    messages=[{"role": "user", "content": prompt}],
                )
            except self._anthropic.RateLimitError as exc:
                raise LLMRateLimitError(str(exc)) from exc
            return "".join(block.text for block in response.content if hasattr(block, "text"))

        return await _with_retries(_call, max_retries=self.max_retries)


class OpenAILLMClient(LLMClient):
    """Adapter for the OpenAI Chat Completions API (``pip install openai``)."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini", max_retries: int = 5) -> None:
        try:
            import openai
        except ImportError as exc:  # pragma: no cover - exercised only without the dep
            raise RuntimeError("OpenAILLMClient requires 'pip install openai'") from exc
        self._openai = openai
        self._client = openai.AsyncOpenAI(api_key=api_key)
        self.model = model
        self.max_retries = max_retries

    async def complete(self, prompt: str) -> str:
        async def _call() -> str:
            try:
                response = await self._client.chat.completions.create(
                    model=self.model,
                    max_tokens=1024,
                    messages=[{"role": "user", "content": prompt}],
                )
            except self._openai.RateLimitError as exc:
                raise LLMRateLimitError(str(exc)) from exc
            return response.choices[0].message.content or ""

        return await _with_retries(_call, max_retries=self.max_retries)


class MockLLMClient(LLMClient):
    """Deterministic, offline stand-in for a real LLM.

    Used by the ``__main__`` demo and by tests so the pipeline is
    exercisable with no API key and no network access.
    """

    async def complete(self, prompt: str) -> str:
        citation_match = re.search(r"ORS Citation:\s*(\S+)", prompt)
        citation = citation_match.group(1) if citation_match else "unknown"
        terms = re.findall(r'"([^"]{2,60})":\s*[^\n]+', prompt)
        terms = terms or ["this statute"]

        payload = {
            "layperson_questions": [
                f"What does ORS {citation} say about {terms[0]}?",
                f"How is {terms[0]} defined under Oregon law?",
                f"What counts as {terms[0]} in Oregon?",
                f"Is there an Oregon statute about {terms[0]}?",
            ],
            "colloquial_synonyms": {term: [f"what counts as {term}", f"{term} explained"] for term in terms},
            "legal_terms_of_art": terms,
        }
        return json.dumps(payload)


async def expand_definitions_with_llm(
    chunks_and_definitions: Sequence[tuple[StatuteChunk, Sequence[ExtractedDefinition]]],
    llm_client: LLMClient,
    concurrency: int = 5,
) -> List[QueryExpansion]:
    """Batch-expand statutes into synthetic queries/synonyms via ``llm_client``.

    Runs with bounded concurrency so a large corpus does not overwhelm the
    provider's rate limits. A single statute's failure (a malformed JSON
    reply, an unrecoverable API error) is logged and skipped rather than
    aborting the whole batch.
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def _run(chunk: StatuteChunk, definitions: Sequence[ExtractedDefinition]) -> Optional[QueryExpansion]:
        async with semaphore:
            prompt = _build_expansion_prompt(chunk, definitions)
            try:
                raw = await llm_client.complete(prompt)
                return _parse_llm_response(raw, chunk.citation)
            except Exception:
                logger.exception("LLM expansion failed for %s", chunk.citation)
                return None

    results = await asyncio.gather(*(_run(chunk, defs) for chunk, defs in chunks_and_definitions))
    return [r for r in results if r is not None]


# ---------------------------------------------------------------------------
# 4. Database schema
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class Statute(Base):
    __tablename__ = "statutes"

    id: Mapped[int] = mapped_column(primary_key=True)
    citation: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    text_content: Mapped[str] = mapped_column(Text, nullable=False)

    definitions: Mapped[List["Definition"]] = relationship(
        back_populates="statute", cascade="all, delete-orphan"
    )
    synonyms: Mapped[List["SynonymKey"]] = relationship(
        back_populates="statute", cascade="all, delete-orphan"
    )


class Definition(Base):
    __tablename__ = "definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    statute_id: Mapped[int] = mapped_column(ForeignKey("statutes.id"), nullable=False, index=True)
    defined_term: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    definition_text: Mapped[str] = mapped_column(Text, nullable=False)

    statute: Mapped["Statute"] = relationship(back_populates="definitions")


class SynonymKey(Base):
    """A row associating a canonical legal term with one alternative phrase.

    ``query_context`` discriminates *why* the row exists so a lookup can
    tell a colloquial synonym apart from a whole synthetic question or a
    bare legal term of art: one of ``"synonym"``, ``"layperson_question"``
    or ``"legal_term_of_art"``.
    """

    __tablename__ = "synonyms_and_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    statute_id: Mapped[int] = mapped_column(ForeignKey("statutes.id"), nullable=False, index=True)
    canonical_term: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    layperson_synonym: Mapped[str] = mapped_column(Text, nullable=False)
    query_context: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    statute: Mapped["Statute"] = relationship(back_populates="synonyms")


def get_engine(db_url: str):
    """Create a SQLAlchemy engine and ensure the schema exists."""
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    return engine


def get_session_factory(engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# 5. Ingestion
# ---------------------------------------------------------------------------


def ingest_statute(
    session: Session,
    chunk: StatuteChunk,
    definitions: Sequence[ExtractedDefinition],
    expansion: Optional[QueryExpansion],
) -> Statute:
    """Insert (or update) one statute plus its definitions and synonym rows.

    Re-running against the same citation replaces that statute's child
    rows rather than duplicating them, so the build is safely re-runnable.
    """
    statute = session.execute(select(Statute).where(Statute.citation == chunk.citation)).scalar_one_or_none()
    if statute is None:
        statute = Statute(citation=chunk.citation, title=chunk.title, text_content=chunk.text_content)
        session.add(statute)
        session.flush()
    else:
        statute.title = chunk.title
        statute.text_content = chunk.text_content
        statute.definitions.clear()
        statute.synonyms.clear()
        session.flush()

    for d in definitions:
        session.add(Definition(statute_id=statute.id, defined_term=d.defined_term, definition_text=d.definition_text))

    if expansion is not None:
        primary_term = next(iter(expansion.colloquial_synonyms), None) or (
            definitions[0].defined_term if definitions else chunk.citation
        )

        for term, synonyms in expansion.colloquial_synonyms.items():
            for synonym in synonyms:
                session.add(
                    SynonymKey(
                        statute_id=statute.id,
                        canonical_term=term,
                        layperson_synonym=synonym,
                        query_context="synonym",
                    )
                )

        for question in expansion.layperson_questions:
            session.add(
                SynonymKey(
                    statute_id=statute.id,
                    canonical_term=primary_term,
                    layperson_synonym=question,
                    query_context="layperson_question",
                )
            )

        covered_terms = set(expansion.colloquial_synonyms)
        for term in expansion.legal_terms_of_art:
            if term in covered_terms:
                continue
            session.add(
                SynonymKey(
                    statute_id=statute.id,
                    canonical_term=term,
                    layperson_synonym=term,
                    query_context="legal_term_of_art",
                )
            )

    session.commit()
    return statute


async def build_database(
    chunks: Sequence[StatuteChunk],
    engine,
    llm_client: Optional[LLMClient] = None,
    concurrency: int = 5,
) -> None:
    """Run the full pipeline: extract definitions, expand via LLM, persist."""
    session_factory = get_session_factory(engine)

    chunk_definitions = [(chunk, extract_definitions(chunk.text_content, chunk.citation)) for chunk in chunks]

    expansions_by_citation: Dict[str, QueryExpansion] = {}
    if llm_client is not None:
        expansions = await expand_definitions_with_llm(chunk_definitions, llm_client, concurrency=concurrency)
        expansions_by_citation = {e.citation: e for e in expansions}

    with session_factory() as session:
        for chunk, definitions in chunk_definitions:
            expansion = expansions_by_citation.get(chunk.citation)
            try:
                ingest_statute(session, chunk, definitions, expansion)
            except Exception:
                session.rollback()
                logger.exception("failed to ingest %s", chunk.citation)


# ---------------------------------------------------------------------------
# 6. Query expansion middleware
# ---------------------------------------------------------------------------


_STOPWORDS = {
    "a", "an", "the", "is", "are", "of", "to", "for", "my", "how", "do", "i",
    "in", "on", "what", "does", "can", "and", "or", "about", "me",
}


def expand_user_query(raw_query: str, db_connection: Session) -> dict:
    """Expand an incoming search string against the synonym/key-term table.

    Args:
        raw_query: the user's raw search text.
        db_connection: an open SQLAlchemy ``Session`` bound to the
            key-term database (SQLite or PostgreSQL).

    Returns:
        A dict payload for a hybrid search layer to consume:
        ``matched_canonical_terms``, ``ors_citations`` and
        ``alternative_phrases`` are deduplicated, sorted lists; ``matches``
        carries the full per-row detail behind them.
    """
    normalized = _normalize_whitespace(raw_query).lower()
    if not normalized:
        return {
            "raw_query": raw_query,
            "normalized_query": normalized,
            "matched_canonical_terms": [],
            "ors_citations": [],
            "alternative_phrases": [],
            "matches": [],
        }

    tokens = [t for t in re.findall(r"[a-z0-9]+", normalized) if len(t) >= 3 and t not in _STOPWORDS]

    conditions = [
        func.lower(SynonymKey.canonical_term).like(f"%{normalized}%"),
        func.lower(SynonymKey.layperson_synonym).like(f"%{normalized}%"),
    ]
    for token in tokens:
        like = f"%{token}%"
        conditions.append(func.lower(SynonymKey.canonical_term).like(like))
        conditions.append(func.lower(SynonymKey.layperson_synonym).like(like))

    stmt = (
        select(SynonymKey, Statute)
        .join(Statute, SynonymKey.statute_id == Statute.id)
        .where(or_(*conditions))
    )

    matched_canonical_terms: set = set()
    ors_citations: set = set()
    alternative_phrases: set = set()
    matches: List[dict] = []

    for synonym_key, statute in db_connection.execute(stmt).all():
        matched_canonical_terms.add(synonym_key.canonical_term)
        ors_citations.add(statute.citation)
        alternative_phrases.add(synonym_key.layperson_synonym)
        matches.append(
            {
                "statute_citation": statute.citation,
                "statute_title": statute.title,
                "canonical_term": synonym_key.canonical_term,
                "layperson_synonym": synonym_key.layperson_synonym,
                "query_context": synonym_key.query_context,
            }
        )

    return {
        "raw_query": raw_query,
        "normalized_query": normalized,
        "matched_canonical_terms": sorted(matched_canonical_terms),
        "ors_citations": sorted(ors_citations),
        "alternative_phrases": sorted(alternative_phrases),
        "matches": matches,
    }


# ---------------------------------------------------------------------------
# 7. Mock data + CLI runner
# ---------------------------------------------------------------------------

# Illustrative sample text approximating the structure of ORS 192.311's
# definitions section, written for this demo -- not a verbatim reproduction
# of the official statute.
_MOCK_CHUNKS = [
    StatuteChunk(
        citation="192.311",
        title="Definitions for ORS 192.311 to 192.478",
        text_content=(
            "As used in ORS 192.311 to 192.478, unless the context requires otherwise:\n"
            '(1) "Attorney fees" means the reasonable attorney fees incurred by a person '
            "in connection with a proceeding to compel a public body to comply with an "
            "order or judgment requiring disclosure of a public record.\n"
            '(2) "Custodian" means the public body that has custody of a public record, '
            "whether or not the public body prepared the record.\n"
            '(3) "Public body" means every state officer, agency, department, division, '
            "bureau, board and commission; every county and city governing body, school "
            "district, special district and municipal corporation; and any board, "
            "department, commission, council or agency of any of the foregoing.\n"
            '(4) "Public record" includes, but is not limited to, a document, book, '
            "paper, photograph, file, sound recording or machine-readable electronic or "
            "electromagnetic data, made, received, filed or recorded by a public body in "
            "connection with the transaction of public business, regardless of physical "
            "form or characteristics."
        ),
    ),
    StatuteChunk(
        citation="192.420",
        title="Right to inspect records",
        text_content=(
            "Every person has a right to inspect any public record of a public body in "
            "this state, except as otherwise expressly provided by ORS 192.311 to "
            "192.478."
        ),
    ),
]


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _build_llm_client(provider: str, model: Optional[str]) -> Optional[LLMClient]:
    if provider == "none":
        return None
    if provider == "mock":
        return MockLLMClient()
    if provider == "anthropic":
        return AnthropicLLMClient(model=model) if model else AnthropicLLMClient()
    if provider == "openai":
        return OpenAILLMClient(model=model) if model else OpenAILLMClient()
    raise ValueError(f"unknown LLM provider: {provider}")


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=None,
        help="Directory of .txt/.xml statutory chunks to ingest (default: bundled mock sample).",
    )
    parser.add_argument(
        "--db-url",
        default="sqlite:///ors_synonym_db.sqlite3",
        help="SQLAlchemy database URL (default: %(default)s). Any PostgreSQL URL also works.",
    )
    parser.add_argument(
        "--llm-provider",
        choices=["mock", "anthropic", "openai", "none"],
        default="mock",
        help="LLM backend for synthetic query expansion (default: %(default)s).",
    )
    parser.add_argument("--llm-model", default=None, help="Override the provider's default model name.")
    parser.add_argument("--concurrency", type=int, default=5, help="Max concurrent LLM requests.")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


async def _async_main(args: argparse.Namespace) -> None:
    chunks = load_statute_chunks(args.input_dir) if args.input_dir else _MOCK_CHUNKS
    if not chunks:
        logger.error("no statute chunks found under %s", args.input_dir)
        sys.exit(1)

    llm_client = _build_llm_client(args.llm_provider, args.llm_model)
    engine = get_engine(args.db_url)

    await build_database(chunks, engine, llm_client=llm_client, concurrency=args.concurrency)

    session_factory = get_session_factory(engine)
    with session_factory() as session:
        statute_count = session.scalar(select(func.count()).select_from(Statute))
        definition_count = session.scalar(select(func.count()).select_from(Definition))
        synonym_count = session.scalar(select(func.count()).select_from(SynonymKey))
        print(f"Ingested {statute_count} statutes, {definition_count} definitions, {synonym_count} synonym rows.")

        for sample_query in ["what is a public record", "who has to hand over government documents", "attorney fees"]:
            result = expand_user_query(sample_query, session)
            print(f"\nQuery: {sample_query!r}")
            print(json.dumps(result, indent=2))


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = _parse_args(argv)
    _configure_logging(args.verbose)
    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
