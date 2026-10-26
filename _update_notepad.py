import sqlite3

db_path = "/home/waris/.hermes/state.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

full_state = {
  "scan_date": "2026-10-12",
  "drought": "4",
  "drought_level_okanagan": 4,
  "drought_updated": "2026-09-03",
  "drought_note": "Province-level Okanagan basin drought level unchanged at 4; local municipal restrictions steady (Penticton Stage 2, Naramata Stage 2, Oliver Eased Stage 2/1, Osoyoos Stage 3).",
  "restrictions": {
    "penticton": "Stage 2 (Ag -20% mandatory)",
    "naramata_rdos": "Stage 2",
    "oliver": "Domestic Stage 2, Irrigation Stage 1 removed; basin drought level 4",
    "osoyoos": "Stage 3 (Districts 8 & 9)"
  },
  "EFP": {
    "status": "ON FILE - owner-confirmed 2026-09-16",
    "cost_share": "n/a",
    "note": "Confirmed requests open on bciaf.ca/programs 2026-10-12."
  },
  "BMP": {
    "status": "open-until-2026-10-31",
    "stream": "Extreme Weather: FireSmart BC Farm & Ranch Assessment (P&D)",
    "cost_share": "100%",
    "deadline": "2026-10-31",
    "days_remaining": 19,
    "confirmed_live_2026-10-12": True,
    "project": {
      "block": "Rust (Oliver bench) / portfolio perimeter",
      "acres": 12.0,
      "practice": "FireSmart Farm and Extreme Weather Preparedness Assessment",
      "est_cost_cad": 3500,
      "est_share_cad": 3500,
      "qualifies_because": "wildfire and extreme weather risk plan for high-risk benchland; EFP not required for this stream"
    }
  },
  "BMP_main": {
    "status": "closed-next-intake-winter-2026",
    "stream": "Water Infrastructure / Irrigation Efficiency (and other non-EWP BMP categories)",
    "cost_share": "50-100% depending on category",
    "confirmed_via": "bciaf.ca/programs 2026-10-12: Closed, Winter 2026 reopen stated",
    "project": {
      "block": "Upper Bench (Penticton) & Oliver blocks",
      "acres": 70.0,
      "practice": "drip retrofit & irrigation scheduling automation",
      "est_cost_cad": 25000,
      "est_share_cad": 12500,
      "qualifies_because": "irrigation efficiency BMP under Stage 2/3 drought restrictions; EFP prerequisite already satisfied; awaiting reopen window"
    },
    "qualifies_note": "EFP prerequisite MET. Still CLOSED 2026-10-12 - did NOT transition to open this scan, so owner special irrigation-grant alert does not fire."
  },
  "AWIP": {
    "status": "not-accepting-applications-2026-10-12",
    "stream": "Stream 1 (Producer) and Stream 2 (Community) Not Accepting Applications / Coming Soon on bciaf.ca/programs.",
    "cost_share": "Stream 1: 50% max $1M",
    "project": None
  },
  "ERP": {
    "status": "stream2-wine-grape-opens-2026-11-03",
    "stream": "Stream 2: Wine Grape Replant",
    "cost_share": "cost-share per vine/acre",
    "open_date": "2026-11-03",
    "close_date": "2026-12-01",
    "days_until_open": 22,
    "confirmed_live_2026-10-12": True,
    "project": {
      "block": "Hwy 97 / Cassini (Oliver)",
      "acres": 5.0,
      "practice": "winter freeze vine replant with climate-resilient varieties",
      "est_cost_cad": 30000,
      "est_share_cad": 15000,
      "qualifies_because": "replanting winter-damaged vinifera acreage; intake window Nov 3-Dec 1 2026"
    }
  },
  "CAF": {"status": "closed-for-2026-27", "project": None},
  "Food_Safety": {"status": "closed-next-intake-january-2027", "project": None},
  "programs": {
    "EFP": "on-file-owner-confirmed",
    "BMP_FireSmart": "open-until-2026-10-31",
    "BMP_main": "closed-next-intake-winter-2026",
    "ERP_wine_grape": "opens-2026-11-03-closes-2026-12-01",
    "AWIP_stream1_producer": "closed-not-accepting",
    "CAF": "closed-for-2026-27",
    "Food_Safety": "closed-next-intake-january-2027"
  },
  "EFP_prereq_met": True,
  "last_full_live_scan_2026-10-12": True,
  "irrigation_grant_alert_status": "BMP main / water infrastructure remains CLOSED this scan - no open-transition, no owner alert sent 2026-10-12"
}

# Find job_id for grants_watch in cron notepad table or update via hermes cli
# Let's check table name in state.db
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
print("Tables:", cursor.fetchall())
conn.close()
