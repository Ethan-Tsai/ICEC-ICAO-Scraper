from __future__ import annotations

import asyncio
import random
import re
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from bs4 import BeautifulSoup
from playwright.async_api import Page

from .config import SiteConfig
from .models import RunRecord

logger = logging.getLogger(__name__)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _parse_number(text: str) -> Optional[float]:
    m = re.search(r"(\d[\d,]*\.?\d*)", text or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _to_kg(value_text: str) -> Optional[float]:
    up = (value_text or "").upper()
    n = _parse_number(up)
    if n is None:
        return None
    if "KG" in up:
        return n
    if "LBS" in up:
        return round(n * 0.45359237, 6)
    return None


def _to_km(value_text: str) -> Optional[float]:
    up = (value_text or "").upper()
    n = _parse_number(up)
    if n is None:
        return None
    if "KM" in up:
        return n
    if "MI" in up:
        return round(n * 1.609344, 6)
    return None


class IcecRunner:
    def __init__(self, page: Page, cfg: SiteConfig):
        self.page = page
        self.cfg = cfg
        # Adaptive Smart Delay State
        self.current_delay = self.cfg.rate_limit.max_delay_seconds

    async def open(self) -> None:
        await self.page.goto(self.cfg.target_url, wait_until="domcontentloaded")

    async def _sleep_rate_limit(self, idx: int, success: bool = True) -> None:
        rl = self.cfg.rate_limit
        if rl.long_pause_every > 0 and idx > 0 and idx % rl.long_pause_every == 0:
            await asyncio.sleep(rl.long_pause_seconds)
            
        if success:
            # Gradually speed up if queries are completing successfully without WAF drops
            self.current_delay = max(rl.min_delay_seconds, self.current_delay * 0.9)
        else:
            # Exponential Backoff penalty for failure to evade WAF
            self.current_delay = min(60.0, self.current_delay * 1.5)
            
        target_sleep = self.current_delay + random.uniform(0, 1.5)
        logger.info(f"Adaptive rate limit -> Wait time set to {target_sleep:.2f}s")
        await asyncio.sleep(target_sleep)

    async def _dump_debug_artifacts(self, prefix: str) -> None:
        debug_dir = Path("out") / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        html = await self.page.content()
        (debug_dir / f"{prefix}.html").write_text(html, encoding="utf-8")
        await self.page.screenshot(path=str(debug_dir / f"{prefix}.png"), full_page=True)

    async def _safe_click(self, selector: str, timeout_ms: int = 15000) -> None:
        locator = self.page.locator(selector).first
        await locator.wait_for(state="attached", timeout=timeout_ms)
        # Adding random delay between 50ms and 150ms to simulate human clicking pattern
        await locator.click(timeout=timeout_ms, delay=random.randint(50, 150))

    async def _set_fixed_ui_inputs(self) -> None:
        s = self.cfg.selectors

        await self._safe_click(s.passenger_tab)
        await self._safe_click(s.trip_one_way_button)

        pax = self.page.locator(s.passengers_input).first
        await pax.fill(str(self.cfg.fixed_inputs.number_of_passenger))

        cabin = self.page.locator(s.cabin_select).first
        # Try value by enum id first, then by label/value text.
        try:
            await cabin.select_option(value=str(self.cfg.fixed_inputs.cabin_class_compute), force=True)
        except Exception:
            try:
                await cabin.select_option(label=self.cfg.fixed_inputs.cabin_class_result, force=True)
            except Exception:
                await cabin.select_option(value=self.cfg.fixed_inputs.cabin_class_result, force=True)

    async def _extract_departures_visually(self) -> List[Dict[str, str]]:
        trigger_selector = "span.select2-selection[aria-controls='select2-SelectPassengerDeparture-container']"
        await self._safe_click(trigger_selector)
        
        options = self.page.locator(".select2-results__option[role='option']")
        await options.first.wait_for(state="attached", timeout=10000)
        
        texts = await options.evaluate_all("opts => opts.map(o => o.innerText.trim())")
        
        rows: List[Dict[str, str]] = []
        for i, text in enumerate(texts):
            if i == 0:  # skip the first empty/placeholder option if it's index 0
                continue
            text = _normalize(text)
            if not text:
                continue
            rows.append({"text": text, "index": i, "code": text})

        await self.page.keyboard.press("Escape")

        if self.cfg.run_limits.max_departures:
            rows = rows[: self.cfg.run_limits.max_departures]
        return rows

    async def _select_departure_visually_by_index(self, index: int) -> None:
        trigger_selector = "span.select2-selection[aria-controls='select2-SelectPassengerDeparture-container']"
        await self._safe_click(trigger_selector)

        options = self.page.locator(".select2-results__option[role='option']")
        await options.first.wait_for(state="attached", timeout=10000)
        
        await options.nth(index).click()
        await asyncio.sleep(0.5)

    async def _extract_destinations_for_departure(self, dep_info: Dict[str, str]) -> List[Dict[str, str]]:
        dst_sel = self.cfg.selectors.destination_select

        # Select departure by index visually
        await self._select_departure_visually_by_index(dep_info["index"])
        dep_code = _normalize(
            await self.page.locator(self.cfg.selectors.departure_select).first.input_value()
        )
        dep_info["code"] = dep_code # update with actual code

        deadline = asyncio.get_event_loop().time() + 25.0
        dest_rows: List[Dict[str, str]] = []

        while asyncio.get_event_loop().time() < deadline:
            # We use Javascript evaluation directly to fetch all options instantly
            # bypassing the slow sequential IPC calls.
            rows = await self.page.evaluate('''([sel, dep_code]) => {
                const elements = Array.from(document.querySelectorAll(sel + " option"));
                const results = [];
                for (let opt of elements) {
                    let val = (opt.value || "").trim();
                    let txt = (opt.innerText || "").trim();
                    let saf = (opt.getAttribute("data-saf") || "").trim();
                    if (val && txt && val !== dep_code) {
                        results.push({code: val, text: txt, saf: saf});
                    }
                }
                return results;
            }''', [dst_sel, dep_code])
            
            if rows:
                dest_rows = rows
                break
            await asyncio.sleep(0.4)

        if self.cfg.run_limits.max_destinations_per_departure:
            dest_rows = dest_rows[: self.cfg.run_limits.max_destinations_per_departure]
        return dest_rows

    async def _calculate_and_get_result_html_ui(self, dep_code: str, dst_code: str) -> str:
        s = self.cfg.selectors

        await self.page.locator(s.departure_select).first.select_option(value=dep_code, force=True)
        await asyncio.sleep(0.2)
        await self.page.locator(s.destination_select).first.select_option(value=dst_code, force=True)
        await asyncio.sleep(0.2)

        prev = _normalize(await self.page.locator(s.result_root).first.inner_text())
        await self.page.mouse.move(random.randint(100, 500), random.randint(100, 500))
        await asyncio.sleep(0.5)
        await self._safe_click(s.calculate_button)

        deadline = asyncio.get_event_loop().time() + 45.0
        while asyncio.get_event_loop().time() < deadline:
            try:
                root = self.page.locator(s.result_root).first
                now = _normalize(await root.inner_text())
                if now and now != prev:
                    container = self.page.locator(s.result_metric_economy_container).first
                    if await container.count() > 0:
                        html = await container.inner_html()
                        if _normalize(html):
                            return html
                    return await root.inner_html()
            except Exception:
                pass
            await asyncio.sleep(0.5)

        await self._dump_debug_artifacts(prefix=f"debug_result_timeout_{dep_code}_{dst_code}")
        raise RuntimeError("Result did not update in time after clicking Calculate.")

    def _extract_target_values(self, html: str) -> tuple[str, str, Optional[float], Optional[float], Optional[float]]:
        soup = BeautifulSoup(html, "html.parser")

        target_label = ""
        target_value = ""
        target_kg: Optional[float] = None
        fuel_kg: Optional[float] = None
        distance_km: Optional[float] = None

        for row in soup.select(".result-item-layout"):
            label_el = row.select_one(".result-item-label-layout > label.small-label")
            value_el = row.select_one(".result-item-value-layout > label.small-label.small-label-normal")
            if not label_el or not value_el:
                continue
            label = _normalize(label_el.get_text(" ", strip=True))
            value = _normalize(value_el.get_text(" ", strip=True))
            if not label or not value:
                continue

            if not target_value and label in self.cfg.result_mapping.target_labels:
                target_label = label
                target_value = value
                target_kg = _to_kg(value)

            if distance_km is None and label in self.cfg.result_mapping.distance_labels:
                distance_km = _to_km(value)
                
            if fuel_kg is None and label in getattr(self.cfg.result_mapping, 'fuel_labels', []):
                fuel_kg = _to_kg(value)

        return target_label, target_value, target_kg, distance_km, fuel_kg

    async def dry_run_selector_validation(self) -> None:
        self.cfg.assert_required_runtime_fields()
        s = self.cfg.selectors
        mandatory = [
            s.passenger_tab,
            s.departure_select,
            s.departure_select2_trigger,
            s.destination_select,
            s.trip_one_way_button,
            s.passengers_input,
            s.cabin_select,
            s.calculate_button,
            s.result_root,
        ]
        for selector in mandatory:
            loc = self.page.locator(selector)
            if await loc.count() == 0:
                raise RuntimeError(f"Selector not found: {selector}")

        option_count = await self.page.locator(f"{s.departure_select} option").count()
        if option_count == 0:
            raise RuntimeError("Departure select is found but has no options.")

    async def run_framework_only(self, skip_departures: int = 0, on_record_cb=None) -> List[RunRecord]:
        await self.open()
        await self.dry_run_selector_validation()
        await self._set_fixed_ui_inputs()

        departures = await self._extract_departures_visually()
        
        if skip_departures > 0:
            logger.info("Skipping the first %s departures", skip_departures)
            departures = departures[skip_departures:]

        records: List[RunRecord] = []
        pair_idx = 0
        max_pairs = self.cfg.run_limits.max_pairs

        for dep in departures:
            destinations = await self._extract_destinations_for_departure(dep_info=dep)
            for dst in destinations:
                if max_pairs and pair_idx >= max_pairs:
                    return records

                pair_idx += 1
                logger.info("SEARCHING_ROUTE: %s -> %s", dep['code'], dst['code'])
                error = ""
                raw_html = ""
                target_label = ""
                target_value = ""
                target_kg: Optional[float] = None
                distance_km: Optional[float] = None
                fuel_kg: Optional[float] = None

                for attempt in range(1, self.cfg.rate_limit.retry_attempts + 2):
                    try:
                        raw_html = await self._calculate_and_get_result_html_ui(
                            dep_code=dep["code"],
                            dst_code=dst["code"],
                        )
                        target_label, target_value, target_kg, distance_km, fuel_kg = self._extract_target_values(raw_html)
                        error = ""
                        break
                    except Exception as exc:  # pylint: disable=broad-except
                        error = str(exc)
                        if attempt <= self.cfg.rate_limit.retry_attempts:
                            await asyncio.sleep(min(60.0, (2 ** (attempt - 1)) * 2.0 + random.uniform(0, 1.5)))

                if not error:
                    logger.info("Successfully calculated result for %s -> %s: distance=%skm, CO2=%skg, Fuel=%skg", dep['code'], dst['code'], distance_km, target_kg, fuel_kg)
                    if self.cfg.selectors.back_button:
                        try:
                            await self._safe_click(self.cfg.selectors.back_button, timeout_ms=5000)
                            await self.page.locator(self.cfg.selectors.calculate_button).first.wait_for(state="attached", timeout=10000)
                        except Exception as back_exc:
                            logger.warning("Failed to return via back button: %s", back_exc)
                else:
                    logger.error("Failed to calculate result for %s -> %s. Error: %s", dep['code'], dst['code'], error)

                new_rec = RunRecord(
                    departure_code=dep["code"],
                        departure_text=dep["text"],
                        destination_code=dst["code"],
                        destination_text=dst["text"],
                        saf_flag=dst.get("saf", ""),
                        status="ok" if not error else "error",
                        target_label_text=target_label,
                        target_value_raw=target_value,
                        target_value_kg=target_kg,
                        distance_value_km=distance_km,
                        fuel_value_kg=fuel_kg,
                        raw_result_html=raw_html,
                        scraped_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                        error=error,
                    )
                records.append(new_rec)
                if on_record_cb:
                    on_record_cb(new_rec)
                await self._sleep_rate_limit(pair_idx, success=(not error))

        return records

    async def run_custom_list(self, csv_path: Path, skip: int = 0, max_pairs: Optional[int] = None, on_record_cb=None) -> List[RunRecord]:
        import csv
        pairs = []
        try:
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                headers = next(reader, None)
                for row in reader:
                    if len(row) >= 2 and row[0].strip():
                        pairs.append({"dep": row[0].strip(), "dst": row[1].strip()})
        except UnicodeDecodeError:
            with open(csv_path, "r", encoding="big5") as f:
                reader = csv.reader(f)
                headers = next(reader, None)
                for row in reader:
                    if len(row) >= 2 and row[0].strip():
                        pairs.append({"dep": row[0].strip(), "dst": row[1].strip()})

        if skip > 0:
            logger.info("Skipping the first %s custom list pairs", skip)
            pairs = pairs[skip:]
        if max_pairs:
            pairs = pairs[:max_pairs]

        logger.info("Loaded %s valid target pairs from CSV", len(pairs))

        await self.open()
        await self.dry_run_selector_validation()
        await self._set_fixed_ui_inputs()

        records: List[RunRecord] = []
        pair_idx = 0
        dep_trigger = "span.select2-selection[aria-controls='select2-SelectPassengerDeparture-container']"
        dst_trigger = "span.select2-selection[aria-controls='select2-SelectPassengerDestination1-container']"

        curr_idx = 0
        while curr_idx < len(pairs):
            pair = pairs[curr_idx]
            curr_idx += 1
            pair_idx += 1
            dep_code = pair["dep"]
            dst_code = pair["dst"]
            logger.info("SEARCHING_ROUTE: %s -> %s", dep_code, dst_code)
            error = ""
            raw_html = ""
            target_label = ""
            target_value = ""
            target_kg: Optional[float] = None
            distance_km: Optional[float] = None
            fuel_kg: Optional[float] = None

            for attempt in range(1, self.cfg.rate_limit.retry_attempts + 2):
                try:
                    # Select departure visually
                    await self._safe_click(dep_trigger)
                    await self.page.locator(".select2-results__option[role='option']").first.wait_for(state="attached", timeout=10000)
                    dep_idx = await self.page.evaluate('''([code]) => Array.from(document.querySelectorAll(".select2-results__option[role='option']")).findIndex(o => o.innerText.includes(code))''', [dep_code])
                    if dep_idx == -1: raise RuntimeError(f"Departure {dep_code} not found in dropdown")
                    await self.page.locator(".select2-results__option[role='option']").nth(dep_idx).click(delay=random.randint(50, 150))
                    await asyncio.sleep(0.5)

                    # Select destination visually
                    await self._safe_click(dst_trigger)
                    await self.page.locator(".select2-results__option[role='option']").first.wait_for(state="attached", timeout=10000)
                    dst_idx = await self.page.evaluate('''([code]) => Array.from(document.querySelectorAll(".select2-results__option[role='option']")).findIndex(o => o.innerText.includes(code))''', [dst_code])
                    if dst_idx == -1: raise RuntimeError(f"Destination {dst_code} not found in dropdown")
                    await self.page.locator(".select2-results__option[role='option']").nth(dst_idx).click(delay=random.randint(50, 150))
                    await asyncio.sleep(0.5)

                    raw_html = await self._calculate_and_get_result_html_ui(dep_code=dep_code, dst_code=dst_code)
                    target_label, target_value, target_kg, distance_km, fuel_kg = self._extract_target_values(raw_html)
                    error = ""
                    break
                except Exception as exc:
                    error = str(exc)
                    await self.page.keyboard.press("Escape")
                    if attempt <= self.cfg.rate_limit.retry_attempts:
                        await asyncio.sleep(min(60.0, (2 ** (attempt - 1)) * 2.0 + random.uniform(0, 1.5)))

            if not error:
                logger.info("Successfully calculated list target %s -> %s: distance=%skm, CO2=%skg, Fuel=%skg", dep_code, dst_code, distance_km, target_kg, fuel_kg)
                if self.cfg.selectors.back_button:
                    try:
                        await self._safe_click(self.cfg.selectors.back_button, timeout_ms=5000)
                        await self.page.locator(self.cfg.selectors.calculate_button).first.wait_for(state="attached", timeout=10000)
                    except Exception as back_exc:
                        logger.warning("Failed to return via back button: %s", back_exc)
            else:
                logger.error("Failed to calculate list target %s -> %s. Error: %s", dep_code, dst_code, error)
                if not pair.get("_retried"):
                    logger.warning("Auto-Retry trigger: Appending %s -> %s to the back of the queue to retry once WAF cools down.", dep_code, dst_code)
                    pair["_retried"] = True
                    pairs.append(pair)
                    continue  # Skip saving the record so it doesn't leave an empty row in CSV
                else:
                    logger.error("Permanent Failure: Target %s -> %s failed twice. Skipping permanently.", dep_code, dst_code)

            new_rec = RunRecord(
                    departure_code=dep_code,
                    departure_text=dep_code,
                    destination_code=dst_code,
                    destination_text=dst_code,
                    saf_flag="",
                    status="ok" if not error else "error",
                    target_label_text=target_label,
                    target_value_raw=target_value,
                    target_value_kg=target_kg,
                    distance_value_km=distance_km,
                    fuel_value_kg=fuel_kg,
                    raw_result_html=raw_html,
                    scraped_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    error=error,
                )
            records.append(new_rec)
            if on_record_cb:
                on_record_cb(new_rec)
            await self._sleep_rate_limit(pair_idx, success=(not error))

        return records
