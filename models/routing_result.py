from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoutingResult:
    """Final decision and execution outcome for one payment attempt."""

    payment_id: str
    chosen_route_id: str
    chosen_bank: str
    score: float
    success: bool
    latency_ms: float
    error_code: str | None
    retry_attempts: int = 0
    attempted_route_ids: tuple[str, ...] = ()
