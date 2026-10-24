"""Version-pinned, validated Foundry Prompt Agent workflow."""
import asyncio, json, os, time
from app.agents.contracts import AnalysisRequest, AnalysisResponse, InvestigatorHandoff, PredictionHandoff, InsightHandoff, AgentExecutionTrace, PredictionArgs
from app.agents import tools
from app.agents.provenance import agent_context, begin, calls, execute
from app.agents.validation import parse_json, validate_evidence
from app.agents.isolated_diagnostics import parse_prediction_handoff
from app.agents.diagnostics import correlation_id, event

class FoundryConfigurationError(RuntimeError): pass
class FoundryResponseError(RuntimeError): pass
def _result_text(result) -> str:
    text=getattr(result,"text",None)
    if isinstance(text,str): return text
    if isinstance(result,str): return result
    raise FoundryResponseError("Foundry agent returned no text")
def _configuration() -> dict[str, dict[str,str] | str]:
    result={"endpoint":os.getenv("FOUNDRY_PROJECT_ENDPOINT","")}
    for role,default in (("investigator","matchlens-investigator"),("predictor","matchlens-predictor"),("insight","matchlens-insight")):
        result[role]={"name":os.getenv(f"FOUNDRY_{role.upper()}_NAME",default),"version":os.getenv(f"FOUNDRY_{role.upper()}_VERSION","")}
    missing=["FOUNDRY_PROJECT_ENDPOINT"] if not result["endpoint"] else []
    missing += [f"FOUNDRY_{role.upper()}_VERSION" for role in ("investigator","predictor","insight") if not result[role]["version"]]
    if missing: raise FoundryConfigurationError(f"Foundry mode requires explicitly resolved values: {', '.join(missing)}")
    return result
def reconcile_forecast(agent_forecast: dict, canonical: dict, tolerance: float = 0.01) -> None:
    for key in ("home_win_probability","draw_probability","away_win_probability","expected_home_goals","expected_away_goals"):
        if key not in agent_forecast or abs(float(agent_forecast[key])-float(canonical[key])) > tolerance: raise FoundryResponseError(f"Predictor forecast mismatch for {key}")
async def _text(agent, payload: dict, model, label: str, agent_name: str, agent_version: str, *, http_timeout: float):
    prompt=json.dumps(payload); last=None
    for attempt in range(2):
        event("agent_invocation_started", agent_name=agent_name, agent_version=agent_version, stage=label, attempt=attempt + 1)
        event("sdk_http_request_started", agent_name=agent_name, agent_version=agent_version, stage=label, request_kind="agent_run", timeout_seconds=http_timeout)
        sdk_started=time.perf_counter()
        try:
            with agent_context(agent_name, agent_version):
                result = await agent.run(prompt)
            event("sdk_run_response_received", agent_name=agent_name, agent_version=agent_version, stage=label, attempt=attempt + 1, response_type=type(result).__name__)
            event("sdk_http_response_received", agent_name=agent_name, agent_version=agent_version, stage=label, request_kind="agent_run", status="sdk_response_received", latency_ms=round((time.perf_counter()-sdk_started)*1000))
        except Exception as exc:
            event("agent_invocation_failed", agent_name=agent_name, agent_version=agent_version, stage=label, attempt=attempt + 1, failure_class="transport_or_tool", error_type=type(exc).__name__, latency_ms=round((time.perf_counter()-sdk_started)*1000))
            raise FoundryResponseError(f"{label} invocation failed (correlation_id={correlation_id()}): {type(exc).__name__}: {exc}") from exc
        try:
            parsed = model(_result_text(result))
        except (ValueError, TypeError) as exc:
            last=exc
            event("agent_response_validation_failed", agent_name=agent_name, agent_version=agent_version, stage=label, attempt=attempt + 1, failure_class="response_validation", error_type=type(exc).__name__)
            if attempt == 0:
                prompt=json.dumps({"correction":"Previous output failed validation. Return JSON only matching the required schema; do not add prose.","original":payload})
                continue
            break
        event("final_agent_response_received", agent_name=agent_name, agent_version=agent_version, stage=label, attempt=attempt + 1)
        return parsed
    raise FoundryResponseError(f"{label} structured response failed after one retry (correlation_id={correlation_id()}): {last}")
async def _run_foundry(request: AnalysisRequest) -> AnalysisResponse:
    cfg=_configuration()
    try:
        from agent_framework.foundry import FoundryAgent
        from azure.identity.aio import AzureCliCredential
    except ImportError as exc: raise FoundryConfigurationError("Install requirements-foundry.txt to use AGENT_MODE=foundry") from exc
    from app.agents.foundry_tools import FOUNDRY_FUNCTIONS
    http_timeout=float(os.getenv("FOUNDRY_TIMEOUT_SECONDS","60"))
    credential=AzureCliCredential(); common={"project_endpoint":cfg["endpoint"],"credential":credential,"timeout":http_timeout}
    def make(role):
        item=cfg[role]; tool_names={"investigator":["get_head_to_head","get_team_form","get_player_stats","get_match_context"],"predictor":["predict_match","predict_player","get_model_explanation"],"insight":[]}[role]
        agent = FoundryAgent(**common,agent_name=item["name"],agent_version=item["version"],tools=[FOUNDRY_FUNCTIONS[name] for name in tool_names])
        event("foundry_agent_initialized", role=role, agent_name=item["name"], agent_version=item["version"], tool_count=len(tool_names), timeout_seconds=common["timeout"])
        return agent
    investigator,predictor,insight=make("investigator"),make("predictor"),make("insight"); begin()
    try:
        inv_payload={"match_id":request.match_id,"minute":request.minute,"question":request.question,"required_output":"JSON InvestigatorHandoff with evidence and missing_information. Evidence IDs must refer to synthetic records."}
        inv=validate_evidence(await _text(investigator,inv_payload,lambda text:parse_json(text,InvestigatorHandoff),"investigator",cfg["investigator"]["name"],cfg["investigator"]["version"],http_timeout=http_timeout),request.match_id)
        event("agent_handoff_completed", from_agent=cfg["investigator"]["name"], to_agent=cfg["predictor"]["name"])
        canonical=execute("predict_match",tools.predict_match,PredictionArgs(match_id=request.match_id,minute=request.minute).model_dump(),agent_name=cfg["predictor"]["name"],agent_version=cfg["predictor"]["version"])
        pred_payload={"match_id":request.match_id,"minute":request.minute,"investigator":inv.model_dump(),"canonical_python_forecast":canonical,"required_output":"JSON PredictionHandoff. Preserve canonical forecast values exactly; unsupported_scenarios must be explicit."}
        pred=await _text(predictor,pred_payload,parse_prediction_handoff,"predictor",cfg["predictor"]["name"],cfg["predictor"]["version"],http_timeout=http_timeout)
        reconcile_forecast(pred.forecast.model_dump(),canonical)
        event("agent_handoff_completed", from_agent=cfg["predictor"]["name"], to_agent=cfg["insight"]["name"])
        ins_payload={"audience":request.audience,"question":request.question,"investigator":inv.model_dump(),"prediction":pred.model_dump(),"required_output":"JSON InsightHandoff with summary, bullets, unsupported_claims, contradictions. Do not add statistics."}
        ins=await _text(insight,ins_payload,lambda text:parse_json(text,InsightHandoff),"insight",cfg["insight"]["name"],cfg["insight"]["version"],http_timeout=http_timeout)
        traces=[AgentExecutionTrace(agent_name=cfg[role]["name"],agent_version=cfg[role]["version"],status="success",tool_calls=[call for call in calls() if call.agent_name==cfg[role]["name"]]) for role in ("investigator","predictor","insight")]
        return AnalysisResponse(status="ok",mode="foundry",audience=request.audience,match_id=request.match_id,question=request.question,investigator=inv,predictor=pred,insight=ins,tool_calls=calls(),traces=traces)
    except (ValueError, FoundryResponseError) as exc: raise FoundryResponseError(str(exc)) from exc
    finally: await credential.close()

async def run_foundry(request: AnalysisRequest) -> AnalysisResponse:
    """Run the workflow under an application deadline independent of HTTP timeout."""
    end_to_end_timeout=float(os.getenv("FOUNDRY_END_TO_END_TIMEOUT_SECONDS", "120"))
    if end_to_end_timeout <= 0:
        raise FoundryConfigurationError("FOUNDRY_END_TO_END_TIMEOUT_SECONDS must be positive")
    event("foundry_end_to_end_timeout_configured", timeout_seconds=end_to_end_timeout)
    try:
        return await asyncio.wait_for(_run_foundry(request), timeout=end_to_end_timeout)
    except asyncio.TimeoutError as exc:
        event("foundry_end_to_end_timeout", timeout_seconds=end_to_end_timeout)
        raise FoundryResponseError(f"Foundry end-to-end timeout after {end_to_end_timeout:g}s (correlation_id={correlation_id()})") from exc
