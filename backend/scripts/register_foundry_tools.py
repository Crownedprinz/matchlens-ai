"""Inspect, diff, and optionally version existing Foundry Prompt Agents.

Default mode is a read-only dry run. The script refuses to construct an apply
payload until the current agent definition has been retrieved and its model,
instructions, version, and existing tools have been captured.
"""
import argparse, json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agents.contracts import HeadToHeadArgs, TeamFormArgs, PlayerStatsArgs, MatchContextArgs, PredictionArgs, PlayerPredictionArgs, ExplanationArgs
from app.agents.schema import normalize_foundry_schema

AGENTS = {
    "investigator": {"env_name":"FOUNDRY_INVESTIGATOR_NAME", "env_version":"FOUNDRY_INVESTIGATOR_VERSION", "default_name":"matchlens-investigator", "tools":["get_head_to_head","get_team_form","get_player_stats","get_match_context"]},
    "predictor": {"env_name":"FOUNDRY_PREDICTOR_NAME", "env_version":"FOUNDRY_PREDICTOR_VERSION", "default_name":"matchlens-predictor", "tools":["predict_match","predict_player","get_model_explanation"]},
    "insight": {"env_name":"FOUNDRY_INSIGHT_NAME", "env_version":"FOUNDRY_INSIGHT_VERSION", "default_name":"matchlens-insight", "tools":[]},
}
MODELS = {"get_head_to_head":HeadToHeadArgs,"get_team_form":TeamFormArgs,"get_player_stats":PlayerStatsArgs,"get_match_context":MatchContextArgs,"predict_match":PredictionArgs,"predict_player":PlayerPredictionArgs,"get_model_explanation":ExplanationArgs}
SUPPORTED_TOOL_NAMES = tuple(MODELS)

# These are intentionally structured declarations rather than names inferred
# from prompt text.  The declarations are the source of truth for registration
# and for checking that an agent's instructions advertise only executable
# tools.  A prompt may mention an unavailable tool as a prohibition.
PROHIBITED_MENTION_PATTERNS = (
    r"\b(?:not|never|do not|don't|must not|cannot|can't|unavailable|unsupported|excluded|omit)\b",
    r"\bnot\s+(?:currently\s+)?available\b",
    r"\bnot\s+supported\b",
)

def tool_schema(name: str) -> dict:
    schema = normalize_foundry_schema(MODELS[name].model_json_schema())
    return {"type":"function", "name":name, "description":f"MatchLens synthetic football tool: {name}.", "parameters":schema, "strict":True}

def config_from_env() -> dict:
    result = {"endpoint":os.getenv("FOUNDRY_PROJECT_ENDPOINT", ""), "model":os.getenv("FOUNDRY_MODEL", "gpt-5-mini")}
    for role, item in AGENTS.items():
        result[role] = {"name":os.getenv(item["env_name"], item["default_name"]), "version":os.getenv(item["env_version"], "")}
    return result

def _get(obj, *names, default=None):
    for name in names:
        value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
        if value is not None: return value
    return default
def _mapping(obj) -> dict:
    if isinstance(obj, dict): return obj
    if hasattr(obj, "as_dict"): return obj.as_dict()
    if hasattr(obj, "model_dump"): return obj.model_dump()
    return {}

def snapshot(record, requested_name: str, requested_version: str) -> dict:
    versions = _get(record, "versions")
    version_obj = _get(record, "version", "latest") or (_get(versions, "latest") if versions else None)
    definition = _get(version_obj, "definition") or _get(record, "definition") or {}
    definition_dict = _mapping(definition)
    tools = definition_dict.get("tools", []) or []
    extras = {key:value for key,value in definition_dict.items() if key not in {"model","instructions","tools"}}
    return {"name":_get(record,"name",default=requested_name), "version":_get(version_obj,"version",default=requested_version), "model":definition_dict.get("model"), "instructions":definition_dict.get("instructions"), "tools":tools, "other_config":extras, "definition":definition_dict, "raw":record}

def required_snapshot_fields(agent: dict) -> list[str]: return [key for key in ("name","version","model","instructions") if not agent.get(key)]

def proposed(existing: dict, role: str) -> dict:
    desired = dict(existing)
    existing_tools = list(existing.get("tools") or [])
    preserved = [tool for tool in existing_tools if not isinstance(tool, dict) or not tool.get("name")]
    by_name = {tool.get("name"):tool for tool in existing_tools if isinstance(tool, dict) and tool.get("name")}
    for name in AGENTS[role]["tools"]: by_name[name] = tool_schema(name)
    desired["tools"] = preserved + list(by_name.values())
    return desired

def diff(existing: dict, desired: dict) -> list[str]:
    lines=[]
    for key in ("name","version","model","instructions","tools","other_config"):
        if existing.get(key) != desired.get(key):
            lines.append(f"  {key}: {'UNCHANGED' if existing.get(key)==desired.get(key) else 'PRESERVE' if key in {'model','instructions'} else 'UPDATE'}")
            if key == "tools": lines.append(f"    existing={len(existing.get(key) or [])} proposed={len(desired.get(key) or [])}")
    if not lines: lines.append("  no changes")
    return lines

def _instruction_sentences(instructions: str) -> list[tuple[int, int, str]]:
    """Return sentence-ish spans while retaining offsets for each tool mention."""
    import re
    return [(match.start(), match.end(), match.group(0)) for match in re.finditer(r"[^.!?\n]+[.!?]?", instructions)]

def _is_prohibited_mention(instructions: str, start: int, end: int) -> bool:
    """Treat explicit unavailable/prohibited mentions as non-advertisements."""
    import re
    for sentence_start, sentence_end, sentence in _instruction_sentences(instructions):
        if sentence_start <= start < sentence_end:
            # Limit the context to the sentence. This avoids allowing a
            # prohibition in one sentence to mask an executable tool in the
            # next sentence.
            before = instructions[sentence_start:start]
            after = instructions[end:sentence_end]
            context = f"{before} {after}"
            return any(re.search(pattern, context, flags=re.IGNORECASE) for pattern in PROHIBITED_MENTION_PATTERNS)
    return False

def instruction_warnings(existing: dict, role: str) -> list[str]:
    import re
    instructions=existing.get("instructions","") or ""; warnings=[]
    configured={tool.get("name") for tool in existing.get("tools",[]) if isinstance(tool,dict)} | set(AGENTS[role]["tools"])
    for name in sorted(set(SUPPORTED_TOOL_NAMES) | {"simulate_scenario"}):
        for match in re.finditer(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", instructions, flags=re.IGNORECASE):
            if not _is_prohibited_mention(instructions, match.start(), match.end()) and name not in configured:
                warnings.append(f"instructions advertise {name}, but it is not in the preserved/proposed tool definitions")
                break
    return warnings

def print_proposed_configuration(existing: dict, desired: dict, role: str) -> None:
    """Print the exact read-only payload delta and preserved fields."""
    new_tools = [tool for tool in desired["tools"] if tool not in existing.get("tools", [])]
    print("  model: PRESERVED")
    print(f"    {existing['model']}")
    print("  instructions: PRESERVED (exact text)")
    print(json.dumps(existing["instructions"], indent=4, ensure_ascii=False))
    print("  existing tools: PRESERVED")
    print(json.dumps(existing.get("tools", []), indent=4, ensure_ascii=False, default=str))
    print("  new/updated MatchLens tool definitions:")
    print(json.dumps(new_tools, indent=4, ensure_ascii=False, default=str))
    preserved_keys = sorted(key for key in existing.get("definition", {}) if key not in {"tools"})
    print(f"  complete definition preserved: yes (all definition keys except tools: {preserved_keys})")

def repair_investigator_instructions(instructions: str) -> str:
    """Align legacy Investigator signature examples with registered schemas."""
    replacements = {
        "get_head_to_head(home_team, away_team, limit)": "get_head_to_head(match_id)",
        "get_team_form(team, limit)": "get_team_form(match_id, team_side)",
        "get_player_stats(team, limit)": "get_player_stats(match_id, team_side)",
    }
    repaired = instructions
    for old, new in replacements.items():
        repaired = repaired.replace(old, new)
    return repaired

def client():
    try:
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential
    except ImportError as exc: raise SystemExit("Install requirements-foundry.txt for Foundry inspection") from exc
    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    if not endpoint: raise SystemExit("FOUNDRY_PROJECT_ENDPOINT is required for inspection")
    return AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())

def inspect_agents(project, config: dict) -> dict:
    snapshots={}
    for role, item in AGENTS.items():
        record = project.agents.get_version(config[role]["name"], config[role]["version"]) if config[role]["version"] else project.agents.get(config[role]["name"])
        snapshots[role] = snapshot(record, config[role]["name"], config[role]["version"])
        missing=required_snapshot_fields(snapshots[role])
        if missing: raise RuntimeError(f"Cannot safely preserve {role}: missing {', '.join(missing)}")
    return snapshots

def main():
    parser=argparse.ArgumentParser(); group=parser.add_mutually_exclusive_group(); group.add_argument("--inspect",action="store_true"); group.add_argument("--dry-run",action="store_true"); group.add_argument("--apply",action="store_true"); group.add_argument("--repair-signatures",action="store_true"); args=parser.parse_args()
    mode="repair-signatures" if args.repair_signatures else "apply" if args.apply else "inspect" if args.inspect else "dry-run"; cfg=config_from_env(); print(f"mode={mode} endpoint={cfg['endpoint'] or '<unset>'}")
    for role in AGENTS: print(f"{role}: name={cfg[role]['name']} version={cfg[role]['version'] or '<must resolve from Foundry>'} tools={AGENTS[role]['tools']}")
    project=client()
    try:
        existing=inspect_agents(project,cfg)
        if args.repair_signatures:
            investigator = existing["investigator"]
            repaired = repair_investigator_instructions(investigator["instructions"] or "")
            if repaired == investigator["instructions"]:
                print("investigator instructions already match the registered signatures; no remote mutation performed")
                return
            print("investigator instructions: UPDATE signature examples only")
            print("  model: PRESERVED")
            print("  tools: PRESERVED (4 registered function definitions)")
            print("  all other definition fields: PRESERVED")
            from azure.ai.projects.models import PromptAgentDefinition, FunctionTool
            tools=[FunctionTool(name=t["name"], description=t.get("description", ""), parameters=t["parameters"], strict=True) for t in investigator["tools"]]
            definition_payload=dict(investigator["definition"])
            definition_payload["instructions"] = repaired
            definition_payload["tools"] = tools
            created=project.agents.create_version(agent_name=investigator["name"], definition=PromptAgentDefinition(**definition_payload))
            print(f"created {investigator['name']} version {getattr(created, 'version', '<unknown>')}")
            return
        if args.apply:
            for role in AGENTS:
                if not cfg[role]["version"]: raise RuntimeError(f"--apply requires {AGENTS[role]['env_version']} and will not guess latest")
                if cfg[role]["version"] != existing[role]["version"]: raise RuntimeError(f"{role} version mismatch: requested {cfg[role]['version']} but inspected {existing[role]['version']}")
        if mode == "inspect":
            for role, snap in existing.items(): print(json.dumps({k:v for k,v in snap.items() if k != "raw"}, indent=2, default=str))
            return
        desired={role:proposed(snap,role) for role,snap in existing.items()}
        for role in AGENTS:
            print(f"\n[{role}] {existing[role]['name']} version {existing[role]['version']}")
            print("existing → proposed"); print("\n".join(diff(existing[role],desired[role])))
            print_proposed_configuration(existing[role], desired[role], role)
            for warning in instruction_warnings(existing[role],role): print(f"  WARNING: {warning}")
            if existing[role]["instructions"] != desired[role]["instructions"] or existing[role]["model"] != desired[role]["model"]: raise RuntimeError(f"Unexpected protected-field change for {role}")
            if args.apply and instruction_warnings(existing[role],role): raise RuntimeError(f"Cannot apply {role}: preserved instructions advertise unsupported or unregistered tools")
        print("\nRollback: retain the recorded versions above and point each *_VERSION variable back to the prior version; no versions are deleted.")
        if not args.apply: print("dry-run complete; no remote mutation performed"); return
        from azure.ai.projects.models import PromptAgentDefinition, FunctionTool
        for role, item in AGENTS.items():
            if desired[role] == existing[role]:
                print(f"skipped {existing[role]['name']}: no proposed changes")
                continue
            tools=[FunctionTool(name=t["name"], description=t.get("description",""), parameters=t["parameters"], strict=True) for t in desired[role]["tools"]]
            definition_payload=dict(existing[role]["definition"]); definition_payload["model"]=existing[role]["model"]; definition_payload["instructions"]=existing[role]["instructions"]; definition_payload["tools"]=tools
            definition=PromptAgentDefinition(**definition_payload)
            created=project.agents.create_version(agent_name=existing[role]["name"], definition=definition)
            print(f"created {existing[role]['name']} version {getattr(created,'version','<unknown>')}")
    finally:
        close=getattr(project,"close",None)
        if close: close()
if __name__ == "__main__": main()
