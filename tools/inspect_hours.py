import json

with open("/tmp/hourly_penticton.json") as f:
    d = json.load(f)

for h in d["hourly"]:
    print(f"{h['time']} | {h['temp_c']}C | wind: {h['wind_kmh']} km/h | gust: {h['gust_kmh']} | pop: {h['precip_prob_pct']}% | {h['condition']}")
