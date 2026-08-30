from hello_coin.ingestion.position_skew import SkewAlert, SkewTracker, compute_skew, next_zone


def test_compute_skew_returns_zero_zero_for_zero_total():
    assert compute_skew(0, 0) == (0.0, 0.0)


def test_compute_skew_splits_long_and_short_percentages():
    assert compute_skew(800_000, 200_000) == (0.8, 0.2)


def test_next_zone_enters_long_dominant_above_75_percent():
    assert next_zone("neutral", 0.80, 0.20) == "long_dominant"


def test_next_zone_enters_short_dominant_above_75_percent():
    assert next_zone("neutral", 0.20, 0.80) == "short_dominant"


def test_next_zone_stays_neutral_in_dead_zone():
    assert next_zone("neutral", 0.72, 0.28) == "neutral"


def test_next_zone_stays_long_dominant_within_dead_zone():
    assert next_zone("long_dominant", 0.72, 0.28) == "long_dominant"


def test_next_zone_exits_long_dominant_below_70_percent():
    assert next_zone("long_dominant", 0.65, 0.35) == "neutral"


def test_next_zone_exits_short_dominant_below_70_percent():
    assert next_zone("short_dominant", 0.35, 0.65) == "neutral"


def test_tracker_stays_neutral_with_no_positions_ever_observed():
    tracker = SkewTracker()

    assert tracker.update("LINK", 0, 0) is None


def test_tracker_emits_enter_alert_on_first_crossing():
    tracker = SkewTracker()

    alert = tracker.update("LINK", 800_000, 200_000)

    assert alert == SkewAlert("LINK", "long_dominant", "enter", 800_000, 200_000, 0.8, 0.2)


def test_tracker_stays_silent_while_remaining_in_dominant_zone():
    tracker = SkewTracker()
    tracker.update("LINK", 800_000, 200_000)

    assert tracker.update("LINK", 780_000, 220_000) is None


def test_tracker_emits_exit_alert_when_dropping_below_70_percent():
    tracker = SkewTracker()
    tracker.update("LINK", 800_000, 200_000)

    alert = tracker.update("LINK", 650_000, 350_000)

    assert alert == SkewAlert("LINK", "long_dominant", "exit", 650_000, 350_000, 0.65, 0.35)


def test_tracker_emits_exit_alert_when_all_positions_close():
    tracker = SkewTracker()
    tracker.update("LINK", 800_000, 200_000)

    alert = tracker.update("LINK", 0, 0)

    assert alert == SkewAlert("LINK", "long_dominant", "exit", 0, 0, 0.0, 0.0)


def test_tracker_tracks_each_coin_independently():
    tracker = SkewTracker()

    link_alert = tracker.update("LINK", 800_000, 200_000)
    sol_alert = tracker.update("SOL", 100_000, 900_000)

    assert link_alert.zone == "long_dominant"
    assert sol_alert.zone == "short_dominant"
