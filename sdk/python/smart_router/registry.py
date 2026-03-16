from __future__ import annotations

from smart_router._bootstrap import ensure_repo_root_on_path

ensure_repo_root_on_path()

from core.strategy_registry import StrategyRegistry as _StrategyRegistry

StrategyRegistry = _StrategyRegistry

__all__ = ["StrategyRegistry"]
