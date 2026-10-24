"""Opt-in, one-request full Foundry workflow diagnostic."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.agents.contracts import AnalysisRequest
from app.agents.diagnostics import start_request
from app.agents.foundry_workflow import FoundryResponseError, run_foundry


async def run_once(timeout: float, http_timeout: float, validation_retries: int) -> None:
    os.environ["FOUNDRY_END_TO_END_TIMEOUT_SECONDS"] = str(timeout)
    os.environ["FOUNDRY_TIMEOUT_SECONDS"] = str(http_timeout)
    os.environ["FOUNDRY_VALIDATION_RETRIES"] = str(validation_retries)
    request = AnalysisRequest(match_id="match-001", audience="fan", question="Why is the home team favored?", minute=0)
    try:
        response = await run_foundry(request)
    except FoundryResponseError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
        raise SystemExit(1) from exc
    print(json.dumps({
        "status": response.status,
        "mode": response.mode,
        "match_id": response.match_id,
        "agent_versions": {
            "investigator": os.getenv("FOUNDRY_INVESTIGATOR_VERSION"),
            "predictor": os.getenv("FOUNDRY_PREDICTOR_VERSION"),
            "insight": os.getenv("FOUNDRY_INSIGHT_VERSION"),
        },
        "insight": response.insight.model_dump(),
        "tool_calls": [call.model_dump() for call in response.tool_calls],
        "traces": [trace.model_dump() for trace in response.traces],
    }, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--http-timeout", type=float, default=60.0)
    parser.add_argument("--validation-retries", type=int, default=0)
    args = parser.parse_args()
    if not args.confirm_live:
        print("diagnostic not run; pass --confirm-live to authorize one bounded full Foundry workflow")
        return
    if args.timeout <= 0 or args.http_timeout <= 0 or args.validation_retries < 0:
        raise SystemExit("timeouts must be positive and validation retries cannot be negative")
    start_request()
    asyncio.run(run_once(args.timeout, args.http_timeout, args.validation_retries))


if __name__ == "__main__":
    main()
