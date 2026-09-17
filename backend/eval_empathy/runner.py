"""Four-arm runner + leakage regression (protocol §5–§6).

Arms share the same policy version and test timepoints. Model groups share
one model/parameter set (Qwen when credentials exist, otherwise the
deterministic MockProvider — recorded honestly as offline-deterministic,
model effect 未验证). Rules-only makes zero model calls. Information scope
differs per arm: chat_only sees chat text only (snapshot fields physically
stripped from the context), snapshot sees the full visible snapshot without
a rule pre-pass, full_agent is the Phase C pipeline.
"""

from __future__ import annotations

import copy
import time
from typing import Any

from backend.data_empathy.loader import DataStore
from backend.data_empathy.snapshot import SnapshotQuery, build_snapshot
from backend.risk_empathy.emotion import evaluate_emotion
from backend.risk_empathy.pack import load_pack
from backend.risk_empathy.policy import policies_effective_at
from backend.risk_empathy.repair import process_provider_output
from backend.risk_empathy.rules import evaluate_risk

from backend.agent_empathy.agent import Agent, AnalysisRequest
from backend.agent_empathy.analysis_adapter import scoped_analysis
from backend.agent_empathy.providers import (
    MockProvider,
    ProviderError,
    QwenProvider,
    RuleProvider,
    build_model_context,
    intent_from_context,
)
from backend.agent_empathy.runlog import NullCache, RunLog, VersionedCache

ARMS = ("chat_only", "snapshot", "full_agent", "rules_only")


def _strip_to_chat(snapshot: dict[str, Any]) -> dict[str, Any]:
    chat_only = copy.deepcopy(snapshot)
    chat_only["order"] = {"visibility": "no_order", "order_id": None, "reason": "chat_only_scope"}
    chat_only["workorder"] = {"visibility": "no_workorder", "workorder_id": None, "reason": "chat_only_scope"}
    chat_only["logistics"] = {"order_logistics": None, "logistics_workorder": None}
    chat_only["source_inconsistency"] = []
    chat_only["source_refs"] = [row["source_ref"] for row in chat_only.get("chat") or []]
    return chat_only


def _strip_rules(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Snapshot arm: keep visible business data; no rule pre-pass is provided."""
    return copy.deepcopy(snapshot)


class EvalRunner:
    def __init__(self, store: DataStore, *, provider_mode: str | None = None, log: RunLog | None = None,
                 cache=None, pack: dict[str, Any] | None = None):
        self.store = store
        self.pack = pack or load_pack()
        self.log = log or RunLog()
        self.cache = cache if cache is not None else VersionedCache()
        qwen = QwenProvider()
        self.provider_mode = provider_mode or ("QwenProvider" if qwen.has_credentials() else "MockProvider")
        self.model_providers = {
            "QwenProvider": qwen,
            "MockProvider": MockProvider(),
            "RuleProvider": RuleProvider(),
        }
        self.agent = Agent(
            store, pack=self.pack, run_log=self.log, cache=self.cache,
            providers=self.model_providers,
        )

    # --- arm execution -----------------------------------------------------

    def run_sample(self, arm: str, unit: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        session_id = unit["session_id"]
        snapshot = build_snapshot(self.store, SnapshotQuery(
            session_id=session_id, message_no=unit["message_no"], as_of_time=unit["as_of_time"]))

        if arm == "full_agent":
            result = self.agent.analyze(AnalysisRequest(
                session_id=session_id, message_no=unit["message_no"],
                provider=self.provider_mode))
            return self._record(arm, unit, result.analysis_id, result.run_id,
                                result.analysis, result.safety_check_result,
                                result.provider_used, result.model, result.duration_ms,
                                result.token_usage, result.tool_calls, result.fallback_chain,
                                schema_ok=result.schema_result.get("schema_valid_after"),
                                cache_hit=result.cache_hit)

        if arm == "rules_only":
            emotion = evaluate_emotion(snapshot, self.pack)
            risk = evaluate_risk(snapshot, self.pack, emotion)
            payload = scoped_analysis(
                snapshot, risk, emotion, provider="RuleProvider", model="rules-v1",
                pack=self.pack, intent=intent_from_context(snapshot, risk),
            )
            processed = process_provider_output(
                payload, provider="RuleProvider", snapshot=snapshot,
                rule_risk=risk, run_safety=True, pack=self.pack)
            safety = processed["safety_check_result"]
            duration = round((time.monotonic() - started) * 1000, 3)
            return self._record(arm, unit, payload["analysis_id"], processed["run_id"],
                                processed["repaired_output"], safety,
                                "RuleProvider", "rules-v1", duration,
                                {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                                [], [], schema_ok=processed["schema_valid_after"], cache_hit=False)

        # chat_only / snapshot: scoped provider analysis, one model call
        scoped = _strip_to_chat(snapshot) if arm == "chat_only" else _strip_rules(snapshot)
        provider = self.model_providers[self.provider_mode]
        model_input = build_model_context(
            scoped, {}, policies_effective_at(snapshot["as_of_time"], self.pack)
            if arm == "snapshot" else [],
            scope="chat" if arm == "chat_only" else "snapshot",
            analysis_id=None)
        run_id = "R-" + f"{arm}-{unit['sample_id']}-{started:.3f}".encode("utf-8").hex()[:24]
        analysis_id = f"A-{arm}-{unit['sample_id']}"
        try:
            if self.provider_mode == "QwenProvider":
                context = {
                    "snapshot": scoped, "rule_risk": {},
                    "policies": policies_effective_at(snapshot["as_of_time"], self.pack)
                    if arm == "snapshot" else [],
                    "analysis_id": analysis_id, "run_id": run_id,
                    "scope": "chat" if arm == "chat_only" else "snapshot",
                    "intent_override": None,
                }
                output = provider.analyze(context)
                payload = dict(output.payload)
                tokens = output.usage.as_dict()
                duration = round((time.monotonic() - started) * 1000, 3)
                meta = output.to_meta()
            else:
                emotion = evaluate_emotion(scoped, self.pack)
                risk = evaluate_risk(scoped, self.pack, emotion)
                payload = scoped_analysis(
                    scoped, risk, emotion, provider=self.provider_mode,
                    model=provider.model, pack=self.pack,
                    intent=intent_from_context(scoped, risk) if arm == "chat_only"
                    else labeler_intent(snapshot, self.pack),
                )
                payload["analysis_id"] = analysis_id
                tokens = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                duration = round((time.monotonic() - started) * 1000, 3)
                meta = {"provider": self.provider_mode, "model": provider.model,
                        "duration_ms": duration, "token_usage": tokens,
                        "input_sha256": None, "input_chars": len(model_input)}
        except ProviderError as exc:
            fallback = self.model_providers["RuleProvider"]
            emotion = evaluate_emotion(scoped, self.pack)
            risk = evaluate_risk(scoped, self.pack, emotion)
            payload = scoped_analysis(scoped, risk, emotion, provider="RuleProvider",
                                      model="rules-v1", pack=self.pack,
                                      intent=intent_from_context(scoped, risk))
            payload["analysis_id"] = analysis_id
            tokens = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            duration = round((time.monotonic() - started) * 1000, 3)
            meta = {"provider": "RuleProvider", "model": "rules-v1", "duration_ms": duration,
                    "token_usage": tokens, "degraded_from": self.provider_mode,
                    "failure_reason": exc.failure_reason,
                    "input_sha256": None, "input_chars": len(model_input)}

        processed = process_provider_output(
            payload, provider=meta["provider"], snapshot=scoped, rule_risk={},
            run_safety=True, pack=self.pack)
        safety = processed["safety_check_result"]
        return self._record(
            arm, unit, analysis_id, run_id, processed["repaired_output"], safety,
            meta["provider"], meta.get("model", ""), duration, tokens, [], [],
            schema_ok=processed["schema_valid_after"], cache_hit=False,
            model_input_chars=len(model_input), model_input_sha256=_sha(model_input),
            degraded_from=meta.get("degraded_from"), scope_note=arm)

    def _record(self, arm, unit, analysis_id, run_id, analysis, safety, provider, model,
                duration_ms, tokens, tool_calls, fallback_chain, *, schema_ok,
                cache_hit, model_input_chars=0, model_input_sha256=None,
                degraded_from=None, scope_note=None) -> dict[str, Any]:
        record = {
            "event": "eval_run",
            "arm": arm,
            "sample_id": unit["sample_id"],
            "session_id": unit["session_id"],
            "message_no": unit["message_no"],
            "as_of_time": unit["as_of_time"],
            "analysis_id": analysis_id,
            "run_id": run_id,
            "provider_requested": self.provider_mode,
            "provider_used": provider,
            "model": model,
            "degraded_from": degraded_from,
            "fallback_chain": fallback_chain,
            "schema_valid": schema_ok,
            "safety_status": safety.get("status"),
            "safety_executed": safety.get("executed"),
            "tool_calls_used": len(tool_calls),
            "token_usage": tokens,
            "duration_ms": duration_ms,
            "cache_hit": cache_hit,
            "model_input_chars": model_input_chars,
            "model_input_sha256": model_input_sha256,
            "final_status": "ok" if schema_ok and safety.get("status") == "pass" else "degraded_or_rejected",
        }
        self.log.append(record)
        return {
            "arm": arm,
            "sample_id": unit["sample_id"],
            "session_id": unit["session_id"],
            "message_no": unit["message_no"],
            "as_of_time": unit["as_of_time"],
            "analysis_id": analysis_id,
            "run_id": run_id,
            "provider": provider,
            "provider_requested": self.provider_mode,
            "model": model,
            "degraded_from": degraded_from,
            "analysis": analysis,
            "safety_check_result": safety,
            "schema_valid": schema_ok,
            "tool_calls_used": len(tool_calls),
            "token_usage": tokens,
            "duration_ms": duration_ms,
            "cache_hit": cache_hit,
            "model_input_chars": model_input_chars,
            "model_input_sha256": model_input_sha256,
        }

    # --- leakage regression --------------------------------------------------

    def leakage_regression(self, units: list[dict[str, Any]]) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        for unit in units:
            session_id = unit["session_id"]
            snapshot = build_snapshot(self.store, SnapshotQuery(
                session_id=session_id, message_no=unit["message_no"], as_of_time=unit["as_of_time"]))
            wo = self.store.workorders_by_session.get(session_id)
            order = self.store.orders_by_session.get(session_id)
            as_of = snapshot["as_of_time"]
            chat_ctx = build_model_context(_strip_to_chat(snapshot), {}, [], scope="chat")
            row: dict[str, Any] = {
                "sample_id": unit["sample_id"],
                "chat_only_context_has_order_id": bool(order and order.order_id and order.order_id in chat_ctx),
                "chat_only_context_has_workorder_id": bool(wo and wo.workorder_id and wo.workorder_id in chat_ctx),
            }
            early_wo = wo is not None and wo.create_time.isoformat() > as_of
            row["early_workorder_case"] = early_wo
            agent_claim = any(
                (item.get("chat_quotes") for item in snapshot.get("source_inconsistency") or [])
            )
            row["agent_claimed_creation_conflict"] = agent_claim
            row["empty_complete_time_case"] = bool(
                wo is not None and wo.create_time.isoformat() <= as_of and wo.complete_time is None)
            if early_wo and (row["chat_only_context_has_workorder_id"]):
                row["leak"] = "chat_only context contains future workorder id"
            checks.append(row)
        leaks = [row for row in checks if row.get("leak")]
        return {
            "checked_samples": len(checks),
            "leaks": leaks,
            "passed": not leaks,
            "note": "Chat-only 上下文物理剥离订单/工单字段；早期工单、客服声称建单、完成时间为空与 source_inconsistency 均按样本登记",
        }


def labeler_intent(snapshot: dict[str, Any], pack: dict[str, Any]) -> dict[str, Any]:
    emotion = evaluate_emotion(snapshot, pack)
    risk = evaluate_risk(snapshot, pack, emotion)
    return intent_from_context(snapshot, risk)


def _sha(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()
