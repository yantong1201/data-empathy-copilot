"""CLI: selfcheck, snapshot, fixtures, verify."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .codec import dumps_canonical
from .fixtures import generate_case_fixtures
from .loader import DataStore, default_xlsx_path, load_workbook_readonly, repo_root
from .selfcheck import run_selfcheck, write_selfcheck
from .snapshot import SnapshotQuery, build_snapshot
from .verify import format_verify_text, verify_phase_a


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.data_empathy")
    parser.add_argument("--xlsx", default=None, help="Official MOCK Excel path")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_self = sub.add_parser("selfcheck", help="DATA-T001 loader self-check")
    p_self.add_argument("--out", default=None)

    p_snap = sub.add_parser("snapshot", help="Build one snapshot JSON")
    p_snap.add_argument("--session", required=True)
    p_snap.add_argument("--message-no", type=int, default=None)
    p_snap.add_argument("--as-of", default=None)

    p_fix = sub.add_parser("fixtures", help="Write three-case fixtures")
    p_fix.add_argument("--out", default=None)

    sub.add_parser("verify", help="Run DATA-C001–C004")

    args = parser.parse_args(argv)
    xlsx = Path(args.xlsx) if args.xlsx else default_xlsx_path()
    if args.cmd == "selfcheck":
        bundle = load_workbook_readonly(xlsx)
        report = run_selfcheck(bundle)
        out = Path(args.out) if args.out else repo_root() / "data" / "reports" / "loader_selfcheck.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        write_selfcheck(report, out)
        sys.stdout.write(dumps_canonical({"wrote": str(out), "input_audit_all_match": report["input_audit_all_match"]}))
        return 0 if report["input_audit_all_match"] else 1
    if args.cmd == "snapshot":
        store = DataStore(load_workbook_readonly(xlsx))
        snap = build_snapshot(
            store,
            SnapshotQuery(session_id=args.session, message_no=args.message_no, as_of_time=args.as_of),
        )
        sys.stdout.write(dumps_canonical(snap))
        return 0
    if args.cmd == "fixtures":
        store = DataStore(load_workbook_readonly(xlsx))
        out = Path(args.out) if args.out else repo_root() / "data" / "fixtures"
        manifest = generate_case_fixtures(store, out)
        sys.stdout.write(dumps_canonical({"wrote": str(out), "files": list(manifest["file_sha256"])}))
        return 0
    if args.cmd == "verify":
        report = verify_phase_a(xlsx)
        sys.stdout.write(format_verify_text(report))
        return 0 if report["passed"] else 1
    raise AssertionError(args.cmd)
