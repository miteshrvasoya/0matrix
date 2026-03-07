from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PaymentContext:
    """Input details used by the routing engine to select a bank route."""

    payment_id: str
    amount: float
    currency: str
    country: str
    merchant_id: str
    preferred_bank: str | None = None
