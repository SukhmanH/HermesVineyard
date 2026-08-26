"""Typed settings, loaded from .env + config/settings.yaml.

Secrets live in the environment (Hermes Agent routes them to ~/.hermes/.env); everything
tunable lives in settings.yaml so the owner can adjust a spray threshold without touching code.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parent.parent


class Site(BaseModel):
    key: str
    label: str
    lat: float
    lon: float
    eccc_citypage: str | None = None
    # Only Penticton has a station of its own; the other two borrow the nearest. Carry the
    # station name and distance so a brief can say WHERE a marginal reading came from -
    # "Osoyoos, 18 km south" is honest, presenting it as Oliver's weather is not.
    eccc_station: str | None = None
    station_distance_km: float | None = None
    # Hyper-local personal weather station (Wunderground/PWS) near this site. Observations only -
    # never forecasts. Gives humidity and dew point at (near) the vines themselves, which the
    # ECCC citypage stations cannot. Station IDs resolved 2026-08-25.
    wunderground_pws: str | None = None


class SprayWindow(BaseModel):
    """Thresholds for compute_spray_window(). Tuned with the owner, not guessed."""

    wind_min_kmh: float = 3.0  # dead calm = inversion drift risk, not safe
    wind_max_kmh: float = 15.0
    gust_max_kmh: float = 25.0
    temp_min_c: float = 8.0
    temp_max_c: float = 28.0  # product max_temp_c overrides (sulfur ~30 phytotoxicity)
    rain_prob_max_pct: float = 30.0
    rain_free_hours_after: int = 4
    min_window_hours: int = 2
    day_start_hour: int = 5
    day_end_hour: int = 21
    max_data_age_hours: float = 6.0  # older than this is STALE -> fail-safe NO


class Frost(BaseModel):
    threshold_c: float = 2.0
    watch_windows: list[dict[str, str]] = Field(
        default_factory=lambda: [
            {"from": "03-01", "to": "05-31"},
            {"from": "09-15", "to": "11-15"},
        ]
    )


class Irrigation(BaseModel):
    """Crop coefficients and the deficit strategy. Owner-set, because these are FARMING
    decisions, not facts: Kc varies with canopy and training, and how much deficit you run
    post-veraison is a quality choice the winemaker has an opinion about."""

    kc_default: float = 0.6           # mid-season wine grape, VSP, moderate canopy
    kc_by_stage: dict[str, float] = Field(
        default_factory=lambda: {
            "budbreak": 0.3, "bloom": 0.5, "fruitset": 0.7,
            "veraison": 0.6, "post_veraison": 0.45, "postharvest": 0.4,
        }
    )
    # Deliberate under-watering to concentrate flavour and check vegetative growth. 1.0 = full
    # replacement. Wine grapes are commonly farmed well under that after veraison.
    deficit_fraction: float = 0.7
    # Below this, a deficit is not worth a message.
    deficit_alert_mm: float = 20.0


class Autonomy(BaseModel):
    """docs/01 §D8 — Hermes leads; these are the few hard edges.

    These are enforced in tools rather than stated in prompts, because an eager agent on an
    eventful day would sail straight past an instruction.
    """

    max_unsolicited_dm_per_contact_per_day: int = 3  # safety messages exempt
    quiet_hours: dict[str, str] = Field(
        default_factory=lambda: {"from": "21:00", "to": "05:30"}
    )
    # Job names allowed to deliver inside quiet hours. The grower asked for a 04:30 report;
    # that request IS the consent, recorded here so the exemption stays explicit and narrow.
    quiet_hours_exempt_jobs: list[str] = Field(default_factory=lambda: ["grower_daily_report"])
    may_message_managers_anytime: bool = True
    escalate_to_owner_after_failed_nudges: int = 3
    log_every_decision: bool = True


class Listings(BaseModel):
    """The owner's property-hunt filter (docs/08 Phase 2). listings_poll applies this before
    anything reaches the owner; tune with the owner, not by guessing their budget."""

    areas: list[str] = Field(default_factory=list)
    min_acres: float = 2.0
    max_price: float | None = None
    keywords: list[str] = Field(
        default_factory=lambda: ["vineyard", "grape", "winery", "acreage", "farm"]
    )


class Settings(BaseModel):
    db_path: Path
    media_dir: Path
    export_dir: Path
    backup_dir: Path
    timezone: str = "America/Vancouver"

    sites: list[Site] = Field(default_factory=list)
    spray_window: SprayWindow = Field(default_factory=SprayWindow)
    frost: Frost = Field(default_factory=Frost)
    irrigation: Irrigation = Field(default_factory=Irrigation)
    autonomy: Autonomy = Field(default_factory=Autonomy)
    listings: Listings = Field(default_factory=Listings)
    wunderground_api_key: str | None = None

    draft_ttl_hours: int = 24
    emergency_keywords: list[str] = Field(
        default_factory=lambda: ["emergencia", "accidente", "ayuda urgente", "911"]
    )

    def site(self, key: str) -> Site | None:
        return next((s for s in self.sites if s.key == key), None)


def _resolve(raw: str | None, default: str) -> Path:
    """Resolve a path from env, relative to the repo root when not absolute.

    Relative-by-default matters: the same settings work on the Windows build machine and on the
    Ubuntu host without editing four env vars at migration time.
    """
    p = Path(raw or default)
    return p if p.is_absolute() else (REPO_ROOT / p)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(REPO_ROOT / ".env", override=False)

    settings_file = _resolve(os.getenv("SETTINGS_PATH"), "config/settings.yaml")
    data: dict = {}
    if settings_file.exists():
        data = yaml.safe_load(settings_file.read_text(encoding="utf-8")) or {}

    return Settings(
        db_path=_resolve(os.getenv("DB_PATH"), "data/hermes.db"),
        media_dir=_resolve(os.getenv("MEDIA_DIR"), "data/media"),
        export_dir=_resolve(os.getenv("EXPORT_DIR"), "exports"),
        backup_dir=_resolve(os.getenv("BACKUP_DIR"), "backups"),
        timezone=os.getenv("TZ") or data.get("timezone") or "America/Vancouver",
        sites=[Site(**s) for s in data.get("sites", [])],
        spray_window=SprayWindow(**(data.get("spray_window") or {})),
        frost=Frost(**(data.get("frost") or {})),
        irrigation=Irrigation(**(data.get("irrigation") or {})),
        autonomy=Autonomy(**(data.get("autonomy") or {})),
        listings=Listings(**(data.get("listings") or {})),
        wunderground_api_key=(data.get("weather_sources") or {}).get("wunderground_api_key"),
        draft_ttl_hours=int(data.get("draft_ttl_hours", 24)),
        emergency_keywords=(data.get("safety") or {}).get(
            "emergency_keywords", ["emergencia", "accidente", "ayuda urgente", "911"]
        ),
    )


