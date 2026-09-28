from app.models import DocumentType
from app.services.parsers.act import ActParser
from app.services.parsers.base import BaseParser
from app.services.parsers.invoice import InvoiceCorrectionParser, InvoiceParser
from app.services.parsers.receipt_kkt import ReceiptKKTParser
from app.services.parsers.selfemployed import SelfEmployedParser
from app.services.parsers.tortorg import Torg12Parser, TTNParser
from app.services.parsers.upd import UKDParser, UPDParser

# Registry of parsers by document type
PARSER_REGISTRY: dict[DocumentType, BaseParser] = {}

def register_parsers(db) -> None:
    """Initialize all parsers with DB session"""
    global PARSER_REGISTRY
    PARSER_REGISTRY = {
        DocumentType.RECEIPT_KKT: ReceiptKKTParser(db),
        DocumentType.UPD: UPDParser(db),
        DocumentType.UKD: UKDParser(db),
        DocumentType.INVOICE: InvoiceParser(db),
        DocumentType.INVOICE_CORRECTION: InvoiceCorrectionParser(db),
        DocumentType.ACT: ActParser(db),
        DocumentType.TORG12: Torg12Parser(db),
        DocumentType.TTN: TTNParser(db),
        DocumentType.SELFEMPLOYED: SelfEmployedParser(db),
    }

def get_parser(doc_type: DocumentType, db) -> BaseParser | None:
    """Get a parser for a document type, registering the set on first use.

    Returns None for a type that has no parser, such as the `unknown` sentinel,
    so every caller has to check the result rather than call straight through.
    """
    if doc_type not in PARSER_REGISTRY:
        register_parsers(db)
    return PARSER_REGISTRY.get(doc_type)

__all__ = [
    "BaseParser",
    "ReceiptKKTParser",
    "UPDParser",
    "UKDParser",
    "InvoiceParser",
    "InvoiceCorrectionParser",
    "ActParser",
    "Torg12Parser",
    "TTNParser",
    "SelfEmployedParser",
    "register_parsers",
    "get_parser",
    "PARSER_REGISTRY",
]
