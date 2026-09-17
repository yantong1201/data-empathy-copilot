"""Workbench HTTP server: real snapshots + real Agent + confirmations.

stdlib http.server only — no extra dependency. Serves the static workbench
and a JSON API. All data comes from the real Excel via Phase A and the Phase
C agent; nothing here fabricates values.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from backend.data_empathy.codec import dumps_canonical
from backend.data_empathy.loader import (
    DataStore,
    default_xlsx_path,
    load_workbook_readonly,
)
from backend.data_empathy.snapshot import SnapshotQuery, build_snapshot
from backend.data_empathy.timeutil import format_iso
from backend.risk_empathy.emotion import evaluate_emotion
from backend.risk_empathy.pack import load_pack
from backend.risk_empathy.rules import evaluate_risk
from backend.risk_empathy.evidence import snapshot_inconsistency_schema_items

from backend.agent_empathy.agent import Agent, AnalysisRequest
from backend.agent_empathy.providers import MockProvider, QwenProvider, RuleProvider
from backend.agent_empathy.runlog import RunLog, VersionedCache

from .state import WorkbenchState, new_operation_id

STATIC_DIR = Path(__file__).resolve().parent / "static"


class WorkbenchApp:
    def __init__(self, xlsx: Path | None = None):
        xlsx = xlsx or default_xlsx_path()
        self.store = DataStore(load_workbook_readonly(xlsx))
        self.pack = load_pack()
        self.agent = Agent(
            self.store,
            pack=self.pack,
            run_log=RunLog(),
            cache=VersionedCache(),
            providers={
                "MockProvider": MockProvider(),
                "RuleProvider": RuleProvider(),
                "QwenProvider": QwenProvider(),
            },
        )
        self.state = WorkbenchState()
        self._queue_lock = threading.Lock()
        self._queue: list[dict[str, Any]] | None = None

    # --- queue -------------------------------------------------------------

    def queue(self) -> list[dict[str, Any]]:
        with self._queue_lock:
            if self._queue is not None:
                return self._queue
        rows: list[dict[str, Any]] = []
        for session_id, chats in sorted(self.store.chats_by_session.items()):
            last = chats[-1]
            first_buyer = next((c for c in chats if c.role == "买家"), None)
            order = self.store.orders_by_session.get(session_id)
            wo = self.store.workorders_by_session.get(session_id)
            snap = build_snapshot(self.store, SnapshotQuery(
                session_id=session_id, message_no=last.message_no))
            emotion = evaluate_emotion(snap, self.pack)
            risk = evaluate_risk(snap, self.pack, emotion)
            rows.append({
                "session_id": session_id,
                "buyer_nick": last.buyer_nick,
                "shop": last.shop,
                "order_id": order.order_id if order else None,
                "workorder_id": wo.workorder_id if wo else None,
                "scene": (first_buyer.scene_major if first_buyer else None)
                or (last.scene_major if last.scene_major else "未标注"),
                "message_count": len(chats),
                "last_time": format_iso(last.message_time),
                "preview": (chats[-1].message_text or "")[:60],
                "risk_level": risk["level"],
                "risk_status": risk["status"],
                "risk_type": risk["type"],
                "status": self.state.status_of(session_id),
            })
        with self._queue_lock:
            self._queue = rows
        return rows

    # --- messages for replay ----------------------------------------------

    def messages(self, session_id: str) -> dict[str, Any]:
        rows = self.store.require_session(session_id)
        order = self.store.orders_by_session.get(session_id)
        wo = self.store.workorders_by_session.get(session_id)
        return {
            "session_id": session_id,
            "buyer_nick": rows[0].buyer_nick,
            "shop": rows[0].shop,
            "order_id": order.order_id if order else None,
            "workorder": {
                "workorder_id": wo.workorder_id if wo else None,
                "kind": wo.kind if wo else None,
                "create_time": format_iso(wo.create_time) if wo else None,
                "complete_time": format_iso(wo.complete_time) if wo and wo.complete_time else None,
            },
            "messages": [
                {
                    "message_no": row.message_no,
                    "message_time": format_iso(row.message_time),
                    "role": row.role,
                    "buyer_nick": row.buyer_nick,
                    "is_target_buyer_message": row.is_target_buyer_message,
                    "message_text": row.message_text,
                    "content_type": row.content_type,
                    "image_path": row.image_path,
                    "source_ref": f"chat:{row.session_id}:{row.message_no}",
                }
                for row in rows
            ],
        }

    # --- analysis ----------------------------------------------------------

    def analyze(
        self,
        session_id: str,
        message_no: int | None,
        as_of: str | None,
        provider: str,
    ) -> dict[str, Any]:
        if message_no is None and not as_of:
            raise ValueError("message_no or as_of required")
        request = AnalysisRequest(
            session_id=session_id,
            message_no=message_no,
            as_of_time=as_of,
            provider=provider if provider in {"MockProvider", "RuleProvider", "QwenProvider"} else "MockProvider",
        )
        result = self.agent.analyze(request)
        snap = build_snapshot(self.store, SnapshotQuery(
            session_id=session_id,
            message_no=message_no,
            as_of_time=as_of,
        ))
        inconsistencies = snapshot_inconsistency_schema_items(snap)
        risk = result.analysis.get("risk") or {}
        required_pending = bool(
            (snap.get("workorder") or {}).get("visibility") == "visible"
            and ((snap.get("workorder") or {}).get("status") or {}).get("snapshot_value") == "not_completed"
        ) or bool(result.analysis.get("missing_fields"))
        self.state.register_analysis(
            session_id=session_id,
            as_of_time=result.as_of_time,
            analysis_id=result.analysis_id,
            run_id=result.run_id,
            provider_used=result.provider_used,
            degraded=result.degraded,
            safety_status=result.safety_check_result.get("status"),
            confirmable=result.can_enter_human_confirmation(),
            risk={"level": risk.get("level"), "status": risk.get("status")},
            has_source_conflict=bool(inconsistencies),
            required_actions_pending=required_pending,
        )
        order = snap.get("order") or {}
        return {
            "analysis_id": result.analysis_id,
            "run_id": result.run_id,
            "session_id": result.session_id,
            "as_of_time": result.as_of_time,
            "message_no": snap.get("message_no"),
            "provider_requested": result.requested_provider,
            "provider_used": result.provider_used,
            "model": result.model,
            "degraded": result.degraded,
            "fallback_chain": result.fallback_chain,
            "duration_ms": result.duration_ms,
            "cache_hit": result.cache_hit,
            "token_usage": result.token_usage,
            "analysis": result.analysis,
            "safety_check_result": result.safety_check_result,
            "schema_result": result.schema_result,
            "tool_calls": result.tool_calls,
            "status_summary": result.status_summary,
            "confirmable": result.can_enter_human_confirmation(),
            "snapshot": {
                "as_of_time": snap["as_of_time"],
                "message_no": snap["message_no"],
                "visible_message_count": len(snap.get("chat") or []),
                "order": snap.get("order"),
                "workorder": snap.get("workorder"),
                "logistics": snap.get("logistics"),
                "source_inconsistency": snap.get("source_inconsistency"),
                "source_refs": snap.get("source_refs"),
            },
            "disposal_status": self.state.status_of(session_id),
        }


APP: WorkbenchApp | None = None


class Handler(BaseHTTPRequestHandler):
    server_version = "DataEmpathyWorkbench/1.0"

    def log_message(self, fmt, *args):  # quiet default access log
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # --- helpers -----------------------------------------------------------

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = dumps_canonical(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str, **extra: Any) -> None:
        self._send_json({"error": message, **extra}, status=status)

    def _query(self) -> dict[str, str]:
        parsed = urllib.parse.urlparse(self.path)
        return {k: v[-1] for k, v in urllib.parse.parse_qs(parsed.query).items()}

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"request body must be UTF-8 JSON: {exc}") from exc
        return json.loads(text)

    # --- routing -----------------------------------------------------------

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        try:
            if path in {"/", "/index.html"}:
                content = (STATIC_DIR / "index.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            if path == "/api/bootstrap":
                self._send_json({
                    "sessions": APP.queue(),
                    "providers": {
                        "default": "MockProvider",
                        "available": ["MockProvider", "RuleProvider", "QwenProvider"],
                        "qwen_credentials": APP.agent.providers["QwenProvider"].has_credentials(),
                    },
                })
                return
            if path.startswith("/api/session/") and path.endswith("/messages"):
                session_id = path.split("/")[3]
                self._send_json(APP.messages(session_id))
                return
            if path == "/api/analyze":
                q = self._query()
                message_no = int(q["message_no"]) if q.get("message_no") else None
                self._send_json(APP.analyze(
                    q["session_id"], message_no, q.get("as_of"), q.get("provider", "MockProvider")))
                return
            if path == "/api/draft":
                q = self._query()
                draft = APP.state.get_draft(q["session_id"], q["as_of_time"])
                self._send_json({"draft": draft})
                return
            if path == "/api/disposal":
                q = self._query()
                rows = APP.state.disposal_records(q.get("session_id") or None)
                self._send_json({"records": rows, "status": {
                    sid: APP.state.status_of(sid) for sid in {
                        row.get("session_id") for row in rows if row.get("session_id")
                    }
                } if not q.get("session_id") else {"status": APP.state.status_of(q["session_id"])}})
                return
            self._error(404, "not found", path=path)
        except KeyError as exc:
            self._error(404, str(exc))
        except ValueError as exc:
            self._error(400, str(exc))
        except Exception as exc:  # noqa: BLE001 - surface real errors, never fake data
            self._error(500, f"{type(exc).__name__}: {exc}")

    def do_POST(self):  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        try:
            body = self._body()
            if path == "/api/draft":
                draft = APP.state.save_draft(
                    body["session_id"], body["as_of_time"], str(body.get("text") or ""))
                self._send_json({"draft": draft})
                return
            if path == "/api/confirm":
                body.setdefault("operation_id", new_operation_id())
                self._send_json(APP.state.confirm(body))
                return
            if path == "/api/reset-demo":
                APP.state.reset_demo_state()
                self._send_json({"reset": True})
                return
            self._error(404, "not found", path=path)
        except KeyError as exc:
            self._error(400, f"missing field: {exc}")
        except Exception as exc:  # noqa: BLE001
            self._error(500, f"{type(exc).__name__}: {exc}")


def build_server(xlsx: Path | None = None, port: int = 8765) -> ThreadingHTTPServer:
    global APP
    started = time.monotonic()
    APP = WorkbenchApp(xlsx)
    APP.queue()  # precompute queue risk at startup
    elapsed = round((time.monotonic() - started) * 1000)
    sys.stderr.write(f"workbench: loaded {len(APP.store.chats_by_session)} sessions in {elapsed}ms\n")
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.workbench")
    parser.add_argument("--xlsx", default=None)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    server = build_server(Path(args.xlsx) if args.xlsx else None, args.port)
    sys.stderr.write(f"workbench: http://127.0.0.1:{args.port}/\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
