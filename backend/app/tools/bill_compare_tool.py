from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.bill_compare import (
    DEFAULT_HOURS_PER_MONTH,
    BillComparisonAnalyzer,
    LimitCatalog,
)
from app.services.oci_sdk import OciSdk


DEFAULT_CATALOG = Path(__file__).resolve().parents[1] / "data" / "oci_limit_catalog.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze cloud bill-comparison exports against OCI service-limit names."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    refresh = subparsers.add_parser("refresh-catalog", help="Build an offline OCI limits catalog.")
    refresh.add_argument("--output", type=Path, default=DEFAULT_CATALOG)
    refresh.add_argument("--profile", default=None)
    refresh.add_argument("--region", default=None)
    refresh.add_argument("--compartment-id", default=None)

    analyze = subparsers.add_parser("analyze", help="Analyze a bill-comparison .xlsx or .csv file.")
    analyze.add_argument("--input", type=Path, required=True)
    analyze.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    analyze.add_argument("--output", type=Path)
    analyze.add_argument("--format", choices=["json", "csv"], default="json")
    analyze.add_argument("--hours-per-month", type=float, default=DEFAULT_HOURS_PER_MONTH)
    analyze.add_argument("--unmapped-limit", type=int, default=200)

    args = parser.parse_args(argv)
    if args.command == "refresh-catalog":
        return _refresh_catalog(args)
    if args.command == "analyze":
        return _analyze(args)
    parser.error(f"Unsupported command: {args.command}")
    return 2


def _refresh_catalog(args: argparse.Namespace) -> int:
    settings = get_settings()
    sdk_updates = {"oci_default_region": args.region or settings.oci_default_region}
    if args.profile:
        sdk_updates.update({"oci_auth_mode": "profile", "oci_profile": args.profile})
    sdk_settings = settings.model_copy(update=sdk_updates)
    catalog = LimitCatalog.from_oci_sdk(
        compartment_id=args.compartment_id or settings.oci_tenancy_ocid,
        region=args.region or settings.oci_default_region,
        sdk=OciSdk(sdk_settings),
    )
    catalog.save(args.output)
    print(
        f"Wrote {args.output} with {len(catalog.services)} services and "
        f"{sum(len(items) for items in catalog.definitions_by_service.values())} limits."
    )
    return 0


def _analyze(args: argparse.Namespace) -> int:
    catalog = LimitCatalog.load(args.catalog)
    analyzer = BillComparisonAnalyzer(
        catalog,
        hours_per_month=args.hours_per_month,
        unmapped_limit=args.unmapped_limit,
    )
    result = analyzer.analyze_file(args.input)
    if args.format == "csv":
        content = _requirements_csv(result)
    else:
        content = json.dumps(result, indent=2, sort_keys=True) + "\n"

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(content, end="")
    return 0


def _requirements_csv(result: dict[str, Any]) -> str:
    rows = result.get("requirements", [])
    fieldnames = [
        "service_name",
        "limit_name",
        "metric",
        "required_quantity",
        "unit",
        "confidence",
        "source_line_count",
        "scope_type",
        "limit_description",
    ]
    from io import StringIO

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field) for field in fieldnames})
    return buffer.getvalue()


if __name__ == "__main__":
    raise SystemExit(main())
