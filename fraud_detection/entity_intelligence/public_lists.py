from __future__ import annotations

import csv
import xml.etree.ElementTree as ET
from pathlib import Path

from fraud_detection.entity_intelligence.sanctions import SanctionsIndex
from fraud_detection.schema import SanctionsEntry


def _clean(value: str | None) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).replace("\x00", " ").split())
    if text in {"", "-0-", "N/A", "na", "NA"}:
        return ""
    return text


def _add(entries: list[SanctionsEntry], seen: set[tuple[str, str]], name: str, list_name: str, entity_type: str, programs: list[str]) -> None:
    cleaned = _clean(name)
    if len(cleaned) < 2:
        return
    key = (list_name, cleaned.upper())
    if key in seen:
        return
    seen.add(key)
    entries.append(
        SanctionsEntry(
            name=cleaned,
            list_name=list_name,
            entity_type=entity_type or "entity",
            programs=[item for item in programs if item],
        )
    )


def _open_text(path: Path):
    raw = path.read_bytes()[:400]
    encoding = "utf-8-sig"
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        encoding = "latin-1"
    return path.open("r", encoding=encoding, newline="")


def load_ofac(sdn_path: Path, alt_path: Path | None = None) -> list[SanctionsEntry]:
    entries: list[SanctionsEntry] = []
    seen: set[tuple[str, str]] = set()
    with _open_text(sdn_path) as handle:
        for row in csv.reader(handle):
            if len(row) < 2:
                continue
            programs = []
            if len(row) > 3 and _clean(row[3]):
                programs = [part.strip() for part in row[3].split("]")[0].split(",") if part.strip()]
                if not programs:
                    programs = [_clean(row[3])]
            entity_type = _clean(row[2]) if len(row) > 2 else "entity"
            _add(entries, seen, row[1], "OFAC_SDN", entity_type or "entity", programs)
    if alt_path is not None and alt_path.exists():
        with _open_text(alt_path) as handle:
            for row in csv.reader(handle):
                if len(row) < 4:
                    continue
                _add(entries, seen, row[3], "OFAC_SDN", "alias", [])
    return entries


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ET.Element, name: str) -> str:
    for child in list(element):
        if _local(child.tag) == name and child.text:
            return _clean(child.text)
    return ""


def load_un(path: Path) -> list[SanctionsEntry]:
    entries: list[SanctionsEntry] = []
    seen: set[tuple[str, str]] = set()
    for _event, element in ET.iterparse(path, events=("end",)):
        tag = _local(element.tag)
        if tag not in {"INDIVIDUAL", "ENTITY"}:
            continue
        if tag == "INDIVIDUAL":
            parts = [
                _child_text(element, "FIRST_NAME"),
                _child_text(element, "SECOND_NAME"),
                _child_text(element, "THIRD_NAME"),
                _child_text(element, "FOURTH_NAME"),
            ]
            _add(entries, seen, " ".join(part for part in parts if part), "UN", "individual", [_child_text(element, "UN_LIST_TYPE")])
            for alias in element.iter():
                if _local(alias.tag) == "ALIAS_NAME":
                    _add(entries, seen, alias.text or "", "UN", "alias", [])
        else:
            _add(entries, seen, _child_text(element, "FIRST_NAME"), "UN", "entity", [_child_text(element, "UN_LIST_TYPE")])
            for alias in element.iter():
                if _local(alias.tag) == "ALIAS_NAME":
                    _add(entries, seen, alias.text or "", "UN", "alias", [])
        element.clear()
    return entries


def load_eu(path: Path) -> list[SanctionsEntry]:
    entries: list[SanctionsEntry] = []
    seen: set[tuple[str, str]] = set()
    with _open_text(path) as handle:
        reader = csv.reader(handle, delimiter=";")
        header = next(reader)
        def position(name: str) -> int | None:
            return header.index(name) if name in header else None
        whole = position("Naal_wholename")
        first = position("Naal_firstname")
        last = position("Naal_lastname")
        programme = position("Programme")
        subject = position("Subject_type")
        if whole is None and (first is None or last is None):
            raise ValueError("EU sanctions file has no name columns")
        for row in reader:
            def cell(index: int | None) -> str:
                if index is None or index >= len(row):
                    return ""
                return _clean(row[index])
            name = cell(whole)
            if not name:
                name = " ".join(part for part in (cell(first), cell(last)) if part)
            programs = [cell(programme)] if cell(programme) else []
            _add(entries, seen, name, "EU", cell(subject) or "entity", programs)
    return entries


def load_public_sanctions(raw_dir: Path) -> tuple[SanctionsIndex, dict[str, int]]:
    folder = raw_dir / "sanctions"
    entries: list[SanctionsEntry] = []
    counts = {"OFAC_SDN": 0, "UN": 0, "EU": 0}
    sdn = folder / "ofac_sdn.csv"
    if sdn.exists() and sdn.stat().st_size > 1000:
        loaded = load_ofac(sdn, folder / "ofac_alt.csv")
        counts["OFAC_SDN"] = len(loaded)
        entries.extend(loaded)
    un = folder / "un_consolidated.xml"
    if un.exists() and un.stat().st_size > 1000:
        loaded = load_un(un)
        counts["UN"] = len(loaded)
        entries.extend(loaded)
    eu = folder / "eu_sanctions.csv"
    if eu.exists() and eu.stat().st_size > 1000:
        loaded = load_eu(eu)
        counts["EU"] = len(loaded)
        entries.extend(loaded)
    return SanctionsIndex(entries), counts
