"""CLI: analyze, verify, report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from backend.data_empathy.codec import dumps_canonical
from backend.data_empathy.loader import DataStore, default_xlsx_path, load_workbook_readonly

from .agent import Agent, AnalysisRequest
from .runlog import RUN_LOG_PATH, cost_summary


def _build_agent(xlsx: str | None) -> Agent:
    path = Path(xlsx) if xlsx else default_xlsx_path()
    store = DataStore(load_workbook_readonly(path))
    return Agent(store)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.agent_empathy")
    parser.add_argument("--xlsx", default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify", help="Run AGENT-C001–C004 verification")
    p_an = sub.add_parser("analyze", help="Run one analysis")
    p_an.add_argument("--session", required=True)
    p_an.add_argument("--message-no", type=int, default=None)
    p_an.add_argument("--as-of", default=None)
    p_an.add_argument("--provider", default="MockProvider", choices=["MockProvider", "RuleProvider", "QwenProvider"])
    p_an.add_argument("--no-cache", action="store_true")
    p_cost = sub.add_parser("cost", help="Print cost summary from the run log")
    args = parser.parse_args(argv)

    if args.cmd == "verify":
        from .verify import format_verify_text, verify_phase_c

        xlsx = Path(args.xlsx) if args.xlsx else default_xlsx_path()
        report = verify_phase_c(xlsx)
        out = Path(report["artifacts"]["phase_c_verification"])
        sys.stdout.write(format_verify_text(report))
        sys.stdout.write(f"\nreport: {out}\n")
        return 0 if report["passed"] else 1

    if args.cmd == "analyze":
        agent = _build_agent(args.xlsx)
        if args.no_cache:
            from .runlog import NullCache

            agent.cache = NullCache()
        result = agent.analyze(AnalysisRequest(
            session_id=args.session,
            message_no=args.message_no,
            as_of_time=args.as_of,
            provider=args.provider,
        ))
        sys.stdout.write(dumps_canonical({
            "analysis_id": result.analysis_id,
            "run_id": result.run_id,
            "provider_used": result.provider_used,
            "degraded": result.degraded,
            "analysis": result.analysis,
            "safety_check_result": result.safety_check_result,
            "tool_calls": [
                {"tool": row["tool"], "status": row["status"], "duration_ms": row["duration_ms"]}
                for row in result.tool_calls
            ],
            "duration_ms": result.duration_ms,
            "cache_hit": result.cache_hit,
        }))
        return 0

    if args.cmd == "cost":
        from .runlog import RunLog

        log = RunLog()
        records = log.records()
        sys.stdout.write(dumps_canonical(cost_summary(records)))
        sys.stdout.write(f"\nrun_log: {RUN_LOG_PATH}\n")
        return 0

    raise AssertionError(args.cmd)
