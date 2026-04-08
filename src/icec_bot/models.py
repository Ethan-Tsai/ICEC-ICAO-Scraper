from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class RunRecord:
    departure_code: str
    departure_text: str
    destination_code: str
    destination_text: str
    saf_flag: str
    status: str
    target_label_text: str
    target_value_raw: str
    target_value_kg: Optional[float]
    fuel_value_kg: Optional[float]
    distance_value_km: Optional[float]
    raw_result_html: str
    scraped_at: str
    error: str
