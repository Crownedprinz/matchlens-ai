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

def repair_investigator_output_instructions(instructions: str) -> str:
    """Replace only the legacy Investigator output contract."""
    import re
    start = instructions.find("# Output")
    if start < 0:
        raise ValueError("Investigator instructions do not contain the expected output section")
    suffix_match = re.search(r"\n# (?!Output(?: Format)?\b)", instructions[start + len("# Output"):])
    suffix = instructions[start + len("# Output") + suffix_match.start() + 1:] if suffix_match else ""
    replacement = '''# Output Format

Return exactly one valid JSON object containing exactly these two top-level keys:

- evidence
- missing_information

The response must conform to the MatchLens AI backend's `InvestigatorHandoff` contract.

## evidence

An array of grounded evidence objects. Every object must contain exactly these three string fields:

- record_type
- record_id
- statement

Use only records returned by the registered Python tools or explicitly supplied in the request. Every `record_id` must be copied exactly from an actual synthetic record and must use the repository's existing ID format. For match-001, return meaningful evidence when the registered tools provide it. Never invent records, IDs, players, results, statistics, or source references. If a record cannot be verified, omit it and explain the limitation in `missing_information`.

## missing_information

An array of strings describing genuine missing, unavailable, or unverifiable information. Preserve relevant data-quality limitations here rather than creating placeholder evidence.

# Strict Output Requirements

1. Return valid JSON only, without Markdown fences, introductory text, or commentary.
2. Include exactly `evidence` and `missing_information` at the top level; do not add any other keys.
3. `evidence` must be an array of objects with exactly `record_type`, `record_id`, and `statement`, all nonempty strings.
4. `missing_information` must be an array of strings.
5. Do not output legacy fields such as status, data_quality, match_id, teams, headline, key_findings, limitations, evidence_references, or any other extra fields.
6. Ground every evidence statement in an actual authorized synthetic record and preserve its exact record identifier.
7. Treat all hackathon records as synthetic and report uncertainty or missing data instead of guessing.

# Core Principle

The MatchLens Investigator provides trustworthy, evidence-grounded synthetic football records for downstream agents; it does not create predictions or unsupported facts.
'''
    return instructions[:start] + replacement + ("\n" + suffix if suffix else "")

def repair_predictor_instructions(instructions: str) -> str:
    """Return a read-only corrected prompt with the local PredictionHandoff contract."""
    start = instructions.find("# Output Format")
    end = instructions.find("# Core Principle", start)
    if start < 0 or end < 0:
        raise ValueError("Predictor instructions do not contain the expected output sections")
    replacement = '''# Output Format

Return exactly one JSON object with exactly these three top-level keys:

- forecast
- player_projections
- unsupported_scenarios

The response must not contain status, match_id, model_version, forecast_timestamp, scoreline_probabilities, scenario_comparisons, model_drivers, uncertainty, evidence_references, or any other top-level keys.

`forecast` must be the complete, unmodified result returned by `predict_match`, including:

- minute
- current_home_score
- current_away_score
- expected_home_goals
- expected_away_goals
- home_win_probability
- draw_probability
- away_win_probability
- most_likely_scores, as an array of objects with home, away, and probability
- explanation, as the returned array of strings

`player_projections` must be an array of complete, unmodified `predict_player` results. Every item must contain exactly these five fields: player_id, player_name, projected_goals, projected_assists, and basis. The basis field is required and must be copied from the tool result. If no supported player projection was requested or returned, use an empty array; never fabricate a player projection or placeholder value.

`unsupported_scenarios` must be an array of strings describing requested scenario calculations that the registered tools do not support. Use an empty array when no unsupported scenario was requested. Do not create scenario comparisons or substitute estimates.

# Output Requirements

- Return valid JSON without Markdown fences or additional explanatory text.
- Preserve every tool-returned field and numerical value without renaming, flattening, rounding, or omission.
- Do not add any top-level field beyond the three keys above.
- Do not fabricate missing values, statistics, evidence references, or model metadata.

'''
    return instructions[:start] + replacement + instructions[end:]

def repair_insight_instructions(instructions: str) -> str:
    """Return a read-only corrected prompt with the local InsightHandoff contract."""
    start = instructions.find("# Output")
    if start < 0:
        raise ValueError("Insight instructions do not contain the expected output section")
    prefix = instructions[:start].replace(
        'If an important inconsistency is detected, set status to "needs_review" and describe the issue.',
        'If an important inconsistency is detected, describe it in the contradictions array; the backend diagnostic records review status separately.',
    )
    replacement = '''# Output Format

Return exactly one valid JSON object containing exactly four top-level keys:

- summary
- bullets
- unsupported_claims
- contradictions

The output must conform to the MatchLens AI backend's `InsightHandoff` contract.

## summary

A nonempty string containing a clear, concise, audience-appropriate explanation of the match analysis. Answer the user's actual question. Base the explanation exclusively on the supplied Investigator evidence and Predictor results. Distinguish statistical forecasts from actual match outcomes. Clearly communicate uncertainty where relevant. Do not invent statistics, evidence, or causal relationships.

## bullets

An array of strings containing the most useful supporting insights. Explain principal forecast drivers, historical context, player information, or limitations relevant to the question. Tailor the presentation to the requested audience: fan, analyst, or fantasy. Preserve numerical values from the supplied validated forecast. Never introduce unsupported percentages, expected goals, player projections, or historical results. If there are no supported additional insights, return an empty array.

## unsupported_claims

An array of strings describing claims that could not be verified from the supplied evidence and forecast. Do not present unsupported claims as facts in summary or bullets. Use an empty array when none were identified.

## contradictions

An array of strings describing inconsistencies between the supplied evidence, forecast, and proposed explanation. Report genuine contradictions rather than silently reconciling conflicting information. Do not modify Python-generated forecasts. Use an empty array when none were identified.

# Strict Output Requirements

1. Return valid JSON only, without Markdown fences, introductory text, or commentary.
2. Include all four required top-level keys and no other top-level keys.
3. `summary` must be a string; `bullets`, `unsupported_claims`, and `contradictions` must be arrays of strings.
4. Do not output legacy fields such as status, match_id, audience_mode, headline, key_insights, supporting_evidence, forecast_explanation, uncertainty_statement, data_warnings, or broadcast_overlay.
5. Preserve useful legacy presentation requirements within summary and bullets where evidence-supported.
6. Never fabricate missing evidence or numerical values.
7. Use only the provided validated evidence and forecasting results. Do not access external sources.
8. If supporting information is insufficient, communicate that limitation rather than producing an unsupported explanation.

# Required JSON Structure

{"summary":"Evidence-grounded explanation appropriate for the requested audience.","bullets":["Supporting insight derived from the supplied evidence."],"unsupported_claims":[],"contradictions":[]}

# Core Principle

The MatchLens Insight Agent explains validated football intelligence; it does not create new predictions.

Every numerical claim must be grounded in the supplied Python-generated forecast or validated evidence.

Return trustworthy, understandable explanations without inventing facts.
'''
    return prefix + replacement

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
