"""
Coverage for the monthly batch cadence added to MKT-LI1 2026-07-23
(replacing the old weekly 4/week model): _compute_schedule spreads a
batch across a target month on Tue/Wed/Thu at 9am ET, and
_current_batch_month gives the default when none is passed in.
"""
from datetime import date

import agents.marketing.mkt_li1_linkedin_brand as li1


def test_compute_schedule_returns_one_datetime_per_post():
    schedule = li1._compute_schedule("2026-08", 12)
    assert len(schedule) == 12


def test_compute_schedule_only_uses_configured_weekdays():
    schedule = li1._compute_schedule("2026-08", 12)
    for dt in schedule:
        assert dt.weekday() in li1.POST_WEEKDAYS


def test_compute_schedule_is_chronologically_increasing():
    schedule = li1._compute_schedule("2026-08", 12)
    assert schedule == sorted(schedule)


def test_compute_schedule_uses_configured_hour_and_et_timezone():
    schedule = li1._compute_schedule("2026-08", 3)
    for dt in schedule:
        assert dt.hour == li1.POST_HOUR_ET
        assert str(dt.tzinfo) == "America/New_York"


def test_compute_schedule_stays_within_target_month_for_a_normal_batch_size():
    # 12 posts at 3 weekdays/week fits inside a single calendar month.
    schedule = li1._compute_schedule("2026-08", 12)
    assert all(dt.year == 2026 and dt.month == 8 for dt in schedule)


def test_compute_schedule_spills_into_next_month_rather_than_dropping_a_post():
    # August 2026 has ~13 Tue/Wed/Thu slots; requesting more than the month
    # can hold must roll forward, never silently drop a post.
    schedule = li1._compute_schedule("2026-08", 20)
    assert len(schedule) == 20
    assert not all(dt.month == 8 for dt in schedule)


def test_current_batch_month_format(monkeypatch):
    assert li1._current_batch_month(today=date(2026, 3, 5)) == "2026-03"
