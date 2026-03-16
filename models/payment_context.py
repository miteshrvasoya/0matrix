from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PaymentContext:
    amount: float
    payment_method: str
    payer_bank: str | None
    region: str
    timestamp: datetime | str
