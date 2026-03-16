# Integration Guide

This guide focuses on embedding `smart-routing-algorithms` into an existing payment orchestration system.

## 1. Integration Checklist

Before integrating, confirm your host system already has or can provide:

- a payment execution layer
- a route catalog or route configuration source
- recent route performance metrics
- a place to persist strategy state snapshots
- a safe fallback policy if no route is usable

The library assumes those host capabilities exist.

## 2. What the Host Must Provide

### Payment Execution

The engine returns only a route decision. Your host must still call the processor, gateway, or PSP.

### Route Inventory

The host decides which routes are currently eligible and converts them into `RouteDefinition` objects.

Examples of host-side filters:

- merchant configuration
- currency or region support
- maintenance windows
- processor outage flags
- routing policy overrides

### Metrics Snapshot

The host must provide a metrics view for each route.

Recommended metrics sources:

- rolling transaction windows
- recent route health streams
- service-level metrics tables
- aggregated execution logs

### Persistence

The host owns storage for:

- strategy snapshots
- benchmark outputs if desired
- historical route metrics

## 3. Mapping Existing Data to Framework Models

### Payment Request -> `PaymentContext`

Typical mapping:

- transaction amount -> `amount`
- payment method type -> `payment_method`
- issuer or bank -> `payer_bank`
- market/country/geo bucket -> `region`
- request time -> `timestamp`

### Route Configuration -> `RouteDefinition`

Typical mapping:

- processor route key -> `name`
- fixed or average unit cost -> `cost`
- host-computed availability / throughput headroom -> `capacity`

### Route Health Metrics -> `RouteMetrics`

Typical mapping:

- recent success fraction -> `success_rate`
- recent failure fraction -> `error_rate`
- rolling p50/p95 average proxy -> `avg_latency`
- transaction count behind the metric -> `sample_size`

## 4. Reference Integration Flow

```python
from core.router_engine import RouterEngine
from models.payment_context import PaymentContext
from models.route_definition import RouteDefinition
from models.route_metrics import RouteMetrics


def route_payment(payment_request, route_store, metrics_store, state_store):
    context = PaymentContext(
        amount=payment_request.amount,
        payment_method=payment_request.payment_method,
        payer_bank=payment_request.payer_bank,
        region=payment_request.region,
        timestamp=payment_request.timestamp,
    )

    routes = [
        RouteDefinition(name=route.name, cost=route.cost, capacity=route.capacity)
        for route in route_store.list_available_routes(payment_request)
    ]

    metrics = {
        row.route_name: RouteMetrics(
            success_rate=row.success_rate,
            error_rate=row.error_rate,
            avg_latency=row.avg_latency_ms,
            sample_size=row.sample_size,
        )
        for row in metrics_store.load_recent_metrics()
    }

    engine = RouterEngine(strategy="thompson")

    saved_state = state_store.load("thompson")
    if saved_state is not None:
        engine.restore_state(saved_state)

    decision = engine.route(context=context, routes=routes, metrics=metrics)

    execution = execute_payment_via_host(payment_request, decision.selected_route)

    engine.record_outcome(
        route_name=decision.selected_route,
        success=execution.success,
        latency_ms=execution.latency_ms,
        cost=execution.cost,
    )

    state_store.save("thompson", engine.snapshot_state())
    return decision, execution
```

## 5. Recommended Host Responsibilities by Layer

### Request Layer

Responsible for:

- building `PaymentContext`
- selecting the candidate route set
- invoking `RouterEngine`

### Execution Layer

Responsible for:

- sending the payment to the chosen route
- timing the attempt
- measuring success or failure
- capturing realized cost where available

### Metrics Layer

Responsible for:

- aggregating route performance
- defining freshness windows
- publishing normalized route metrics into the engine format

### Persistence Layer

Responsible for:

- saving strategy snapshots
- restoring strategy state after restart or deploy
- optionally versioning strategy state across migrations

## 6. State Persistence Patterns

### Option A: Snapshot Per Outcome Batch

Persist every N outcomes.

Use when:

- your process is long-lived
- some state loss is acceptable
- you want lower write volume

### Option B: Snapshot On Shutdown + Periodic Timer

Persist on graceful shutdown and every fixed interval.

Use when:

- you want predictable overhead
- your process lifecycle is controlled

### Option C: External Stateful Worker Ownership

Keep one engine instance in a dedicated orchestration worker and snapshot centrally.

Use when:

- multiple stateless API workers feed one routing brain
- you want strict control of shared strategy state

## 7. Concurrency and Multi-Worker Considerations

If you run multiple workers, decide explicitly whether strategy state should be:

- shared across workers
- isolated per worker
- isolated per tenant, merchant, or region

Practical guidance:

- Use isolated state if traffic populations are very different.
- Use shared state if you want faster learning across the same traffic pool.
- Do not accidentally mix unrelated merchants into one adaptive state bucket unless that is an intentional policy.

## 8. Metrics Freshness Guidance

The framework is only as good as the metrics it receives.

Recommended practices:

- use rolling windows appropriate for your traffic volume
- ensure `sample_size` reflects the confidence of the metric
- normalize latency consistently across all routes
- avoid sending stale metrics after long route outages

A good default is to use recent windows for route scoring and the strategy's own internal state for short-term adaptation.

## 9. Strategy Rollout Plan in Production

A safe rollout usually looks like this:

1. Start with `WeightedRouter` as the baseline.
2. Benchmark candidate adaptive strategies offline.
3. Run adaptive strategies in shadow mode if possible.
4. Compare selected routes and simulated outcomes.
5. Enable the new strategy for a small slice of traffic.
6. Persist strategy state to avoid repeated cold starts.
7. Expand rollout after confirming latency, success, and cost behavior.

## 10. Fallback and Error Handling

The host should own the last-resort fallback policy.

Suggested handling:

- if no routes are eligible, fall back to your host-defined safe route or fail fast
- if metrics are missing, allow deterministic strategies to use neutral defaults
- if state restore fails, start with a clean strategy state and alert operationally
- if route execution fails, still call `record_outcome(...)` so adaptive strategies learn

## 11. Integrating by Configuration

Many systems want the active strategy to be changeable without code deployment.

```python
engine = RouterEngine(
    strategy=active_strategy_name,
    config=active_strategy_config,
)
```

Examples of configuration-driven fields:

- strategy name
- bank affinity rules
- scoring weights
- maximum latency normalization bounds
- predictive risk weights

## 12. Integration Examples by Strategy Type

### Deterministic Baseline

Use `WeightedRouter` when you want a stable, easy-to-explain choice function.

### Adaptive Online Learning

Use `EpsilonBanditRouter` or `ThompsonSamplingRouter` when the host reliably records outcomes.

### Context-Aware Routing

Use `ContextualBanditRouter` when route performance varies by payer bank, method, amount, or time.

### Risk-Aware Routing

Use `PredictiveFailureRouter` when route degradation appears before outright failure.

## 13. Language Notes

### Python

Python is the reference integration surface today. It includes the full advanced strategy set and benchmark tooling.

### Node.js and Go

The SDK directories preserve the same engine shape and integration model:

- build context, routes, and metrics
- call `route`
- send execution feedback
- optionally persist state where supported by the strategy implementation

## 14. What to Read Next

- [usage.md](usage.md) for API-level examples
- [algorithms.md](algorithms.md) for choosing the right strategy
- [benchmarking.md](benchmarking.md) for pre-rollout evaluation
