"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const {
  RouterEngine,
  WeightedRouter,
  EpsilonBanditRouter,
  ThompsonSamplingRouter,
} = require("../sdk/node");

const fixturePath = path.join(__dirname, "parity_fixtures.json");
const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));

function run(strategy) {
  const engine = new RouterEngine(strategy);
  return engine.route(fixture.context, fixture.routes, fixture.metrics).selected_route;
}

assert.strictEqual(run(new WeightedRouter()), fixture.expected.weighted);
assert.strictEqual(
  run(new EpsilonBanditRouter({ epsilon: 0.1, seed: 42 })),
  fixture.expected.epsilon_bandit
);
assert.strictEqual(run(new ThompsonSamplingRouter({ seed: 42 })), fixture.expected.thompson);

console.log("Node parity tests passed.");
