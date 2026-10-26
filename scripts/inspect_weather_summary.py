#!/usr/bin/env python3
import json

with open("/tmp/weather_fetch_data.json") as f:
    data = json.load(f)

for key, site_data in data.items():
    print(f"=== {key.upper()} ===")
    print(f"Pub age: {site_data['age_hours']}h (pub: {site_data['pub_dt_utc']})")
    print(f"Hourly count: {len(site_data['hourly'])}")
    print(f"ECCC CC: {site_data['eccc_cc']}")
    print(f"PWS CC: {site_data['pws_obs']}")
