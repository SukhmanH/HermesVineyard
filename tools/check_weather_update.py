import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

import json

from tools.fetch_weather_runner import SITES, fetch_eccc_forecast, fetch_wu_current, parse_eccc_xml
from vineyard_mcp.db import connect
from vineyard_mcp.queries import cache_weather
from vineyard_mcp.weather_math import compute_spray_window


def main():
    conn = connect()
    results = {}

    for s in SITES:
        key = s["key"]
        xml = fetch_eccc_forecast(s["code"])
        if not xml:
            print(f"Failed to fetch ECCC XML for {key}")
            continue
        parsed = parse_eccc_xml(xml)
        hourly = parsed["hourly"]
        age_hours = parsed["age_hours"]

        # Compute spray window
        verdict = compute_spray_window(hourly=hourly, source="eccc", age_hours=age_hours)
        verdict["site"] = key

        # Cache weather
        payload = {"hourly": hourly}
        cache_res = cache_weather(conn, site=key, source="eccc", payload=payload, verdict=verdict)

        pws_obs = None
        if s["pws"]:
            pws_obs = fetch_wu_current(s["pws"])

        results[key] = {
            "verdict": verdict,
            "age_hours": age_hours,
            "eccc_current": parsed["current"],
            "pws_current": pws_obs,
            "cache_res": cache_res
        }
        print(f"Site {key}: verdict={verdict.get('verdict')}, reason={verdict.get('reason')}, age={age_hours}h, cached={cache_res}")

    with open("/tmp/weather_check_results.json", "w") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    main()
