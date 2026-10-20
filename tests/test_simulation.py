"""End-to-end regression tests: fly each scenario against the full tracker and a simulated camera."""
import pytest

from tests.conftest import make_config
from tracker.simulation import FakeClock, run_simulation


@pytest.mark.parametrize("scenario", ["orbit", "flyby", "pair", "takeoff"])
def test_scenarios_stay_in_frame(tmp_path, scenario):
    result = run_simulation(make_config(tmp_path), scenario)
    assert result["tracked_seconds"] > 30
    assert result["in_frame_pct"] >= 97, result


def test_overhead_pass_does_not_crash(tmp_path):
    # Azimuth swings 180° almost instantly overhead, and the drone goes above the tilt limit; just keep going
    result = run_simulation(make_config(tmp_path), "overhead")
    assert result["in_frame_pct"] > 80


def test_v2_is_smoother_than_v1_style_control(tmp_path):
    cfg = make_config(tmp_path)
    v2 = run_simulation(cfg, "orbit")
    cfg["control"].update(mode="position", min_step=4.0, lookahead=0.0)
    v1_style = run_simulation(cfg, "orbit")
    assert v2["rms_pan_accel"] < v1_style["rms_pan_accel"] / 2
    assert v2["in_frame_pct"] > v1_style["in_frame_pct"]


def test_auto_waits_for_takeoff(tmp_path):
    result = run_simulation(make_config(tmp_path), "takeoff")
    first_active = next(e for e in result["events"] if e["type"] == "track_active")
    # The drone sits on the ground for 15 s before climbing past min_height
    assert first_active["t"] - FakeClock().t > 15
