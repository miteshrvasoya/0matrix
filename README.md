# 0matrix Payment Routing Simulation

A Python simulation project for intelligent payment routing across multiple bank routes.

The project models:
- Route scoring based on success rate, latency, error rate, cost, and bank affinity
- Route health monitoring and temporary circuit breaking
- Retry/failover across ranked routes
- Optional adaptive routing using an epsilon-greedy bandit
- Global and per-bank metrics collection

## Project Structure

```text
0matrix/
  main.py
  models/
    payment_context.py
    route.py
    routing_result.py
  routing/
    bandit_router.py
    circuit_breaker.py
    failover_engine.py
    metrics_store.py
    route_health.py
    routing_engine.py
    scoring.py
  simulation/
    bank_simulator.py
    metrics.py
```

## Requirements

- Python 3.10+

No third-party dependencies are required.

## Quick Start

From the project root (`e:\Projects\0matrix`):

```powershell
python main.py
```

You should see:
- Per-payment execution logs (selected route, retries, final status, latency)
- Global summary metrics
- Per-bank summary metrics

## How It Works

### 1) Input Models

- `PaymentContext`: payment attributes used for decisioning (`models/payment_context.py`)
- `Route`: bank route profile and supported geo/currency (`models/route.py`)
- `RoutingResult`: final decision and execution outcome (`models/routing_result.py`)

### 2) Route Ranking

`RoutingEngine` (`routing/routing_engine.py`) ranks eligible routes:
- Filters routes by `currency` and `country`
- Removes unavailable routes (health monitor + circuit breaker)
- Uses one of two strategies:
  - Static weighted scoring (`ScoringAlgorithm` in `routing/scoring.py`)
  - Adaptive bandit-based ranking (`EpsilonGreedyBanditRouter` in `routing/bandit_router.py`)

### 3) Execution + Failover

`BankRouteSimulator` (`simulation/bank_simulator.py`):
- Simulates route attempt outcomes based on route success/latency profile
- Records live metrics in `MetricsStore`
- Recalculates route health after each attempt
- Triggers circuit breaker for unavailable routes
- Uses `RetryFailoverEngine` to retry next-best routes

### 4) Reporting

`MetricsCollector` (`simulation/metrics.py`) returns:
- Global totals, success/error rate, avg latency, avg score
- Per-bank routed count, success rate, avg latency

## Running with Current Defaults

Current `main.py` defaults:
- 3 routes: `BankA`, `BankB`, `BankC`
- 6 sample payments
- `adaptive_routing_enabled = False`
- Circuit breaker cooldown: `10s`
- Retry attempts: up to `3`
- Metrics recent window: `200`
- Simulator random seed: `42` (deterministic runs)

## Configuration Points

### Enable Adaptive Routing

In `main.py`, set:

```python
adaptive_routing_enabled = True
```

This switches ranking from static weighted scoring to epsilon-greedy adaptive routing.

### Tune Scoring Weights

Create custom weights in `routing/scoring.py` and pass into `RoutingEngine`:

```python
from routing import ScoreWeights, ScoringAlgorithm

weights = ScoreWeights(
    success_rate=0.35,
    latency=0.25,
    error_rate=0.20,
    cost=0.10,
    bank_affinity=0.10,
)
scoring = ScoringAlgorithm(weights)
```

Then pass `scoring=scoring` while building `RoutingEngine`.

### Tune Failover / Health / Circuit Logic

- Retry count: `RetryFailoverEngine(max_retries=...)`
- Health thresholds: `RouteHealthMonitor.evaluate(...)`
- Cooldown: `CircuitBreaker(cooldown_seconds=...)`
- Bandit exploration: `EpsilonGreedyBanditRouter(epsilon=...)`

## Typical Usage in Existing Structure

1. Define route inventory in `build_routes()` in `main.py`.
2. Define payment traffic in `build_sample_payments()` in `main.py`.
3. Build engine components (metrics, health, breaker, engine, failover).
4. Process each payment via `simulator.process_payment(payment)`.
5. Record each `RoutingResult` with `MetricsCollector.record(...)`.
6. Print/use `summary()` and `per_bank_summary()` outputs.

## Troubleshooting

### `No eligible routes for currency=... country=...`

No route supports that payment currency-country pair. Update `supported_currencies` and `supported_countries` in route definitions.

### `No available routes for currency=... country=...`

All eligible routes are blocked by health/circuit logic at decision time. Increase route pool, loosen thresholds, or reduce cooldown duration.

### `python` not found

Use your installed Python launcher command (for example `py main.py` on Windows).

## Suggested Next Improvements

- Add unit tests for scoring, health state transitions, and failover behavior
- Add CLI flags for adaptive mode, retries, and seed
- Load routes/payments from JSON or YAML files instead of hardcoding
- Persist simulation metrics to CSV/JSON for analysis
