"""Primitive-argument wrappers for Agent Framework tool binding.

Each wrapper immediately validates through the same Pydantic argument model used
by the local tools, so Foundry cannot bypass application validation.
"""
from agent_framework import FunctionTool
from app.agents.contracts import HeadToHeadArgs, MatchContextArgs, TeamFormArgs, PlayerStatsArgs, PredictionArgs, PlayerPredictionArgs, ExplanationArgs
from app.agents import tools
from app.agents.provenance import execute
from app.agents.schema import normalize_foundry_schema
def foundry_get_head_to_head(match_id: str): return execute("get_head_to_head", tools.get_head_to_head, HeadToHeadArgs(match_id=match_id).model_dump())
def foundry_get_team_form(match_id: str, team_side: str): return execute("get_team_form", tools.get_team_form, TeamFormArgs(match_id=match_id, team_side=team_side).model_dump())
def foundry_get_player_stats(match_id: str, team_side: str | None = None): return execute("get_player_stats", tools.get_player_stats, PlayerStatsArgs(match_id=match_id, team_side=team_side).model_dump())
def foundry_get_match_context(match_id: str, minute: int | None = 0): return execute("get_match_context", tools.get_match_context, MatchContextArgs(match_id=match_id, minute=0 if minute is None else minute).model_dump())
def foundry_predict_match(match_id: str, minute: int | None = 0): return execute("predict_match", tools.predict_match, PredictionArgs(match_id=match_id, minute=0 if minute is None else minute).model_dump())
def foundry_predict_player(match_id: str, player_id: str): return execute("predict_player", tools.predict_player, PlayerPredictionArgs(match_id=match_id, player_id=player_id).model_dump())
def foundry_get_model_explanation(match_id: str, minute: int | None = 0): return execute("get_model_explanation", tools.get_model_explanation, ExplanationArgs(match_id=match_id, minute=0 if minute is None else minute).model_dump())
_FUNCTIONS = {
    "get_head_to_head": (foundry_get_head_to_head, HeadToHeadArgs),
    "get_team_form": (foundry_get_team_form, TeamFormArgs),
    "get_player_stats": (foundry_get_player_stats, PlayerStatsArgs),
    "get_match_context": (foundry_get_match_context, MatchContextArgs),
    "predict_match": (foundry_predict_match, PredictionArgs),
    "predict_player": (foundry_predict_player, PlayerPredictionArgs),
    "get_model_explanation": (foundry_get_model_explanation, ExplanationArgs),
}


def make_foundry_function_tool(name: str, function, input_model: type) -> FunctionTool:
    """Bind one callable to the normalized schema and Pydantic runtime model."""
    return FunctionTool(
        name=name,
        description=f"MatchLens synthetic football tool: {name}.",
        func=function,
        input_model=normalize_foundry_schema(input_model.model_json_schema()),
    )


FOUNDRY_FUNCTIONS = {
    name: make_foundry_function_tool(name, function, model)
    for name, (function, model) in _FUNCTIONS.items()
}
