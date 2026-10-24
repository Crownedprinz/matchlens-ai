import json, random
from pathlib import Path
random.seed(42)
root = Path(__file__).resolve().parents[1] / "data"; root.mkdir(exist_ok=True)
teams = [{"id":"aurora","name":"Aurora City","short_name":"AUR","color":"#38bdf8","city":"Northbank"},{"id":"northstar","name":"Northstar United","short_name":"NSU","color":"#a78bfa","city":"Eastmere"},{"id":"rivergate","name":"Rivergate FC","short_name":"RIV","color":"#34d399","city":"Rivergate"},{"id":"cobalt","name":"Cobalt Athletic","short_name":"COB","color":"#f59e0b","city":"Cobalt"}]
fixtures = [{"id":"match-001","home_team_id":"aurora","away_team_id":"northstar","date":"2026-10-24T15:00:00Z","status":"LIVE · SYNTHETIC REPLAY","home_score":2,"away_score":1,"venue":"The Lantern"},{"id":"match-002","home_team_id":"rivergate","away_team_id":"cobalt","date":"2026-10-25T14:00:00Z","status":"UPCOMING","home_score":0,"away_score":0,"venue":"Rivergate Bowl"},{"id":"match-003","home_team_id":"cobalt","away_team_id":"aurora","date":"2026-10-26T18:30:00Z","status":"UPCOMING","home_score":0,"away_score":0,"venue":"Forge Park"}]
strength = {"aurora":{"attack":1.18,"defence":.92},"northstar":{"attack":1.05,"defence":1.04},"rivergate":{"attack":.97,"defence":1.10},"cobalt":{"attack":1.10,"defence":1.16}}
names = {"aurora":[("Milo Hart","FW"),("Jules Kade","MF"),("Tariq Bell","MF"),("Owen Vale","DF"),("Eli Stone","GK")],"northstar":[("Nico Ray","FW"),("Samir Cole","MF"),("Luca Venn","MF"),("Theo Moss","DF"),("Ivo Lane","GK")],"rivergate":[("Noah Pike","FW"),("Arlo Fox","MF"),("Kai Reed","DF"),("Mina Cole","MF"),("Remy Dale","GK")],"cobalt":[("Zane Wolf","FW"),("Mara Quinn","MF"),("Ben Sol","DF"),("Ari Knox","MF"),("Leo Gray","GK")]}
players=[]
for tid in strength:
    for i in range(11):
        first, pos = names[tid][i%5]; players.append({"id":f"{tid}-p{i+1}","name":first if i<5 else f"{first.split()[0]} {['Vale','Rook','Moss','Kite','Lane','West'][i%6]}","team_id":tid,"position":pos,"number":i+1,"minutes":810,"goals":2 if i==0 else 1 if i in (1,2) else 0,"assists":2 if i==1 else 1 if i==2 else 0,"shots":8-i%4,"key_passes":5-i%3,"tackles":3+i%5,"pressures":18+i%7})
h2h=[]
for i, scores in enumerate([(2,1),(1,1),(0,2),(3,2),(1,0)]): h2h.append({"date":f"2026-0{i+5}-12","home_team_id":"aurora" if i%2==0 else "northstar","away_team_id":"northstar" if i%2==0 else "aurora","home_score":scores[0],"away_score":scores[1]})
form=[]
for tid in strength:
    for i in range(5):
        gf=(i+len(tid))%3+1; ga=(i*2+len(tid))%3; form.append({"team_id":tid,"date":f"2026-10-{10-i:02d}","opponent":teams[(i+len(tid))%4]["name"],"venue":"H" if i%2==0 else "A","score":f"{gf}-{ga}","outcome":"W" if gf>ga else "D" if gf==ga else "L","goals_for":gf,"goals_against":ga})
events=[]
def ev(i, minute, typ, tid, pid, desc, related=None): events.append({"id":f"event-{i}","match_id":"match-001","minute":minute,"event_type":typ,"team_id":tid,"player_id":pid,"related_player_id":related,"description":desc})
ev(1,3,"Pass","aurora","aurora-p2","Kade finds Hart between the lines.")
ev(2,12,"Shot","northstar","northstar-p1","Ray tests the keeper from distance.")
ev(3,27,"Goal","aurora","aurora-p1","Hart finishes a fast transition.")
ev(4,28,"Assist","aurora","aurora-p2","Kade claims the assist.","aurora-p1")
ev(5,41,"Pressure","northstar","northstar-p2","Cole forces a hurried clearance.")
ev(6,53,"Goal","northstar","northstar-p1","Ray equalises after a loose ball.")
ev(7,54,"Assist","northstar","northstar-p2","Cole supplies the final pass.","northstar-p1")
ev(8,66,"Tackle","aurora","aurora-p4","Vale wins the ball cleanly.")
ev(9,72,"Shot","aurora","aurora-p3","Bell strikes the post.")
ev(10,78,"Goal","aurora","aurora-p3","Bell curls into the far corner.")
ev(11,79,"Assist","aurora","aurora-p2","Kade creates the winner.","aurora-p3")
ev(12,84,"Substitution","northstar","northstar-p3","Venn is replaced to refresh midfield.")
ev(13,89,"Red card","northstar","northstar-p4","Moss is dismissed after a late challenge.")
(root/"demo.json").write_text(json.dumps({"teams":teams,"fixtures":fixtures,"players":players,"h2h":h2h,"form":form,"events":events,"team_strength":strength},indent=2)); print(f"Wrote {root/'demo.json'}")
