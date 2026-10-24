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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.agents.diagnostics import event, start_request


async def run_once(timeout: float, retries: int) -> None:
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
            timeout=timeout,
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
            try:
                result = await asyncio.wait_for(agent.run(json.dumps(payload)), timeout=timeout)
                event("remote_response_received", agent_name=name, agent_version=version, stage="investigator-diagnostic", attempt=attempt + 1, response_type=type(result).__name__)
                print(getattr(result, "text", result))
                event("final_agent_response_received", agent_name=name, agent_version=version, stage="investigator-diagnostic", attempt=attempt + 1)
                return
            except Exception as exc:
                event("agent_invocation_failed", agent_name=name, agent_version=version, stage="investigator-diagnostic", attempt=attempt + 1, error_type=type(exc).__name__)
                if attempt >= retries:
                    raise
    finally:
        await credential.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-live", action="store_true", help="Authorize one or more bounded live Foundry calls")
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-attempt timeout in seconds (default: 30)")
    parser.add_argument("--retries", type=int, default=0, help="Additional attempts after failure (default: 0)")
    args = parser.parse_args()
    if args.timeout <= 0 or args.retries < 0:
        raise SystemExit("--timeout must be positive and --retries cannot be negative")
    if not args.confirm_live:
        print("diagnostic not run; pass --confirm-live to authorize a bounded live Foundry call")
        return
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    start_request()
    asyncio.run(run_once(args.timeout, args.retries))


if __name__ == "__main__":
    main()
