from __future__ import annotations

import sys
from pathlib import Path

SDK_PYTHON_PATH = Path(__file__).resolve().parents[2] / "sdk" / "python"
if str(SDK_PYTHON_PATH) not in sys.path:
    sys.path.insert(0, str(SDK_PYTHON_PATH))

from smart_router import PaymentContext, RouteDefinition, RouteMetrics, RouterEngine, WeightedRouter


def main() -> None:
    context = PaymentContext(
        amount=120.5,
        payment_method="card",
        payer_bank="BankA",
        region="US",
        timestamp="2026-03-07T00:00:00Z",
    )
    routes = [
        RouteDefinition(name="route_a", cost=0.32, capacity=1000),
        RouteDefinition(name="route_b", cost=0.18, capacity=1000),
        RouteDefinition(name="route_c", cost=0.27, capacity=1000),
    ]
    metrics = {
        "route_a": RouteMetrics(success_rate=0.96, error_rate=0.04, avg_latency=180, sample_size=2000),
        "route_b": RouteMetrics(success_rate=0.93, error_rate=0.07, avg_latency=95, sample_size=1800),
        "route_c": RouteMetrics(success_rate=0.91, error_rate=0.09, avg_latency=240, sample_size=1300),
    }

    engine = RouterEngine(strategy=WeightedRouter())
    decision = engine.route(context=context, routes=routes, metrics=metrics)
    print("Selected route:", decision.selected_route)
    print("Score:", decision.score)
    print("Confidence:", decision.confidence)


if __name__ == "__main__":
    main()
