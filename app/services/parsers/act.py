"""Акт выполненных работ / оказанных услуг.

ФНС publishes this format under приказ ММВ-7-10/552@, and it shares its
structure with ТОРГ-12 rather than with the invoice family: the work lines live
in `<ОписРабот><Работа>` and the participants use `СвЮЛ`. The implementation
therefore sits with ТОРГ-12 and ЭТрН in `tortorg.py`, and this module is the
name the parser registry imports.
"""

from __future__ import annotations

from app.services.parsers.tortorg import ActParser

__all__ = ["ActParser"]
