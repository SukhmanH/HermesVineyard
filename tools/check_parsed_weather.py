import json

with open("/tmp/weather_fetch_result.json") as f:
    data = json.load(f)

for site, d in data.items():
    print(f"=== {site.upper()} ({d['station_name']}) ===")
    print("Age hours:", d.get("age_hours"))
    print("Hourly count:", len(d.get("hourly", [])))
    print("First 3 hours:", d.get("hourly", [])[:3])
    print("ECCC current:", d.get("eccc_current"))
    print("PWS current:", d.get("pws_current"))
    print()
