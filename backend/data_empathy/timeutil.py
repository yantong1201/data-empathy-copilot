"""Parse and format times as Asia/Shanghai. Never use the host local zone."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
SHANGHAI_NAME = "Asia/Shanghai"
ISO_OFFSET = "+08:00"

_NAIVE_DT = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(?:\.\d+)?"
)
_ISO_OFFSET = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)
_NOTE_SPLIT = re.compile(r"[（(]")


class TimeParseError(ValueError):
    pass


def _datetime_shanghai(year: int, month: int, day: int, hour: int, minute: int, second: int) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=SHANGHAI_TZ)


def parse_shanghai(value, *, field: str = "time") -> datetime | None:
    """Interpret a source value as Asia/Shanghai. None/empty → None.

    Naive strings and naive datetime/date are Shanghai, not the host TZ.
    Aware values are converted to Shanghai.
    """
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        return parse_shanghai_text(text, field=field)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(microsecond=0, tzinfo=SHANGHAI_TZ)
        return value.astimezone(SHANGHAI_TZ).replace(microsecond=0)
    if isinstance(value, date) and not isinstance(value, datetime):
        return _datetime_shanghai(value.year, value.month, value.day, 0, 0, 0)
    if isinstance(value, time):
        raise TimeParseError(f"{field}: time-only value {value!r} is not a snapshot timestamp")
    return parse_shanghai_text(str(value).strip(), field=field)


def parse_shanghai_text(text: str, *, field: str = "time") -> datetime:
    raw = text.strip()
    if not raw:
        raise TimeParseError(f"{field}: empty time")

    iso = _ISO_OFFSET.match(raw)
    if iso:
        date_s, time_s, off = iso.group(1), iso.group(2), iso.group(3)
        year, month, day = (int(p) for p in date_s.split("-"))
        hour, minute, second = (int(p) for p in time_s.split(":"))
        if off == "Z":
            dt = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
        else:
            sign = 1 if off[0] == "+" else -1
            oh, om = int(off[1:3]), int(off[4:6])
            dt = datetime(
                year, month, day, hour, minute, second,
                tzinfo=timezone(sign * timedelta(hours=oh, minutes=om)),
            )
        return dt.astimezone(SHANGHAI_TZ).replace(microsecond=0)

    head = _NOTE_SPLIT.split(raw, maxsplit=1)[0].strip()
    naive = _NAIVE_DT.match(head)
    if not naive:
        raise TimeParseError(f"{field}: cannot parse {text!r} as Asia/Shanghai time")
    date_s, time_s = naive.group(1), naive.group(2)
    year, month, day = (int(p) for p in date_s.split("-"))
    hour, minute, second = (int(p) for p in time_s.split(":"))
    return _datetime_shanghai(year, month, day, hour, minute, second)


def time_annotation(value) -> str | None:
    """Keep trailing notes such as （定金） after the timestamp."""
    if not isinstance(value, str):
        return None
    parts = _NOTE_SPLIT.split(value.strip(), maxsplit=1)
    if len(parts) < 2:
        return None
    note = parts[1].strip()
    if note.endswith("）") or note.endswith(")"):
        note = note[:-1]
    return note or None


def format_iso(dt: datetime | None) -> str | None:
    """RFC 3339 / ISO 8601 with explicit +08:00. Independent of host TZ."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=SHANGHAI_TZ)
    else:
        dt = dt.astimezone(SHANGHAI_TZ)
    dt = dt.replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ISO_OFFSET


def as_of_or_parse(value) -> datetime:
    if isinstance(value, datetime):
        parsed = parse_shanghai(value, field="as_of_time")
        if parsed is None:
            raise TimeParseError("as_of_time is empty")
        return parsed
    if value is None or (isinstance(value, str) and not value.strip()):
        raise TimeParseError("as_of_time is required")
    return parse_shanghai_text(str(value), field="as_of_time")
