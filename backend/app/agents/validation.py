import json
from typing import TypeVar
from pydantic import BaseModel, ValidationError
from app.agents.contracts import InvestigatorHandoff, PredictionHandoff, InsightHandoff
from app.repositories.synthetic import get_fixture, h2h, form, players
T=TypeVar("T", bound=BaseModel)
def parse_json(text: str, model: type[T]) -> T:
    try: return model.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc: raise ValueError(f"Invalid {model.__name__} payload: {exc}") from exc
def valid_evidence_ids(match_id: str) -> set[str]:
    fixture=get_fixture(match_id); ids={f"h2h:{match_id}:{i}" for i,_ in enumerate(h2h(match_id))}
    ids |= {f"form:{fixture.home_team_id}:{i}" for i,_ in enumerate(form(fixture.home_team_id))}
    ids |= {f"form:{fixture.away_team_id}:{i}" for i,_ in enumerate(form(fixture.away_team_id))}
    ids |= {f"player:{p.id}" for p in players(fixture.home_team_id)+players(fixture.away_team_id)}
    return ids
def validate_evidence(payload: InvestigatorHandoff, match_id: str) -> InvestigatorHandoff:
    allowed=valid_evidence_ids(match_id); unknown=[item.record_id for item in payload.evidence if item.record_id not in allowed]
    if unknown: raise ValueError(f"Unsupported evidence references: {', '.join(unknown)}")
    return payload
