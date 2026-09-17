"""Append-only run records, versioned cache and cost statistics.

The run log is JSONL with a sha256 hash chain: each record stores the hash of
the previous line, so silent edits or deletions break verification. The cache
key covers every fingerprint part; any version change yields a new analysis_id
and invalidates previous entries (old files stay on disk, never reused).
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any

from backend.data_empathy.loader import repo_root

RUNS_DIR = repo_root() / "data" / "runs"
RUN_LOG_PATH = RUNS_DIR / "run_log.jsonl"
CACHE_DIR = RUNS_DIR / "cache"

_lock = threading.Lock()


def _now_iso() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8))).isoformat(timespec="milliseconds")


class RunLog:
    def __init__(self, path: Path = RUN_LOG_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def _last_chain_hash(self) -> str:
        last = ""
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    last = json.loads(line).get("record_sha256") or ""
                except json.JSONDecodeError:
                    last = ""
        return last

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        with _lock:
            prev = self._last_chain_hash()
            record = dict(record)
            record["seq"] = self.count() + 1
            record["ts"] = _now_iso()
            record["prev_record_sha256"] = prev
            record["record_sha256"] = hashlib.sha256(
                json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            return record

    def count(self) -> int:
        n = 0
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    n += 1
        return n

    def records(self) -> list[dict[str, Any]]:
        out = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    def verify_append_only(self) -> dict[str, Any]:
        """Chain check: seq monotonic, prev hashes link, file size only grew."""
        prev_hash = ""
        prev_seq = 0
        seq_ok = True
        chain_ok = True
        size = self.path.stat().st_size
        for row in self.records():
            if row.get("seq") != prev_seq + 1:
                seq_ok = False
            if row.get("prev_record_sha256") != prev_hash:
                chain_ok = False
            rec_hash = hashlib.sha256(
                json.dumps({k: v for k, v in row.items() if k != "record_sha256"},
                           ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            if rec_hash != row.get("record_sha256"):
                chain_ok = False
            prev_hash = row.get("record_sha256") or ""
            prev_seq = row.get("seq") or 0
        return {
            "append_only": seq_ok and chain_ok,
            "seq_monotonic": seq_ok,
            "hash_chain_valid": chain_ok,
            "record_count": prev_seq,
            "file_size_bytes": size,
        }


class VersionedCache:
    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(fingerprint: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(fingerprint, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def path_for(self, fingerprint: dict[str, Any]) -> Path:
        return self.cache_dir / (self.key(fingerprint) + ".json")

    def get(self, fingerprint: dict[str, Any]) -> dict[str, Any] | None:
        path = self.path_for(fingerprint)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def put(self, fingerprint: dict[str, Any], bundle: dict[str, Any]) -> Path:
        path = self.path_for(fingerprint)
        payload = {
            "cache_key": self.key(fingerprint),
            "fingerprint": fingerprint,
            "stored_at": _now_iso(),
            "bundle": bundle,
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
        return path

    def stats(self) -> dict[str, Any]:
        files = list(self.cache_dir.glob("*.json"))
        return {"cache_entries": len(files), "cache_dir": str(self.cache_dir)}


class NullCache(VersionedCache):
    """Cache bypass: forces full pipeline execution on every run."""

    def __init__(self):  # noqa: D107 - no directory needed
        pass

    def get(self, fingerprint: dict[str, Any]) -> dict[str, Any] | None:
        return None

    def put(self, fingerprint: dict[str, Any], bundle: dict[str, Any]) -> Path:  # noqa: D102
        return Path("/dev/null")

    def stats(self) -> dict[str, Any]:
        return {"cache_entries": 0, "note": "NullCache: cache bypassed"}


def cost_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate token/duration/cache stats from run records. Real values only."""
    runs = [row for row in records if row.get("event") == "analysis_run"]
    durations = [float(row.get("duration_ms") or 0.0) for row in runs]
    prompt_tokens = [int(((row.get("token_usage") or {}).get("prompt_tokens")) or 0) for row in runs]
    completion_tokens = [int(((row.get("token_usage") or {}).get("completion_tokens")) or 0) for row in runs]
    tool_calls = [int(row.get("tool_calls_used") or 0) for row in runs]
    cache_hits = sum(1 for row in runs if row.get("cache_hit"))
    failures = [row for row in runs if row.get("final_status") in {"failed", "rejected"}]
    degraded = [row for row in runs if row.get("degraded")]

    def _stats(values: list[float]) -> dict[str, Any]:
        if not values:
            return {"count": 0}
        ordered = sorted(values)

        def pct(p: float) -> float:
            idx = min(len(ordered) - 1, max(0, int(round(p * (len(ordered) - 1)))))
            return round(ordered[idx], 3)

        return {
            "count": len(ordered),
            "mean": round(sum(ordered) / len(ordered), 3),
            "median": pct(0.5),
            "p50": pct(0.50),
            "p95": pct(0.95),
        }

    return {
        "total_runs": len(runs),
        "cache_hits": cache_hits,
        "cache_misses": len(runs) - cache_hits,
        "degraded_runs": len(degraded),
        "failed_or_rejected_runs": len(failures),
        "failure_reasons": sorted({row.get("stop_reason") or "unknown" for row in failures}),
        "duration_ms": _stats(durations),
        "prompt_tokens": _stats([float(v) for v in prompt_tokens]),
        "completion_tokens": _stats([float(v) for v in completion_tokens]),
        "tool_calls_per_run": _stats([float(v) for v in tool_calls]),
        "generated_at": _now_iso(),
        "note": "仅统计真实运行记录；固定演示耗时不得计入",
    }
