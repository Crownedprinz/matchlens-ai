import json
from functools import lru_cache
from pathlib import Path
from fastapi import HTTPException
from app.models.domain import Team, Player, Fixture, HistoricalMeeting, FormResult, MatchEvent
DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "demo.json"
@lru_cache
def data() -> dict:
    if not DATA_PATH.exists(): raise RuntimeError("Synthetic dataset missing. Run python scripts/generate_data.py")
    return json.loads(DATA_PATH.read_text())
def get_fixture(match_id: str) -> Fixture:
    raw = next((x for x in data()["fixtures"] if x["id"] == match_id), None)
    if not raw: raise HTTPException(404, detail=f"Match '{match_id}' not found")
    return Fixture.model_validate(raw)
def team(team_id: str) -> Team: return Team.model_validate(next(x for x in data()["teams"] if x["id"] == team_id))
def players(team_id: str) -> list[Player]: return [Player.model_validate(x) for x in data()["players"] if x["team_id"] == team_id]
def events(match_id: str) -> list[MatchEvent]: return [MatchEvent.model_validate(x) for x in data()["events"] if x["match_id"] == match_id]
def h2h(match_id: str) -> list[HistoricalMeeting]:
    fixture = get_fixture(match_id)
    return [HistoricalMeeting.model_validate(x) for x in data()["h2h"] if {x["home_team_id"], x["away_team_id"]} == {fixture.home_team_id, fixture.away_team_id}]
def form(team_id: str) -> list[FormResult]: return [FormResult.model_validate(x) for x in data()["form"] if x["team_id"] == team_id]
