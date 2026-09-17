"""CLI: run, verify."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from backend.data_empathy.loader import DataStore, default_xlsx_path, load_workbook_readonly


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.eval_empathy")
    parser.add_argument("--xlsx", default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="Build split/gold, run four arms, emit frozen reports")
    sub.add_parser("verify", help="EVAL-C001–C004 verification over generated artifacts")
    args = parser.parse_args(argv)

    if args.cmd == "run":
        from .report import run_frozen

        xlsx = Path(args.xlsx) if args.xlsx else default_xlsx_path()
        store = DataStore(load_workbook_readonly(xlsx))
        report = run_frozen(store)
        sys.stdout.write(
            f"frozen report: provider_mode={report['provider_mode']} "
            f"samples={len(report['samples'])} leakage_passed={report['leakage_regression']['passed']}\n"
        )
        return 0

    if args.cmd == "verify":
        from .verify import format_verify_text, verify_phase_e

        report = verify_phase_e()
        sys.stdout.write(format_verify_text(report))
        return 0 if report["passed"] else 1

    raise AssertionError(args.cmd)
