"""Opt-in, Insight-only Foundry diagnostic; never runs without --confirm-live."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.agents import tools
from app.agents.contracts import AnalysisRequest, InsightHandoff, PlayerPredictionArgs, PredictionArgs, PredictionHandoff
from app.agents.diagnostics import event, start_request
from app.agents.foundry_workflow import FoundryResponseError, _result_text
from app.agents.isolated_diagnostics import build_investigator_handoff, insight_check, insight_report
from app.agents.provenance import agent_context, begin, calls, execute
from app.agents.validation import parse_json, validate_evidence


async def run_once(end_to_end_timeout: float, http_timeout: float) -> None:
    from agent_framework.foundry import FoundryAgent
    from azure.identity.aio import AzureCliCredential

    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    name = os.getenv("FOUNDRY_INSIGHT_NAME", "matchlens-insight")
    version = os.getenv("FOUNDRY_INSIGHT_VERSION")
    if not endpoint or not version:
        raise SystemExit("FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_INSIGHT_VERSION are required")
    request = AnalysisRequest(match_id="match-001", audience="fan", question="Why is the home team favored?", minute=0)
    investigator = validate_evidence(build_investigator_handoff(request.match_id), request.match_id)
    canonical = execute("predict_match", tools.predict_match, PredictionArgs(match_id=request.match_id, minute=request.minute).model_dump(), agent_name="local-python-preparation", agent_version="local")
    players_data = tools.get_player_stats({"match_id": request.match_id, "team_side": None})["players"]
    projections = [execute("predict_player", tools.predict_player, PlayerPredictionArgs(match_id=request.match_id, player_id=row["id"]).model_dump(), agent_name="local-python-preparation", agent_version="local") for row in sorted(players_data, key=lambda row: (row["goals"], row["assists"], row["key_passes"]), reverse=True)[:3]]
    prediction = PredictionHandoff(forecast=canonical, player_projections=projections)
    payload = {"audience": request.audience, "question": request.question, "investigator": investigator.model_dump(), "prediction": prediction.model_dump(), "required_output": "JSON InsightHandoff with summary, bullets, unsupported_claims, contradictions. Do not add statistics."}
    credential = AzureCliCredential()
    try:
        agent = FoundryAgent(project_endpoint=endpoint, agent_name=name, agent_version=version, credential=credential, timeout=http_timeout, tools=[])
        event("foundry_agent_initialized", role="insight", agent_name=name, agent_version=version, tool_count=0, timeout_seconds=http_timeout)
        event("agent_invocation_started", agent_name=name, agent_version=version, stage="insight-diagnostic", attempt=1)
        started = time.perf_counter()
        try:
            with agent_context(name, version):
                result = await asyncio.wait_for(agent.run(json.dumps(payload)), timeout=end_to_end_timeout)
        except Exception as exc:
            event("agent_invocation_failed", agent_name=name, agent_version=version, stage="insight-diagnostic", failure_class="transport_or_timeout", error_type=type(exc).__name__, latency_ms=round((time.perf_counter() - started) * 1000))
            raise FoundryResponseError(f"insight invocation failed: {type(exc).__name__}: {exc}") from exc
        insight = parse_json(_result_text(result), InsightHandoff)
        checks = insight_check(insight, investigator, prediction)
        print(json.dumps({"status": "review_required" if checks["valid"] else "validation_warning", "agent_name": name, "agent_version": version, "returned_insight": insight_report(insight, checks), "preparation_tool_calls": [call.model_dump() for call in calls() if call.agent_name == "local-python-preparation"], "agent_tool_calls": [call.model_dump() for call in calls() if call.agent_name == name and call.agent_version == version]}, indent=2))
    finally:
        await credential.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--timeout", type=float, default=90.0, help="End-to-end timeout in seconds")
    parser.add_argument("--http-timeout", type=float, default=float(os.getenv("FOUNDRY_TIMEOUT_SECONDS", "60")))
    args = parser.parse_args()
    if not args.confirm_live:
        print("diagnostic not run; pass --confirm-live to authorize one bounded live Foundry call")
        return
    if args.timeout <= 0 or args.http_timeout <= 0:
        raise SystemExit("--timeout and --http-timeout must be positive")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    start_request(); begin()
    asyncio.run(run_once(args.timeout, args.http_timeout))


if __name__ == "__main__":
    main()
