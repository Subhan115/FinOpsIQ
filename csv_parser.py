#!/usr/bin/env python3
"""Parse and normalize Azure Cost Management CSV reports.

The parser returns all valid actual-cost records. It does not decide how many
historical days are needed for a baseline; that belongs in spike_detection.py.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class CostReportError(Exception):
    """Raised when an Azure cost report cannot be read or validated."""


DATE_COLUMNS = (
    "date",
    "usagedate",
    "serviceperiodstartdate",
    "billingperiodstartdate",
)

COST_COLUMNS = (
    "costinbillingcurrency",
    "costinpricingcurrency",
    "costinusd",
    "pretaxcost",
    "cost",
)

FORECAST_COLUMNS = (
    "forecastcost",
    "forecastcostusd",
)

SUBSCRIPTION_ID_COLUMNS = (
    "subscriptionid",
    "subscriptionidentification",
    "billingsubscriptionid",
)

SUBSCRIPTION_NAME_COLUMNS = (
    "subscriptionname",
    "billingprofilename",
)

SERVICE_COLUMNS = (
    "consumedservice",
    "servicename",
    "servicefamily",
    "metercategory",
)

RESOURCE_GROUP_COLUMNS = (
    "resourcegroup",
    "resourcegroupname",
)

RESOURCE_ID_COLUMNS = (
    "resourceid",
)

RESOURCE_NAME_COLUMNS = (
    "resourcename",
    "resource_name",
)

LOCATION_COLUMNS = (
    "location",
    "resourcelocation",
    "meterregion",
)

CURRENCY_COLUMNS = (
    "currency",
    "billingcurrency",
    "pricingcurrency",
)

COST_TYPE_COLUMNS = ("costtype",)
CHARGE_TYPE_COLUMNS = ("chargetype",)

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


def _normalise_header(value: Any) -> str:
    """Normalize spaces, punctuation, case, and BOMs in a CSV header."""
    text = _normalise(value).lstrip("\\ufeff").casefold()
    return re.sub(r"[^a-z0-9]+", "", text)


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
            return datetime.strptime(
                text.replace("Z", ""),
                date_format,
            ).date()
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(
            text.replace("Z", "+00:00")
        ).date()
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


def _first_value(
    row: Mapping[str, Any],
    columns: Sequence[str],
) -> str:
    for column in columns:
        value = _normalise(row.get(column))
        if value:
            return value
    return ""


def _first_date(
    row: Mapping[str, Any],
    columns: Sequence[str],
) -> date | None:
    for column in columns:
        value = _normalise(row.get(column))
        if value:
            parsed = _parse_date(value)
            if parsed is not None:
                return parsed
    return None


def _first_decimal(
    row: Mapping[str, Any],
    columns: Sequence[str],
) -> Decimal | None:
    for column in columns:
        value = _normalise(row.get(column))
        if value:
            parsed = _parse_decimal(value)
            if parsed is not None:
                return parsed
    return None


def _value_or_none(
    row: Mapping[str, Any],
    columns: Sequence[str],
) -> str | None:
    value = _first_value(row, columns)
    return value or None


def _resource_name_from_id(resource_id: str | None) -> str | None:
    if not resource_id:
        return None
    value = resource_id.rstrip("/")
    return value.rsplit("/", 1)[-1] or None


def _detail_record(
    row_number: int,
    row: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Convert one raw row into a normalized actual-cost record.

    Forecast-only rows are ignored because FinOpsIQ's initial spike analysis
    uses actual costs only.
    """
    usage_date = _first_date(row, DATE_COLUMNS)
    actual_cost = _first_decimal(row, COST_COLUMNS)
    forecast_cost = _first_decimal(row, FORECAST_COLUMNS)

    if usage_date is None:
        raise CostReportError(
            f"Row {row_number}: usage date is missing or invalid"
        )

    if actual_cost is None and forecast_cost is not None:
        return None

    if actual_cost is None:
        raise CostReportError(
            f"Row {row_number}: actual cost is missing or invalid"
        )

    resource_id = _value_or_none(row, RESOURCE_ID_COLUMNS)
    resource_name = _value_or_none(row, RESOURCE_NAME_COLUMNS)

    return {
        "usage_date": usage_date,
        "subscription_id": _value_or_none(
            row,
            SUBSCRIPTION_ID_COLUMNS,
        ),
        "subscription_name": _value_or_none(
            row,
            SUBSCRIPTION_NAME_COLUMNS,
        ),
        "resource_group": _value_or_none(
            row,
            RESOURCE_GROUP_COLUMNS,
        ),
        "resource_id": resource_id,
        "resource_name": (
            resource_name
            or _resource_name_from_id(resource_id)
        ),
        "service_name": _value_or_none(row, SERVICE_COLUMNS),
        "location": _value_or_none(row, LOCATION_COLUMNS),
        "cost": actual_cost,
        "currency": _value_or_none(row, CURRENCY_COLUMNS),
        "cost_type": _value_or_none(row, COST_TYPE_COLUMNS) or "actual",
        "charge_type": _value_or_none(row, CHARGE_TYPE_COLUMNS) or "Usage",
    }


def _read_rows(
    path: Path,
) -> tuple[list[str], Iterable[tuple[int, dict[str, str]]]]:
    if not path.exists():
        raise CostReportError(f"CSV file does not exist: {path}")
    if not path.is_file():
        raise CostReportError(f"CSV path is not a file: {path}")

    try:
        handle = path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        )
    except OSError as exc:
        raise CostReportError(
            f"Unable to open CSV file '{path}': {exc}"
        ) from exc

    try:
        reader = csv.DictReader(handle, strict=True)

        if not reader.fieldnames:
            raise CostReportError(
                "CSV file is empty or has no header row"
            )

        fieldnames = [
            _normalise_header(name)
            for name in reader.fieldnames
            if name and _normalise_header(name)
        ]

        if not fieldnames:
            raise CostReportError(
                "CSV header contains no usable column names"
            )

        def rows() -> Iterable[tuple[int, dict[str, str]]]:
            try:
                for row_number, row in enumerate(reader, start=2):
                    if row is None:
                        continue

                    if not any(
                        _normalise(value)
                        for value in row.values()
                    ):
                        continue

                    if None in row and row[None]:
                        raise CostReportError(
                            "Malformed CSV row "
                            f"{row_number}: too many columns"
                        )

                    yield row_number, {
                        _normalise_header(key): _normalise(value)
                        for key, value in row.items()
                        if key is not None
                    }
            except csv.Error as exc:
                raise CostReportError(
                    f"Malformed CSV near row {row_number}: {exc}"
                ) from exc
            finally:
                handle.close()

        return fieldnames, rows()
    except Exception:
        handle.close()
        raise


def parse_cost_records(
    file_path: str | Path,
) -> list[dict[str, Any]]:
    """Parse and normalize all actual-cost records in a CSV.

    The function returns every valid actual-cost row in chronological order.
    It does not select a seven-day window; the spike detector owns that rule.
    """
    path = Path(file_path).expanduser()
    fieldnames, rows = _read_rows(path)
    field_set = set(fieldnames)

    if not any(column in field_set for column in DATE_COLUMNS):
        raise CostReportError(
            "CSV is missing a supported date column; expected one of "
            f"{DATE_COLUMNS}"
        )

    if not any(column in field_set for column in COST_COLUMNS):
        raise CostReportError(
            "CSV is missing a supported actual cost column; expected one of "
            f"{COST_COLUMNS}"
        )

    records: list[dict[str, Any]] = []

    for row_number, row in rows:
        record = _detail_record(row_number, row)
        if record is not None:
            records.append(record)

    return sorted(
        records,
        key=lambda item: item["usage_date"],
    )


def _missing_dates(
    records: Sequence[Mapping[str, Any]],
    first_date: date,
    last_date: date,
) -> list[date]:
    observed_dates = {
        record["usage_date"]
        for record in records
    }

    expected_dates = {
        first_date + timedelta(days=offset)
        for offset in range((last_date - first_date).days + 1)
    }

    return sorted(expected_dates - observed_dates)


def detailed_seven_day_analysis(
    file_path: str | Path,
) -> list[dict[str, Any]]:
    """Return records for the latest seven calendar days.

    This compatibility helper remains available, but baseline selection should
    normally be performed by spike_detection.py.
    """
    records = parse_cost_records(file_path)

    if not records:
        return []

    latest_date = max(record["usage_date"] for record in records)
    first_date = latest_date - timedelta(days=6)
    selected = [
        {field: record[field] for field in DETAIL_FIELDS}
        for record in records
        if first_date <= record["usage_date"] <= latest_date
    ]

    missing_dates = _missing_dates(
        selected,
        first_date,
        latest_date,
    )

    if missing_dates:
        raise CostReportError(
            "Missing dates in latest seven-day window: "
            + ", ".join(value.isoformat() for value in missing_dates)
        )

    return selected


def parse_cost_management_report(
    file_path: str | Path,
) -> dict[str, Any]:
    """Return a summary of actual-cost records in a CSV."""
    records = parse_cost_records(file_path)

    dates = [record["usage_date"] for record in records]
    subscriptions = sorted(
        {
            record["subscription_id"]
            for record in records
            if record.get("subscription_id")
        }
    )
    services = sorted(
        {
            record["service_name"]
            for record in records
            if record.get("service_name")
        }
    )
    currencies = sorted(
        {
            record["currency"]
            for record in records
            if record.get("currency")
        }
    )

    return {
        "number_of_records": len(records),
        "earliest_date": min(dates).isoformat() if dates else None,
        "latest_date": max(dates).isoformat() if dates else None,
        "total_cost": str(
            sum(
                (record["cost"] for record in records),
                Decimal("0"),
            )
        ),
        "currency": currencies[0] if len(currencies) == 1 else None,
        "subscriptions_found": subscriptions,
        "services_found": services,
        "warnings": [],
    }


def analyze_csv(file_path: str | Path) -> dict[str, Any]:
    """Backward-compatible alias for parse_cost_management_report."""
    return parse_cost_management_report(file_path)


def print_seven_day_analysis(
    records: Sequence[Mapping[str, Any]],
) -> None:
    """Print records in ascending date order with daily totals."""
    grouped: defaultdict[date, list[Mapping[str, Any]]] = defaultdict(list)

    for record in records:
        usage_date = record.get("usage_date")
        cost = record.get("cost")

        if not isinstance(usage_date, date):
            raise CostReportError(
                "Detailed records must contain a date usage_date"
            )
        if not isinstance(cost, Decimal):
            raise CostReportError(
                "Detailed records must contain a Decimal cost"
            )

        grouped[usage_date].append(record)

    for day_number, usage_date in enumerate(sorted(grouped), start=1):
        day_records = grouped[usage_date]
        total = sum(
            (record["cost"] for record in day_records),
            Decimal("0"),
        )
        currencies = sorted(
            {
                str(record["currency"])
                for record in day_records
                if record.get("currency")
            }
        )
        currency_label = (
            currencies[0]
            if len(currencies) == 1
            else "mixed currencies"
        )

        print(
            f"Day {day_number} ({usage_date.isoformat()}) "
            f"total cost: {total} {currency_label}"
        )

        for record in day_records:
            print(f"  {record}")


def _json_seven_day_analysis(
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Create chronological JSON output with daily totals."""
    grouped: defaultdict[date, list[Mapping[str, Any]]] = defaultdict(list)

    for record in records:
        usage_date = record.get("usage_date")
        cost = record.get("cost")

        if not isinstance(usage_date, date):
            raise CostReportError(
                "Detailed records must contain a date usage_date"
            )
        if not isinstance(cost, Decimal):
            raise CostReportError(
                "Detailed records must contain a Decimal cost"
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
                    (record["cost"] for record in day_records),
                    Decimal("0"),
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
        description=(
            "Parse and summarize an Azure Cost Management CSV report."
        )
    )
    parser.add_argument(
        "csv_file",
        type=Path,
        help="Path to the Azure cost CSV file",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output",
    )

    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--details",
        action="store_true",
        help="Return the latest seven calendar days",
    )
    output_group.add_argument(
        "--summary",
        action="store_true",
        help="Return the aggregate report summary",
    )
    output_group.add_argument(
        "--json",
        action="store_true",
        help="Return detailed records as JSON",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        if args.summary:
            result = parse_cost_management_report(args.csv_file)
        elif args.details:
            result = detailed_seven_day_analysis(args.csv_file)
        else:
            result = parse_cost_records(args.csv_file)
    except CostReportError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        if args.summary:
            print(
                json.dumps(
                    result,
                    cls=_JsonEncoder,
                    indent=2 if args.pretty else None,
                )
            )
        elif args.json:
            print(
                json.dumps(
                    _json_seven_day_analysis(result),
                    cls=_JsonEncoder,
                    indent=2,
                )
            )
        elif args.details:
            print_seven_day_analysis(result)
        else:
            print(
                json.dumps(
                    result,
                    cls=_JsonEncoder,
                    indent=2 if args.pretty else None,
                )
            )
    except BrokenPipeError:
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
