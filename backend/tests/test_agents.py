import asyncio
import json
import os
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.agents.contracts import HeadToHeadArgs, PredictionArgs
from app.agents.tools import get_head_to_head, predict_match
from app.agents.contracts import TeamFormArgs, PlayerStatsArgs, ScenarioArgs
from app.agents.foundry_tools import FOUNDRY_FUNCTIONS, foundry_get_head_to_head, foundry_get_team_form
from app.agents.schema import normalize_foundry_schema
from app.agents.provenance import agent_context, begin, calls
from app.agents.foundry_workflow import FoundryResponseError, _text, reconcile_forecast
from app.agents.isolated_diagnostics import build_investigator_handoff, forecast_mismatches, insight_check, insight_report, parse_insight_handoff, parse_investigator_handoff, parse_prediction_handoff, required_tool_verification
from app.agents.validation import validate_evidence
from app.agents.contracts import EvidenceItem, InvestigatorHandoff
from scripts.register_foundry_tools import AGENTS, instruction_warnings, repair_investigator_instructions, repair_investigator_output_instructions, repair_insight_instructions, repair_predictor_instructions, tool_schema, proposed
from app.repositories.synthetic import get_fixture
client = TestClient(app)
def test_tools_validate_and_use_real_data():
    result = get_head_to_head(HeadToHeadArgs(match_id="match-001")); assert len(result["records"]) == 5
    forecast = predict_match(PredictionArgs(match_id="match-001")); assert abs(sum(forecast[x] for x in ("home_win_probability","draw_probability","away_win_probability"))-100) < .1

def test_investigator_tool_records_use_canonical_evidence_ids():
    from app.agents.contracts import PlayerStatsArgs, TeamFormArgs
    from app.agents.tools import get_player_stats, get_team_form
    from app.agents.validation import valid_evidence_ids
    allowed=valid_evidence_ids("match-001")
    h2h_result=get_head_to_head(HeadToHeadArgs(match_id="match-001"))
    form_result=get_team_form(TeamFormArgs(match_id="match-001", team_side="home"))
    player_result=get_player_stats(PlayerStatsArgs(match_id="match-001"))
    records=h2h_result["records"] + form_result["records"] + player_result["players"]
    assert records
    assert all(record["record_id"] in allowed for record in records)
    assert all(record["record_type"] == record["record_id"].split(":", 1)[0] for record in records)
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

def test_multiple_simulated_calls_are_attributed_and_continue_with_real_outputs():
    async def simulated_turn():
        begin()
        with agent_context("matchlens-investigator", "6"):
            outputs=[]
            for index, name, arguments in (
                ("offline-call-1", "get_head_to_head", {"match_id":"match-001"}),
                ("offline-call-2", "get_match_context", {"match_id":"match-001", "minute":0}),
            ):
                result=await FOUNDRY_FUNCTIONS[name].invoke(arguments=arguments, tool_call_id=index)
                outputs.append({"type":"function_call_output", "call_id":index, "output":result})
            return outputs, calls()
    outputs, recorded=asyncio.run(simulated_turn())
    assert [item["call_id"] for item in outputs] == ["offline-call-1", "offline-call-2"]
    assert [call.name for call in recorded] == ["get_head_to_head", "get_match_context"]
    assert all(call.agent_name == "matchlens-investigator" and call.agent_version == "6" for call in recorded)
    assert all(call.duration_ms >= 0 and call.outcome == "success" for call in recorded)
    assert all(call.output_ids for call in recorded)

def test_transport_timeout_is_not_retried():
    class TimeoutAgent:
        calls = 0
        async def run(self, prompt):
            self.calls += 1
            raise TimeoutError("simulated timeout")
    agent=TimeoutAgent()
    with pytest.raises(FoundryResponseError, match="invocation failed"):
        asyncio.run(_text(agent, {"match_id":"match-001"}, lambda text: text, "investigator", "matchlens-investigator", "6", http_timeout=60))
    assert agent.calls == 1

def test_response_validation_retries_once_but_transport_does_not():
    class ValidationAgent:
        calls = 0
        async def run(self, prompt):
            self.calls += 1
            return type("Result", (), {"text": "bad" if self.calls == 1 else "good"})()
    agent=ValidationAgent()
    result=asyncio.run(_text(agent, {"match_id":"match-001"}, lambda text: (_ for _ in ()).throw(ValueError("bad JSON")) if text == "bad" else text, "investigator", "matchlens-investigator", "6", http_timeout=60))
    assert result == "good"
    assert agent.calls == 2

def test_response_validation_zero_retries_fails_once():
    class InvalidAgent:
        calls = 0
        async def run(self, prompt):
            self.calls += 1
            return type("Result", (), {"text": "invalid"})()
    agent=InvalidAgent()
    with pytest.raises(FoundryResponseError, match="0 validation retries"):
        asyncio.run(_text(agent, {"match_id":"match-001"}, lambda text: (_ for _ in ()).throw(ValueError("bad JSON")), "investigator", "matchlens-investigator", "6", http_timeout=60, validation_retries=0))
    assert agent.calls == 1

def test_end_to_end_timeout_is_bounded_and_reported(monkeypatch):
    import app.agents.foundry_workflow as workflow
    async def slow_workflow(request):
        await asyncio.sleep(0.05)
    monkeypatch.setattr(workflow, "_run_foundry", slow_workflow)
    monkeypatch.setenv("FOUNDRY_END_TO_END_TIMEOUT_SECONDS", "0.001")
    with pytest.raises(FoundryResponseError, match="end-to-end timeout"):
        asyncio.run(workflow.run_foundry(__import__("app.agents.contracts", fromlist=["AnalysisRequest"]).AnalysisRequest(match_id="match-001", question="Why?")))

def test_isolated_diagnostic_inputs_use_valid_synthetic_references():
    handoff=build_investigator_handoff("match-001")
    assert handoff.evidence
    assert validate_evidence(handoff, "match-001") == handoff

def test_insight_check_detects_numbers_and_contradictions():
    prediction=__import__("app.agents.contracts", fromlist=["PredictionHandoff"]).PredictionHandoff(forecast=predict_match(PredictionArgs(match_id="match-001")), player_projections=[])
    clean=__import__("app.agents.contracts", fromlist=["InsightHandoff"]).InsightHandoff(summary="The home side is favored.", bullets=["The model is based on synthetic evidence."])
    investigator=build_investigator_handoff("match-001")
    assert insight_check(clean, investigator, prediction)["valid"]
    noisy=__import__("app.agents.contracts", fromlist=["InsightHandoff"]).InsightHandoff(summary="The home side wins 999.0%.", bullets=[], contradictions=["conflict"])
    result=insight_check(noisy, investigator, prediction)
    assert result["unsupported_numerical_claims"] == ["999.0%"]
    assert result["contradictions"] == ["conflict"]
    assert result["review_required"] is True

def test_known_missing_data_limitation_does_not_fail_grounded_insight():
    from app.agents.contracts import InsightHandoff, PredictionHandoff
    prediction=PredictionHandoff(forecast=predict_match(PredictionArgs(match_id="match-001")), player_projections=[])
    investigator=build_investigator_handoff("match-001")
    insight=InsightHandoff(summary="The home side has a modest forecast edge.", bullets=[], unsupported_claims=["Any claim about official lineups is unverified because official lineup data is not provided."], contradictions=[])
    result=insight_check(insight, investigator, prediction)
    assert result["supported_limitations"] == insight.unsupported_claims
    assert result["genuine_unsupported_claims"] == []
    assert result["valid"] is True
    assert result["review_required"] is True

def test_cautious_h2h_claim_is_supported_by_supplied_evidence():
    from app.agents.contracts import InsightHandoff, PredictionHandoff
    prediction=PredictionHandoff(forecast=predict_match(PredictionArgs(match_id="match-001")), player_projections=[])
    investigator=build_investigator_handoff("match-001")
    claim="A claim that historical head-to-head dominance exists is not supported; the supplied results are mixed."
    result=insight_check(InsightHandoff(summary="Grounded.", bullets=[], unsupported_claims=[claim], contradictions=[]), investigator, prediction)
    assert result["supported_evidence_claims"] == [claim]
    assert result["genuine_unsupported_claims"] == []

def test_genuine_unsupported_insight_claim_remains_visible_and_fails():
    from app.agents.contracts import InsightHandoff, PredictionHandoff
    prediction=PredictionHandoff(forecast=predict_match(PredictionArgs(match_id="match-001")), player_projections=[])
    investigator=build_investigator_handoff("match-001")
    insight=InsightHandoff(summary="The home side has a modest forecast edge.", bullets=[], unsupported_claims=["The referee has a strong historical bias."], contradictions=[])
    result=insight_check(insight, investigator, prediction)
    assert result["unsupported_claims"] == insight.unsupported_claims
    assert result["genuine_unsupported_claims"] == insight.unsupported_claims
    assert result["valid"] is False

def test_insight_report_includes_returned_prose_and_checks():
    from app.agents.contracts import InsightHandoff
    insight=InsightHandoff(summary="Home advantage matters.", bullets=["Synthetic form supports the conclusion."], unsupported_claims=["No odds data."], contradictions=[])
    report=insight_report(insight, {"valid": True, "review_required": True})
    assert report["summary"] == insight.summary
    assert report["bullets"] == insight.bullets
    assert report["unsupported_claims"] == insight.unsupported_claims
    assert report["automated_checks"]["review_required"] is True

def test_missing_real_predictor_tools_fails_closed():
    from app.agents.contracts import Forecast, ToolCall
    canonical=predict_match(PredictionArgs(match_id="match-001"))
    returned=Forecast.model_validate(canonical)
    mismatches=forecast_mismatches(returned, canonical)
    assert mismatches == []
    calls=[ToolCall(name="predict_match", agent_name="matchlens-predictor", agent_version="5", duration_ms=1, outcome="success")]
    assert required_tool_verification(calls, "matchlens-predictor", "5") == ["get_model_explanation", "predict_player"]

def test_legitimate_rounded_insight_values_are_supported():
    from app.agents.contracts import InsightHandoff
    prediction=__import__("app.agents.contracts", fromlist=["PredictionHandoff"]).PredictionHandoff(forecast=predict_match(PredictionArgs(match_id="match-001")), player_projections=[])
    investigator=build_investigator_handoff("match-001")
    insight=InsightHandoff(summary="The model gives the home side about 50.0%.", bullets=[])
    assert insight_check(insight, investigator, prediction)["unsupported_numerical_claims"] == []

def test_mismatched_likely_scoreline_is_reported():
    from app.agents.contracts import Forecast
    canonical=predict_match(PredictionArgs(match_id="match-001"))
    altered={**canonical, "most_likely_scores": [dict(score, home=99) if index == 0 else score for index, score in enumerate(canonical["most_likely_scores"])]}
    mismatches=forecast_mismatches(Forecast.model_validate(altered), canonical)
    assert "forecast.most_likely_scores[0].home" in mismatches

def test_simulated_predictor_response_is_validated_and_reconciled():
    from app.agents.contracts import PredictionHandoff
    canonical=predict_match(PredictionArgs(match_id="match-001"))
    class PredictorAgent:
        async def run(self, prompt):
            return type("Result", (), {"text": json.dumps({"forecast": canonical, "player_projections": [], "unsupported_scenarios": []})})()
    parsed=asyncio.run(_text(PredictorAgent(), {"canonical_python_forecast":canonical}, lambda text: __import__("app.agents.validation", fromlist=["parse_json"]).parse_json(text, PredictionHandoff), "predictor", "matchlens-predictor", "5", http_timeout=60))
    reconcile_forecast(parsed.forecast.model_dump(), canonical)

def test_prediction_contract_rejects_old_flat_output():
    with pytest.raises(ValueError, match="exactly forecast"):
        parse_prediction_handoff(json.dumps({"status":"success", "home_win_probability":50, "player_projections":[], "scenario_comparisons":[]}))

def _valid_investigator_payload():
    return {"evidence":[{"record_type":"h2h", "record_id":"h2h:match-001:0", "statement":"Synthetic H2H result 1-0."}], "missing_information":[]}

def test_investigator_contract_accepts_grounded_evidence():
    parsed=parse_investigator_handoff(json.dumps(_valid_investigator_payload()), "match-001")
    assert parsed.evidence[0].record_id == "h2h:match-001:0"

def test_investigator_contract_rejects_legacy_flat_output():
    with pytest.raises(ValueError, match="exactly evidence"):
        parse_investigator_handoff(json.dumps({"status":"sufficient_data", "data_quality":"good"}), "match-001")

def test_investigator_contract_rejects_missing_fields_and_malformed_evidence():
    with pytest.raises(ValueError, match="exactly evidence"):
        parse_investigator_handoff(json.dumps({"evidence":[]}), "match-001")
    malformed={"evidence":[{"record_type":"h2h", "record_id":"h2h:match-001:0"}], "missing_information":[]}
    with pytest.raises(ValueError, match="exactly record_type"):
        parse_investigator_handoff(json.dumps(malformed), "match-001")

def test_investigator_contract_rejects_unknown_evidence_id():
    payload=_valid_investigator_payload()
    payload["evidence"][0]["record_id"]="h2h:match-001:invented"
    with pytest.raises(ValueError, match="Unsupported evidence"):
        parse_investigator_handoff(json.dumps(payload), "match-001")

def test_investigator_contract_rejects_record_type_prefix_mismatch():
    payload=_valid_investigator_payload()
    payload["evidence"][0]["record_type"]="form"
    with pytest.raises(ValueError, match="record_type"):
        parse_investigator_handoff(json.dumps(payload), "match-001")

def test_investigator_empty_evidence_fails_for_match_001():
    with pytest.raises(ValueError, match="grounded evidence"):
        parse_investigator_handoff(json.dumps({"evidence":[], "missing_information":["No records"]}), "match-001")

def test_insight_contract_rejects_legacy_extra_keys():
    with pytest.raises(ValueError, match="exactly summary"):
        parse_insight_handoff(json.dumps({"summary":"ok", "bullets":[], "unsupported_claims":[], "contradictions":[], "status":"ok"}))

def test_insight_contract_accepts_exact_nested_output():
    parsed=parse_insight_handoff(json.dumps({"summary":"Grounded.", "bullets":["Supported."], "unsupported_claims":[], "contradictions":[]}))
    assert parsed.summary == "Grounded."

def test_prediction_contract_rejects_missing_forecast():
    with pytest.raises(ValueError, match="exactly forecast"):
        parse_prediction_handoff(json.dumps({"player_projections":[], "unsupported_scenarios":[]}))

def test_prediction_contract_rejects_missing_player_basis():
    canonical=predict_match(PredictionArgs(match_id="match-001"))
    with pytest.raises(ValueError, match="all five"):
        parse_prediction_handoff(json.dumps({"forecast":canonical, "player_projections":[{"player_id":"aurora-p1", "player_name":"Milo Hart", "projected_goals":0.64, "projected_assists":0.3}], "unsupported_scenarios":[]}))

def test_prediction_contract_accepts_valid_nested_output():
    canonical=predict_match(PredictionArgs(match_id="match-001"))
    value=parse_prediction_handoff(json.dumps({"forecast":canonical, "player_projections":[{"player_id":"aurora-p1", "player_name":"Milo Hart", "projected_goals":0.64, "projected_assists":0.3, "basis":"synthetic season attacking rates; not a validated player model"}], "unsupported_scenarios":[]}))
    assert value.forecast.most_likely_scores
    assert value.player_projections[0].basis

def test_predictor_prompt_replaces_legacy_output_fields():
    existing="""# Output Format\n- status\n- home_win_probability\n# Core Principle\nNever invent forecasts."""
    repaired=repair_predictor_instructions(existing)
    assert "exactly these three top-level keys" in repaired
    assert "scoreline_probabilities" in repaired
    assert "forecast_timestamp" in repaired
    assert repaired.endswith("# Core Principle\nNever invent forecasts.")

def test_investigator_prompt_replaces_legacy_output_fields():
    existing="# Role\nKeep grounding rules.\n# Output\n- status\n- data_quality\n"
    repaired=repair_investigator_output_instructions(existing)
    assert "exactly these two top-level keys" in repaired
    assert "record_type" in repaired and "record_id" in repaired and "statement" in repaired
    assert "data_quality" in repaired
    assert repaired.startswith("# Role\nKeep grounding rules.")

def test_investigator_prompt_preserves_instructions_after_legacy_output():
    existing="# Role\nKeep grounding rules.\n# Output\n- status\n# Additional Safeguard\nNever use external sources."
    repaired=repair_investigator_output_instructions(existing)
    assert repaired.endswith("# Additional Safeguard\nNever use external sources.")

def test_investigator_prompt_declares_canonical_record_type_mapping():
    repaired=repair_investigator_output_instructions("# Role\n# Output\nlegacy")
    assert "`h2h` for `h2h:<match_id>:<index>`" in repaired
    assert "`form` for `form:<team_id>:<index>`" in repaired
    assert "`player` for `player:<player_id>`" in repaired

def test_insight_prompt_replaces_legacy_output_fields():
    existing='# Role\nKeep validation rules.\n- If an important inconsistency is detected, set status to "needs_review" and describe the issue.\n# Output\n- status\n- headline\n'
    repaired=repair_insight_instructions(existing)
    assert "exactly four top-level keys" in repaired
    assert "summary" in repaired and "unsupported_claims" in repaired and "contradictions" in repaired
    assert "- status\n- headline" not in repaired
    assert "Do not output legacy fields" in repaired
    assert 'set status to "needs_review"' not in repaired
    assert "describe it in the contradictions array" in repaired

def test_workflow_uses_exact_prediction_contract_parser():
    import inspect
    from app.agents import foundry_workflow
    assert "parse_prediction_handoff" in inspect.getsource(foundry_workflow)
    assert "parse_insight_handoff" in inspect.getsource(foundry_workflow)
    assert "parse_investigator_handoff" in inspect.getsource(foundry_workflow)

def test_workflow_attributes_canonical_forecast_to_local_preparation():
    import inspect
    from app.agents import foundry_workflow
    source=inspect.getsource(foundry_workflow)
    assert 'agent_name="local-python-preparation"' in source
    assert 'agent_name=cfg["predictor"]["name"]' not in source.split('canonical=execute', 1)[1].split('pred_payload', 1)[0]

def test_comprehensive_reconciliation_catches_scores_and_player_values():
    from app.agents.contracts import Forecast
    canonical=predict_match(PredictionArgs(match_id="match-001"))
    altered={**canonical, "current_home_score": 1}
    returned=Forecast.model_validate(altered)
    expected_player={"aurora-p1": {"player_id":"aurora-p1", "projected_goals":0.64, "projected_assists":0.3}}
    mismatches=forecast_mismatches(returned, canonical, returned_players=[{"player_id":"aurora-p1", "projected_goals":9, "projected_assists":0.3}], expected_players=expected_player)
    assert "forecast.current_home_score" in mismatches
    assert "player_projections[aurora-p1].projected_goals" in mismatches

def test_simulated_insight_response_is_validated_without_tool_calls():
    from app.agents.contracts import InsightHandoff
    class InsightAgent:
        async def run(self, prompt):
            return type("Result", (), {"text": json.dumps({"summary":"Grounded synthetic analysis.", "bullets":["The evidence package was provided."], "unsupported_claims":[], "contradictions":[]})})()
    parsed=asyncio.run(_text(InsightAgent(), {"prediction":{}}, lambda text: __import__("app.agents.validation", fromlist=["parse_json"]).parse_json(text, InsightHandoff), "insight", "matchlens-insight", "3", http_timeout=60))
    assert parsed.contradictions == []
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
