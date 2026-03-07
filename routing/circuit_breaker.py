from __future__ import annotations

import time
from collections.abc import Callable


class CircuitBreaker:
    """Temporarily disables routes that become unavailable."""

    def __init__(self, cooldown_seconds: float = 30.0, time_fn: Callable[[], float] | None = None) -> None:
        if cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be > 0")

        self.cooldown_seconds = cooldown_seconds
        self._time_fn = time_fn or time.monotonic
        self._disabled_until: dict[str, float] = {}

    def disable_route(self, route_id: str) -> None:
        self._disabled_until[route_id] = self._time_fn() + self.cooldown_seconds

    def is_route_active(self, route_id: str) -> bool:
        until = self._disabled_until.get(route_id)
        if until is None:
            return True

        if self._time_fn() >= until:
            del self._disabled_until[route_id]
            return True
        return False
