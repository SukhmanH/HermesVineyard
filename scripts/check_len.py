#!/usr/bin/env python3
import json

for key in ["penticton", "naramata", "oliver"]:
    with open(f"/tmp/hourly_{key}.json") as f:
        d = json.load(f)
    print(f"{key}: {len(d['hourly'])} hours, age {d['age_hours']}")
