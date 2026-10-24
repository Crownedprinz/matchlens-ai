# Production Verification Report

Date: 2026-10-24

This is a sanitized record of the controlled production verification. It contains no access codes, API keys, tokens, authorization headers, or confidential payloads.

## Live Foundry result

- HTTP status: 200
- End-to-end latency: 51.6 seconds
- Match: `match-001`
- Replay minute: 14
- Investigator: `matchlens-investigator` v8
- Predictor: `matchlens-predictor` v6
- Insight: `matchlens-insight` v5
- Workflow status: `ok`
- Workflow errors: none
- Agent-attributed tool calls: 29
- Local deterministic preparation calls: 23
- Investigator tools executed: `get_head_to_head`, `get_match_context`, `get_player_stats`, `get_team_form`
- Predictor tools executed: `predict_match`, `predict_player`
- Insight tools: none

## Numerical reconciliation

The live Predictor response reconciled with the deterministic Python forecast at minute 14:

- Expected goals: home `1.49`, away `1.05`
- Probabilities: home `47.17`, draw `26.01`, away `26.82`
- Probability total: `100.00`
- Current score: `0–0`
- Likely scoreline structures: valid and finite

The Insight response contained a valid summary and six bullets. It retained four unsupported-claim notices and two contradiction notices for human review; those notices were not silently discarded.

## Operational notes

- The first health request took approximately 23.6 seconds during scale-to-zero cold start.
- Subsequent API requests completed normally.
- Managed-identity authentication remains an unresolved limitation. This successful verification used the deployed API-key credential mode.
- Public Foundry is currently enabled for the verified demo fixture.
- The public access GUID is intentionally documented as an opt-in demo code, not a secure credential.
- The public workflow remains bounded by the per-IP limiter, 10 Foundry attempts per UTC day per process, 40 attempts per process lifetime, one concurrent execution, and zero validation retries.
