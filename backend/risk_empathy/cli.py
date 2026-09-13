"""CLI: evaluate, verify."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from backend.data_empathy.codec import dumps_canonical
from backend.data_empathy.loader import DataStore, default_xlsx_path, load_workbook_readonly
from backend.data_empathy.snapshot import SnapshotQuery, build_snapshot

from .assemble import assemble_analysis
from .pack import load_pack
from .repair import process_provider_output
from .verify import format_verify_text, verify_phase_b


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.risk_empathy")
    parser.add_argument("--xlsx", default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify", help="Run RISK-C001–C004")
    p_eval = sub.add_parser("evaluate", help="Evaluate one snapshot")
    p_eval.add_argument("--session", required=True)
    p_eval.add_argument("--message-no", type=int, default=None)
    p_eval.add_argument("--as-of", default=None)
    args = parser.parse_args(argv)
    if args.cmd == "verify":
        xlsx = Path(args.xlsx) if args.xlsx else default_xlsx_path()
        report = verify_phase_b(xlsx)
        sys.stdout.write(format_verify_text(report))
        return 0 if report["passed"] else 1
    if args.cmd == "evaluate":
        xlsx = Path(args.xlsx) if args.xlsx else default_xlsx_path()
        store = DataStore(load_workbook_readonly(xlsx))
        snap = build_snapshot(
            store,
            SnapshotQuery(session_id=args.session, message_no=args.message_no, as_of_time=args.as_of),
        )
        pack = load_pack()
        bundled = assemble_analysis(snap, pack=pack)
        processed = process_provider_output(
            bundled["analysis"],
            provider="RuleProvider",
            snapshot=snap,
            rule_risk=bundled["risk_full"],
            pack=pack,
        )
        sys.stdout.write(dumps_canonical({
            "analysis": bundled["analysis"],
            "risk_full": bundled["risk_full"],
            "emotion_full": bundled["emotion_full"],
            "degradation": {
                "can_enter_human_confirmation": processed["can_enter_human_confirmation"],
                "fallback": processed["fallback"],
                "safety_status": processed["safety_check_result"]["status"],
            },
        }))
        return 0
    raise AssertionError(args.cmd)
