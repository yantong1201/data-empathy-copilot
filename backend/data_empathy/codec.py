"""String-ID coercion and stable JSON. IDs must never become floats."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from .timeutil import format_iso


class IdCoercionError(ValueError):
    pass


def as_string_id(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise IdCoercionError(f"{field}: boolean is not a string ID")
    if isinstance(value, float):
        raise IdCoercionError(
            f"{field}: refused float ID {value!r}; IDs must be read as strings"
        )
    if isinstance(value, int):
        return str(value)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(".0") and text[:-2].lstrip("-").isdigit():
        raise IdCoercionError(
            f"{field}: value {value!r} looks float-coerced; refuse implicit ID float"
        )
    return text


def as_int(value: Any, *, field: str) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise IdCoercionError(f"{field}: boolean is not an int")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        raise IdCoercionError(f"{field}: non-integer float {value!r}")
    text = str(value).strip()
    if text == "":
        return None
    return int(text)


def as_number(value: Any, *, field: str):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise IdCoercionError(f"{field}: boolean is not a number")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return value
    text = str(value).strip()
    if text == "":
        return None
    if "." in text or "e" in text.lower():
        num = float(text)
        if num.is_integer():
            return int(num)
        return num
    return int(text)


def as_bool(value: Any, *, field: str) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value in (0, 1):
            return bool(value)
        raise IdCoercionError(f"{field}: int {value!r} is not a 0/1 bool")
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    raise IdCoercionError(f"{field}: cannot parse bool {value!r}")


def as_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return value
    if isinstance(value, datetime):
        return format_iso(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    return json_ready(str(value))


def dumps_canonical(value: Any) -> str:
    ready = json_ready(value)
    return json.dumps(ready, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def dumps_hash_payload(value: Any) -> str:
    ready = json_ready(value)
    return json.dumps(ready, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
