import math
import numpy as np
from app.models.domain import Forecast, Scoreline
from app.repositories.synthetic import data, get_fixture, form, events
def _pmf(lam: float, goals: int) -> float: return math.exp(-lam) * lam ** goals / math.factorial(goals)
def forecast(match_id: str, minute: int = 0) -> Forecast:
    if minute < 0 or minute > 90: raise ValueError("minute must be between 0 and 90")
    fixture = get_fixture(match_id); strength = data()["team_strength"]
    home, away = strength[fixture.home_team_id], strength[fixture.away_team_id]
    hf, af = form(fixture.home_team_id), form(fixture.away_team_id)
    h_recent = sum(x.goals_for - x.goals_against for x in hf) / max(1, len(hf)); a_recent = sum(x.goals_for - x.goals_against for x in af) / max(1, len(af))
    base_h = max(.15, 1.35 * home["attack"] / away["defence"] + .18 + h_recent * .06); base_a = max(.15, 1.05 * away["attack"] / home["defence"] + a_recent * .06)
    scored_h = sum(e.event_type == "Goal" and e.team_id == fixture.home_team_id and e.minute <= minute for e in events(match_id)); scored_a = sum(e.event_type == "Goal" and e.team_id == fixture.away_team_id and e.minute <= minute for e in events(match_id))
    remaining = max(0, 90 - minute) / 90; lam_h, lam_a = base_h * remaining, base_a * remaining; current_h, current_a = (0, 0) if minute == 0 else (scored_h, scored_a)
    matrix = np.array([[_pmf(lam_h, h) * _pmf(lam_a, a) for a in range(8)] for h in range(8)]); outcomes = {"home": 0., "draw": 0., "away": 0.}; scores = []
    for h in range(8):
        for a in range(8):
            p = float(matrix[h, a]); final_h, final_a = current_h + h, current_a + a; scores.append(Scoreline(home=final_h, away=final_a, probability=p)); outcomes["home" if final_h > final_a else "away" if final_a > final_h else "draw"] += p
    total = sum(outcomes.values()); outcomes = {k: v / total for k, v in outcomes.items()}; scores = sorted(scores, key=lambda x: x.probability, reverse=True)[:5]
    return Forecast(minute=minute, current_home_score=current_h, current_away_score=current_a, expected_home_goals=round(current_h + lam_h, 2), expected_away_goals=round(current_a + lam_a, 2), home_win_probability=round(outcomes["home"] * 100, 2), draw_probability=round(outcomes["draw"] * 100, 2), away_win_probability=round(outcomes["away"] * 100, 2), most_likely_scores=scores, explanation=[f"Remaining-time model: {90-minute} minutes simulated with Poisson goal rates.", "Rates combine synthetic attack, opponent defence, home advantage, and five-match form.", "Recorded goals are fixed in the score and only remaining goals are simulated."])
