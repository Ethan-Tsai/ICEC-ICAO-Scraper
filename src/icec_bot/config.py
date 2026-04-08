from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field, ValidationError


class BrowserConfig(BaseModel):
    headless: bool = True
    locale: str = "zh-TW"
    timezone_id: str = "Asia/Taipei"
    user_agent: str
    accept_language: str = "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7"


class RateLimitConfig(BaseModel):
    min_delay_seconds: float = 2.0
    max_delay_seconds: float = 5.0
    long_pause_every: int = 50
    long_pause_seconds: float = 30.0
    retry_attempts: int = 2


class SelectorsConfig(BaseModel):
    passenger_tab: str = ""
    departure_select: str = ""
    departure_select2_trigger: str = ""
    select2_open_options: str = ".select2-container--open .select2-results__option"
    destination_select: str = ""
    trip_one_way_button: str = ""
    passengers_input: str = ""
    cabin_select: str = ""
    calculate_button: str = ""
    result_root: str = ""
    result_rows: str = ""
    result_label_in_row: str = ""
    result_value_in_row: str = ""
    result_metric_economy_container: str = "#ResultDivPassengerEconomyMetric"
    back_button: str = ""


class ResultMappingConfig(BaseModel):
    target_labels: List[str] = Field(default_factory=list)
    distance_labels: List[str] = Field(default_factory=list)
    fuel_labels: List[str] = Field(default_factory=list)


class ApiConfig(BaseModel):
    passenger_get_airports_by_departure: str = "/Home/PassengerGetAirportsByDeparture"
    passenger_compute: str = "/Home/PassengerCompute"
    passenger_result: str = "/Home/PassengerResult"


class FixedInputsConfig(BaseModel):
    is_round_trip: bool = False
    cabin_class_compute: int = 0
    number_of_passenger: int = 1
    cabin_class_result: str = "Economy"
    indicator_result: str = "Metric"


class RunLimitsConfig(BaseModel):
    max_departures: Optional[int] = None
    max_destinations_per_departure: Optional[int] = None
    max_pairs: Optional[int] = None


class SiteConfig(BaseModel):
    target_url: str
    browser: BrowserConfig
    rate_limit: RateLimitConfig
    api: ApiConfig = Field(default_factory=ApiConfig)
    fixed_inputs: FixedInputsConfig = Field(default_factory=FixedInputsConfig)
    run_limits: RunLimitsConfig = Field(default_factory=RunLimitsConfig)
    selectors: SelectorsConfig
    result_mapping: ResultMappingConfig

    def assert_required_runtime_fields(self) -> None:
        missing = []
        required_selector_keys = [
            "departure_select",
            "result_rows",
            "result_label_in_row",
            "result_value_in_row",
        ]
        selectors = self.selectors.model_dump()
        for key in required_selector_keys:
            value = selectors.get(key, "")
            if not value.strip():
                missing.append(f"selectors.{key}")
        if not self.result_mapping.target_labels:
            missing.append("result_mapping.target_labels")
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"Missing required config fields: {joined}")


def load_config(path: Path) -> SiteConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return SiteConfig.model_validate(raw)


def validate_config_file(path: Path) -> None:
    try:
        cfg = load_config(path)
        cfg.assert_required_runtime_fields()
    except (ValidationError, ValueError) as exc:
        raise SystemExit(f"Config validation failed: {exc}") from exc
