from fastapi import APIRouter, Query, HTTPException, Request
from app.agents.contracts import AnalysisRequest, AnalysisResponse
from app.agents.service import run_analysis
from app.agents.foundry_workflow import FoundryConfigurationError, FoundryResponseError
from app.models.domain import MatchSummary, MatchDetail
from app.repositories.synthetic import data, get_fixture, team, players, h2h, form, events
from app.forecasting.poisson import forecast
from app.agents.diagnostics import event, start_request
router = APIRouter(prefix="/api")
def summary(fixture): return MatchSummary(id=fixture.id, home_team=team(fixture.home_team_id), away_team=team(fixture.away_team_id), date=fixture.date, status=fixture.status, home_score=fixture.home_score, away_score=fixture.away_score, venue=fixture.venue)
@router.get("/health")
def health(): return {"status":"ok", "dataset":"synthetic", "version":"phase-1"}
@router.get("/matches", response_model=list[MatchSummary])
def matches(): return [summary(get_fixture(x["id"])) for x in data()["fixtures"]]
@router.get("/matches/{match_id}", response_model=MatchDetail)
def match(match_id: str):
    fixture = get_fixture(match_id); return MatchDetail(**summary(fixture).model_dump(), home_starters=players(fixture.home_team_id), away_starters=players(fixture.away_team_id))
@router.get("/matches/{match_id}/h2h")
def match_h2h(match_id: str): get_fixture(match_id); return h2h(match_id)
@router.get("/matches/{match_id}/form")
def match_form(match_id: str):
    fixture = get_fixture(match_id); return {"home": form(fixture.home_team_id), "away": form(fixture.away_team_id)}
@router.get("/matches/{match_id}/players")
def match_players(match_id: str):
    fixture = get_fixture(match_id); return {"home": players(fixture.home_team_id), "away": players(fixture.away_team_id)}
@router.get("/matches/{match_id}/forecast")
def match_forecast(match_id: str, minute: int = Query(0, ge=0, le=90)): return forecast(match_id, minute)
@router.get("/matches/{match_id}/events")
def match_events(match_id: str): get_fixture(match_id); return events(match_id)
@router.post("/analysis", response_model=AnalysisResponse)
async def analysis(request: Request, payload: AnalysisRequest):
    correlation = start_request(request.headers.get("x-correlation-id"))
    event("api_request_received", route="/api/analysis", method="POST")
    try:
        result = await run_analysis(payload)
        event("api_request_completed", status="success")
        return result
    except FoundryConfigurationError as exc:
        event("api_request_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except FoundryResponseError as exc:
        event("api_request_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        event("api_request_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
