"""Phase C: single main Agent, 8 structured tools, three Providers, run records.

Read-only/draft tools only; no real business side effects. Human confirmation
gates all business actions (see risk SPEC); this module never executes them.
"""

from .agent import Agent, AnalysisRequest, AnalysisResult
from .budget import BudgetConfig, StopReason
from .providers import MockProvider, ProviderError, QwenProvider, RuleProvider
from .runlog import RunLog, VersionedCache
from .tools import TOOL_SPECS, ToolBox

__all__ = [
    "Agent",
    "AnalysisRequest",
    "AnalysisResult",
    "BudgetConfig",
    "StopReason",
    "MockProvider",
    "ProviderError",
    "QwenProvider",
    "RuleProvider",
    "RunLog",
    "VersionedCache",
    "TOOL_SPECS",
    "ToolBox",
]
