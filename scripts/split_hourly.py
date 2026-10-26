#!/usr/bin/env python3
import json

with open("/tmp/weather_fetch_data.json") as f:
    data = json.load(f)

for key in ["penticton", "naramata", "oliver"]:
    hourly = data[key]["hourly"]
    age_hours = data[key]["age_hours"]
    with open(f"/tmp/hourly_{key}.json", "w") as out_f:
        json.dump({"site": key, "age_hours": age_hours, "hourly": hourly}, out_f)
print("Saved per-site hourly files.")
