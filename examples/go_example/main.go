package main

import (
	"fmt"

	smartrouter "github.com/<org>/smart-routing-algorithms/sdk/go"
)

func main() {
	router := smartrouter.MustNewRouterEngine(smartrouter.NewWeightedRouterDefault())

	context := smartrouter.PaymentContext{
		Amount:        120.5,
		PaymentMethod: "card",
		PayerBank:     "BankA",
		Region:        "US",
		Timestamp:     "2026-03-07T00:00:00Z",
	}

	routes := []smartrouter.RouteDefinition{
		{Name: "route_a", Cost: 0.32, Capacity: 1000},
		{Name: "route_b", Cost: 0.18, Capacity: 1000},
		{Name: "route_c", Cost: 0.27, Capacity: 1000},
	}

	metrics := map[string]smartrouter.RouteMetrics{
		"route_a": {SuccessRate: 0.96, ErrorRate: 0.04, AvgLatency: 180, SampleSize: 2000},
		"route_b": {SuccessRate: 0.93, ErrorRate: 0.07, AvgLatency: 95, SampleSize: 1800},
		"route_c": {SuccessRate: 0.91, ErrorRate: 0.09, AvgLatency: 240, SampleSize: 1300},
	}

	decision, err := router.Route(context, routes, metrics)
	if err != nil {
		panic(err)
	}

	fmt.Printf("Selected route: %s\n", decision.SelectedRoute)
	fmt.Printf("Score: %.6f\n", decision.Score)
	fmt.Printf("Confidence: %.6f\n", decision.Confidence)
}
