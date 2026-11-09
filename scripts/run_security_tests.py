"""Run the security test suite and write the report.

    uv run python scripts/run_security_tests.py            # deterministic tests only (free)
    uv run python scripts/run_security_tests.py --live     # also send real attacks to the configured model

Reports are written to docs/SECURITY_TEST_REPORT.md and docs/security_test_results.json.
The API key is read the same way as the app (environment or .streamlit/secrets.toml) and is
never printed or written to the report.
"""

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
logging.disable(logging.WARNING)  # keep expected parser and HTTP warnings out of the console

from interview_app.openrouter import get_api_key, get_capabilities, get_model  # noqa: E402
from interview_app.security_suite import LiveContext, report_json, report_markdown, run_suite  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help="also run live jailbreak tests against the model")
    parser.add_argument("--model", help="model for live tests (default: OPENROUTER_MODEL)")
    args = parser.parse_args()

    context = None
    model = None
    if args.live:
        api_key = get_api_key()
        if not api_key:
            print("OPENROUTER_API_KEY is not configured; cannot run live tests.")
            return 2
        model = args.model or get_model()
        context = LiveContext(api_key=api_key, model=model, capabilities=get_capabilities(model))

    records = run_suite(context)
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "SECURITY_TEST_REPORT.md").write_text(report_markdown(records, model), encoding="utf-8")
    (docs / "security_test_results.json").write_text(report_json(records), encoding="utf-8")

    for record in records:
        print(f"{record.test_id:8} {record.status:4} {'(live) ' if record.live else ''}{record.scenario}")
    passed = sum(record.passed for record in records)
    print(f"\n{passed}/{len(records)} passed. Report: docs/SECURITY_TEST_REPORT.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
