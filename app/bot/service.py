"""Turn an uploaded file into a parsed result.

Only the parsers listed in `IMPLEMENTED` are trusted to return real data.
Everything else is reported to the client as still being in development, so the
bot never invents numbers for a format we have not actually validated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.bot.detect import Detection, detect

# Document types the bot accepts and honestly reports as "in development".
# Empty right now: every type in the registry has a parser that
# scripts/validate_all.py or the receipt layouts actually exercise.
PENDING_TYPES: dict[str, str] = {}


def _make_parser(doc_type: str):
    """Build the parser for a document type, or None when not ready yet."""
    from app.models import DocumentType
    from app.services.parsers import get_parser

    if doc_type == "receipt_kkt":
        from app.services.parsers.receipt_kkt import ReceiptKKTParser

        return ReceiptKKTParser(None)

    mapping = {
        "upd": DocumentType.UPD,
        "ukd": DocumentType.UKD,
        "invoice": DocumentType.INVOICE,
        "invoice_correction": DocumentType.INVOICE_CORRECTION,
        "torg12": DocumentType.TORG12,
        "act": DocumentType.ACT,
        "ttn": DocumentType.TTN,
        "selfemployed": DocumentType.SELFEMPLOYED,
    }
    if doc_type in mapping:
        return get_parser(mapping[doc_type], None)
    return None


@dataclass
class Outcome:
    """What the bot should tell the client about one file."""

    ok: bool
    doc_type: str
    label: str
    source: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    note: str = ""

    @property
    def pending(self) -> bool:
        return not self.ok and self.error == "not_implemented"


async def process(file_bytes: bytes, filename: str | None = None) -> Outcome:
    """Classify the file and parse it with the matching parser."""
    detection: Detection = detect(file_bytes, filename)
    doc_type, label = detection.doc_type, detection.label

    parser = _make_parser(doc_type)
    if parser is None:
        pretty = PENDING_TYPES.get(doc_type)
        if pretty:
            return Outcome(
                ok=False,
                doc_type=doc_type,
                label=label,
                source=detection.source,
                error="not_implemented",
                note=f"{pretty}: формат принят, но парсер ещё не доведён до продакшена.",
            )
        return Outcome(
            ok=False,
            doc_type=doc_type,
            label=label,
            source=detection.source,
            error="unrecognised",
            note=detection.note or "Не понял, что это за документ.",
        )

    try:
        data = await parser.parse(None, file_bytes)
    except Exception as exc:  # a parser crash must not kill the bot
        return Outcome(
            ok=False,
            doc_type=doc_type,
            label=label,
            source=detection.source,
            error="crash",
            note=f"{type(exc).__name__}: {exc}",
        )

    if not isinstance(data, dict):
        data = {"value": str(data)}

    if data.get("error"):
        return Outcome(
            ok=False,
            doc_type=doc_type,
            label=label,
            source=detection.source,
            data=data,
            error="parse_error",
            note=str(data["error"]),
        )

    return Outcome(
        ok=True,
        doc_type=doc_type,
        label=label,
        source=detection.source,
        data=data,
        note=detection.note,
    )
