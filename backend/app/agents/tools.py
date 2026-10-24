"""Validated local tools shared by mock orchestration and Foundry function calls."""
from typing import Any
from app.agents.contracts import HeadToHeadArgs, MatchContextArgs, TeamFormArgs, PlayerStatsArgs, PredictionArgs, PlayerPredictionArgs, ScenarioArgs, ExplanationArgs
from app.forecasting.poisson import forecast
from app.repositories.synthetic import data, get_fixture, team, players, h2h, form, events
def get_head_to_head(args: HeadToHeadArgs) -> dict[str, Any]:
    args = HeadToHeadArgs.model_validate(args)
    get_fixture(args.match_id); return {"match_id": args.match_id, "records": [x.model_dump() for x in h2h(args.match_id)]}
def get_team_form(args: TeamFormArgs) -> dict[str, Any]:
    args = TeamFormArgs.model_validate(args)
    fixture = get_fixture(args.match_id); team_id = fixture.home_team_id if args.team_side == "home" else fixture.away_team_id; return {"match_id": args.match_id, "team_side": args.team_side, "team_id": team_id, "records": [x.model_dump() for x in form(team_id)]}
def get_player_stats(args: PlayerStatsArgs) -> dict[str, Any]:
    args = PlayerStatsArgs.model_validate(args)
    fixture = get_fixture(args.match_id); ids = [fixture.home_team_id, fixture.away_team_id] if args.team_side is None else [fixture.home_team_id if args.team_side == "home" else fixture.away_team_id]; return {"match_id": args.match_id, "players": [x.model_dump() for team_id in ids for x in players(team_id)]}
def get_match_context(args: MatchContextArgs) -> dict[str, Any]:
    args = MatchContextArgs.model_validate(args)
    fixture = get_fixture(args.match_id); return {"match": fixture.model_dump(), "home_team": team(fixture.home_team_id).model_dump(), "away_team": team(fixture.away_team_id).model_dump(), "minute": args.minute, "events_revealed": [x.model_dump() for x in events(args.match_id) if x.minute <= args.minute]}
def predict_match(args: PredictionArgs) -> dict[str, Any]:
    args = PredictionArgs.model_validate(args); return forecast(args.match_id, args.minute).model_dump()
def predict_player(args: PlayerPredictionArgs) -> dict[str, Any]:
    args = PlayerPredictionArgs.model_validate(args)
    fixture = get_fixture(args.match_id); candidate = next((p for p in players(fixture.home_team_id) + players(fixture.away_team_id) if p.id == args.player_id), None)
    if candidate is None: raise ValueError(f"Player '{args.player_id}' is not in match '{args.match_id}'")
    return {"player_id": candidate.id, "player_name": candidate.name, "projected_goals": round(candidate.shots * .08, 2), "projected_assists": round(candidate.key_passes * .06, 2), "basis": "synthetic season attacking rates; not a validated player model"}
def simulate_scenario(args: ScenarioArgs) -> dict[str, Any]:
    if args.home_goals or args.away_goals: raise ValueError("Scenario overrides are not implemented; use recorded match state only")
    return predict_match(PredictionArgs(match_id=args.match_id, minute=args.minute))
def get_model_explanation(args: ExplanationArgs) -> dict[str, Any]:
    args = ExplanationArgs.model_validate(args); return {"match_id": args.match_id, "explanation": forecast(args.match_id, args.minute).explanation}
TOOL_FUNCTIONS = {"get_head_to_head": get_head_to_head, "get_team_form": get_team_form, "get_player_stats": get_player_stats, "get_match_context": get_match_context, "predict_match": predict_match, "predict_player": predict_player, "get_model_explanation": get_model_explanation}
