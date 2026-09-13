#!/usr/bin/env python3
"""Parse key points from an Azure Cost Management CSV report.

The parser intentionally uses only Python's standard library.  It accepts the
CSV format exported by Azure Cost Management and is tolerant of blank rows,
UTF-8 BOMs, common date formats, and non-numeric values in cost columns.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class CostReportError(Exception):
    """Raised when an Azure cost report cannot be read or validated."""


DATE_COLUMNS = ("date", "serviceperiodstartdate", "billingperiodstartdate")
COST_COLUMNS = (
    "costinbillingcurrency",
    "costinpricingcurrency",
    "costinusd",
    "cost",
)
SUBSCRIPTION_COLUMNS = ("subscriptionid", "subscriptionname")
SERVICE_COLUMNS = ("consumedservice", "servicename", "servicefamily")
DETAIL_FIELDS = (
    "usage_date",
    "subscription_id",
    "subscription_name",
    "resource_group",
    "resource_id",
    "resource_name",
    "service_name",
    "location",
    "cost",
    "currency",
    "cost_type",
    "charge_type",
)


def _normalise(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _parse_date(value: Any) -> date | None:
    text = _normalise(value)
    if not text:
        return None

    formats = (
        "%m/%d/%Y",
        "%m/%d/%y",
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    )
    for date_format in formats:
        try:
            return datetime.strptime(text.replace("Z", ""), date_format).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _parse_decimal(value: Any) -> Decimal | None:
    text = _normalise(value).replace(",", "")
    if not text:
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _first_value(row: Mapping[str, Any], columns: Sequence[str]) -> str:
    for column in columns:
        value = _normalise(row.get(column))
        if value:
            return value
    return ""


def _first_date(row: Mapping[str, Any], columns: Sequence[str]) -> date | None:
    for column in columns:
        value = _normalise(row.get(column))
        if value:
            parsed = _parse_date(value)
            if parsed is not None:
                return parsed
    return None


def _first_decimal(row: Mapping[str, Any], columns: Sequence[str]) -> Decimal | None:
    for column in columns:
        value = _normalise(row.get(column))
        if value:
            parsed = _parse_decimal(value)
            if parsed is not None:
                return parsed
    return None


def _value_or_none(row: Mapping[str, Any], columns: Sequence[str]) -> str | None:
    value = _first_value(row, columns)
    return value or None


def _resource_name_from_id(resource_id: str | None) -> str | None:
    if not resource_id:
        return None
    value = resource_id.rstrip("/")
    return value.rsplit("/", 1)[-1] or None


def _detail_record(row_number: int, row: Mapping[str, Any]) -> dict[str, Any]:
    usage_date = _first_date(row, DATE_COLUMNS)
    cost = _first_decimal(row, COST_COLUMNS)
    if usage_date is None:
        raise CostReportError(f"Row {row_number}: usage date is missing or invalid")
    if cost is None:
        raise CostReportError(f"Row {row_number}: cost is missing or invalid")

    resource_id = _value_or_none(row, ("resourceid", "resource_id"))
    resource_name = _value_or_none(row, ("resourcename", "resource_name"))
    return {
        "usage_date": usage_date,
        "subscription_id": _value_or_none(row, ("subscriptionid",)),
        "subscription_name": _value_or_none(
            row, ("subscriptionname", "billingprofilename")
        ),
        "resource_group": _value_or_none(
            row, ("resourcegroup", "resourcegroupname")
        ),
        "resource_id": resource_id,
        "resource_name": resource_name or _resource_name_from_id(resource_id),
        "service_name": _value_or_none(
            row, ("servicename", "metercategory", "consumedservice", "servicefamily")
        ),
        "location": _value_or_none(row, ("location", "resourcelocation", "meterregion")),
        "cost": cost,
        "currency": _value_or_none(
            row, ("currency", "billingcurrency", "pricingcurrency")
        ),
        "cost_type": _value_or_none(row, ("costtype",)) or "actual",
        "charge_type": _value_or_none(row, ("chargetype",)) or "Usage",
    }


def detailed_seven_day_analysis(file_path: str | Path) -> list[dict[str, Any]]:
    """Return fixed-shape cost records for the latest seven calendar days.

    Records use ``datetime.date`` and ``decimal.Decimal`` values so callers can
    perform reliable date and monetary calculations without float rounding.
    """
    path = Path(file_path).expanduser()
    fieldnames, rows = _read_rows(path)
    field_set = set(fieldnames)
    if not any(column in field_set for column in DATE_COLUMNS):
        raise CostReportError(
            f"CSV is missing a supported date column; expected one of {DATE_COLUMNS}"
        )
    if not any(column in field_set for column in COST_COLUMNS):
        raise CostReportError(
            f"CSV is missing a supported cost column; expected one of {COST_COLUMNS}"
        )

    records: list[dict[str, Any]] = []
    for row_number, row in rows:
        records.append(_detail_record(row_number, row))
    if not records:
        return []

    latest_date = max(record["usage_date"] for record in records)
    first_date = latest_date - timedelta(days=6)
    return [
        {field: record[field] for field in DETAIL_FIELDS}
        for record in sorted(records, key=lambda item: item["usage_date"])
        if first_date <= record["usage_date"] <= latest_date
    ]


def _read_rows(path: Path) -> tuple[list[str], Iterable[tuple[int, dict[str, str]]]]:
    if not path.exists():
        raise CostReportError(f"CSV file does not exist: {path}")
    if not path.is_file():
        raise CostReportError(f"CSV path is not a file: {path}")

    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise CostReportError(f"Unable to open CSV file '{path}': {exc}") from exc

    try:
        reader = csv.DictReader(handle, strict=True)
        if not reader.fieldnames:
            raise CostReportError("CSV file is empty or has no header row")

        fieldnames = [name.strip().casefold() for name in reader.fieldnames if name]
        if not fieldnames:
            raise CostReportError("CSV header contains no usable column names")

        def rows() -> Iterable[tuple[int, dict[str, str]]]:
            row_number = 1
            try:
                for row_number, row in enumerate(reader, start=2):
                    if row is None or not any(_normalise(value) for value in row.values()):
                        continue
                    if None in row and row[None]:
                        raise CostReportError(
                            f"Malformed CSV row {row_number}: too many columns"
                        )
                    yield row_number, {
                        _normalise(key).casefold(): _normalise(value)
                        for key, value in row.items()
                        if key is not None
                    }
            except csv.Error as exc:
                raise CostReportError(f"Malformed CSV near row {row_number}: {exc}") from exc
            finally:
                handle.close()

        return fieldnames, rows()
    except Exception:
        handle.close()
        raise


def parse_cost_management_report(file_path: str | Path) -> dict[str, Any]:
    """Return key points from an Azure Cost Management CSV report.

    The returned mapping contains:
      * ``number_of_records``
      * ``earliest_date`` and ``latest_date`` as ISO date strings or ``None``
      * ``total_cost`` summed from the first available supported cost column
      * ``currency`` when present
      * ``subscriptions_found`` and ``services_found`` as sorted unique values
      * ``warnings`` for recoverable row-level issues
    """
    path = Path(file_path).expanduser()
    fieldnames, rows = _read_rows(path)
    field_set = set(fieldnames)

    if not any(column in field_set for column in DATE_COLUMNS):
        raise CostReportError(
            f"CSV is missing a supported date column; expected one of {DATE_COLUMNS}"
        )
    if not any(column in field_set for column in COST_COLUMNS):
        raise CostReportError(
            f"CSV is missing a supported cost column; expected one of {COST_COLUMNS}"
        )

    dates: list[date] = []
    subscriptions: set[str] = set()
    services: set[str] = set()
    warnings: list[str] = []
    total_cost = Decimal("0")
    record_count = 0
    currency = ""

    for row_number, row in rows:
        record_count += 1

        parsed_date = _first_date(row, DATE_COLUMNS)
        if parsed_date is None:
            warnings.append(f"Row {row_number}: date is missing or invalid")
        else:
            dates.append(parsed_date)

        cost_text = _first_value(row, COST_COLUMNS)
        cost = _first_decimal(row, COST_COLUMNS)
        if cost is None and cost_text:
            warnings.append(f"Row {row_number}: no supported cost value is numeric")
        elif cost is not None:
            total_cost += cost

        subscription = _first_value(row, SUBSCRIPTION_COLUMNS)
        if subscription:
            subscriptions.add(subscription)
        service = _first_value(row, SERVICE_COLUMNS)
        if service:
            services.add(service)
        if not currency:
            currency = _normalise(row.get("billingcurrency")) or _normalise(
                row.get("pricingcurrency")
            )

    result = {
        "number_of_records": record_count,
        "earliest_date": min(dates).isoformat() if dates else None,
        "latest_date": max(dates).isoformat() if dates else None,
        "total_cost": float(total_cost),
        "currency": currency or None,
        "subscriptions_found": sorted(subscriptions),
        "services_found": sorted(services),
        "warnings": warnings,
    }
    return result


def analyze_csv(file_path: str | Path) -> dict[str, Any]:
    """Backward-friendly alias for :func:`parse_cost_management_report`."""
    return parse_cost_management_report(file_path)


def print_seven_day_analysis(records: Sequence[Mapping[str, Any]]) -> None:
    """Print records in ascending date order, with each day's total first."""
    grouped: defaultdict[date, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        usage_date = record.get("usage_date")
        cost = record.get("cost")
        if not isinstance(usage_date, date) or not isinstance(cost, Decimal):
            raise CostReportError(
                "Detailed records must contain a datetime.date usage_date and "
                "decimal.Decimal cost"
            )
        grouped[usage_date].append(record)

    for day_number, usage_date in enumerate(sorted(grouped), start=1):
        day_records = grouped[usage_date]
        total = sum((record["cost"] for record in day_records), Decimal("0"))
        currencies = sorted(
            {
                str(record["currency"])
                for record in day_records
                if record.get("currency")
            }
        )
        currency_label = currencies[0] if len(currencies) == 1 else "mixed currencies"
        print(f"Day {day_number} ({usage_date.isoformat()}) total cost: {total} {currency_label}")
        for record in day_records:
            print(f"  {record}")


def _json_seven_day_analysis(
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Create readable, chronological JSON output with daily totals."""
    grouped: defaultdict[date, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        usage_date = record.get("usage_date")
        cost = record.get("cost")
        if not isinstance(usage_date, date) or not isinstance(cost, Decimal):
            raise CostReportError(
                "Detailed records must contain a datetime.date usage_date and "
                "decimal.Decimal cost"
            )
        grouped[usage_date].append(record)

    result = []
    for day_number, usage_date in enumerate(sorted(grouped), start=1):
        day_records = grouped[usage_date]
        currencies = sorted(
            {
                str(record["currency"])
                for record in day_records
                if record.get("currency")
            }
        )
        result.append(
            {
                "day": day_number,
                "usage_date": usage_date,
                "total_cost": sum(
                    (record["cost"] for record in day_records), Decimal("0")
                ),
                "currency": currencies[0] if len(currencies) == 1 else None,
                "records": list(day_records),
            }
        )
    return result


class _JsonEncoder(json.JSONEncoder):
    def default(self, value: Any) -> Any:
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        return super().default(value)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract key points from an Azure Cost Management CSV report."
    )
    parser.add_argument("csv_file", type=Path, help="Path to the Azure cost CSV file")
    parser.add_argument(
        "--pretty", action="store_true", help="Pretty-print the JSON result"
    )
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--details",
        action="store_true",
        help="Return fixed-shape records for the latest seven calendar days (default)",
    )
    output_group.add_argument(
        "--summary",
        action="store_true",
        help="Return the aggregate report summary instead",
    )
    output_group.add_argument(
        "--json",
        action="store_true",
        help="Return detailed records as JSON instead of sequence-wise text",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.summary:
            result = parse_cost_management_report(args.csv_file)
        else:
            result = detailed_seven_day_analysis(args.csv_file)
    except CostReportError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    try:
        if args.summary:
            print(json.dumps(result, cls=_JsonEncoder, indent=2 if args.pretty else None))
        elif args.json:
            print(json.dumps(_json_seven_day_analysis(result), cls=_JsonEncoder, indent=2))
        else:
            print_seven_day_analysis(result)
    except BrokenPipeError:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
