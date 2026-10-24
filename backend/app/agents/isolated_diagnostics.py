"""Shared, offline-testable inputs and validation for isolated Foundry checks."""
from __future__ import annotations

import re
from typing import Any

from app.agents.contracts import EvidenceItem, InsightHandoff, InvestigatorHandoff, PredictionHandoff
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


def unsupported_insight_numbers(insight: InsightHandoff, prediction: PredictionHandoff) -> list[str]:
    """Return numeric claims not present in the validated prediction payload."""
    source_numbers = {token.rstrip("%") for token in re.findall(r"\d+(?:\.\d+)?%?", prediction.model_dump_json())}
    claims = " ".join([insight.summary, *insight.bullets])
    return [token for token in re.findall(r"\d+(?:\.\d+)?%?", claims) if token.rstrip("%") not in source_numbers]


def insight_check(insight: InsightHandoff, prediction: PredictionHandoff) -> dict[str, Any]:
    return {
        "unsupported_numerical_claims": unsupported_insight_numbers(insight, prediction),
        "contradictions": insight.contradictions,
        "valid": not insight.contradictions and not unsupported_insight_numbers(insight, prediction),
    }
