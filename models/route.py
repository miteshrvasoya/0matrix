from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Route:
    """Represents an available bank route and its dynamic performance profile."""

    route_id: str
    bank_name: str
    success_rate: float
    latency_ms: float
    error_rate: float
    cost_per_txn: float
    supported_currencies: set[str]
    supported_countries: set[str]

    def supports(self, currency: str, country: str) -> bool:
        return currency in self.supported_currencies and country in self.supported_countries
