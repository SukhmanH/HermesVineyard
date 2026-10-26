#!/usr/bin/env python3
import json
import math
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import yaml


def fetch_weather():
    with open("config/settings.yaml") as f:
        settings = yaml.safe_load(f)

    sites = settings.get("sites", [])
    wu_key = settings.get("weather_sources", {}).get("wunderground_api_key")

    now = datetime.now(UTC)
    print(f"Current UTC time: {now.isoformat()}")

    results = {}

    for site in sites:
        key = site["key"]
        code = site["eccc_citypage"]
        pws = site.get("wunderground_pws")

        # 1. Fetch ECCC XML
        found_xml = None
        pub_dt = None
        for delta in range(0, 4):
            h = (now.hour - delta) % 24
            hh = f"{h:02d}"
            dir_url = f"https://dd.weather.gc.ca/today/citypage_weather/BC/{hh}/"
            try:
                req = urllib.request.Request(dir_url, headers={"User-Agent": "HermesVineyard/1.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    listing = resp.read().decode("utf-8")
                    pattern = re.compile(r'(\d{8}T\d{6}\.\d+Z)_MSC_CitypageWeather_' + re.escape(code) + r'_en\.xml')
                    matches = pattern.findall(listing)
                    if matches:
                        latest = sorted(matches)[-1]
                        file_url = f"{dir_url}{latest}_MSC_CitypageWeather_{code}_en.xml"
                        file_req = urllib.request.Request(file_url, headers={"User-Agent": "HermesVineyard/1.0"})
                        with urllib.request.urlopen(file_req, timeout=10) as f_resp:
                            found_xml = f_resp.read().decode("utf-8")
                            break
            except Exception as e:
                print(f"Error fetching {dir_url}: {e}")
                continue

        if not found_xml:
            print(f"Failed to fetch ECCC XML for site {key} ({code})")
            continue

        root = ET.fromstring(found_xml)

        # Parse xmlCreation
        # e.g. <dateTime name="xmlCreation" zone="UTC" UTCOffset="0"><year>2026</year><month name="October">10</month><day name="Sunday">18</day><hour>12</hour><minute>45</minute><timeStamp>20261018124500</timeStamp><textSummary>Sunday October 18 2026 12:45 UTC</textSummary></dateTime>
        creation_elem = root.find(".//dateTime[@name='xmlCreation']")
        if creation_elem is not None:
            ts_text = creation_elem.findtext("timeStamp")
            if ts_text:
                pub_dt = datetime.strptime(ts_text, "%Y%m%d%H%M%S").replace(tzinfo=UTC)

        if pub_dt:
            age_hours = (now - pub_dt).total_seconds() / 3600.0
        else:
            age_hours = 0.5

        # Parse hourly forecasts
        hourly = []
        for h in root.findall(".//hourlyForecastGroup/hourlyForecast"):
            dt_str = h.attrib.get("dateTimeUTC")
            iso_time = None
            if dt_str and len(dt_str) >= 12:
                iso_time = f"{dt_str[0:4]}-{dt_str[4:6]}-{dt_str[6:8]}T{dt_str[8:10]}:{dt_str[10:12]}:00+00:00"
            else:
                dt_utc_str = h.findtext("dateTimeUTC")
                if dt_utc_str and len(dt_utc_str) >= 12:
                    iso_time = f"{dt_utc_str[0:4]}-{dt_utc_str[4:6]}-{dt_utc_str[6:8]}T{dt_utc_str[8:10]}:{dt_utc_str[10:12]}:00+00:00"
                else:
                    for dt in h.findall("dateTime"):
                        if dt.attrib.get("zone") == "UTC":
                            ts = dt.findtext("timeStamp")
                            if ts and len(ts) >= 10:
                                iso_time = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}T{ts[8:10]}:{ts[10:12] if len(ts) >= 12 else '00'}:00+00:00"
                                break

            if not iso_time:
                continue

            temp_str = h.findtext("temperature")
            temp_c = float(temp_str) if temp_str is not None else None

            wind_speed_str = h.findtext("wind/speed")
            wind_kmh = 0.0
            if wind_speed_str:
                if wind_speed_str.strip().lower() == "calm":
                    wind_kmh = 0.0
                else:
                    try:
                        wind_kmh = float(wind_speed_str)
                    except ValueError:
                        wind_kmh = 0.0

            wind_gust_str = h.findtext("wind/gust")
            gust_kmh = float(wind_gust_str) if (wind_gust_str and wind_gust_str.strip()) else None

            precip_str = h.findtext("lop")
            precip_prob_pct = float(precip_str) if precip_str is not None else 0.0

            hourly.append({
                "time": iso_time,
                "temp_c": temp_c,
                "wind_kmh": wind_kmh,
                "gust_kmh": gust_kmh,
                "precip_prob_pct": precip_prob_pct
            })

        # Parse ECCC currentConditions
        cc_elem = root.find(".//currentConditions")
        eccc_cc = {}
        if cc_elem is not None:
            eccc_temp = cc_elem.findtext("temperature")
            eccc_rh = cc_elem.findtext("relativeHumidity")
            eccc_ws = cc_elem.findtext("wind/speed")
            eccc_wg = cc_elem.findtext("wind/gust")
            eccc_wd = cc_elem.findtext("wind/direction")

            if eccc_ws is not None:
                if str(eccc_ws).strip().lower() == "calm":
                    ws_val = 0.0
                else:
                    try:
                        ws_val = float(eccc_ws)
                    except ValueError:
                        ws_val = 0.0
            else:
                ws_val = None

            eccc_cc = {
                "temp_c": float(eccc_temp) if eccc_temp is not None else None,
                "rh_pct": float(eccc_rh) if eccc_rh is not None else None,
                "wind_kmh": ws_val,
                "gust_kmh": float(eccc_wg) if (eccc_wg and eccc_wg.strip()) else None,
                "wind_dir": eccc_wd
            }
            if eccc_cc["temp_c"] is not None and eccc_cc["rh_pct"] is not None and eccc_cc["rh_pct"] > 0:
                T = eccc_cc["temp_c"]
                RH = eccc_cc["rh_pct"]
                gamma = math.log(RH / 100.0) + (17.62 * T) / (243.12 + T)
                eccc_cc["dewpt_c"] = round((243.12 * gamma) / (17.62 - gamma), 1)
            else:
                eccc_cc["dewpt_c"] = None

        # Fetch Wunderground PWS if present
        pws_obs = None
        if pws and wu_key:
            wu_url = f"https://api.weather.com/v2/pws/observations/current?stationId={pws}&format=json&units=m&numericPrecision=decimal&apiKey={wu_key}"
            try:
                wu_req = urllib.request.Request(wu_url, headers={"User-Agent": "HermesVineyard/1.0"})
                with urllib.request.urlopen(wu_req, timeout=10) as wu_resp:
                    wu_data = json.loads(wu_resp.read().decode("utf-8"))
                    obs_list = wu_data.get("observations", [])
                    if obs_list:
                        obs = obs_list[0]
                        m = obs.get("metric", {})
                        epoch = obs.get("epoch")
                        obs_age_m = (now.timestamp() - epoch) / 60.0 if epoch else None
                        pws_obs = {
                            "station_id": pws,
                            "temp_c": m.get("temp"),
                            "dewpt_c": m.get("dewpt"),
                            "rh_pct": obs.get("humidity"),
                            "wind_kmh": m.get("windSpeed"),
                            "gust_kmh": m.get("windGust"),
                            "wind_dir": obs.get("winddir"),
                            "precip_total": m.get("precipTotal"),
                            "age_minutes": round(obs_age_m, 1) if obs_age_m else None
                        }
            except Exception as e:
                print(f"Error fetching PWS {pws}: {e}")

        results[key] = {
            "site": key,
            "label": site["label"],
            "station": site["eccc_station"],
            "distance_km": site["station_distance_km"],
            "pub_dt_utc": pub_dt.isoformat() if pub_dt else None,
            "age_hours": round(age_hours, 2),
            "hourly": hourly,
            "eccc_cc": eccc_cc,
            "pws_obs": pws_obs
        }

    with open("/tmp/weather_fetch_data.json", "w") as out_f:
        json.dump(results, out_f, indent=2)
    print("Done. Saved to /tmp/weather_fetch_data.json")

if __name__ == "__main__":
    fetch_weather()
