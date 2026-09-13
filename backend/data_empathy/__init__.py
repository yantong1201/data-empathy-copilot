"""Phase A: read-only Excel load, canonical mapping, time snapshots."""

from .fixtures import CASE_FIXTURE_POINTS, generate_case_fixtures
from .loader import CanonicalBundle, DataStore, default_xlsx_path, load_workbook_readonly
from .selfcheck import EXPECTED_INPUT_AUDIT, run_selfcheck
from .snapshot import SnapshotQuery, build_snapshot
from .timeutil import SHANGHAI_TZ, format_iso, parse_shanghai

__all__ = [
    "CASE_FIXTURE_POINTS",
    "CanonicalBundle",
    "DataStore",
    "EXPECTED_INPUT_AUDIT",
    "SHANGHAI_TZ",
    "SnapshotQuery",
    "build_snapshot",
    "default_xlsx_path",
    "format_iso",
    "generate_case_fixtures",
    "load_workbook_readonly",
    "parse_shanghai",
    "run_selfcheck",
]
