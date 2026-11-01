"""Control layer (next generation, Stage 3): forecasts, plant futures, multi-step MPC, an independent
safety filter and an approved fallback. Optimisers *propose* actions; only the safety filter's output
reaches the plant."""
