from datetime import date

from restaurantos.nightly_schedule import aligned_month_windows


def test_aligned_month_windows_match_day_of_month():
    current, previous = aligned_month_windows(date(2026, 8, 20))

    assert current.start_date == date(2026, 8, 1)
    assert current.end_date == date(2026, 8, 20)
    assert current.label == "August 1-20"
    assert previous.start_date == date(2026, 7, 1)
    assert previous.end_date == date(2026, 7, 20)
    assert previous.label == "July 1-20"


def test_previous_window_caps_at_shorter_month_end():
    current, previous = aligned_month_windows(date(2026, 3, 31))

    assert current.start_date == date(2026, 3, 1)
    assert current.end_date == date(2026, 3, 31)
    assert previous.start_date == date(2026, 2, 1)
    assert previous.end_date == date(2026, 2, 28)
    assert previous.label == "February 1-28"


def test_first_day_compares_to_first_day_of_previous_month():
    current, previous = aligned_month_windows(date(2027, 1, 1))

    assert current.start_date == date(2027, 1, 1)
    assert current.end_date == date(2027, 1, 1)
    assert current.label == "January 1"
    assert previous.start_date == date(2026, 12, 1)
    assert previous.end_date == date(2026, 12, 1)
    assert previous.label == "December 1"
