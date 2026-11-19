import pytest

from tello_controller.diagnostics import LED_TABLE, BatteryMonitor


def fly(monitor, start_pct, pct_per_min, seconds, step=1.0, t0=0.0):
    t = t0
    while t <= t0 + seconds:
        monitor.update(t, int(start_pct - pct_per_min * (t - t0) / 60), flying=True)
        t += step
    return t


def test_needs_enough_data_before_judging():
    m = BatteryMonitor()
    fly(m, 90, 8, 20)
    r = m.report(88)
    assert r.drain_pct_per_min is None
    assert r.verdict[1] == "info"


def test_healthy_drain():
    m = BatteryMonitor()
    fly(m, 95, 7.5, 120)
    r = m.report(80)
    assert r.drain_pct_per_min == pytest.approx(7.5, abs=1.0)
    assert r.verdict[1] == "ok"
    assert r.est_minutes_left == pytest.approx(80 / r.drain_pct_per_min)


def test_fast_drain_flags_worn_battery():
    m = BatteryMonitor()
    fly(m, 95, 16, 90)
    text, severity = m.report(70).verdict
    assert severity == "bad" and "worn" in text


def test_sudden_drop_detected():
    m = BatteryMonitor()
    t = fly(m, 80, 7, 30)
    m.update(t, 70, flying=True)  # 76% -> 70% in a second: voltage sag
    assert m.sudden_drops == 1
    fly(m, 70, 7, 60, t0=t + 1)
    assert m.report(63).verdict[1] == "bad"


def test_ground_time_is_ignored_and_resets_window():
    m = BatteryMonitor()
    fly(m, 95, 8, 60)
    m.update(61, 85, flying=False)
    assert m.drain_pct_per_min() is None


def test_led_table_says_red_is_never_normal():
    reds = [row for row in LED_TABLE if row[0] == "red"]
    assert len(reds) == 3 and all(sev in ("warn", "bad") for *_, sev in reds)
