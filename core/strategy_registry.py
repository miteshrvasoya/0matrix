from __future__ import annotations

from importlib import import_module
from importlib.metadata import EntryPoints, entry_points
from typing import Callable

from core.base_strategy import BaseRoutingStrategy

StrategyFactory = Callable[..., BaseRoutingStrategy]


class StrategyRegistry:
    """Global in-process strategy registry."""

    _registry: dict[str, StrategyFactory] = {}

    @classmethod
    def register(
        cls,
        name: str,
        factory: StrategyFactory,
        *,
        overwrite: bool = False,
    ) -> None:
        key = name.strip().lower()
        if not key:
            raise ValueError("strategy name must not be empty")
        if not overwrite and key in cls._registry:
            raise ValueError(f"strategy '{key}' is already registered")
        cls._registry[key] = factory

    @classmethod
    def create(cls, name: str, config: dict | None = None) -> BaseRoutingStrategy:
        key = name.strip().lower()
        if key not in cls._registry:
            raise KeyError(f"strategy '{key}' is not registered")

        factory = cls._registry[key]
        cfg = config or {}
        try:
            instance = factory(**cfg)
        except TypeError:
            instance = factory(cfg)  # pragma: no cover - compatibility path

        if not isinstance(instance, BaseRoutingStrategy):
            raise TypeError(
                f"factory for strategy '{key}' must return BaseRoutingStrategy, got {type(instance)}"
            )
        return instance

    @classmethod
    def list(cls) -> list[str]:
        return sorted(cls._registry.keys())

    @classmethod
    def autodiscover(
        cls,
        *,
        entrypoint_group: str = "smart_router.strategies",
        module_paths: list[str] | None = None,
    ) -> None:
        """Load strategy plugins from entry points and optional module imports."""
        for ep in cls._select_entry_points(entrypoint_group):
            factory = ep.load()
            cls.register(ep.name, factory, overwrite=False)

        for module_path in module_paths or []:
            module = import_module(module_path)
            hook = getattr(module, "register_strategies", None)
            if callable(hook):
                hook(cls)

    @staticmethod
    def _select_entry_points(group: str) -> EntryPoints:
        eps = entry_points()
        if hasattr(eps, "select"):
            return eps.select(group=group)
        return eps.get(group, [])  # pragma: no cover - python<3.10 fallback
