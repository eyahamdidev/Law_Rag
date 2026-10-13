"""Build Tunisia metadata and context tables from files already on disk.

This script does not download, synthesize, or relabel anything. It records
checksums of the preserved originals and extracts aggregate context rows.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

from fraud_detection.paths import PACKAGE

RAW = PACKAGE / "data" / "raw" / "tunisia"
PROCESSED = PACKAGE / "data" / "processed" / "tunisia"
METADATA = PACKAGE / "data" / "metadata" / "tunisia"
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
DOWNLOAD_DATE = "2026-10-06"

MONTHS = {
    "janv": 1,
    "jan": 1,
    "févr": 2,
    "fevr": 2,
    "mars": 3,
    "avr": 4,
    "mai": 5,
    "juin": 6,
    "juil": 7,
    "août": 8,
    "aout": 8,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "déc": 12,
    "dec": 12,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path, **fields) -> dict:
    stat = path.stat()
    return {
        "path": str(path.relative_to(PACKAGE)),
        "bytes": stat.st_size,
        "sha256": sha256(path),
        "download_date": DOWNLOAD_DATE,
        **fields,
    }


def _cell_map(path: Path) -> tuple[dict[int, dict[str, str]], list[str]]:
    with zipfile.ZipFile(path) as book:
        shared_root = ET.fromstring(book.read("xl/sharedStrings.xml"))
        strings = ["".join(item.itertext()) for item in shared_root.findall(f".//{NS}si")]
        sheet = ET.fromstring(book.read("xl/worksheets/sheet1.xml"))
    rows: dict[int, dict[str, str]] = {}
    for row in sheet.iter(f"{NS}row"):
        number = int(row.get("r") or 0)
        cells: dict[str, str] = {}
        for cell in row.findall(f"{NS}c"):
            ref = cell.get("r") or ""
            column = "".join(ch for ch in ref if ch.isalpha())
            value = cell.find(f"{NS}v")
            if value is None or value.text is None:
                continue
            if cell.get("t") == "s":
                cells[column] = strings[int(value.text)]
            else:
                cells[column] = value.text
        rows[number] = cells
    return rows, strings


def _column_key(column: str) -> tuple[int, str]:
    return (len(column), column)


def _period(value: str) -> bool:
    return bool(re.fullmatch(r"\d{4}(?:-\d{2}|-Q[1-4])?", value.strip()))


def _sdmx_number(value: str) -> float | None:
    text = value.strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def sdmx_summary(path: Path) -> dict:
    rows, _strings = _cell_map(path)
    header_number = None
    header: dict[str, str] = {}
    for number in sorted(rows):
        cells = rows[number]
        if sum(1 for value in cells.values() if _period(value)) >= 2:
            header_number = number
            header = cells
            break
    period_columns = [column for column in sorted(header, key=_column_key) if _period(header[column])]
    dates = [header[column] for column in period_columns]
    flat = {}
    for cells in rows.values():
        items = list(cells.items())
        for index, (column, value) in enumerate(items[:-1]):
            nxt = items[index + 1][1]
            if value in {"DATA_DOMAIN", "FREQ", "REF_AREA", "UNIT_MULT"}:
                flat[value] = nxt
            if value.endswith(" Name") or value in {"Frequency = Monthly", "Frequency = Annual"}:
                flat[value] = value
    series = []
    for number in sorted(rows):
        if header_number is None or number <= header_number:
            continue
        cells = rows[number]
        code = ""
        label = ""
        for column in sorted(cells, key=_column_key):
            value = cells[column].strip()
            if not code and re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", value):
                code = value
                continue
            if code and not label and value and not _period(value) and _sdmx_number(value) is None:
                label = value
                break
        if not code or not label:
            continue
        observations = []
        for column in period_columns:
            raw = cells.get(column)
            if raw is None:
                continue
            value = _sdmx_number(raw)
            if value is None:
                continue
            observations.append((header[column], value))
        if not observations:
            continue
        series.append(
            {
                "code": code,
                "label": label,
                "n_observations": len(observations),
                "period_start": observations[0][0],
                "period_end": observations[-1][0],
                "latest_value": observations[-1][1],
            }
        )
    return {
        "dataset": flat.get("DATA_DOMAIN", path.stem),
        "country": flat.get("REF_AREA", ""),
        "frequency": flat.get("FREQ", ""),
        "n_periods": len(dates),
        "period_start": dates[0] if dates else None,
        "period_end": dates[-1] if dates else None,
        "n_series": len(series),
        "series": series,
    }


def _parse_month(label: str) -> str | None:
    text = label.strip().lower().replace(".", "")
    match = re.search(r"([a-zéûô]+)\s+(\d{4})", text)
    if not match:
        return None
    month = MONTHS.get(match.group(1)[:4]) or MONTHS.get(match.group(1))
    if month is None:
        return None
    return f"{match.group(2)}-{month:02d}"


def _number(value: str) -> float | None:
    text = value.strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not text or text in {"-", "–"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def payment_window(path: Path) -> list[dict]:
    html = path.read_text(encoding="utf-8", errors="replace")
    start = html.find("bct-table-fixed")
    chunk = html[start : start + 20000] if start >= 0 else html
    parsed = []
    for row in re.findall(r"<tr[\s\S]*?</tr>", chunk):
        cells = re.findall(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", row)
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", cell)).strip() for cell in cells]
        if any(cells):
            parsed.append(cells)
    if not parsed:
        return []
    header = parsed[0]
    periods = [_parse_month(item) for item in header[1:]]
    records = []
    for cells in parsed[1:]:
        channel = cells[0]
        if not channel or channel.lower().startswith("indicateur"):
            continue
        for period, raw in zip(periods, cells[1:]):
            if period is None:
                continue
            value = _number(raw) if raw else None
            records.append({"channel": channel, "period": period, "value": value})
    return records


def build_payment_baseline() -> list[dict]:
    counts = {
        (row["channel"], row["period"]): row["value"]
        for row in payment_window(RAW / "payments" / "bct_pl202020_nombre_transactions.html")
    }
    values = {
        (row["channel"], row["period"]): row["value"]
        for row in payment_window(RAW / "payments" / "bct_pl202010_volume_transactions.html")
    }
    # The volume page labels cards "Cartes bancaire"; the count page uses the plural.
    alias = {"Cartes bancaire": "Cartes bancaires"}
    values = {(alias.get(channel, channel), period): value for (channel, period), value in values.items()}
    rows = []
    for key in sorted(set(counts) | set(values)):
        channel, period = key
        count_thousands = counts.get(key)
        value_mdt = values.get(key)
        average = None
        if count_thousands and value_mdt:
            average = (value_mdt * 1_000_000) / (count_thousands * 1_000)
        rows.append(
            {
                "period": period,
                "channel": channel,
                "transaction_count": None if count_thousands is None else count_thousands * 1000,
                "transaction_count_unit": "transactions; source figure is published in thousands",
                "transaction_value": None if value_mdt is None else value_mdt * 1_000_000,
                "transaction_value_unit": "TND; source figure is published in millions of dinars",
                "average_value": None if average is None else round(average, 2),
                "average_value_unit": "TND per transaction, derived from the two published aggregates",
                "market_category": "bct_payment_instrument",
                "source": "Banque Centrale de Tunisie, PL202020 and PL202010",
                "source_urls": [
                    "https://www.bct.gov.tn/bct/siteprod/tableau_statistique.jsp?params=PL202020",
                    "https://www.bct.gov.tn/bct/siteprod/tableau_statistique.jsp?params=PL202010",
                ],
                "level": "AGGREGATE",
                "published_count_thousands": count_thousands,
                "published_value_millions_tnd": value_mdt,
            }
        )
    return rows


def write_parquet(rows: list[dict], path: Path) -> bool:
    try:
        import pandas as pd
    except ImportError:
        return False
    frame = pd.DataFrame(rows)
    try:
        frame.to_parquet(path, index=False)
    except Exception:
        return False
    return True


def metadata_documents(payment_rows: list[dict], macro: dict) -> list[dict]:
    ctaf_common = {
        "source": "Commission Tunisienne des Analyses Financières (CTAF)",
        "license_usage": (
            "Official public report hosted on ctaf.gov.tn. No separate machine-learning "
            "license is stated on the download page. The text is a case-based typology "
            "source. It is not a transaction table and it is not used as training labels."
        ),
        "fraud_labels": False,
        "usable_for_ml_training": False,
        "ml_training_reason": "Case narratives and annual statistics are not transaction-level labeled rows.",
        "level": "CASE_BASED",
    }
    documents = [
        file_record(
            RAW / "ctaf" / "ctaf_rapport_activite_2024_fr.pdf",
            source_name="CTAF annual activity report 2024 (French)",
            official_url="https://www.ctaf.gov.tn/data/uploads/pdf/68ed20ef1333f7.67071673.pdf",
            also_published_at="https://www.ctaf.gov.tn/data/uploads/pdf/68ed1fe9a608d8.67857585.pdf",
            publication_date="2024 activity year; exact publication day is not printed in the extracted text",
            format="PDF",
            n_pages=45,
            columns=[],
            n_records=7,
            record_meaning="Seven typology cases in Chapter III, plus annual suspicious-activity statistics. Not transactions.",
            **ctaf_common,
        ),
        file_record(
            RAW / "ctaf" / "ctaf_rapport_activite_2023_fr.pdf",
            source_name="CTAF annual activity report 2023 (French)",
            official_url="https://www.ctaf.gov.tn/data/uploads/pdf/66aa02b723c2e3.57823642.pdf",
            publication_date="2023 activity year; exact publication day is not printed in the extracted text",
            format="PDF",
            n_pages=42,
            columns=[],
            n_records=5,
            record_meaning="Five typology cases named in the report. Preserved as a source. Not expanded into training rows.",
            **ctaf_common,
        ),
        file_record(
            RAW / "ctaf" / "ctaf_typologies_2020_2025_fr.pdf",
            source_name="CTAF terrorism-financing lessons from files transmitted 2020-2025",
            official_url="https://www.ctaf.gov.tn/data/uploads/pdf/6a26c622d81294.49709769.pdf",
            publication_date="Covers 2020-2025; exact publication day is not printed in the extracted text",
            format="PDF",
            n_pages=23,
            columns=[],
            n_records=None,
            record_meaning="Strategic bulletin: declarative statistics, one described case, and warning-sign indicators.",
            **ctaf_common,
        ),
    ]
    sdmx_urls = {
        "DCS": ("Comptes analytiques du secteur bancaire", "https://gosdmx.bct.gov.tn/gosdmx/telechargerFichierExcel?rubriqueId=8"),
        "CBS": ("Comptes analytiques de la Banque Centrale", "https://gosdmx.bct.gov.tn/gosdmx/telechargerFichierExcel?rubriqueId=9"),
        "BOP6": ("Balance des paiements", "https://gosdmx.bct.gov.tn/gosdmx/telechargerFichierExcel?rubriqueId=12"),
        "ILV1": ("Réserves internationales", "https://gosdmx.bct.gov.tn/gosdmx/telechargerFichierExcel?rubriqueId=13"),
        "ILV2": ("Tableau des réserves", "https://gosdmx.bct.gov.tn/gosdmx/telechargerFichierExcel?rubriqueId=14"),
        "MET": ("Commerce extérieur", "https://gosdmx.bct.gov.tn/gosdmx/telechargerFichierExcel?rubriqueId=15"),
        "IIP6": ("Position extérieure globale", "https://gosdmx.bct.gov.tn/gosdmx/telechargerFichierExcel?rubriqueId=16"),
        "EXD": ("Position de la dette extérieure brute", "https://gosdmx.bct.gov.tn/gosdmx/telechargerFichierExcel?rubriqueId=18"),
    }
    for code, (title, url) in sdmx_urls.items():
        summary = macro[code]
        documents.append(
            file_record(
                RAW / "bct" / f"{code}.xls",
                source_name=f"BCT SDMX {title}",
                official_url=url,
                sdmx_xml_url=f"https://gosdmx.bct.gov.tn/gosdmx/telechargerFichierXML?rubriqueAbbreviation={code}",
                catalog_url="https://gosdmx.bct.gov.tn/gosdmx/pnrd?lang=FR",
                publication_date=f"Series span {summary['period_start']} to {summary['period_end']}",
                license_usage="Public statistical dissemination by the Banque Centrale de Tunisie through its SDMX portal.",
                format="Office Open XML workbook served with a .xls name",
                level="AGGREGATE",
                fraud_labels=False,
                usable_for_ml_training=False,
                ml_training_reason="Monthly or quarterly national aggregates. Not transaction rows and not fraud labels.",
                n_records=summary["n_series"],
                n_periods=summary["n_periods"],
                columns=["code", "label_fr", "label_en", "unit", "scale", "period", "value"],
                record_meaning="One national time series per indicator, not one transaction.",
            )
        )
    documents.append(
        file_record(
            RAW / "payments" / "bct_pl202020_nombre_transactions.html",
            source_name="BCT number of payment transactions",
            official_url="https://www.bct.gov.tn/bct/siteprod/tableau_statistique.jsp?params=PL202020",
            publication_date="Published window visible in the saved page: 2025-04 to 2025-09",
            license_usage="Public BCT statistical table.",
            format="HTML",
            level="AGGREGATE",
            fraud_labels=False,
            usable_for_ml_training=False,
            ml_training_reason="Instrument-level monthly totals. The historical export endpoint did not return values.",
            n_records=sum(1 for row in payment_rows if row["published_count_thousands"] is not None),
            columns=["period", "channel", "transaction_count_thousands"],
            record_meaning="One monthly aggregate per payment instrument.",
        )
    )
    documents.append(
        file_record(
            RAW / "payments" / "bct_pl202010_volume_transactions.html",
            source_name="BCT value of payment transactions",
            official_url="https://www.bct.gov.tn/bct/siteprod/tableau_statistique.jsp?params=PL202010",
            publication_date="Published window visible in the saved page: 2025-04 to 2025-09",
            license_usage="Public BCT statistical table.",
            format="HTML",
            level="AGGREGATE",
            fraud_labels=False,
            usable_for_ml_training=False,
            ml_training_reason="Instrument-level monthly totals in millions of dinars.",
            n_records=sum(1 for row in payment_rows if row["published_value_millions_tnd"] is not None),
            columns=["period", "channel", "transaction_value_millions_tnd"],
            record_meaning="One monthly aggregate per payment instrument.",
        )
    )
    return documents


def main() -> None:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    METADATA.mkdir(parents=True, exist_ok=True)
    macro = {}
    for code in ("DCS", "CBS", "BOP6", "ILV1", "ILV2", "MET", "IIP6", "EXD"):
        macro[code] = sdmx_summary(RAW / "bct" / f"{code}.xls")
    (PROCESSED / "tunisia_macro_context.json").write_text(
        json.dumps(
            {
                "level": "AGGREGATE",
                "fraud_labels": False,
                "note": "Latest observation per published BCT SDMX series. These are not transactions.",
                "datasets": macro,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    payment_rows = build_payment_baseline()
    (PROCESSED / "tunisia_payment_market_baseline.json").write_text(
        json.dumps(payment_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    parquet_ok = write_parquet(payment_rows, PROCESSED / "tunisia_payment_market_baseline.parquet")
    findex_rows = []
    for path in sorted((RAW / "findex").glob("wb_FX*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload[1]:
            if row.get("value") is None:
                continue
            findex_rows.append(
                {
                    "indicator_id": row["indicator"]["id"],
                    "indicator": row["indicator"]["value"],
                    "country": row["countryiso3code"],
                    "year": int(row["date"]),
                    "value": row["value"],
                    "level": "AGGREGATE",
                    "source": "World Bank API, Global Findex indicator",
                }
            )
    (PROCESSED / "tunisia_findex_context.json").write_text(
        json.dumps(findex_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    documents = metadata_documents(payment_rows, macro)
    (METADATA / "downloaded_files.json").write_text(
        json.dumps(
            {
                "download_date": DOWNLOAD_DATE,
                "parquet_payment_baseline_written": parquet_ok,
                "files": documents,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"payment rows {len(payment_rows)} parquet {parquet_ok} macro datasets {len(macro)}")
    print(f"findex aggregate rows {len(findex_rows)}")


if __name__ == "__main__":
    main()
