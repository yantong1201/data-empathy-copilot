"""Phase D workbench: server-side disposal state, drafts and confirmations.

All business actions stay human-confirmed local records; no real business
system is ever contacted. Logs are append-only; disposal state changes only
through validated confirmations.
"""

from .state import WorkbenchState
from .server import build_server, main

__all__ = ["WorkbenchState", "build_server", "main"]
