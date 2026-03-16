"use strict";

const {
  RouterEngine,
  WeightedRouter,
} = require("../../sdk/node");

const context = {
  amount: 120.5,
  payment_method: "card",
  payer_bank: "BankA",
  region: "US",
  timestamp: "2026-03-07T00:00:00Z",
};

const routes = [
  { name: "route_a", cost: 0.32, capacity: 1000 },
  { name: "route_b", cost: 0.18, capacity: 1000 },
  { name: "route_c", cost: 0.27, capacity: 1000 },
];

const metrics = {
  route_a: { success_rate: 0.96, error_rate: 0.04, avg_latency: 180, sample_size: 2000 },
  route_b: { success_rate: 0.93, error_rate: 0.07, avg_latency: 95, sample_size: 1800 },
  route_c: { success_rate: 0.91, error_rate: 0.09, avg_latency: 240, sample_size: 1300 },
};

const engine = new RouterEngine(new WeightedRouter());
const decision = engine.route(context, routes, metrics);
console.log("Selected route:", decision.selected_route);
console.log("Score:", decision.score);
console.log("Confidence:", decision.confidence);
