from fastapi.testclient import TestClient
from app.main import app
client=TestClient(app)
def test_health(): assert client.get('/api/health').json()['dataset']=='synthetic'
def test_matches_and_invalid(): assert len(client.get('/api/matches').json())==3; assert client.get('/api/matches/nope').status_code==404
def test_forecast_normalizes():
    f=client.get('/api/matches/match-001/forecast').json(); assert abs(f['home_win_probability']+f['draw_probability']+f['away_win_probability']-100)<.1
def test_boundaries_and_scoring_change():
    kickoff=client.get('/api/matches/match-001/forecast?minute=0').json(); live=client.get('/api/matches/match-001/forecast?minute=90').json(); assert kickoff['current_home_score']==0; assert live['current_home_score']==2; assert live['expected_away_goals']==1
    assert client.get('/api/matches/match-001/forecast?minute=91').status_code==422
def test_reproducible(): assert client.get('/api/matches/match-001/forecast?minute=45').json()==client.get('/api/matches/match-001/forecast?minute=45').json()
