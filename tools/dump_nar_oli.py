import json

with open("/tmp/weather_fetch_result.json") as f:
    d = json.load(f)

for s in ["naramata", "oliver"]:
    print(f"=== {s} ===")
    print("age_hours:", d[s]["age_hours"])
    print("first hour:", d[s]["hourly"][0])
    print("length:", len(d[s]["hourly"]))
