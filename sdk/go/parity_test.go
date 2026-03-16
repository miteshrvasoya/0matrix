package smartrouter

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

type parityFixture struct {
	Context  PaymentContext           `json:"context"`
	Routes   []RouteDefinition        `json:"routes"`
	Metrics  map[string]RouteMetrics  `json:"metrics"`
	Expected map[string]string        `json:"expected"`
}

func loadParityFixture(t *testing.T) parityFixture {
	t.Helper()
	root := filepath.Join("..", "..", "tests", "parity_fixtures.json")
	raw, err := os.ReadFile(root)
	if err != nil {
		t.Fatalf("failed to read parity fixture: %v", err)
	}
	var fixture parityFixture
	if err := json.Unmarshal(raw, &fixture); err != nil {
		t.Fatalf("failed to unmarshal parity fixture: %v", err)
	}
	return fixture
}

func TestWeightedParity(t *testing.T) {
	fixture := loadParityFixture(t)
	engine, err := NewRouterEngine(NewWeightedRouter(nil))
	if err != nil {
		t.Fatalf("failed to create engine: %v", err)
	}
	decision, err := engine.Route(fixture.Context, fixture.Routes, fixture.Metrics)
	if err != nil {
		t.Fatalf("failed to route: %v", err)
	}
	if decision.SelectedRoute != fixture.Expected["weighted"] {
		t.Fatalf("expected %s got %s", fixture.Expected["weighted"], decision.SelectedRoute)
	}
}

func TestBanditParity(t *testing.T) {
	fixture := loadParityFixture(t)
	engine, err := NewRouterEngine(NewEpsilonBanditRouter(map[string]any{"seed": 42}))
	if err != nil {
		t.Fatalf("failed to create engine: %v", err)
	}
	decision, err := engine.Route(fixture.Context, fixture.Routes, fixture.Metrics)
	if err != nil {
		t.Fatalf("failed to route: %v", err)
	}
	if decision.SelectedRoute != fixture.Expected["epsilon_bandit"] {
		t.Fatalf("expected %s got %s", fixture.Expected["epsilon_bandit"], decision.SelectedRoute)
	}
}

func TestThompsonParity(t *testing.T) {
	fixture := loadParityFixture(t)
	engine, err := NewRouterEngine(NewThompsonSamplingRouter(map[string]any{"seed": 42}))
	if err != nil {
		t.Fatalf("failed to create engine: %v", err)
	}
	decision, err := engine.Route(fixture.Context, fixture.Routes, fixture.Metrics)
	if err != nil {
		t.Fatalf("failed to route: %v", err)
	}
	if decision.SelectedRoute != fixture.Expected["thompson"] {
		t.Fatalf("expected %s got %s", fixture.Expected["thompson"], decision.SelectedRoute)
	}
}
