from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoutingDecision:
    selected_route: str
    score: float
    confidence: float
