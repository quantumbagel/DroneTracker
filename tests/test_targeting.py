import pytest

from tracker.targeting import GROUP_HYSTERESIS, TargetSelector, TargetView, frame

FRAMING = {"drone_size": 1.0, "target_fraction": 0.2, "uncertainty_k": 2.0, "min_hfov": 0.0, "group": True,
           "max_group_hfov": 40.0, "group_fill": 0.8, "aspect": 16 / 9, "priority": []}


def view(drone_id, az, el=10.0, activated_at=0.0, size=1.0, uncertainty=0.0):
    return TargetView(drone_id, az, el, 0.0, 0.0, 100.0, size, uncertainty, activated_at)


def views(*items):
    return {v.drone_id: v for v in items}


def test_single_target_framing():
    aim = frame([view("a", 30, uncertainty=0.5)], FRAMING)
    assert (aim.az, aim.el) == (30, 10)
    assert aim.hfov == pytest.approx(1.0 / 0.2 + 2 * 2.0 * 0.5)


def test_min_hfov_floor():
    assert frame([view("a", 30, size=0.1)], {**FRAMING, "min_hfov": 4.0}).hfov == 4.0


def test_group_framing_across_the_180_seam():
    aim = frame([view("a", 179, el=0, size=0.1), view("b", -179, el=0, size=0.1)], FRAMING)
    assert abs(aim.az) == pytest.approx(180)
    assert aim.hfov == pytest.approx(2.1 / 0.8)  # 2° apart plus half a drone either side


def test_close_group_is_never_tighter_than_a_lone_drone():
    aim = frame([view("a", 0, el=0), view("b", 0.5, el=0)], FRAMING)
    assert aim.hfov == pytest.approx(1.0 / 0.2)


def test_group_framing_accounts_for_vertical_spread():
    aim = frame([view("a", 0, el=0), view("b", 0, el=10)], FRAMING)
    assert aim.el == pytest.approx(5)
    assert aim.hfov == pytest.approx(11 * 16 / 9 / 0.8)


def test_earliest_activated_drone_is_primary():
    selector = TargetSelector({**FRAMING, "group": False})
    assert selector.select(views(view("b", 0, activated_at=2), view("a", 90, activated_at=5))) == ("b",)


def test_priority_wins_and_switches_immediately():
    selector = TargetSelector({**FRAMING, "group": False, "priority": ["vip"]})
    assert selector.select(views(view("a", 0, activated_at=1))) == ("a",)
    assert selector.select(views(view("a", 0, activated_at=1), view("vip", 90, activated_at=9))) == ("vip",)


def test_incumbent_is_kept_against_equal_rank():
    selector = TargetSelector({**FRAMING, "group": False})
    assert selector.select(views(view("b", 0, activated_at=5))) == ("b",)
    # "a" activated earlier (e.g. it was briefly out of view) but "b" is already being filmed
    assert selector.select(views(view("a", 90, activated_at=1), view("b", 0, activated_at=5))) == ("b",)


def test_manual_selection_overrides_everything():
    selector = TargetSelector({**FRAMING, "priority": ["a"]})
    selector.manual = "c"
    assert selector.select(views(view("a", 0), view("c", 1))) == ("c",)
    selector.manual = None
    assert selector.select(views(view("a", 0), view("c", 1))) == ("a", "c")


def test_drones_are_grouped_only_while_they_fit():
    selector = TargetSelector(FRAMING)
    assert selector.select(views(view("a", 0, el=0), view("b", 20, el=0))) == ("a", "b")
    assert selector.select(views(view("a", 0, el=0), view("b", 90, el=0))) == ("a",)


def test_group_hysteresis():
    selector = TargetSelector(FRAMING)
    width_for = lambda hfov: hfov * 0.8 - 1.0  # noqa: E731 (azimuth gap giving a required hfov, at el 0)
    assert selector.select(views(view("a", 0, el=0), view("b", width_for(39), el=0))) == ("a", "b")
    # Needs 42°: over max_group_hfov, but "b" is already in the shot so it stays until 40 * GROUP_HYSTERESIS
    assert selector.select(views(view("a", 0, el=0), view("b", width_for(42), el=0))) == ("a", "b")
    assert selector.select(views(view("a", 0, el=0), view("b", width_for(40 * GROUP_HYSTERESIS + 1), el=0))) == ("a",)
    assert selector.select(views(view("a", 0, el=0), view("b", width_for(42), el=0))) == ("a",)


def test_nothing_to_film():
    assert TargetSelector(FRAMING).select({}) == ()
