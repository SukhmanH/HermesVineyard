"""Grower-entered estimates are scenarios, never new operational records."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def scenario():
    return {
        "block_name": "Upper Bench",
        "sampled_on": "2026-09-16",
        "bearing_vines": 1000,
        "clusters_per_sampled_vine": [20, 30, 10],
        "harvest_cluster_weight_g": {"low": 100, "expected": 150, "high": 200},
        "weight_basis": "Block harvest weights from previous seasons",
        "bin_payload_kg": 400,
    }


def run_cli(tmp_path, data):
    source = tmp_path / "scenario.json"
    source.write_text(json.dumps(data))
    before = source.read_bytes()
    result = subprocess.run(
        [sys.executable, "-m", "tools.plan_harvest", str(source)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert source.read_bytes() == before
    return result


def test_cli_estimates_metric_crop_and_whole_bins(tmp_path):
    result = run_cli(tmp_path, scenario())
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["block_name"] == "Upper Bench"
    assert data["mean_clusters_per_vine"] == 20
    assert data["sampled_vines"] == 3
    assert data["scenarios"]["expected"] == {
        "kg": 3000, "metric_tonnes": 3, "bins": 8,
    }
    assert data["scenarios"]["low"]["kg"] == 2000
    assert data["scenarios"]["high"]["kg"] == 4000
    assert data["estimate_only"] is True
    assert data["recorded"] is False
    assert data["inputs"] == scenario()
    assert "not_a_confidence_interval" in data["cautions"]


@pytest.mark.parametrize("field,value", [
    ("bearing_vines", True), ("bearing_vines", -1), ("bearing_vines", 2.5),
    ("bearing_vines", None), ("clusters_per_sampled_vine", []),
    ("clusters_per_sampled_vine", [1, -1]),
    ("clusters_per_sampled_vine", [True]),
    ("clusters_per_sampled_vine", [2.5]),
    ("clusters_per_sampled_vine", [float("nan")]),
    ("bin_payload_kg", 0), ("bin_payload_kg", float("inf")),
    ("bin_payload_kg", "400"), ("sampled_on", "2026-02-30"),
    ("sampled_on", "20260916"), ("block_name", "  "), ("weight_basis", ""),
    ("harvest_cluster_weight_g", {"low": 200, "expected": 150, "high": 100}),
    ("harvest_cluster_weight_g", {"low": 100, "expected": 150}),
    ("harvest_cluster_weight_g", {"low": -1, "expected": 150, "high": 200}),
    ("harvest_cluster_weight_g", {"low": 100, "expected": True, "high": 200}),
])
def test_invalid_scenario_fails_cleanly(tmp_path, field, value):
    data = scenario()
    data[field] = value
    result = run_cli(tmp_path, data)
    assert result.returncode == 2
    assert not result.stdout
    assert "Traceback" not in result.stderr


def test_sample_cannot_exceed_bearing_vines(tmp_path):
    data = scenario()
    data["bearing_vines"] = 2
    result = run_cli(tmp_path, data)
    assert result.returncode == 2


@pytest.mark.parametrize("data", [None, [], {}, {"block_name": "Upper Bench"}])
def test_missing_input_is_not_invented(tmp_path, data):
    result = run_cli(tmp_path, data)
    assert result.returncode == 2
    assert not result.stdout
    assert "Traceback" not in result.stderr


def test_zero_crop_is_not_missing(tmp_path):
    data = scenario()
    data["clusters_per_sampled_vine"] = [0, 0, 0]
    result = run_cli(tmp_path, data)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["scenarios"]["expected"]["bins"] == 0

