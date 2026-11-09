"""Export the security test results (docs/security_test_results.json) to an Excel sheet.

Run: uv run --with openpyxl python scripts/export_security_xlsx.py
openpyxl is only needed for this export, so it is not an app dependency.
"""

import json
from collections import Counter
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "security_test_results.json"
TARGET = ROOT / "docs" / "SECURITY_TEST_RESULTS.xlsx"

COLUMNS = (
    ("ID", "test_id", 11), ("Category", "category", 24), ("Scenario", "scenario", 34),
    ("Test input", "test_input", 50), ("Expected behaviour", "expected", 50), ("Actual behaviour", "actual", 50),
    ("Result", "status", 9), ("Vulnerability", "vulnerability", 36), ("Recommendation", "recommendation", 44),
    ("Live model call", "live", 10), ("Cost (USD)", "cost_usd", 11),
)
PASS_FILL = PatternFill("solid", fgColor="DCEFE0")
FAIL_FILL = PatternFill("solid", fgColor="F8D7D3")


def cell_value(record: dict, key: str):
    value = record.get(key)
    if key == "live":
        return "Yes" if value else "No"
    if isinstance(value, str):
        # Excel rejects control characters; the tests deliberately contain some.
        return "".join(ch if ch in "\n\t" or ord(ch) >= 32 else f"\\x{ord(ch):02x}" for ch in value)[:32000]
    return value


def main() -> None:
    records = json.loads(SOURCE.read_text(encoding="utf-8"))
    book = Workbook()

    sheet = book.active
    sheet.title = "Results"
    sheet.append([title for title, _key, _width in COLUMNS])
    for record in records:
        sheet.append([cell_value(record, key) for _title, key, _width in COLUMNS])
    for index, (_title, _key, width) in enumerate(COLUMNS, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    result_column = [key for _t, key, _w in COLUMNS].index("status") + 1
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        status = row[result_column - 1]
        status.font = Font(bold=True)
        status.fill = PASS_FILL if status.value == "PASS" else FAIL_FILL
        row[[key for _t, key, _w in COLUMNS].index("cost_usd")].number_format = "$0.00000"
    sheet.freeze_panes = "B2"
    table = Table(displayName="SecurityTests", ref=f"A1:{get_column_letter(len(COLUMNS))}{len(records) + 1}")
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium7", showRowStripes=True)
    sheet.add_table(table)

    summary = book.create_sheet("Summary")
    passed = sum(1 for r in records if r["status"] == "PASS")
    summary.append(["Interview App security and jailbreak tests"])
    summary["A1"].font = Font(bold=True, size=14)
    summary.append([])
    summary.append(["Total tests", len(records)])
    summary.append(["Passed", passed])
    summary.append(["Failed", len(records) - passed])
    summary.append(["Pass rate", passed / len(records)])
    summary["B6"].number_format = "0%"
    summary.append(["Live model calls", sum(1 for r in records if r.get("live"))])
    summary.append([])
    summary.append(["Category", "Tests", "Passed", "Failed"])
    for cell in summary[9]:
        cell.font = Font(bold=True)
    totals, passes = Counter(r["category"] for r in records), Counter(r["category"] for r in records if r["status"] == "PASS")
    for category, count in totals.items():
        summary.append([category, count, passes[category], count - passes[category]])
    summary.append([])
    summary.append(["Full details, including the failed test and its mitigation: docs/SECURITY_TEST_REPORT.md"])
    summary.column_dimensions["A"].width = 40
    for column in "BCD":
        summary.column_dimensions[column].width = 10
    book.move_sheet("Summary", offset=-1)
    book.active = 0

    book.save(TARGET)
    print(f"Wrote {TARGET.relative_to(ROOT)}: {len(records)} tests, {passed} passed")


if __name__ == "__main__":
    main()
