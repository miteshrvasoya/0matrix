from __future__ import annotations

from smart_router._bootstrap import ensure_repo_root_on_path

ensure_repo_root_on_path()

from core.router_engine import RouterEngine as _RouterEngine

RouterEngine = _RouterEngine

__all__ = ["RouterEngine"]
