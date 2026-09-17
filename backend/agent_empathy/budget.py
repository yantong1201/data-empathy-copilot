"""Run budgets, duplicate-call detection, retry and stop reasons."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from backend.data_empathy.codec import dumps_hash_payload


class StopReason(str, enum.Enum):
    COMPLETED = "completed"
    DUPLICATE_CALL = "duplicate_call"
    TOOL_BUDGET_EXCEEDED = "tool_budget_exceeded"
    LLM_BUDGET_EXCEEDED = "llm_budget_exceeded"
    TOOL_TIMEOUT = "tool_timeout"
    PROVIDER_TIMEOUT = "provider_timeout"
    CANCELLED = "cancelled"
    CONSECUTIVE_TOOL_FAILURES = "consecutive_tool_failures"
    PROVIDER_FALLBACK_EXHAUSTED = "provider_fallback_exhausted"
    SAFETY_NOT_PASS = "safety_not_pass"


@dataclass(frozen=True)
class BudgetConfig:
    max_llm_turns: int = 2
    max_tool_calls: int = 12
    readonly_tool_timeout_s: float = 5.0
    provider_timeout_s: float = 30.0
    idempotent_retry_max: int = 1
    consecutive_failure_break: int = 3


@dataclass
class BudgetState:
    config: BudgetConfig
    tool_calls_used: int = 0
    llm_turns_used: int = 0
    retries_used: int = 0
    consecutive_failures: int = 0
    stop_reason: StopReason | None = None
    cancelled: bool = False
    notes: list[str] = field(default_factory=list)

    def tool_budget_left(self) -> int:
        return max(0, self.config.max_tool_calls - self.tool_calls_used)

    def llm_budget_left(self) -> int:
        return max(0, self.config.max_llm_turns - self.llm_turns_used)

    def stop(self, reason: StopReason, note: str = "") -> None:
        if self.stop_reason is None:
            self.stop_reason = reason
        if note:
            self.notes.append(note)

    def summary(self) -> dict[str, Any]:
        return {
            "max_llm_turns": self.config.max_llm_turns,
            "max_tool_calls": self.config.max_tool_calls,
            "tool_calls_used": self.tool_calls_used,
            "llm_turns_used": self.llm_turns_used,
            "retries_used": self.retries_used,
            "consecutive_failures": self.consecutive_failures,
            "stop_reason": self.stop_reason.value if self.stop_reason else None,
            "cancelled": self.cancelled,
            "notes": list(self.notes),
        }


def canonical_params(tool: str, params: dict[str, Any]) -> str:
    return dumps_hash_payload({"tool": tool, "params": params})
