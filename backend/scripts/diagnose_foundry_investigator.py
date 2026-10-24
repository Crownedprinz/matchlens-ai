"""Opt-in, bounded Investigator-only Foundry diagnostic.

This script performs no network call unless --confirm-live is supplied. It
uses the currently configured, explicitly pinned Investigator version and the
same four local FunctionTool bindings as the FastAPI adapter.
"""
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

from app.agents.diagnostics import event, start_request
from app.agents.provenance import agent_context, begin, calls
from app.agents.isolated_diagnostics import parse_investigator_handoff


def _print_tool_summary() -> None:
    summary = [{"tool": call.name, "agent_name": call.agent_name, "agent_version": call.agent_version,
                "argument_keys": sorted(call.arguments), "duration_ms": call.duration_ms,
                "outcome": call.outcome, "output_ids": call.output_ids}
               for call in calls() if call.outcome == "success"]
    print(json.dumps({"successful_python_tools": summary}, separators=(",", ":")))


async def run_once(end_to_end_timeout: float, http_timeout: float, retries: int) -> None:
    from agent_framework.foundry import FoundryAgent
    from azure.identity.aio import AzureCliCredential
    from app.agents.foundry_tools import FOUNDRY_FUNCTIONS

    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    name = os.getenv("FOUNDRY_INVESTIGATOR_NAME", "matchlens-investigator")
    version = os.getenv("FOUNDRY_INVESTIGATOR_VERSION")
    if not endpoint or not version:
        raise SystemExit("FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_INVESTIGATOR_VERSION are required")

    credential = AzureCliCredential()
    try:
        agent = FoundryAgent(
            project_endpoint=endpoint,
            agent_name=name,
            agent_version=version,
            credential=credential,
            timeout=http_timeout,
            tools=[FOUNDRY_FUNCTIONS[tool] for tool in (
                "get_head_to_head", "get_team_form", "get_player_stats", "get_match_context"
            )],
        )
        event("foundry_agent_initialized", role="investigator", agent_name=name, agent_version=version, tool_count=4)
        payload = {
            "match_id": "match-001",
            "minute": 0,
            "question": "Why is the home team favored?",
            "required_output": "JSON InvestigatorHandoff with evidence and missing_information. Evidence IDs must refer to synthetic records.",
        }
        for attempt in range(retries + 1):
            event("agent_invocation_started", agent_name=name, agent_version=version, stage="investigator-diagnostic", attempt=attempt + 1)
            event("sdk_http_request_started", agent_name=name, agent_version=version, stage="investigator-diagnostic", request_kind="agent_run", timeout_seconds=http_timeout)
            sdk_started=time.perf_counter()
            try:
                with agent_context(name, version):
                    result = await asyncio.wait_for(agent.run(json.dumps(payload)), timeout=end_to_end_timeout)
                event("sdk_run_response_received", agent_name=name, agent_version=version, stage="investigator-diagnostic", attempt=attempt + 1, response_type=type(result).__name__)
                event("sdk_http_response_received", agent_name=name, agent_version=version, stage="investigator-diagnostic", request_kind="agent_run", status="sdk_response_received", latency_ms=round((time.perf_counter()-sdk_started)*1000))
                try:
                    handoff = parse_investigator_handoff(getattr(result, "text", result), "match-001")
                except Exception as exc:
                    event("agent_response_validation_failed", agent_name=name, agent_version=version, stage="investigator-diagnostic", failure_class="response_validation", error_type=type(exc).__name__)
                    print(json.dumps({
                        "status": "validation_error",
                        "agent_name": name,
                        "agent_version": version,
                        "validation_error": str(exc),
                        "partial_tool_provenance": [call.model_dump() for call in calls()],
                    }, indent=2))
                    raise SystemExit(1) from exc
                event("final_agent_response_received", agent_name=name, agent_version=version, stage="investigator-diagnostic", attempt=attempt + 1)
                print(json.dumps({
                    "status": "ok",
                    "agent_name": name,
                    "agent_version": version,
                    "evidence": [item.model_dump() for item in handoff.evidence],
                    "missing_information": handoff.missing_information,
                    "evidence_validation": "passed",
                    "python_tool_provenance": [call.model_dump() for call in calls()],
                }, indent=2))
                return
            except Exception as exc:
                event("agent_invocation_failed", agent_name=name, agent_version=version, stage="investigator-diagnostic", attempt=attempt + 1, failure_class="transport_or_tool_or_timeout", error_type=type(exc).__name__, latency_ms=round((time.perf_counter()-sdk_started)*1000))
                if attempt >= retries:
                    raise
    finally:
        await credential.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-live", action="store_true", help="Authorize one or more bounded live Foundry calls")
    parser.add_argument("--timeout", type=float, default=90.0, help="Bounded end-to-end timeout per attempt (default: 90)")
    parser.add_argument("--http-timeout", type=float, default=float(os.getenv("FOUNDRY_TIMEOUT_SECONDS", "60")), help="Foundry SDK HTTP timeout (default: FOUNDRY_TIMEOUT_SECONDS or 60)")
    parser.add_argument("--retries", type=int, default=0, help="Additional attempts after failure (default: 0)")
    args = parser.parse_args()
    if args.timeout <= 0 or args.http_timeout <= 0 or args.retries < 0:
        raise SystemExit("--timeout and --http-timeout must be positive and --retries cannot be negative")
    if not args.confirm_live:
        print("diagnostic not run; pass --confirm-live to authorize a bounded live Foundry call")
        return
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    start_request()
    begin()
    try:
        asyncio.run(run_once(args.timeout, args.http_timeout, args.retries))
    finally:
        _print_tool_summary()


if __name__ == "__main__":
    main()
