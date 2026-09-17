"""Offline metric crop scenarios. No database, network, or harvest clearance.

Run from repository root: python -m tools.plan_harvest scenario.json
Based on NC State Extension, Winegrape Grower's Guide, Chapter 12:
bearing vines * representative mean clusters/vine * expected harvest cluster weight.
Weight scenarios are supplied by the grower, not statistical confidence bounds.
"""
import argparse
import json
import math
from datetime import date
from pathlib import Path
from statistics import mean


def _positive_number(value):
    return (type(value) in (int, float) and math.isfinite(value) and value > 0)


def _validate(data):
    if not isinstance(data, dict):
        raise ValueError("invalid_scenario_object")
    for key in ("block_name", "weight_basis"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"invalid_{key}")
    sampled_on = data.get("sampled_on")
    if not isinstance(sampled_on, str) or date.fromisoformat(sampled_on).isoformat() != sampled_on:
        raise ValueError("invalid_sampled_on")
    vines = data.get("bearing_vines")
    if type(vines) is not int or vines <= 0:
        raise ValueError("invalid_bearing_vines")
    counts = data.get("clusters_per_sampled_vine")
    if (not isinstance(counts, list) or not counts or len(counts) > vines
            or any(type(n) is not int or n < 0 for n in counts)):
        raise ValueError("invalid_clusters_per_sampled_vine")
    weights = data.get("harvest_cluster_weight_g")
    if (not isinstance(weights, dict) or set(weights) != {"low", "expected", "high"}
            or not all(_positive_number(w) for w in weights.values())
            or not weights["low"] <= weights["expected"] <= weights["high"]):
        raise ValueError("invalid_harvest_cluster_weight_g")
    if not _positive_number(data.get("bin_payload_kg")):
        raise ValueError("invalid_bin_payload_kg")


def estimate_crop(data):
    _validate(data)
    counts = data["clusters_per_sampled_vine"]
    average = mean(counts)
    scenarios = {}
    for name, weight in data["harvest_cluster_weight_g"].items():
        kg = data["bearing_vines"] * average * weight / 1000
        scenarios[name] = {
            "kg": kg, "metric_tonnes": kg / 1000,
            "bins": math.ceil(kg / data["bin_payload_kg"]),
        }
    return {
        "block_name": data["block_name"], "inputs": data,
        "mean_clusters_per_vine": average, "sampled_vines": len(counts),
        "scenarios": scenarios, "estimate_only": True, "recorded": False,
        "cautions": ["not_a_confidence_interval", "representative_sampling_required",
                     "harvest_weight_not_current_immature_weight",
                     "resample_after_thinning_or_crop_loss", "not_harvest_clearance"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text())
        output = json.dumps(estimate_crop(data), allow_nan=False)
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        parser.error(str(exc))
    print(output)


if __name__ == "__main__":
    main()
