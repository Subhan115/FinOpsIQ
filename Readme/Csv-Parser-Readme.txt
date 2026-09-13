CSV Parser for Azure Cost Management Reports
============================================

File
----

The program is located at:

    csv_parser.py

It uses only Python's standard library. No third-party packages are required.


Purpose
-------

This program reads Azure Cost Management CSV reports and extracts detailed
cost records. It supports both the Azure export format in part_0_0001.csv and
the simpler FinOpsIQ report format in finopsiq-demo-costs-spike.csv.

The detailed output includes:

    usage_date
    subscription_id
    subscription_name
    resource_group
    resource_id
    resource_name
    service_name
    location
    cost
    currency
    cost_type
    charge_type


Requirements
------------

Python 3.10 or newer is recommended.

The program uses:

    csv
    json
    argparse
    datetime
    decimal
    pathlib
    typing

All of these modules are included with Python. No pip installation is needed.


Running on Windows 11
---------------------

Yes. This program can run directly on Windows 11 as long as Python 3.10 or
newer is installed and available from the command prompt.

To check whether Python is installed, open Command Prompt or PowerShell and
run:

    py --version

or:

    python --version

If Python is not installed, install it from:

    https://www.python.org/downloads/windows/

During installation, enable the option:

    Add python.exe to PATH

The program does not depend on Linux-only commands, shell scripts, Terraform,
or third-party Python packages.


Command-Line Usage
------------------

From the project directory, run:

    python3 csv_parser.py finopsiq-demo-costs-spike.csv

On Windows, use either:

    py csv_parser.py finopsiq-demo-costs-spike.csv

or:

    python csv_parser.py finopsiq-demo-costs-spike.csv

The default output is detailed records for the latest seven calendar days
found in the CSV file. Days are printed in ascending sequence order. For each
day, the total cost is printed first, followed by that day's detailed records.

For formatted JSON output:

    py csv_parser.py finopsiq-demo-costs-spike.csv --pretty

To print detailed records as JSON instead of sequence-wise daily text:

    py csv_parser.py finopsiq-demo-costs-spike.csv --json

JSON mode groups records by Day 1 through Day 7 and prints each day's date and
total cost before that day's records. JSON mode is formatted for readability
automatically.

To use the original aggregate summary mode:

    py csv_parser.py finopsiq-demo-costs-spike.csv --summary

The summary includes:

    number_of_records
    earliest_date
    latest_date
    total_cost
    currency
    subscriptions_found
    services_found
    warnings


Python API
----------

Detailed seven-day analysis:

    from csv_parser import detailed_seven_day_analysis

    records = detailed_seven_day_analysis(
        "finopsiq-demo-costs-spike.csv"
    )

Aggregate summary:

    from csv_parser import parse_cost_management_report

    summary = parse_cost_management_report(
        "finopsiq-demo-costs-spike.csv"
    )

The detailed analysis returns a list of dictionaries. In Python:

    usage_date is datetime.date
    cost is decimal.Decimal

This avoids inaccurate floating-point calculations for dates and monetary
values.

When the same result is printed by the command-line program as JSON:

    dates are printed as ISO strings, for example "2026-09-07"
    Decimal values are printed as strings, for example "210.00"


Seven-Day Behavior
------------------

The parser finds the latest valid usage date in the report and includes that
date plus the previous six calendar days.

For example, if the latest date is 2026-09-11, the selected range is:

    2026-09-05 through 2026-09-11

Rows outside this range are not included in detailed output.

If the CSV has fewer than seven calendar days, all available rows within the
calculated range are returned.


CSV Header Handling
-------------------

CSV header names are matched without regard to capitalization. These headers
are treated equivalently:

    date
    Date
    DATE

The same behavior applies to subscription, service, cost, resource, location,
currency, and charge-type headers.

Supported date examples include:

    2026-09-07
    09/07/2026
    2026-09-07T00:00:00

Supported cost columns include:

    Cost
    costInBillingCurrency
    costInPricingCurrency
    costInUsd


Default Values
--------------

If a detailed row does not contain cost_type, the parser uses:

    actual

If a detailed row does not contain charge_type, the parser uses:

    Usage

If resource_name is missing but resource_id is available, the parser derives
the resource name from the final part of the resource ID.


Error Handling
--------------

The parser raises CostReportError for problems such as:

    missing CSV files
    paths that are not files
    empty files
    missing or unusable headers
    malformed CSV rows
    missing supported date columns
    missing supported cost columns
    invalid dates in detailed records
    invalid costs in detailed records

The command-line program prints a clear error message and exits with status
code 1 when a CostReportError occurs.


Example
-------

Command:

    py csv_parser.py finopsiq-demo-costs-spike.csv --pretty

Example detailed record:

    {
      "usage_date": "2026-09-07",
      "subscription_id": "sub-demo-001",
      "subscription_name": "FinOpsIQ Demo Subscription",
      "resource_group": "demo-production-rg",
      "resource_id": "/subscriptions/sub-demo-001/resourceGroups/demo-production-rg/providers/Microsoft.Compute/virtualMachines/web-vm-01",
      "resource_name": "web-vm-01",
      "service_name": "Virtual Machines",
      "location": "eastus",
      "cost": "210.00",
      "currency": "USD",
      "cost_type": "actual",
      "charge_type": "Usage"
    }


Notes
-----

The parser reads the CSV file but does not modify it.

Use quotes around paths that contain spaces. For example:

    py csv_parser.py "C:\Reports\Azure Costs.csv" --pretty
