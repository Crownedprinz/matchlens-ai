import os
import time
from collections import defaultdict, deque
from fastapi import APIRouter, Query, HTTPException, Request
from app.agents.contracts import AnalysisRequest, AnalysisResponse, FoundryAccessRequest
from app.agents.service import run_analysis
from app.agents.foundry_workflow import FoundryConfigurationError, FoundryResponseError
from app.models.domain import MatchSummary, MatchDetail
from app.repositories.synthetic import data, get_fixture, team, players, h2h, form, events
from app.forecasting.poisson import forecast
from app.agents.diagnostics import event, start_request
from app.public_access import PublicAccessError, reserve_foundry_attempt, supported_public_match, verify_access_guid
router = APIRouter(prefix="/api")
_analysis_requests: dict[str, deque[float]] = defaultdict(deque)
def _check_analysis_limit(request: Request) -> None:
    limit = int(os.getenv("ANALYSIS_RATE_LIMIT_PER_MINUTE", "12"))
    if limit <= 0: return
    key = request.client.host if request.client else "unknown"
    now = time.monotonic(); window = _analysis_requests[key]
    while window and now - window[0] >= 60: window.popleft()
    if len(window) >= limit: raise HTTPException(status_code=429, detail="Analysis rate limit reached; try again shortly.")
    window.append(now)
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
@router.post("/foundry/access")
async def foundry_access(payload: FoundryAccessRequest):
    try:
        verify_access_guid(payload.access_guid)
        return {"enabled": True, "message": "Microsoft Foundry Live access enabled for this session."}
    except PublicAccessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
@router.post("/analysis", response_model=AnalysisResponse)
async def analysis(request: Request, payload: AnalysisRequest):
    _check_analysis_limit(request)
    correlation = start_request(request.headers.get("x-correlation-id"))
    event("api_request_received", route="/api/analysis", method="POST")
    try:
        if payload.mode == "foundry":
            verify_access_guid(payload.access_guid)
            if not supported_public_match(payload.match_id):
                raise HTTPException(status_code=400, detail="Microsoft Foundry Live is currently limited to the verified match fixture.")
            with reserve_foundry_attempt():
                result = await run_analysis(payload)
        else:
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
    except PublicAccessError as exc:
        event("public_foundry_request_rejected", status_code=exc.status_code)
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
