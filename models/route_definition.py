from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RouteDefinition:
    name: str
    cost: float
    capacity: float
