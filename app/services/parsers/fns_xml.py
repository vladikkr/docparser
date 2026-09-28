"""Shared helpers for the ФНС electronic document formats (приказ ЕД-7-26/970@).

Everything here was checked against the published XSDs, and several details are
counter-intuitive enough to be worth stating once:

* The instance documents carry NO namespace. The XSDs are shipped in a `Схемы`
  folder next to the file and referenced by name, so element names are plain
  Russian words.
* A счёт-фактура and a УПД are the *same* schema. Only the `Функция` attribute
  tells them apart, and there is no separate "СФ" element.
* `<СведТов>` keeps its money and names in *attributes*, but `<СумНал>` is a
  child element that either wraps a number or says "без НДС".
* The document number and date do not sit on `<Документ>`; they live on
  `<СвСчФакт НомерДок=... ДатаДок=...>`.
* Real files are windows-1251 and EDO operators append a detached signature
  (`<УлПрав>`, `<ИнфПрав>`) after `<Файл>`, which breaks the declared sequence.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Iterator

# КНД codes published by ФНС.
KND_INVOICE_LIKE = "1115131"  # УПД and СФ, seller title
KND_INVOICE_LIKE_BUYER = "1115132"  # the same, buyer title
KND_CORRECTION = "1115133"  # УКД / корректировочный счёт-фактура
KND_TORG12 = "1175010"  # товарная накладная
KND_ACT = "1175012"  # акт выполненных работ

# `Функция` values for the invoice family. The correction values live in the
# separate УКД schema (КСЧФ, КСЧФДИС, ДИС, СвИСРК, СвИСЗК).
FUNCTIONS_ORIGINAL = {"СЧФ", "СЧФДОП", "ДОП", "СвРК", "СвЗК"}


class FnsParseError(ValueError):
    """The file is not a document of the expected ФНС format."""


def localname(tag: str) -> str:
    """Tag name without any namespace, so lookups work either way."""
    return tag.rsplit("}", 1)[-1]


def find_all(root: ET.Element, name: str) -> Iterator[ET.Element]:
    """Every descendant with the given local name, in document order."""
    for node in root.iter():
        if localname(node.tag) == name:
            yield node


def find_first(root: ET.Element, *names: str) -> ET.Element | None:
    """First descendant matching any of the given local names."""
    wanted = set(names)
    for node in root.iter():
        if localname(node.tag) in wanted:
            return node
    return None


def direct_child(element: ET.Element, *names: str) -> ET.Element | None:
    """First *direct* child with the given local name."""
    wanted = set(names)
    for node in element:
        if localname(node.tag) in wanted:
            return node
    return None


def children(element: ET.Element, name: str) -> list[ET.Element]:
    """All direct children with the given local name."""
    return [node for node in element if localname(node.tag) == name]


def text_of(element: ET.Element | None) -> str:
    """Stripped text of an element, or an empty string."""
    if element is None or element.text is None:
        return ""
    return element.text.strip()


def child_text(element: ET.Element, *names: str) -> str:
    """Text of the first direct child matching any name."""
    return text_of(direct_child(element, *names))


def to_number(value: str) -> float | None:
    """ФНС writes plain decimals with a dot; be forgiving about the rest."""
    if value is None:
        return None
    cleaned = re.sub(r"[^0-9,.\-]", "", str(value)).replace(",", ".")
    if not cleaned or cleaned in {"-", ".", "-."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def load_xml(file_bytes: bytes) -> ET.Element:
    """Parse a ФНС document, coping with the encoding and the appended signature.

    The declared encoding is honoured first because real files are windows-1251.
    """
    if not file_bytes.strip():
        raise FnsParseError("Пустой файл")

    try:
        return ET.fromstring(file_bytes)
    except ET.ParseError:
        pass

    # No usable declaration: try the encodings we actually see in the wild.
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return ET.fromstring(file_bytes.decode(encoding))
        except (ET.ParseError, UnicodeDecodeError):
            continue

    raise FnsParseError("Файл не является корректным XML")


def document_root(root: ET.Element) -> ET.Element:
    """The `<Документ>` element, whether or not `<Файл>` wraps it."""
    if localname(root.tag) == "Документ":
        return root
    found = find_first(root, "Документ")
    if found is None:
        raise FnsParseError("В файле нет элемента <Документ>")
    return found


def knd_of(root: ET.Element) -> str:
    return (document_root(root).get("КНД") or "").strip()


def function_of(root: ET.Element) -> str:
    return (document_root(root).get("Функция") or "").strip()


def _fio_text(participant: ET.Element) -> str:
    """Assemble a person's name from the <ФИО> attributes."""
    fio = direct_child(participant, "ФИО")
    if fio is None:
        return ""
    parts = [fio.get(attr, "") for attr in ("Фамилия", "Имя", "Отчество")]
    return " ".join(part for part in parts if part).strip()


def parse_participant(element: ET.Element) -> dict[str, Any]:
    """Read a participant from either participant family.

    The УПД/СФ family hangs `СвЮЛУч` / `СвИП` / `СвФЛУч` under `<ИдСв>` and uses
    ИННЮЛ/ИННФЛ, while ТОРГ-12 and Акт use `СвЮЛ` / `СвФЛ` nested one level
    deeper under `<ИдСв><СвОрг>`. Both shapes turn up in real files, so the
    wrapper levels are walked rather than assumed.
    """
    result: dict[str, Any] = {"name": "", "inn": "", "kpp": "", "type": ""}
    if element is None:
        return result

    holder = direct_child(element, "ИдСв") or element
    organisation = direct_child(holder, "СвОрг")
    if organisation is not None:
        holder = organisation

    legal = direct_child(holder, "СвЮЛУч", "СвЮЛ")
    if legal is not None:
        result.update(
            name=(legal.get("НаимОрг") or "").strip(),
            inn=(legal.get("ИННЮЛ") or "").strip(),
            kpp=(legal.get("КПП") or "").strip(),
            type="legal",
        )
        return result

    individual = direct_child(holder, "СвИП")
    if individual is not None:
        result.update(
            name=_fio_text(individual) or _fio_text(element),
            inn=(individual.get("ИННФЛ") or "").strip(),
            type="individual",
        )
        return result

    person = direct_child(holder, "СвФЛУч", "СвФЛ")
    if person is not None:
        result.update(
            name=_fio_text(person) or _fio_text(element),
            inn=(person.get("ИННФЛ") or "").strip(),
            type="person",
        )
        return result

    # A participant from abroad, which carries no domestic INN at all.
    foreign = direct_child(holder, "СвИнНеУч")
    if foreign is not None:
        result.update(
            name=(foreign.get("Наим") or "").strip(),
            type="foreign",
        )
        return result

    fio = _fio_text(element) or _fio_text(holder)
    if fio:
        result.update(name=fio, type="person")
    return result


def parse_tax_amount(element: ET.Element | None) -> tuple[float | None, str]:
    """Read `<СумНал>`, which either wraps a number or says "без НДС"."""
    if element is None:
        return None, ""

    number = text_of(direct_child(element, "СумНал"))
    if number:
        return to_number(number), ""

    for marker in ("БезНДС", "НДСисчисляется", "НДСУплНалАг"):
        if direct_child(element, marker) is not None or text_of(element).lower().startswith(
            "без ндс"
        ):
            return None, text_of(element) or marker

    fallback = to_number(text_of(element))
    return fallback, ""


def parse_currency(root: ET.Element) -> dict[str, str]:
    """`<ДенИзм КодОКВ="643" НаимОКВ="Российский рубль"/>`."""
    node = find_first(root, "ДенИзм")
    if node is None:
        return {"code": "", "name": ""}
    return {
        "code": (node.get("КодОКВ") or "").strip(),
        "name": (node.get("НаимОКВ") or "").strip(),
    }
