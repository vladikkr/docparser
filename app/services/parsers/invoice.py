"""Счёт-фактура and корректировочный счёт-фактура.

ФНС publishes no separate schema for a счёт-фактура: it is the same document
format as a УПД and the two are told apart by the `Функция` attribute. The
implementation therefore lives with the rest of the invoice family in
`upd.py`, and this module is the name the parser registry imports.
"""

from __future__ import annotations

from app.services.parsers.upd import InvoiceCorrectionParser, InvoiceParser

__all__ = ["InvoiceParser", "InvoiceCorrectionParser"]
