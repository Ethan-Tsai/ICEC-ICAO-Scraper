from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from .models import RunRecord


CSV_FIELDS = [
    "departure_code",
    "departure_text",
    "destination_code",
    "destination_text",
    "saf_flag",
    "status",
    "target_label_text",
    "target_value_raw",
    "target_value_kg",
    "distance_value_km",
    "raw_result_html",
    "scraped_at",
    "error",
]


def append_records(path: Path, records: Iterable[RunRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=CSV_FIELDS)
        if not exists:
            writer.writeheader()
        for record in records:
            writer.writerow(record.__dict__)


def write_json(path: Path, records: Iterable[RunRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [record.__dict__ for record in records]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_custom_csv(path: Path, records: Iterable[RunRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    custom_fields = [
        "Dep Airport",
        "Arr Airport",
        "Distance (KM)",
        "Aircraft Fuel Burn/journey (KG)ab",
        "Total passengers’ CO2/journey (KG)c"
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=custom_fields)
        writer.writeheader()
        for record in records:
            writer.writerow({
                "Dep Airport": record.departure_code,
                "Arr Airport": record.destination_code,
                "Distance (KM)": record.distance_value_km if record.distance_value_km is not None else "",
                "Aircraft Fuel Burn/journey (KG)ab": record.fuel_value_kg if record.fuel_value_kg is not None else "",
                "Total passengers’ CO2/journey (KG)c": record.target_value_kg if record.target_value_kg is not None else ""
            })
