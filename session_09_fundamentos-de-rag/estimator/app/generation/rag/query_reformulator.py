"""Query stage: raw transcript → structured query → text worth embedding.

The pre-work trace measured why this module exists. Embedding
``02_ambiguous.txt`` whole returns five chunks between distance 0.6441 and
0.6689 (spread 0.0248) and **none** of the four components of the one truly
analogous budget. A short query describing the same project returns those four
in the top four, between 0.3866 and 0.4606. Same corpus, same retriever, same
k: the only variable is the shape of the embedded text.

Strategy: **structured extraction** rather than free-form rewriting. The model
fills a typed object, and the text that gets embedded is composed from those
fields. Rewriting compresses arbitrarily and gives nothing to filter on;
extraction yields both a clean search text and the structural filters.
"""

from __future__ import annotations

from typing import get_args

import structlog
from pydantic import ValidationError

from app.foundation.llm.responses import ResponsesClient, StructuredOutputError
from app.generation.rag.schemas import (
    EstimationQuery,
    ReformulationResult,
    RetrievalFilters,
    Sector,
)

log = structlog.get_logger()

# Sectors actually present in the corpus. Anything the model extracts outside
# this vocabulary is NOT turned into a filter: filtering by "menaje" or
# "retail" would silently empty a result set the vector search would have
# answered well.
KNOWN_SECTORS = frozenset(get_args(Sector))

REFORMULATION_SYSTEM_PROMPT = """You extract a structured search query from a raw \
sales-meeting transcript, so that a retrieval system can find comparable past \
projects in a corpus of historical software budgets.

The transcript is unedited conversation: participants digress, change their \
mind, use pronouns for things mentioned minutes earlier, and discuss options \
they later discard. Your job is to isolate the project that is actually being \
requested.

Rules:

1. Extract ONLY what is explicitly stated or unambiguously inferable from the \
transcript. If the client never said it, it does not go in the output.

2. Do NOT fill gaps with common sense. Do not infer GDPR because personal data \
is involved, do not infer Stripe because payments are mentioned, do not infer a \
sector from the kind of product. Inference of this kind is the single largest \
source of retrieval errors in production: it fabricates filters that exclude \
the correct historical projects.

3. Leave optional fields null and lists empty when there is no evidence. An \
empty field is a correct answer, not a failure.

4. Ignore options the client explicitly discarded, and ignore topics that are \
not the project (scheduling, small talk, pricing of unrelated work).

5. When the client describes several candidate scopes without choosing, name \
the two main ones in `function` rather than retreating to an abstraction that \
covers both. "multi-vendor marketplace and inventory synchronization" retrieves \
comparable projects; "e-commerce platform modernization" retrieves nothing in \
particular.

6. Write every field in English, regardless of the transcript's language: the \
historical corpus is in English and the query is embedded against it.

Field-level rules, because every field here is embedded and long fields dilute \
the signal:

- `function`: 3-7 words naming the product capability. Not the industry, not \
the client. Good: "multi-vendor marketplace with vendor payouts". Bad: "a \
project for a home goods retailer".

- `constraints`: short noun phrases, at most ~12 words each, naming hard \
technical or regulatory requirements. NOT sentences narrating the discussion. \
Exclude anything that is not a requirement on the software: volumes and scale \
figures, deadlines and campaign dates, undecided options, requests about how \
the proposal should be formatted or priced, and the client's internal team \
situation. Good: "inventory synchronization between web shop and physical \
stores". Bad: "Stock synchronization is a priority and should be delivered for \
the Christmas campaign (client expects this timeline)"."""

REWRITE_SYSTEM_PROMPT = """You rewrite a raw sales-meeting transcript as a single \
concise search query, in English, describing the software project the client is \
asking for.

One or two sentences, no preamble, no bullet points. Name the product capability \
and any technology explicitly mentioned. Ignore small talk, scheduling and any \
option the client discarded. Do not invent requirements that are not in the \
transcript."""


def compose_search_text(query: EstimationQuery) -> str:
    """Build the synthetic text that actually gets embedded.

    Deliberately reads like a project description rather than a list of
    key-values: it is embedded against chunks that are themselves prose
    ("Component: … Description: …"), and prose matches prose better than a
    serialized dict does.
    """
    parts = [query.function]
    if query.technologies:
        parts.append(f"with {', '.join(query.technologies)}")
    if query.sector:
        parts.append(f"for the {query.sector} sector")
    if query.country:
        parts.append(f"in {query.country}")
    if query.regulations:
        parts.append(f"compliant with {', '.join(query.regulations)}")
    if query.constraints:
        parts.append(f"requiring {', '.join(query.constraints)}")
    return ". ".join(parts) + "."


def derive_filters(query: EstimationQuery | None) -> RetrievalFilters:
    """Turn an extracted query into structural filters — conservatively.

    Only the sector is derived, and only when it belongs to the corpus
    vocabulary. Country and year are deliberately NOT derived: on a corpus this
    size they are high-selectivity filters that would empty the result set for
    a gain in precision nobody asked for. They remain available to callers of
    ``POST /v1/retrieval/search``, which pass them explicitly and knowingly.

    This is the recall/precision trade-off of the session, resolved in the
    direction the domain demands: a missing analogous budget costs an entire
    estimate; a slightly off-sector one costs a line the reviewer ignores.
    """
    if query is None or not query.sector:
        return RetrievalFilters()

    sector = query.sector.strip().lower()
    if sector not in KNOWN_SECTORS:
        log.info("query_sector_not_in_corpus_vocabulary", sector=sector)
        return RetrievalFilters()
    return RetrievalFilters(sectors=[sector])


class QueryReformulationError(Exception):
    """Both structured extraction and the rewriting fallback failed."""


class QueryReformulator:
    """Transcript → :class:`ReformulationResult`, with a registered fallback."""

    def __init__(self, client: ResponsesClient, model: str) -> None:
        self._client = client
        self._model = model

    def reformulate(self, transcript: str) -> ReformulationResult:
        try:
            query = self._client.parse(
                model=self._model,
                system_prompt=REFORMULATION_SYSTEM_PROMPT,
                user_content=transcript,
                schema=EstimationQuery,
                stage="reformulation",
            )
        except (StructuredOutputError, ValidationError) as exc:
            return self._fallback(transcript, reason=type(exc).__name__, error=str(exc)[:300])

        search_text = compose_search_text(query)
        log.info(
            "query_reformulated",
            function=query.function,
            technologies=query.technologies,
            sector=query.sector,
            scale=query.scale,
            country=query.country,
            search_text_chars=len(search_text),
            transcript_chars=len(transcript),
        )
        return ReformulationResult(search_text=search_text, query=query, used_fallback=False)

    def _fallback(self, transcript: str, *, reason: str, error: str) -> ReformulationResult:
        """Plain query rewriting when structured extraction fails.

        Logged at warning level on purpose: this path is the health metric of
        the stage. Never firing means the schema is too permissive to be
        catching anything; firing on more than ~5% of traffic means the prompt
        or the schema has a systematic problem.
        """
        log.warning("query_reformulation_fallback", reason=reason, error=error)
        try:
            rewritten = self._client.complete_text(
                model=self._model,
                system_prompt=REWRITE_SYSTEM_PROMPT,
                user_content=transcript,
            )
        except Exception as exc:  # noqa: BLE001 — the caller gets one error type.
            raise QueryReformulationError(
                f"Structured extraction failed ({reason}) and rewriting failed too: {exc}"
            ) from exc

        if not rewritten:
            raise QueryReformulationError(
                f"Structured extraction failed ({reason}) and rewriting returned empty text"
            )
        return ReformulationResult(search_text=rewritten, query=None, used_fallback=True)
