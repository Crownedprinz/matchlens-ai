import asyncio
import os
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.agents.contracts import HeadToHeadArgs, PredictionArgs
from app.agents.tools import get_head_to_head, predict_match
from app.agents.contracts import TeamFormArgs, PlayerStatsArgs, ScenarioArgs
from app.agents.foundry_tools import FOUNDRY_FUNCTIONS, foundry_get_head_to_head, foundry_get_team_form
from app.agents.schema import normalize_foundry_schema
from app.agents.provenance import begin, calls
from app.agents.foundry_workflow import reconcile_forecast
from app.agents.validation import validate_evidence
from app.agents.contracts import EvidenceItem, InvestigatorHandoff
from scripts.register_foundry_tools import AGENTS, instruction_warnings, repair_investigator_instructions, tool_schema, proposed
from app.repositories.synthetic import get_fixture
client = TestClient(app)
def test_tools_validate_and_use_real_data():
    result = get_head_to_head(HeadToHeadArgs(match_id="match-001")); assert len(result["records"]) == 5
    forecast = predict_match(PredictionArgs(match_id="match-001")); assert abs(sum(forecast[x] for x in ("home_win_probability","draw_probability","away_win_probability"))-100) < .1
def test_analysis_mock_is_structured(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "mock")
    response = client.post("/api/analysis", json={"match_id":"match-001","audience":"fantasy","question":"Which attacker has the strongest projected return?"})
    body=response.json(); assert response.status_code==200; assert body["mode"]=="mock"; assert body["investigator"]["evidence"]; assert body["predictor"]["forecast"]["home_win_probability"] > 0
def test_analysis_rejects_bad_input(): assert client.post("/api/analysis", json={"match_id":"nope","audience":"fan","question":"Why?"}).status_code==404
def test_foundry_mode_does_not_fallback(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "foundry"); monkeypatch.delenv("FOUNDRY_PROJECT_ENDPOINT", raising=False)
    response=client.post("/api/analysis", json={"match_id":"match-001","audience":"fan","question":"Why?"}); assert response.status_code==503; assert "FOUNDRY_PROJECT_ENDPOINT" in response.text
    monkeypatch.setenv("AGENT_MODE", "mock")
def test_schema_matches_contract():
    team_schema=tool_schema("get_team_form")["parameters"]; assert "team_side" in team_schema["required"]; assert set(team_schema["properties"]["team_side"]["enum"])=={"home","away"}
    player_schema=tool_schema("get_player_stats")["parameters"]; assert "team_side" in player_schema["required"]; assert "anyOf" in player_schema["properties"]["team_side"]
    assert tool_schema("get_head_to_head")["parameters"]["properties"].keys()=={"match_id"}
    assert "minimum" not in tool_schema("predict_match")["parameters"]["properties"]["minute"]

def _walk_schema(node):
    if isinstance(node, dict):
        yield node
        for value in node.values(): yield from _walk_schema(value)
    elif isinstance(node, list):
        for value in node: yield from _walk_schema(value)

def test_all_registered_schemas_are_strict_and_supported():
    expected={"get_head_to_head","get_team_form","get_player_stats","get_match_context","predict_match","predict_player","get_model_explanation"}
    assert set(FOUNDRY_FUNCTIONS)==expected
    unsupported={"minLength","maxLength","minimum","maximum","exclusiveMinimum","exclusiveMaximum","multipleOf","pattern","format","default","title","$schema"}
    for name in expected:
        declaration=tool_schema(name)
        assert declaration["strict"] is True
        runtime_parameters=FOUNDRY_FUNCTIONS[name].to_json_schema_spec()["function"]["parameters"]
        assert runtime_parameters == declaration["parameters"]
        for node in _walk_schema(declaration["parameters"]):
            assert not unsupported.intersection(node)
            if node.get("type")=="object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node.get("properties",{}))

def test_nested_objects_and_definitions_are_closed_and_required():
    schema=normalize_foundry_schema({
        "type":"object",
        "properties":{"payload":{"$ref":"#/$defs/Payload"}},
        "$defs":{"Payload":{"type":"object","properties":{"value":{"type":"integer","minimum":0}},"required":["value"]}},
    })
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["payload"]
    assert schema["$defs"]["Payload"]["additionalProperties"] is False
    assert "minimum" not in schema["$defs"]["Payload"]["properties"]["value"]

def test_nullable_optional_arguments_are_required_and_nullable():
    schema=tool_schema("get_player_stats")["parameters"]
    assert "team_side" in schema["required"]
    assert any(branch.get("type")=="null" for branch in schema["properties"]["team_side"]["anyOf"])
    minute=tool_schema("predict_match")["parameters"]["properties"]["minute"]
    assert any(branch.get("type")=="null" for branch in minute["anyOf"])

def test_invalid_foundry_arguments_are_rejected_by_pydantic():
    with pytest.raises(Exception): foundry_get_head_to_head("x" * 81)
    with pytest.raises(Exception): foundry_get_team_form("match-001", "neutral")

def test_simulated_foundry_function_call_executes_and_continues_with_output():
    async def simulated_turn():
        begin()
        function_call={"name":"get_head_to_head","arguments":{"match_id":"match-001"},"call_id":"offline-call-1"}
        tool_output=await FOUNDRY_FUNCTIONS[function_call["name"]].invoke(
            arguments=function_call["arguments"], tool_call_id=function_call["call_id"]
        )
        continuation={"type":"function_call_output","call_id":function_call["call_id"],"output":tool_output}
        return continuation, calls()
    continuation, recorded=asyncio.run(simulated_turn())
    assert continuation["call_id"] == "offline-call-1"
    assert continuation["type"] == "function_call_output"
    assert recorded[0].name == "get_head_to_head"
    assert recorded[0].outcome == "success"
def test_unsupported_scenario_is_not_registered():
    assert "simulate_scenario" not in AGENTS["predictor"]["tools"]
    with pytest.raises(Exception): __import__("app.agents.tools",fromlist=["simulate_scenario"]).simulate_scenario(ScenarioArgs(match_id="match-001",home_goals=1))

def test_prohibited_tool_mentions_are_not_reported_as_advertised():
    existing={"tools":[],"instructions":"Only use predict_match. simulate_scenario is unavailable; do not call or reference it."}
    assert instruction_warnings(existing,"predictor") == []

def test_genuinely_unsupported_advertised_tool_fails_closed():
    existing={"tools":[],"instructions":"You may call simulate_scenario when the user asks for a scenario."}
    warnings=instruction_warnings(existing,"predictor")
    assert warnings == ["instructions advertise simulate_scenario, but it is not in the preserved/proposed tool definitions"]

def test_agent_supported_tool_counts():
    assert len(AGENTS["investigator"]["tools"]) == 4
    assert len(AGENTS["predictor"]["tools"]) == 3
    assert AGENTS["insight"]["tools"] == []

def test_insight_has_no_registration_delta():
    existing={"name":"matchlens-insight","version":"2","model":"gpt-5-mini","instructions":"keep this","tools":[]}
    assert proposed(existing,"insight") == existing

def test_investigator_signature_repair_matches_registered_schemas():
    instructions="- get_head_to_head(home_team, away_team, limit)\n- get_team_form(team, limit)\n- get_player_stats(team, limit)"
    repaired=repair_investigator_instructions(instructions)
    assert repaired == "- get_head_to_head(match_id)\n- get_team_form(match_id, team_side)\n- get_player_stats(match_id, team_side)"
def test_protected_registration_fields_are_preserved():
    existing={"name":"matchlens-investigator","version":"3","model":"gpt-5-mini","instructions":"keep this","tools":[]}
    result=proposed(existing,"investigator"); assert result["model"]==existing["model"]; assert result["instructions"]==existing["instructions"]
def test_invalid_evidence_is_rejected():
    with pytest.raises(ValueError,match="Unsupported evidence"):
        validate_evidence(InvestigatorHandoff(evidence=[EvidenceItem(record_type="x",record_id="invented",statement="fake")]),"match-001")
def test_forecast_reconciliation_rejects_model_number_changes():
    canonical={"home_win_probability":50,"draw_probability":20,"away_win_probability":30,"expected_home_goals":1,"expected_away_goals":1}
    reconcile_forecast(canonical,canonical)
    with pytest.raises(Exception,match="mismatch"): reconcile_forecast({**canonical,"home_win_probability":51},canonical)
def test_separate_versions_are_required(monkeypatch):
    from app.agents.foundry_workflow import _configuration, FoundryConfigurationError
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT","https://example")
    for role in ("INVESTIGATOR","PREDICTOR","INSIGHT"): monkeypatch.delenv(f"FOUNDRY_{role}_VERSION",raising=False)
    with pytest.raises(FoundryConfigurationError): _configuration()
