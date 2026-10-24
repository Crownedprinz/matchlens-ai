"""Shared, offline-testable inputs and validation for isolated Foundry checks."""
from __future__ import annotations

import re
from typing import Any

from app.agents.contracts import EvidenceItem, Forecast, InsightHandoff, InvestigatorHandoff, PredictionHandoff, ToolCall
from app.repositories.synthetic import form, get_fixture, h2h, players


def build_investigator_handoff(match_id: str) -> InvestigatorHandoff:
    """Build evidence only from records present in the synthetic repository."""
    fixture = get_fixture(match_id)
    evidence = [
        EvidenceItem(record_type="h2h", record_id=f"h2h:{match_id}:{index}", statement=f"Synthetic H2H result {row.home_score}-{row.away_score}.")
        for index, row in enumerate(h2h(match_id))
    ]
    for team_id, label in ((fixture.home_team_id, "home"), (fixture.away_team_id, "away")):
        evidence.extend(
            EvidenceItem(record_type="form", record_id=f"form:{team_id}:{index}", statement=f"Synthetic {label} form result {row.score} ({row.outcome}).")
            for index, row in enumerate(form(team_id))
        )
    evidence.extend(
        EvidenceItem(record_type="player", record_id=f"player:{player.id}", statement=f"Synthetic player record for {player.name}.")
        for player in players(fixture.home_team_id) + players(fixture.away_team_id)
    )
    return InvestigatorHandoff(evidence=evidence, missing_information=["Market odds and official lineup data are not in the synthetic dataset."])


def _numbers(text: str) -> list[tuple[str, float]]:
    return [(token, float(token.rstrip("%"))) for token in re.findall(r"\d+(?:\.\d+)?%?", text)]


def unsupported_insight_numbers(insight: InsightHandoff, investigator: InvestigatorHandoff, prediction: PredictionHandoff) -> list[str]:
    """Find numeric claims absent from validated evidence/forecast, allowing rounding."""
    source_text = investigator.model_dump_json() + prediction.model_dump_json()
    source_values = [value for _, value in _numbers(source_text)]
    claims = " ".join([insight.summary, *insight.bullets])
    unsupported = []
    for token, value in _numbers(claims):
        tolerance = 1.0 if token.endswith("%") else max(0.11, abs(value) * 0.005)
        if not any(abs(value - source) <= tolerance for source in source_values):
            unsupported.append(token)
    return list(dict.fromkeys(unsupported))


def insight_check(insight: InsightHandoff, investigator: InvestigatorHandoff, prediction: PredictionHandoff) -> dict[str, Any]:
    unsupported = unsupported_insight_numbers(insight, investigator, prediction)
    return {
        "unsupported_numerical_claims": unsupported,
        "unsupported_claims": insight.unsupported_claims,
        "contradictions": insight.contradictions,
        "semantic_accuracy": "not_proven_by_string_check",
        "review_required": True,
        "valid": not insight.contradictions and not unsupported and not insight.unsupported_claims,
    }


def required_tool_verification(tool_calls: list[ToolCall], agent_name: str, agent_version: str) -> list[str]:
    required = {"predict_match", "predict_player", "get_model_explanation"}
    called = {call.name for call in tool_calls if call.agent_name == agent_name and call.agent_version == agent_version and call.outcome == "success"}
    return sorted(required - called)


def forecast_mismatches(returned: Forecast, canonical: dict[str, Any], expected_player: dict[str, Any] | None = None, returned_players: list[dict[str, Any]] | None = None, expected_players: dict[str, dict[str, Any]] | None = None, required_player_id: str | None = None) -> list[str]:
    """Compare all numeric forecast fields without changing either result."""
    actual = returned.model_dump()
    mismatches: list[str] = []
    for key in ("minute", "current_home_score", "current_away_score", "expected_home_goals", "expected_away_goals", "home_win_probability", "draw_probability", "away_win_probability"):
        if abs(float(actual[key]) - float(canonical[key])) > 0.01:
            mismatches.append(f"forecast.{key}")
    expected_scores = canonical.get("most_likely_scores", [])
    actual_scores = actual.get("most_likely_scores", [])
    if len(actual_scores) != len(expected_scores):
        mismatches.append("forecast.most_likely_scores.length")
    else:
        for index, (got, want) in enumerate(zip(actual_scores, expected_scores)):
            for key in ("home", "away", "probability"):
                if abs(float(got[key]) - float(want[key])) > 0.01:
                    mismatches.append(f"forecast.most_likely_scores[{index}].{key}")
    expected = expected_players or ({expected_player["player_id"]: expected_player} if expected_player is not None else {})
    returned_items = returned_players or []
    if required_player_id and not any(item.get("player_id") == required_player_id for item in returned_items):
        mismatches.append(f"player_projections[{required_player_id}] missing")
    for match in returned_items:
        player_id = match.get("player_id")
        expected_projection = expected.get(player_id)
        if expected_projection is None:
            mismatches.append(f"player_projections[{player_id}] unsupported")
            continue
        for key in ("projected_goals", "projected_assists"):
            if abs(float(match[key]) - float(expected_projection[key])) > 0.01:
                mismatches.append(f"player_projections[{player_id}].{key}")
    return mismatches
