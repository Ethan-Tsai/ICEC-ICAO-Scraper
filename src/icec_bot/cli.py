from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .browser import start_session
from .config import load_config, validate_config_file
from .logging_utils import setup_logger
from .runner import IcecRunner
from .storage import append_records, write_json, write_custom_csv


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ICEC Playwright+Stealth scaffold")
    p.add_argument("command", choices=["validate-config", "dry-run", "run"])
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--output-json", type=Path, default=Path("out") / "results.json")
    p.add_argument("--target-csv", type=Path, default=None, help="Path to List.csv with target route pairs")
    p.add_argument("--max-pairs", type=int, default=None)
    p.add_argument("--skip-departures", type=int, default=0, help="Number of departures to skip (for chunking)")
    p.add_argument("--max-departures", type=int, default=None)
    p.add_argument("--max-destinations-per-departure", type=int, default=None)
    p.add_argument("--headful", action="store_true")
    return p.parse_args()


async def _main_async(args: argparse.Namespace) -> int:
    logger = setup_logger()

    if args.command == "validate-config":
        validate_config_file(args.config)
        logger.info("Config is valid and runtime-complete.")
        return 0

    cfg = load_config(args.config)
    if args.max_pairs is not None:
        cfg.run_limits.max_pairs = max(0, args.max_pairs)
    if args.max_departures is not None:
        cfg.run_limits.max_departures = max(0, args.max_departures)
    if args.max_destinations_per_departure is not None:
        cfg.run_limits.max_destinations_per_departure = max(0, args.max_destinations_per_departure)
    playwright, session = await start_session(cfg, headful_override=args.headful)
    primary_error: Exception | None = None
    try:
        runner = IcecRunner(session.page, cfg)
        if args.command == "dry-run":
            await runner.open()
            await runner.dry_run_selector_validation()
            logger.info("Dry run passed. All configured selectors are found.")
            return 0

        all_records = []
        auto_skip = args.skip_departures

        if args.output_json.exists():
            try:
                import json
                from .models import RunRecord
                existing_data = json.loads(args.output_json.read_text(encoding="utf-8"))
                for row in existing_data:
                    # Filter out purely internal or None fields if needed, but dict explosion works if schema matches
                    all_records.append(RunRecord(**row))
                if len(all_records) > auto_skip:
                    auto_skip = len(all_records)
                    logger.info("Auto-Resume: Found %s previous records in JSON. Setting skip to %s.", len(all_records), auto_skip)
            except Exception as e:
                logger.warning("Auto-Resume check failed. Starting fresh or using manual skip. Error: %s", e)

        def on_record(record):
            all_records.append(record)
            write_json(args.output_json, all_records)
            csv_path = args.output_json.with_suffix(".csv")
            write_custom_csv(csv_path, all_records)

        if args.command == "run":
            if args.target_csv:
                await runner.run_custom_list(args.target_csv, skip=auto_skip, max_pairs=args.max_pairs, on_record_cb=on_record)
            else:
                await runner.run_framework_only(skip_departures=auto_skip, on_record_cb=on_record)
            logger.info("Run completed naturally. Records written to JSON and CSV: %s", len(all_records))
            return 0

        raise RuntimeError(f"Unsupported command: {args.command}")
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.warning("Interrupted by user! Progress up to %s records has been saved continuously.", len(all_records))
        return 130
    except Exception as exc:  # pylint: disable=broad-except
        if 'all_records' in locals():
            logger.error("Crashed with error: %s. Progress up to %s records saved.", exc, len(all_records))
        else:
            logger.error("Crashed before records init: %s", exc)
        primary_error = exc
        raise
    finally:
        try:
            await session.close()
        except Exception as close_exc:  # pylint: disable=broad-except
            if primary_error is None:
                raise
            logger.warning("Ignored session close error after primary failure: %s", close_exc)
        try:
            await playwright.stop()
        except Exception as stop_exc:  # pylint: disable=broad-except
            if primary_error is None:
                raise
            logger.warning("Ignored playwright stop error after primary failure: %s", stop_exc)


def main() -> int:
    args = parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
