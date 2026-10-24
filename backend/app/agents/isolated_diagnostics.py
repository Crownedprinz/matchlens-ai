"""Shared, offline-testable inputs and validation for isolated Foundry checks."""
from __future__ import annotations

import re
import json
from typing import Any

from pydantic import ValidationError
from app.agents.contracts import EvidenceItem, Forecast, InsightHandoff, InvestigatorHandoff, PlayerProjection, PredictionHandoff, ToolCall
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
    return InvestigatorHandoff(evidence=evidence, missing_information=[
        "Market odds and official lineup data are not in the synthetic dataset.",
        "Player fitness, injuries, and suspension status are not in the synthetic dataset.",
    ])


def parse_prediction_handoff(text: str) -> PredictionHandoff:
    """Require the exact nested backend contract before numerical reconciliation."""
    try:
        value = json.loads(text)
        if set(value) != {"forecast", "player_projections", "unsupported_scenarios"}:
            raise ValueError("PredictionHandoff must have exactly forecast, player_projections, unsupported_scenarios")
        if set(value["forecast"]) != set(Forecast.model_fields):
            raise ValueError("PredictionHandoff.forecast must preserve the complete predict_match result")
        for projection in value["player_projections"]:
            if set(projection) != set(PlayerProjection.model_fields):
                raise ValueError("PredictionHandoff player projections must preserve all five predict_player fields")
        return PredictionHandoff.model_validate(value)
    except (json.JSONDecodeError, TypeError, ValidationError) as exc:
        raise ValueError(f"Invalid PredictionHandoff payload: {exc}") from exc


def parse_insight_handoff(text: str) -> InsightHandoff:
    """Require exactly the four fields in the InsightHandoff contract."""
    try:
        value = json.loads(text)
        if not isinstance(value, dict) or set(value) != {"summary", "bullets", "unsupported_claims", "contradictions"}:
            raise ValueError("InsightHandoff must have exactly summary, bullets, unsupported_claims, contradictions")
        if not isinstance(value["summary"], str) or not isinstance(value["bullets"], list) or not all(isinstance(item, str) for item in value["bullets"]):
            raise ValueError("InsightHandoff summary must be a string and bullets must be an array of strings")
        for field in ("unsupported_claims", "contradictions"):
            if not isinstance(value[field], list) or not all(isinstance(item, str) for item in value[field]):
                raise ValueError(f"InsightHandoff {field} must be an array of strings")
        return InsightHandoff.model_validate(value)
    except (json.JSONDecodeError, TypeError, ValidationError) as exc:
        raise ValueError(f"Invalid InsightHandoff payload: {exc}") from exc


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


def _limitation_tokens(text: str) -> set[str]:
    stop_words = {"a", "an", "and", "are", "be", "from", "in", "is", "not", "of", "or", "the", "to", "with"}
    return {token.rstrip("s") for token in re.findall(r"[a-z0-9]+", text.lower()) if token not in stop_words and len(token) > 2}


def supported_limitation_claims(insight: InsightHandoff, investigator: InvestigatorHandoff) -> list[str]:
    """Classify limitation disclosures that are grounded in missing_information."""
    known = [_limitation_tokens(item) for item in investigator.missing_information]
    supported = []
    for claim in insight.unsupported_claims:
        claim_tokens = _limitation_tokens(claim)
        if any(len(claim_tokens & limitation) >= 2 for limitation in known):
            supported.append(claim)
    return supported


def supported_evidence_claims(insight: InsightHandoff, investigator: InvestigatorHandoff) -> list[str]:
    """Recognize narrow, cautious claims that point back to supplied evidence."""
    evidence_text = " ".join(item.statement for item in investigator.evidence).lower()
    h2h_count = sum(1 for item in investigator.evidence if item.record_type == "h2h")
    supported = []
    for claim in insight.unsupported_claims:
        lowered = claim.lower()
        if "head-to-head" in lowered and "mixed" in lowered and h2h_count >= 2 and "result" in evidence_text:
            supported.append(claim)
    return supported


def insight_check(insight: InsightHandoff, investigator: InvestigatorHandoff, prediction: PredictionHandoff) -> dict[str, Any]:
    unsupported = unsupported_insight_numbers(insight, investigator, prediction)
    supported_limitations = supported_limitation_claims(insight, investigator)
    supported_evidence = supported_evidence_claims(insight, investigator)
    supported_claims = set(supported_limitations + supported_evidence)
    genuine_unsupported = [claim for claim in insight.unsupported_claims if claim not in supported_claims]
    return {
        "unsupported_numerical_claims": unsupported,
        "unsupported_claims": insight.unsupported_claims,
        "supported_limitations": supported_limitations,
        "supported_evidence_claims": supported_evidence,
        "genuine_unsupported_claims": genuine_unsupported,
        "contradictions": insight.contradictions,
        "semantic_accuracy": "not_proven_by_string_check",
        "review_required": True,
        "valid": not insight.contradictions and not unsupported and not genuine_unsupported,
    }


def insight_report(insight: InsightHandoff, checks: dict[str, Any]) -> dict[str, Any]:
    """Expose the validated prose beside automated checks for human review."""
    return {
        "summary": insight.summary,
        "bullets": insight.bullets,
        "unsupported_claims": insight.unsupported_claims,
        "contradictions": insight.contradictions,
        "automated_checks": checks,
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
