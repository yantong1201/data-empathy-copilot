"""Main Agent: message timepoint → chat → order/workorder → timeline → rules
→ policy → Provider analysis/draft → independent safety check.

One stable analysis_id per logical analysis (full version fingerprint); a
unique run_id per actual execution, retry or degradation. Tools are read-only
or local drafts; no real business side effect ever happens here.
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from backend.data_empathy.codec import dumps_hash_payload
from backend.data_empathy.loader import DataStore, load_workbook_readonly
from backend.data_empathy.snapshot import SnapshotQuery, build_snapshot
from backend.risk_empathy.analysis_id import make_run_id, snapshot_hash
from backend.risk_empathy.emotion import evaluate_emotion
from backend.risk_empathy.pack import load_pack
from backend.risk_empathy.policy import policies_effective_at
from backend.risk_empathy.repair import process_provider_output
from backend.risk_empathy.rules import evaluate_risk
from backend.risk_empathy.safety import evaluate_safety

from .budget import BudgetConfig, BudgetState, StopReason
from .providers import (
    FALLBACK_ORDER,
    BaseProvider,
    MockProvider,
    ProviderError,
    QwenProvider,
    RuleProvider,
    fingerprint_versions,
    intent_from_context,
    prompt_fingerprint,
)
from .runlog import RunLog, VersionedCache
from .tools import ToolBox, ToolContext

RISK_POLICY_QUERY = {
    "adverse_reaction": "不良反应 就医 处理 升级",
    "complaint_escalation": "投诉 升级 安抚",
    "abnormal_refund": "异常退款 空包裹 核实 证据",
    "repeat_contact": "重复进线 跟进",
    "logistics_exception": "物流异常 处理",
    "aftersales_damage": "破损 换货 售后",
    "unresolved_workorder": "工单 跟进",
    "none": "服务 沟通 规范",
    "unclear": "服务 沟通 规范",
}


@dataclass
class AnalysisRequest:
    session_id: str
    message_no: int | None = None
    as_of_time: str | None = None
    provider: str = "MockProvider"
    model: str | None = None
    budget: BudgetConfig | None = None


@dataclass
class AnalysisResult:
    analysis_id: str
    run_id: str
    session_id: str
    as_of_time: str
    message_no: int
    requested_provider: str
    provider_used: str
    model: str
    degraded: bool
    fallback_chain: list[dict[str, Any]]
    versions: dict[str, str]
    snapshot_meta: dict[str, Any]
    analysis: dict[str, Any]
    safety_check_result: dict[str, Any]
    schema_result: dict[str, Any]
    tool_calls: list[dict[str, Any]]
    status_summary: dict[str, Any]
    budget_summary: dict[str, Any]
    token_usage: dict[str, int]
    duration_ms: float
    cache_hit: bool
    provider_meta: dict[str, Any]
    raw_records: dict[str, Any] = field(default_factory=dict)

    def can_enter_human_confirmation(self) -> bool:
        return bool(
            self.schema_result.get("schema_valid_after")
            and self.safety_check_result.get("status") == "pass"
            and self.safety_check_result.get("executed")
        )


class Agent:
    def __init__(
        self,
        store: DataStore,
        *,
        pack: dict[str, Any] | None = None,
        run_log: RunLog | None = None,
        cache: VersionedCache | None = None,
        providers: dict[str, BaseProvider] | None = None,
        budget: BudgetConfig | None = None,
    ):
        self.store = store
        self.pack = pack or load_pack()
        self.run_log = run_log or RunLog()
        self.cache = cache or VersionedCache()
        self.budget = budget or BudgetConfig()
        self.providers: dict[str, BaseProvider] = providers or {
            "MockProvider": MockProvider(),
            "RuleProvider": RuleProvider(),
            "QwenProvider": QwenProvider(),
        }
        self._cancel_event = threading.Event()
        self._consecutive_provider_failures = 0

    def cancel(self) -> None:
        self._cancel_event.set()

    def provider_factory(self, name: str) -> BaseProvider:
        provider = self.providers.get(name)
        if provider is None:
            raise KeyError(f"unknown provider {name}")
        return provider

    # --- identity ---------------------------------------------------------

    def fingerprint(
        self,
        snapshot: dict[str, Any],
        *,
        provider: str,
        model: str,
    ) -> dict[str, Any]:
        return {
            "session_id": snapshot["session_id"],
            "message_no": snapshot["message_no"],
            "as_of_time": snapshot["as_of_time"],
            "snapshot_hash": snapshot_hash(snapshot),
            "provider": provider,
            "model": model,
            **fingerprint_versions(self.pack),
        }

    def make_analysis_id(self, fingerprint: dict[str, Any]) -> str:
        digest = hashlib.sha256(dumps_hash_payload(fingerprint).encode("utf-8")).hexdigest()[:20]
        return f"A-{fingerprint['session_id']}-{digest}"

    # --- main entry -------------------------------------------------------

    def analyze(self, request: AnalysisRequest) -> AnalysisResult:
        started = time.monotonic()
        budget = BudgetState(request.budget or self.budget)
        if request.message_no is None and request.as_of_time is None:
            raise ValueError("message_no or as_of_time is required")
        snapshot = build_snapshot(
            self.store,
            SnapshotQuery(
                session_id=str(request.session_id),
                message_no=request.message_no,
                as_of_time=request.as_of_time,
            ),
        )
        provider = self.provider_factory(request.provider)
        model = request.model or provider.model
        fingerprint = self.fingerprint(snapshot, provider=request.provider, model=model)
        analysis_id = self.make_analysis_id(fingerprint)
        cache_key = self.cache.key(fingerprint)

        cached = self.cache.get(fingerprint)
        if cached is not None:
            bundle = cached["bundle"]
            run_id = make_run_id()
            record = self.run_log.append({
                "event": "analysis_run",
                "analysis_id": analysis_id,
                "run_id": run_id,
                "cache_key": cache_key,
                "session_id": snapshot["session_id"],
                "as_of_time": snapshot["as_of_time"],
                "message_no": snapshot["message_no"],
                "provider_requested": request.provider,
                "provider_used": bundle["provider_used"],
                "model": model,
                "degraded": bundle.get("degraded", False),
                "versions": fingerprint_versions(self.pack),
                "snapshot_hash": fingerprint["snapshot_hash"],
                "tool_calls": [],
                "tool_calls_used": 0,
                "llm_turns_used": 0,
                "budget": {
                    "max_tool_calls": self.budget.max_tool_calls,
                    "max_llm_turns": self.budget.max_llm_turns,
                    "stop_reason": None,
                    "note": "cache hit: no tools or model calls re-executed",
                },
                "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "cache_hit": True,
                "duration_ms": round((time.monotonic() - started) * 1000, 3),
                "safety_status": bundle["safety_check_result"].get("status"),
                "stop_reason": None,
                "final_status": "cache_hit",
            })
            result = self._result_from_bundle(bundle, analysis_id, run_id, cache_hit=True, record=record)
            result.duration_ms = round((time.monotonic() - started) * 1000, 3)
            return result

        ctx = ToolContext(self.store, self.pack)
        ctx.cancel_event = self._cancel_event
        box = ToolBox(ctx, budget)
        rule_risk: dict[str, Any] = {}
        policies: list[dict[str, Any]] = []

        as_of = snapshot["as_of_time"]
        session_id = snapshot["session_id"]
        chat_rows = snapshot.get("chat") or []
        first_buyer = next((row for row in chat_rows if row.get("role") == "买家"), None)
        query_seed = " ".join(filter(None, [
            (first_buyer or {}).get("message_text", "")[:40],
        ]))

        order = self.store.orders_by_session.get(session_id)
        order_id = order.order_id if order else ""
        wo = self.store.workorders_by_session.get(session_id)
        order_id_for_wo = (wo.order_id if wo and wo.order_id else order_id)

        def _call(tool: str, params: dict[str, Any]) -> dict[str, Any]:
            base = {"session_id": session_id, "as_of_time": as_of}
            base.update(params)
            return box.call(tool, base)

        tool_results: dict[str, dict[str, Any]] = {}
        tool_results["get_conversation_until"] = _call("get_conversation_until", {})
        tool_results["get_order_snapshot"] = _call("get_order_snapshot", {"order_id": order_id})
        tool_results["get_workorder_snapshot"] = _call(
            "get_workorder_snapshot", {"order_id": order_id_for_wo}
        )
        tool_results["get_service_timeline"] = _call("get_service_timeline", {})
        risk_tool = _call("check_risk_rules", {})
        tool_results["check_risk_rules"] = risk_tool
        if risk_tool["status"] == "ok":
            rule_risk = dict(risk_tool["data"]["risk"])
            rule_risk["evidence_refs"] = risk_tool.get("source_refs") or []
            emotion_tool_risk = risk_tool["data"].get("emotion") or {}
        else:
            emotion_full = evaluate_emotion(snapshot, self.pack)
            rule_risk = evaluate_risk(snapshot, self.pack, emotion_full)
            emotion_tool_risk = {
                "negative_signal": emotion_full["negative_signal"],
                "escalation": emotion_full["escalation"],
            }
        policy_query = (RISK_POLICY_QUERY.get(rule_risk.get("type") or "unclear") or "服务 规范") + " " + query_seed
        policy_tool = _call("retrieve_policy", {"query": policy_query.strip()})
        tool_results["retrieve_policy"] = policy_tool
        if policy_tool["status"] == "ok":
            policies = policy_tool["data"]["results"]

        draft_tool = _call("draft_reply", {
            "risk": {
                "type": rule_risk.get("type"),
                "level": rule_risk.get("level"),
                "status": rule_risk.get("status"),
                "missing_fields": rule_risk.get("missing_fields") or [],
            },
            "emotion": emotion_tool_risk,
            "policy_ids": [row["policy_id"] for row in policies],
        })
        tool_results["draft_reply"] = draft_tool

        wo_draft_tool = _call("create_workorder_draft", {
            "action": "生成工单草稿：" + str(rule_risk.get("type") or "unclear"),
            "risk": {
                "type": rule_risk.get("type"),
                "level": rule_risk.get("level"),
                "rule_ids": rule_risk.get("rule_ids") or [],
            },
        })
        tool_results["create_workorder_draft"] = wo_draft_tool

        if self._cancel_event.is_set():
            budget.cancelled = True
            budget.stop(StopReason.CANCELLED, "cancelled before provider call")

        attempts: list[dict[str, Any]] = []
        primary_run_id = make_run_id()
        provider_chain: list[str] = [request.provider] + list(FALLBACK_ORDER.get(request.provider, []))
        circuit_open = self._consecutive_provider_failures >= 3
        if circuit_open and len(provider_chain) > 1:
            attempts.append({
                "run_id": make_run_id(),
                "provider": request.provider,
                "skipped": True,
                "failure_reason": "circuit_open",
                "detail": f"连续 {self._consecutive_provider_failures} 次 Provider 失败，熔断跳过云端调用",
                "fallback_reason": "熔断直接降级",
            })

        processed: dict[str, Any] | None = None
        chosen_output_meta: dict[str, Any] = {}
        llm_turns_used = 0
        intent_override = intent_from_context(snapshot, rule_risk)
        for index, provider_name in enumerate(provider_chain):
            if budget.stop_reason in {StopReason.CANCELLED, StopReason.TOOL_BUDGET_EXCEEDED}:
                break
            skipped = any(a.get("provider") == provider_name and a.get("skipped") for a in attempts)
            if skipped:
                continue
            attempt_run_id = primary_run_id if not attempts else make_run_id()
            prov = self.provider_factory(provider_name)
            is_llm = getattr(prov, "network", False)
            if is_llm:
                if budget.llm_budget_left() <= 0:
                    attempts.append({
                        "run_id": attempt_run_id,
                        "provider": provider_name,
                        "skipped": True,
                        "failure_reason": "llm_budget_exceeded",
                        "fallback_reason": "LLM 轮次预算耗尽",
                    })
                    budget.stop(StopReason.LLM_BUDGET_EXCEEDED, f"{provider_name} skipped: no llm budget")
                    continue
                budget.llm_turns_used += 1
            try:
                context = {
                    "snapshot": snapshot,
                    "rule_risk": rule_risk,
                    "policies": policies,
                    "analysis_id": analysis_id,
                    "run_id": attempt_run_id,
                    "scope": "full",
                    "intent_override": intent_override,
                    "pack": self.pack,
                }
                output = prov.analyze(context)
            except ProviderError as exc:
                attempts.append({
                    "run_id": attempt_run_id,
                    "provider": provider_name,
                    "failure_reason": exc.failure_reason,
                    "detail": exc.detail[:300],
                    "fallback_reason": f"{provider_name} 失败，按降级链切换",
                })
                if provider_name == request.provider:
                    self._consecutive_provider_failures += 1
                continue
            # Identity fields are contract echoes enforced by the program; the
            # model's business judgments (intent/emotion/risk/reply) are not
            # altered here.
            payload = dict(output.payload)
            payload["analysis_id"] = analysis_id
            payload["session_id"] = session_id
            payload["message_no"] = int(snapshot["message_no"])
            payload["as_of_time"] = as_of
            processed = process_provider_output(
                payload,
                provider=provider_name,
                snapshot=snapshot,
                rule_risk=rule_risk,
                run_safety=True,
                pack=self.pack,
            )
            processed["run_id"] = attempt_run_id
            if isinstance(processed.get("safety_check_result"), dict):
                processed["safety_check_result"]["run_id"] = attempt_run_id
            chosen_output_meta = output.to_meta()
            schema_ok = processed.get("schema_valid_after")
            safety_status = (processed.get("safety_check_result") or {}).get("status")
            if not schema_ok or safety_status != "pass":
                reason = "schema_invalid_after_repair" if not schema_ok else "safety_check_failed"
                attempts.append({
                    "run_id": attempt_run_id,
                    "provider": provider_name,
                    "failure_reason": reason,
                    "detail": ("; ".join(processed.get("schema_errors") or []) or
                               "; ".join(f.get("type", "") for f in processed["safety_check_result"].get("failures") or []))[:300],
                    "fallback_reason": "Schema 非法或安全校验失败，切换下一 Provider",
                })
                if provider_name == request.provider:
                    self._consecutive_provider_failures += 1
                processed = None
                continue
            if provider_name == request.provider:
                self._consecutive_provider_failures = 0
            break
        llm_turns_used = budget.llm_turns_used

        if processed is None:
            budget.stop(StopReason.PROVIDER_FALLBACK_EXHAUSTED, "所有 Provider 均失败")
            final_status = "failed"
            safety = processed_fallback_safety(analysis_id, primary_run_id)
            analysis_payload = fallback_rule_payload(snapshot, self.pack, analysis_id, rule_risk)
            analysis_payload["intent"] = intent_override or analysis_payload["intent"]
            schema_result = {"schema_valid_before": False, "schema_valid_after": False,
                             "errors": ["all providers failed"], "repair": None}
            provider_used = provider_chain[-1]
            degraded = True
            chosen_output_meta = {}
        else:
            final_status = "ok" if processed["provider"] == request.provider else "degraded"
            safety = processed["safety_check_result"]
            analysis_payload = processed["repaired_output"]
            schema_result = {
                "schema_valid_before": processed["schema_valid_before"],
                "schema_valid_after": processed["schema_valid_after"],
                "errors": processed["schema_errors"],
                "repair": processed["repair"],
            }
            provider_used = processed["provider"]
            degraded = provider_used != request.provider

        if safety.get("status") != "pass" and final_status == "ok":
            final_status = "rejected"

        analysis_payload = dict(analysis_payload)
        analysis_payload["analysis_id"] = analysis_id

        status_summary = {
            "session_id": session_id,
            "as_of_time": as_of,
            "stage": "completed" if final_status in {"ok", "degraded"} else final_status,
            "visible_message_count": len(chat_rows),
            "order_visible": (snapshot.get("order") or {}).get("visibility") == "visible",
            "workorder_visible": (snapshot.get("workorder") or {}).get("visibility") == "visible",
            "source_inconsistency_count": len(snapshot.get("source_inconsistency") or []),
            "missing_fields": rule_risk.get("missing_fields") or [],
            "locked_risk": {
                "type": rule_risk.get("type"),
                "level": rule_risk.get("level"),
                "status": rule_risk.get("status"),
            },
            "tool_budget": {
                "used": budget.tool_calls_used,
                "max": budget.config.max_tool_calls,
            },
            "provider": {
                "requested": request.provider,
                "used": provider_used,
                "model": model,
                "degraded": degraded,
                "fallback_reason": attempts[-1].get("fallback_reason") if attempts else None,
            },
            "safety_status": safety.get("status"),
            "cancelled": budget.cancelled,
        }

        duration_ms = round((time.monotonic() - started) * 1000, 3)
        bundle = {
            "provider_used": provider_used,
            "degraded": degraded,
            "analysis": analysis_payload,
            "safety_check_result": safety,
            "schema_result": schema_result,
            "tool_calls": box.call_log,
            "status_summary": status_summary,
            "fallback_chain": attempts,
            "provider_output_meta": chosen_output_meta,
        }
        record = self.run_log.append({
            "event": "analysis_run",
            "analysis_id": analysis_id,
            "run_id": primary_run_id,
            "cache_key": cache_key,
            "session_id": session_id,
            "as_of_time": as_of,
            "message_no": snapshot["message_no"],
            "provider_requested": request.provider,
            "provider_used": provider_used,
            "model": model,
            "degraded": degraded,
            "fallback_chain": attempts,
            "versions": fingerprint_versions(self.pack),
            "snapshot_hash": fingerprint["snapshot_hash"],
            "tool_calls_used": budget.tool_calls_used,
            "llm_turns_used": llm_turns_used,
            "tool_calls": [
                {
                    "seq": row["seq"],
                    "tool": row["tool"],
                    "request_id": row["request_id"],
                    "status": row["status"],
                    "duration_ms": row["duration_ms"],
                    "deduplicated": row["deduplicated"],
                    "retried": row["retried"],
                }
                for row in box.call_log
            ],
            "budget": budget.summary(),
            "token_usage": chosen_output_meta.get("token_usage")
            or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "provider_output_meta": chosen_output_meta,
            "cache_hit": False,
            "duration_ms": duration_ms,
            "safety_status": safety.get("status"),
            "stop_reason": budget.stop_reason.value if budget.stop_reason else None,
            "final_status": final_status,
        })
        if final_status in {"ok", "degraded"}:
            self.cache.put(fingerprint, bundle)

        result = self._result_from_bundle(
            bundle, analysis_id, primary_run_id, cache_hit=False, record=record
        )
        result.duration_ms = duration_ms
        result.budget_summary = budget.summary()
        result.budget_summary["llm_turns_used"] = llm_turns_used
        result.token_usage = chosen_output_meta.get("token_usage") or result.token_usage
        return result

    def _result_from_bundle(
        self,
        bundle: dict[str, Any],
        analysis_id: str,
        run_id: str,
        *,
        cache_hit: bool,
        record: dict[str, Any],
    ) -> AnalysisResult:
        summary = bundle["status_summary"]
        return AnalysisResult(
            analysis_id=analysis_id,
            run_id=run_id,
            session_id=summary["session_id"],
            as_of_time=summary["as_of_time"],
            message_no=int(record.get("message_no") or summary.get("message_no") or 0),
            requested_provider=summary["provider"]["requested"],
            provider_used=bundle["provider_used"],
            model=summary["provider"]["model"],
            degraded=bundle["degraded"],
            fallback_chain=bundle.get("fallback_chain") or [],
            versions=fingerprint_versions(self.pack),
            snapshot_meta={
                "session_id": summary["session_id"],
                "as_of_time": summary["as_of_time"],
                "visible_message_count": summary["visible_message_count"],
                "order_visible": summary["order_visible"],
                "workorder_visible": summary["workorder_visible"],
                "source_inconsistency_count": summary["source_inconsistency_count"],
            },
            analysis=bundle["analysis"],
            safety_check_result=bundle["safety_check_result"],
            schema_result=bundle["schema_result"],
            tool_calls=bundle["tool_calls"],
            status_summary=summary,
            budget_summary={},
            token_usage=(bundle.get("provider_output_meta") or {}).get("token_usage")
            or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            duration_ms=0.0,
            cache_hit=cache_hit,
            provider_meta=bundle.get("provider_output_meta") or {},
            raw_records={"run_record": record},
        )


def fallback_rule_payload(
    snapshot: dict[str, Any],
    pack: dict[str, Any],
    analysis_id: str,
    rule_risk: dict[str, Any],
) -> dict[str, Any]:
    from backend.risk_empathy.assemble import assemble_analysis

    bundled = assemble_analysis(snapshot, provider="RuleProvider", model="rules-v1", pack=pack)
    payload = bundled["analysis"]
    payload["analysis_id"] = analysis_id
    if rule_risk:
        payload["risk"] = {
            "type": rule_risk.get("type", payload["risk"]["type"]),
            "level": rule_risk.get("level", payload["risk"]["level"]),
            "status": rule_risk.get("status", payload["risk"]["status"]),
            "rule_ids": rule_risk.get("rule_ids", payload["risk"]["rule_ids"]),
            "why": rule_risk.get("why") or payload["risk"]["why"],
            "why_not": rule_risk.get("why_not") or payload["risk"]["why_not"],
        }
    return payload


def processed_fallback_safety(analysis_id: str, run_id: str) -> dict[str, Any]:
    from backend.risk_empathy.safety import not_run_safety

    return not_run_safety(analysis_id, run_id)


def build_default_agent(xlsx_path=None) -> tuple[Agent, DataStore]:
    from backend.data_empathy.loader import default_xlsx_path
    from pathlib import Path

    path = Path(xlsx_path) if xlsx_path else default_xlsx_path()
    store = DataStore(load_workbook_readonly(path))
    return Agent(store), store
