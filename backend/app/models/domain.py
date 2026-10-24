from typing import Literal
from pydantic import BaseModel, Field
EventType = Literal["Pass", "Shot", "Goal", "Assist", "Tackle", "Possession change", "Pressure", "Substitution", "Red card"]
class Team(BaseModel):
    id: str; name: str; short_name: str; color: str; city: str
class Player(BaseModel):
    id: str; name: str; team_id: str; position: str; number: int; minutes: int; goals: int; assists: int; shots: int; key_passes: int; tackles: int; pressures: int
class Fixture(BaseModel):
    id: str; home_team_id: str; away_team_id: str; date: str; status: str; home_score: int; away_score: int; venue: str
class HistoricalMeeting(BaseModel):
    date: str; home_team_id: str; away_team_id: str; home_score: int; away_score: int
class FormResult(BaseModel):
    team_id: str; date: str; opponent: str; venue: Literal["H", "A"]; score: str; outcome: Literal["W", "D", "L"]; goals_for: int; goals_against: int
class MatchEvent(BaseModel):
    id: str; match_id: str; minute: int = Field(ge=0, le=90); event_type: EventType; team_id: str; player_id: str; related_player_id: str | None = None; description: str
class Scoreline(BaseModel):
    home: int; away: int; probability: float
class Forecast(BaseModel):
    minute: int; current_home_score: int; current_away_score: int; expected_home_goals: float; expected_away_goals: float; home_win_probability: float; draw_probability: float; away_win_probability: float; most_likely_scores: list[Scoreline]; explanation: list[str]
class MatchSummary(BaseModel):
    id: str; home_team: Team; away_team: Team; date: str; status: str; home_score: int; away_score: int; venue: str
class MatchDetail(MatchSummary):
    home_starters: list[Player]; away_starters: list[Player]
