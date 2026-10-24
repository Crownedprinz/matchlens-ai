from typing import Any, Literal
from pydantic import BaseModel, Field
from app.models.domain import Forecast
Audience = Literal["fan", "analyst", "fantasy"]
class AnalysisRequest(BaseModel):
    match_id: str = Field(min_length=1, max_length=80); audience: Audience = "fan"; question: str = Field(min_length=3, max_length=500); minute: int = Field(default=0, ge=0, le=90)
class HeadToHeadArgs(BaseModel): match_id: str = Field(min_length=1, max_length=80)
class MatchContextArgs(BaseModel): match_id: str = Field(min_length=1, max_length=80); minute: int = Field(default=0, ge=0, le=90)
class TeamFormArgs(BaseModel): match_id: str = Field(min_length=1, max_length=80); team_side: Literal["home", "away"]
class PlayerStatsArgs(BaseModel): match_id: str = Field(min_length=1, max_length=80); team_side: Literal["home", "away"] | None = None
class PredictionArgs(BaseModel): match_id: str = Field(min_length=1, max_length=80); minute: int = Field(default=0, ge=0, le=90)
class PlayerPredictionArgs(BaseModel): match_id: str = Field(min_length=1, max_length=80); player_id: str = Field(min_length=1, max_length=80)
class ScenarioArgs(BaseModel): match_id: str = Field(min_length=1, max_length=80); minute: int = Field(default=0, ge=0, le=90); home_goals: int = Field(default=0, ge=0, le=20); away_goals: int = Field(default=0, ge=0, le=20)
class ExplanationArgs(BaseModel): match_id: str = Field(min_length=1, max_length=80); minute: int = Field(default=0, ge=0, le=90)
class ToolCall(BaseModel): name: str; agent_name: str | None = None; agent_version: str | None = None; arguments: dict[str, Any] = {}; tool_call_id: str | None = None; duration_ms: int = Field(ge=0); outcome: Literal["success", "error"]; output_ids: list[str] = []; error: str | None = None
class EvidenceItem(BaseModel): record_type: str; record_id: str; statement: str
class InvestigatorHandoff(BaseModel): evidence: list[EvidenceItem]; missing_information: list[str] = []
class PlayerProjection(BaseModel): player_id: str; player_name: str; projected_goals: float; projected_assists: float; basis: str
class PredictionHandoff(BaseModel): forecast: Forecast; player_projections: list[PlayerProjection]; unsupported_scenarios: list[str] = []
class InsightHandoff(BaseModel): summary: str; bullets: list[str]; unsupported_claims: list[str] = []; contradictions: list[str] = []
class AgentExecutionTrace(BaseModel): agent_name: str; agent_version: str; status: Literal["success", "error"]; tool_calls: list[ToolCall] = []; error: str | None = None
class AnalysisResponse(BaseModel):
    status: Literal["ok", "error"]; mode: Literal["mock", "foundry"]; audience: Audience; match_id: str; question: str; investigator: InvestigatorHandoff; predictor: PredictionHandoff; insight: InsightHandoff; tool_calls: list[ToolCall]; traces: list[AgentExecutionTrace] = []; errors: list[str] = []
class FoundryAgentBoundary:
    async def run(self, evidence: InvestigatorHandoff) -> InsightHandoff: raise NotImplementedError("Implement a configured Foundry adapter before calling this boundary")
