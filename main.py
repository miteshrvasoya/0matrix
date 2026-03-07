from __future__ import annotations

from models import PaymentContext, Route
from routing import (
    CircuitBreaker,
    MetricsStore,
    RetryFailoverEngine,
    RouteHealthMonitor,
    RoutingEngine,
)
from simulation import BankRouteSimulator, MetricsCollector


def build_routes() -> list[Route]:
    return [
        Route(
            route_id="route_us_a",
            bank_name="BankA",
            success_rate=0.97,
            latency_ms=210,
            error_rate=0.03,
            cost_per_txn=0.32,
            supported_currencies={"USD", "EUR"},
            supported_countries={"US", "CA", "GB"},
        ),
        Route(
            route_id="route_us_b",
            bank_name="BankB",
            success_rate=0.93,
            latency_ms=120,
            error_rate=0.07,
            cost_per_txn=0.18,
            supported_currencies={"USD"},
            supported_countries={"US", "MX"},
        ),
        Route(
            route_id="route_eu_c",
            bank_name="BankC",
            success_rate=0.95,
            latency_ms=260,
            error_rate=0.05,
            cost_per_txn=0.22,
            supported_currencies={"EUR", "GBP"},
            supported_countries={"GB", "FR", "DE"},
        ),
    ]


def build_sample_payments() -> list[PaymentContext]:
    return [
        PaymentContext("pay_001", 120.50, "USD", "US", "merchant_alpha", preferred_bank="BankB"),
        PaymentContext("pay_002", 87.00, "USD", "US", "merchant_alpha"),
        PaymentContext("pay_003", 310.00, "EUR", "GB", "merchant_beta", preferred_bank="BankC"),
        PaymentContext("pay_004", 29.99, "USD", "MX", "merchant_gamma"),
        PaymentContext("pay_005", 420.10, "EUR", "DE", "merchant_beta"),
        PaymentContext("pay_006", 58.90, "USD", "CA", "merchant_delta", preferred_bank="BankA"),
    ]


def main() -> None:
    routes = build_routes()
    adaptive_routing_enabled = False

    metrics_store = MetricsStore(route_ids=[route.route_id for route in routes], recent_window=200)
    health_monitor = RouteHealthMonitor()
    circuit_breaker = CircuitBreaker(cooldown_seconds=10.0)

    engine = RoutingEngine(
        routes=routes,
        adaptive_routing_enabled=adaptive_routing_enabled,
        metrics_store=metrics_store,
        health_monitor=health_monitor,
        circuit_breaker=circuit_breaker,
    )
    failover_engine = RetryFailoverEngine(max_retries=3, health_monitor=health_monitor)

    simulator = BankRouteSimulator(
        engine=engine,
        metrics_store=metrics_store,
        health_monitor=health_monitor,
        circuit_breaker=circuit_breaker,
        failover_engine=failover_engine,
    )
    metrics = MetricsCollector()

    print("=== Payment Orchestration Simulation ===")
    for payment in build_sample_payments():
        result = simulator.process_payment(payment)
        metrics.record(result)

    print("\n=== Global Metrics ===")
    for key, value in metrics.summary().items():
        print(f"{key}: {value}")

    print("\n=== Per-Bank Metrics ===")
    for bank, bank_metrics in metrics.per_bank_summary().items():
        print(f"{bank}: {bank_metrics}")


if __name__ == "__main__":
    main()
