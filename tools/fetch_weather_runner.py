import json
import math
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import httpx

SITES = [
    {"key": "penticton", "code": "s0000772", "pws": "IPENTI39", "name": "Penticton (2 km)"},
    {"key": "naramata", "code": "s0000351", "pws": "IBCNARAM1", "name": "Summerland (6 km, across lake)"},
    {"key": "oliver", "code": "s0000397", "pws": None, "name": "Osoyoos (18 km south)"}
]

WU_API_KEY = "6532d6454b8aa370768e63d6ba5a832e"

def fetch_eccc_forecast(site_code):
    now_utc = datetime.now(UTC)
    # Walk back 0, 1, 2, 3 hours
    for back in range(4):
        target_h = (now_utc.hour - back) % 24
        dir_url = f"https://dd.weather.gc.ca/today/citypage_weather/BC/{target_h:02d}/"
        try:
            r = httpx.get(dir_url, timeout=10.0, follow_redirects=True)
            if r.status_code != 200:
                continue
            pattern = re.compile(r'(\d{8}T\d{6}\.\d+Z)_MSC_CitypageWeather_' + re.escape(site_code) + r'_en\.xml')
            matches = pattern.findall(r.text)
            if matches:
                latest = sorted(matches)[-1]
                file_url = f"{dir_url}{latest}_MSC_CitypageWeather_{site_code}_en.xml"
                resp_file = httpx.get(file_url, timeout=15.0, follow_redirects=True)
                if resp_file.status_code == 200:
                    return resp_file.text
        except Exception:
            continue
    return None

def parse_eccc_xml(xml_text):
    root = ET.fromstring(xml_text)

    # Check xmlCreation dateTime UTC
    age_hours = 0.5
    for dt in root.findall(".//dateTime"):
        if dt.attrib.get("name") == "xmlCreation" and dt.attrib.get("zone") == "UTC":
            ts_str = dt.findtext("timeStamp") # e.g. 20261009190102
            if ts_str and len(ts_str) >= 12:
                try:
                    pub_dt = datetime(
                        int(ts_str[0:4]), int(ts_str[4:6]), int(ts_str[6:8]),
                        int(ts_str[8:10]), int(ts_str[10:12]), int(ts_str[12:14]) if len(ts_str) >= 14 else 0,
                        tzinfo=UTC
                    )
                    now_utc = datetime.now(UTC)
                    age_hours = round((now_utc - pub_dt).total_seconds() / 3600.0, 2)
                except Exception:
                    pass

    # Hourly forecast
    hourly = []
    # Dump first hourlyForecast xml to inspect
    h_first = root.find(".//hourlyForecastGroup/hourlyForecast")
    if h_first is not None:
        with open("/tmp/hourly_sample.xml", "w") as f:
            f.write(ET.tostring(h_first, encoding="utf-8").decode("utf-8"))

    for h in root.findall(".//hourlyForecastGroup/hourlyForecast"):
        # dateTimeUTC attribute: <hourlyForecast dateTimeUTC="202610092000">
        dt_str = h.attrib.get("dateTimeUTC")
        iso_time = None
        if dt_str and len(dt_str) >= 12:
            iso_time = f"{dt_str[0:4]}-{dt_str[4:6]}-{dt_str[6:8]}T{dt_str[8:10]}:{dt_str[10:12]}:00+00:00"
        else:
            for dt in h.findall("dateTime"):
                if dt.attrib.get("zone") == "UTC":
                    ts = dt.findtext("timeStamp")
                    if ts and len(ts) >= 10:
                        iso_time = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}T{ts[8:10]}:{ts[10:12]}:00+00:00"
                        break

        temp_el = h.findtext("temperature")
        temp_c = float(temp_el) if temp_el else None

        wind_sp = h.findtext("wind/speed")
        wind_kmh = 0.0
        if wind_sp:
            if wind_sp.strip().lower() == "calm":
                wind_kmh = 0.0
            else:
                try:
                    wind_kmh = float(wind_sp)
                except ValueError:
                    wind_kmh = 0.0

        wind_dir = h.findtext("wind/direction")

        wind_gst = h.findtext("wind/gust")
        gust_kmh = float(wind_gst) if wind_gst and wind_gst.strip() else None

        lop = h.findtext("lop")
        precip_prob_pct = float(lop) if lop else 0.0

        condition = h.findtext("condition")

        if iso_time:
            hourly.append({
                "time": iso_time,
                "temp_c": temp_c,
                "wind_kmh": wind_kmh,
                "wind_dir": wind_dir,
                "gust_kmh": gust_kmh,
                "precip_prob_pct": precip_prob_pct,
                "condition": condition
            })

    # currentConditions from ECCC
    cc = root.find(".//currentConditions")
    cc_data = {}
    if cc is not None:
        cc_temp = cc.findtext("temperature")
        cc_rh = cc.findtext("relativeHumidity")
        cc_wind_sp = cc.findtext("wind/speed")
        cc_wind_dir = cc.findtext("wind/direction")
        cc_wind_kmh = 0.0
        if cc_wind_sp:
            if cc_wind_sp.strip().lower() == "calm":
                cc_wind_kmh = 0.0
            else:
                try:
                    cc_wind_kmh = float(cc_wind_sp)
                except ValueError:
                    cc_wind_kmh = 0.0

        cc_wind_gst = cc.findtext("wind/gust")
        cc_wind_gst_val = None
        if cc_wind_gst and cc_wind_gst.strip():
            try:
                cc_wind_gst_val = float(cc_wind_gst)
            except ValueError:
                pass

        cc_dewpt = cc.findtext("dewpoint")
        cc_dewpt_val = float(cc_dewpt) if cc_dewpt else None

        cc_data = {
            "temp_c": float(cc_temp) if cc_temp else None,
            "rh_pct": float(cc_rh) if cc_rh else None,
            "wind_kmh": cc_wind_kmh,
            "wind_dir": cc_wind_dir,
            "gust_kmh": cc_wind_gst_val,
            "dewpt_c": cc_dewpt_val
        }
        if cc_data["dewpt_c"] is None and cc_data["temp_c"] is not None and cc_data["rh_pct"] is not None:
            T = cc_data["temp_c"]
            RH = cc_data["rh_pct"]
            if RH > 0:
                gamma = math.log(RH/100.0) + (17.62 * T) / (243.12 + T)
                cc_data["dewpt_c"] = round((243.12 * gamma) / (17.62 - gamma), 1)

    return {"hourly": hourly, "current": cc_data, "age_hours": age_hours}

def fetch_wu_current(station_id):
    url = f"https://api.weather.com/v2/pws/observations/current?stationId={station_id}&format=json&units=m&numericPrecision=decimal&apiKey={WU_API_KEY}"
    try:
        r = httpx.get(url, timeout=10.0)
        if r.status_code == 200:
            data = r.json()
            obs = data["observations"][0]
            metric = obs["metric"]
            return {
                "station_id": station_id,
                "temp_c": metric.get("temp"),
                "dewpt_c": metric.get("dewpt"),
                "rh_pct": obs.get("humidity"),
                "wind_kmh": metric.get("windSpeed"),
                "wind_gust": metric.get("windGust"),
                "wind_dir": obs.get("winddir"),
                "epoch": obs.get("epoch")
            }
    except Exception:
        return None
    return None

def main():
    results = {}
    for s in SITES:
        key = s["key"]
        xml = fetch_eccc_forecast(s["code"])
        if not xml:
            results[key] = {"error": "Failed to fetch ECCC XML"}
            continue
        parsed = parse_eccc_xml(xml)

        pws_obs = None
        if s["pws"]:
            pws_obs = fetch_wu_current(s["pws"])

        results[key] = {
            "site": key,
            "station_name": s["name"],
            "hourly": parsed["hourly"],
            "eccc_current": parsed["current"],
            "pws_current": pws_obs,
            "age_hours": parsed["age_hours"]
        }

    with open("/tmp/weather_fetch_result.json", "w") as f:
        json.dump(results, f)
    print("SUCCESS: Weather data fetched and saved to /tmp/weather_fetch_result.json")

if __name__ == "__main__":
    main()
