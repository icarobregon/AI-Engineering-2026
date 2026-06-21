"""Attachment text extraction (Camino B — local extraction).

Design choice: Camino B over Camino A (multimodal Files API) because:
- No provider lock-in: works with any LLM provider via LiteLLM.
- Fine-grained control over what enters the context (chunk size, filtering).
- Prepares the text pipeline for the RAG chunking module introduced in
  sessions 7+, where text must be available locally for embedding.

Supported formats:
- PDF  → pypdf (text-layer only; scanned PDFs without OCR return empty text)
- DOCX → python-docx

Other formats are accepted but their binary content is skipped with a warning
rather than raising, so a bad attachment does not abort the whole request.
"""

from __future__ import annotations

import io
from typing import NamedTuple

import structlog

log = structlog.get_logger()

_SEPARATOR = "--- attachment: {filename} ---"


class ExtractionResult(NamedTuple):
    filename: str
    text: str  # empty string if extraction produced nothing


def extract_text(filename: str, content: bytes) -> ExtractionResult:
    """Extract plain text from *content* based on *filename* extension.

    Returns an ``ExtractionResult`` with the extracted text (possibly empty).
    Never raises — extraction errors are logged and return an empty string so
    the pipeline can continue with the transcript alone.
    """
    lower = filename.lower()
    try:
        if lower.endswith(".pdf"):
            text = _extract_pdf(content)
        elif lower.endswith(".docx"):
            text = _extract_docx(content)
        else:
            log.warning("attachment_format_unsupported", filename=filename)
            text = ""
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "attachment_extraction_failed",
            filename=filename,
            error_type=type(exc).__name__,
            error=str(exc)[:200],
        )
        text = ""

    log.info(
        "attachment_extracted",
        filename=filename,
        chars=len(text),
    )
    return ExtractionResult(filename=filename, text=text)


def _extract_pdf(content: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    parts: list[str] = []
    for page in reader.pages:
        page_text = page.extract_text() or ""
        if page_text.strip():
            parts.append(page_text)
    return "\n".join(parts)


def _extract_docx(content: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(content))
    return "\n".join(para.text for para in doc.paragraphs if para.text.strip())


def build_enriched_description(transcript: str, attachments: list[ExtractionResult]) -> str:
    """Combine transcript with extracted attachment text.

    Each non-empty attachment is appended after a clear separator so the LLM
    can distinguish document context from the user's own words.  The combined
    text is what gets passed to the input guardrails and the estimation LLM.
    """
    parts = [transcript]
    for att in attachments:
        if att.text.strip():
            parts.append(_SEPARATOR.format(filename=att.filename))
            parts.append(att.text)
    return "\n\n".join(parts)
