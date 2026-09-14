#!/usr/bin/env python3
"""Detect subscription-level Azure cost spikes."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from csv_parser import CostReportError, parse_cost_records


DEFAULT_THRESHOLD_PERCENT = Decimal("50")
DEFAULT_BASELINE_WINDOW_DAYS = 7

def _group_daily_costs(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, dict[date, Decimal]]:
    """Group actual costs by subscription and usage date."""
    daily_costs: dict[str, dict[date, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: Decimal("0"))
    )

    for record in records:
        usage_date = record["usage_date"]
        cost = record["cost"]
        subscription_id = (
            record.get("subscription_id")
            or "unknown-subscription"
        )

        if not isinstance(usage_date, date):
            raise CostReportError(
                "Record has an invalid usage_date"
            )

        if not isinstance(cost, Decimal):
            raise CostReportError(
                "Record has an invalid Decimal cost"
            )

        daily_costs[subscription_id][usage_date] += cost

    return {
        subscription_id: dict(costs_by_date)
        for subscription_id, costs_by_date
        in daily_costs.items()
    }


def _find_missing_dates(
    daily_costs: Mapping[date, Decimal],
    expected_dates: Sequence[date],
) -> list[date]:
    """Return expected dates that do not exist in the input data."""
    return [
        expected_date
        for expected_date in expected_dates
        if expected_date not in daily_costs
    ]


def _top_cost_drivers(
    records: Sequence[Mapping[str, Any]],
    current_date: date,
    subscription_id: str,
) -> dict[str, Any]:
    """Find the largest service, resource group, and resource for a day."""
    current_records = [
        record
        for record in records
        if record.get("subscription_id")
        == subscription_id
        and record.get("usage_date") == current_date
    ]

    def group_total(field_name: str) -> tuple[str | None, Decimal]:
        totals: dict[str, Decimal] = defaultdict(
            lambda: Decimal("0")
        )

        for record in current_records:
            name = record.get(field_name) or "Unknown"
            totals[name] += record["cost"]

        if not totals:
            return None, Decimal("0")

        name, total = max(
            totals.items(),
            key=lambda item: item[1],
        )
        return name, total

    service_name, service_cost = group_total("service_name")
    resource_group, resource_group_cost = group_total(
        "resource_group"
    )
    resource_name, resource_cost = group_total("resource_name")

    return {
        "top_service": service_name,
        "top_service_cost": service_cost,
        "top_resource_group": resource_group,
        "top_resource_group_cost": resource_group_cost,
        "top_resource": resource_name,
        "top_resource_cost": resource_cost,
    }


def _evaluate_subscription(
    subscription_id: str,
    records: Sequence[Mapping[str, Any]],
    daily_costs: Mapping[date, Decimal],
    threshold_percent: Decimal,
    baseline_window_days: int,
) -> dict[str, Any]:
    """Evaluate the latest available day for one subscription."""
    latest_date = max(daily_costs)

    baseline_dates = [
        latest_date - timedelta(days=offset)
        for offset in range(1, baseline_window_days + 1)
    ]

    missing_dates = _find_missing_dates(
        daily_costs,
        baseline_dates,
    )

    if missing_dates:
        return {
            "subscription_id": subscription_id,
            "status": "insufficient_history",
            "spike_detected": False,
            "current_date": latest_date,
            "missing_dates": missing_dates,
            "baseline_window_days": baseline_window_days,
            "reason": (
                "A reliable baseline cannot be calculated because "
                "historical dates are missing."
            ),
        }

    baseline_cost = (
        sum(
            (daily_costs[day] for day in baseline_dates),
            Decimal("0"),
        )
        / Decimal(baseline_window_days)
    )

    current_cost = daily_costs[latest_date]

    if baseline_cost == 0:
        increase_percent = None
        is_spike = current_cost > 0
    else:
        increase_percent = (
            (current_cost - baseline_cost)
            / baseline_cost
        ) * Decimal("100")

        is_spike = increase_percent >= threshold_percent

    result: dict[str, Any] = {
        "subscription_id": subscription_id,
        "status": "evaluated",
        "current_date": latest_date,
        "current_cost": current_cost,
        "baseline_cost": baseline_cost,
        "baseline_window_days": baseline_window_days,
        "threshold_percent": threshold_percent,
        "increase_percent": increase_percent,
        "is_spike": is_spike,
        "missing_dates": [],
    }

    if is_spike:
        result.update(
            _top_cost_drivers(
                records=records,
                current_date=latest_date,
                subscription_id=subscription_id,
            )
        )

    return result


def detect_spikes(
    records: Sequence[Mapping[str, Any]],
    threshold_percent: int | float | Decimal = (
        DEFAULT_THRESHOLD_PERCENT
    ),
    baseline_window_days: int = (
        DEFAULT_BASELINE_WINDOW_DAYS
    ),
) -> list[dict[str, Any]]:
    """Detect spikes for every subscription in normalized records."""
    if baseline_window_days < 1:
        raise ValueError(
            "baseline_window_days must be at least 1"
        )

    threshold = Decimal(str(threshold_percent))

    if threshold < 0:
        raise ValueError(
            "threshold_percent cannot be negative"
        )

    if not records:
        return []

    daily_costs_by_subscription = _group_daily_costs(records)
    results = []

    for subscription_id, daily_costs in (
        daily_costs_by_subscription.items()
    ):
        results.append(
            _evaluate_subscription(
                subscription_id=subscription_id,
                records=records,
                daily_costs=daily_costs,
                threshold_percent=threshold,
                baseline_window_days=baseline_window_days,
            )
        )

    return results


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, Decimal)):
        return str(value)
    raise TypeError(
        f"Object of type {type(value).__name__} is not JSON serializable"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect Azure cost spikes from a normalized CSV."
    )
    parser.add_argument(
        "csv_file",
        type=Path,
        help="Path to the Azure cost CSV file",
    )
    parser.add_argument(
        "--threshold",
        type=Decimal,
        default=Decimal("50"),
        help="Spike threshold percentage; default: 50",
    )
    parser.add_argument(
        "--baseline-days",
        type=int,
        default=7,
        help="Number of previous days used as baseline; default: 7",
    )
    args = parser.parse_args()

    try:
        records = parse_cost_records(args.csv_file)

        results = detect_spikes(
            records=records,
            threshold_percent=args.threshold,
            baseline_window_days=args.baseline_days,
        )

        print(
            json.dumps(
                results,
                default=_json_default,
                indent=2,
            )
        )
        return 0

    except (CostReportError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
