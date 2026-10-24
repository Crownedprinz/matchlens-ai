"""Safely preview or create a new Insight Prompt Agent version."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.register_foundry_tools import repair_insight_instructions, snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    name = os.getenv("FOUNDRY_INSIGHT_NAME", "matchlens-insight")
    source_version = os.getenv("FOUNDRY_INSIGHT_VERSION")
    if not endpoint or not source_version:
        raise SystemExit("FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_INSIGHT_VERSION are required")
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import PromptAgentDefinition
    from azure.identity import DefaultAzureCredential

    project = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
    try:
        existing = snapshot(project.agents.get_version(name, source_version), name, source_version)
        if existing["version"] != source_version:
            raise RuntimeError(f"Requested source version {source_version}, inspected {existing['version']}")
        revised = repair_insight_instructions(existing["instructions"] or "")
        if revised == existing["instructions"]:
            raise RuntimeError("Insight instructions are already corrected; refusing duplicate version")
        definition_payload = dict(existing["definition"])
        definition_payload["model"] = existing["model"]
        definition_payload["instructions"] = revised
        definition_payload["tools"] = []
        print(json.dumps({"mode": "apply" if args.apply else "dry-run", "source": {"name": name, "version": source_version}, "proposed": {"model": existing["model"], "tool_count": 0, "instructions_changed": True}, "preserved": {"tools": existing["tools"] == [], "other_definition_fields": sorted(key for key in existing["definition"] if key not in {"instructions", "tools"})}, "remote_mutation": bool(args.apply)}, indent=2))
        if not args.apply:
            print("dry-run complete; no remote mutation performed")
            return
        created = project.agents.create_version(agent_name=name, definition=PromptAgentDefinition(**definition_payload))
        print(json.dumps({"created_agent": name, "created_version": getattr(created, "version", "<unknown>")}, indent=2))
    finally:
        close = getattr(project, "close", None)
        if close:
            close()


if __name__ == "__main__":
    main()
