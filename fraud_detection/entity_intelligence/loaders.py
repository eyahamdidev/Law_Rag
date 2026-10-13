from __future__ import annotations

from pathlib import Path

import pandas as pd

from fraud_detection.schema import EntityRecord, SanctionsEntry


def _column(frame: pd.DataFrame, *names: str) -> str | None:
    lookup = {str(column).strip().lower(): column for column in frame.columns}
    for name in names:
        if name in lookup:
            return lookup[name]
    return None


def load_rne_csv(path: str | Path) -> list[EntityRecord]:
    """Load a Tunisian legal-entity extract.

    Header names vary by portal export, so several French and English aliases are accepted.
    This is reference data for enrichment, not a fraud label.
    """
    frame = pd.read_csv(path)
    id_col = _column(frame, "entity_id", "identifiant", "id", "matricule", "numero", "num_registre", "registration_number")
    name_col = _column(frame, "name", "denomination", "raison_sociale", "nom", "company_name")
    if id_col is None or name_col is None:
        raise ValueError("RNE file needs an identifier column and a company name column")
    date_col = _column(frame, "registered_on", "date_debut_activite", "date_immatriculation", "start_date")
    gov_col = _column(frame, "governorate", "gouvernorat", "tribunal")
    activity_col = _column(frame, "activity", "activite", "activité")
    status_col = _column(frame, "status", "statut", "etat")
    revenue_col = _column(frame, "declared_annual_revenue", "chiffre_affaires")
    records: list[EntityRecord] = []
    for row in frame.to_dict(orient="records"):
        entity_id = str(row[id_col]).strip()
        name = str(row[name_col]).strip()
        if not entity_id or not name or name.lower() == "nan":
            continue
        registered = None
        if date_col is not None and pd.notna(row[date_col]):
            registered = pd.to_datetime(row[date_col], errors="coerce")
            registered = None if pd.isna(registered) else registered.to_pydatetime()
        revenue = None
        if revenue_col is not None and pd.notna(row[revenue_col]):
            revenue = float(row[revenue_col])
        records.append(
            EntityRecord(
                entity_id=entity_id,
                name=name,
                kind="company",
                country="TN",
                governorate=None if gov_col is None or pd.isna(row[gov_col]) else str(row[gov_col]),
                activity=None if activity_col is None or pd.isna(row[activity_col]) else str(row[activity_col]),
                registered_on=registered,
                status="active" if status_col is None or pd.isna(row[status_col]) else str(row[status_col]).lower(),
                declared_annual_revenue=revenue,
            )
        )
    return records


def load_sanctions_csv(path: str | Path) -> list[SanctionsEntry]:
    frame = pd.read_csv(path)
    name_col = _column(frame, "name", "entity_name", "primary_name")
    if name_col is None:
        raise ValueError("sanctions file needs a name column")
    list_col = _column(frame, "list_name", "source", "list")
    type_col = _column(frame, "entity_type", "type")
    program_col = _column(frame, "programs", "program")
    entries: list[SanctionsEntry] = []
    for row in frame.to_dict(orient="records"):
        name = str(row[name_col]).strip()
        if not name or name.lower() == "nan":
            continue
        programs: list[str] = []
        if program_col is not None and pd.notna(row[program_col]):
            programs = [part.strip() for part in str(row[program_col]).split("|") if part.strip()]
        entries.append(
            SanctionsEntry(
                name=name,
                list_name="LOCAL" if list_col is None or pd.isna(row[list_col]) else str(row[list_col]),
                entity_type="entity" if type_col is None or pd.isna(row[type_col]) else str(row[type_col]),
                programs=programs,
            )
        )
    return entries
