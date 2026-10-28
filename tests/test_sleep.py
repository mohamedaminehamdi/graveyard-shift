"""The power log becomes nights; the forecast only uses what is known at lights-out."""
from datetime import datetime, timedelta

from graveyard_shift import sleep


def day(d, off, on):
    """Display off at `off` (hour, minute) on day d, back on next morning at `on`."""
    evening = datetime(2026, 10, d, 9, 0)
    return [(evening, True), (datetime(2026, 10, d, *off), False), (datetime(2026, 10, d + 1, *on), True)]


def test_slots_follow_the_display():
    events = [(datetime(2026, 10, 1, 18, 5), True), (datetime(2026, 10, 1, 18, 10), False)]
    assert sleep.on_fraction(events, datetime(2026, 10, 1, 18), 2) == [1 / 3, 0.0]


def test_nights_find_lights_out_and_waking():
    events = day(1, (23, 30), (7, 15)) + day(2, (23, 59), (8, 0))
    nights = sleep.nights(events)
    assert len(nights) == 1
    night = nights[0]
    assert night["evening"] + night["out"] * sleep.SLOT == datetime(2026, 10, 1, 23, 30)
    wake = sleep.first_wake(night["active"][night["out"]:], night["out"], 0.5)
    assert night["evening"] + wake * sleep.SLOT == datetime(2026, 10, 2, 7, 15)


def test_features_never_peek_at_the_morning():
    events = sum((day(d, (23, 30), (7, 0)) for d in range(1, 6)), [])
    history = sleep.nights(events)
    tonight = {"evening": history[-1]["evening"] + timedelta(days=1), "active": [1] * sleep.SLOTS, "out": 22}
    with_truth = sleep.rows(tonight, history, 22)
    tonight["active"] = [0] * sleep.SLOTS
    assert sleep.rows(tonight, history, 22) == with_truth


def test_deadline_adds_up_small_chances():
    probs = [0.0] * 8 + [0.05] * 20
    assert sleep.first_wake(probs, 0, 0.25) == sleep.SLOTS     # no single slot looks likely...
    assert sleep.deadline(probs, 0) == 8 + 5                    # ...but 1 - 0.95^6 > 25%
