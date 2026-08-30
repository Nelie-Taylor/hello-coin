from datetime import UTC, datetime

from hello_coin.dashboard.formatting import (
    coin_panel_id,
    coin_skew,
    format_age,
    format_direction,
    format_event_leverage,
    format_number,
    format_position_leverage,
    format_wallet,
    position_side_label,
    side_class,
)


def test_format_number_handles_none_and_floats():
    assert format_number(None) == "unavailable"
    assert format_number(1234.5) == "1,234.5000"


def test_format_number_passes_through_strings():
    assert format_number("BTCUSDT") == "BTCUSDT"


def test_format_wallet_truncates_long_addresses():
    assert format_wallet("0x1234567890abcdef") == "0x12345…bcdef"
    assert format_wallet(None) == "N/A"


def test_format_age_computes_seconds_since_timestamp():
    now = datetime(2026, 8, 29, 0, 1, tzinfo=UTC)
    assert format_age("2026-08-29T00:00:30+00:00", now) == "30s"
    assert format_age(None, now) == "N/A"


def test_format_direction_maps_buy_and_sell():
    assert format_direction("buy") == "LONG (BUY)"
    assert format_direction("sell") == "SHORT (SELL)"
    assert format_direction(None) == "N/A"


def test_format_event_leverage_reads_nested_and_string_raw():
    assert format_event_leverage('{"leverage": {"type": "cross", "value": 7}}') == "7x"
    assert format_event_leverage("{}") == "N/A"
    assert format_event_leverage("not json") == "N/A"


def test_format_position_leverage_combines_type_and_value():
    assert format_position_leverage({"leverage": {"type": "cross", "value": 7}}) == "cross · 7x"
    assert format_position_leverage({}) == "N/A"


def test_position_side_label_maps_buy_and_sell():
    assert position_side_label("buy") == "LONG"
    assert position_side_label("sell") == "SHORT"
    assert position_side_label("other") == "N/A"


def test_coin_panel_id_slugifies_symbol():
    assert coin_panel_id("LINK") == "coin-link"
    assert coin_panel_id("BTC-PERP") == "coin-btc-perp"


def test_side_class_maps_buy_and_sell():
    assert side_class("buy") == "side-long"
    assert side_class("sell") == "side-short"
    assert side_class(None) == ""


def test_coin_skew_returns_dominant_long_label_and_class():
    rows = [
        {"side": "buy", "amount_usd": 820_000.0, "raw": {}},
        {"side": "sell", "amount_usd": 180_000.0, "raw": {}},
    ]
    assert coin_skew(rows) == ("LONG 82%", "side-long", "")


def test_coin_skew_returns_dominant_short_label_and_class():
    rows = [
        {"side": "buy", "amount_usd": 180_000.0, "raw": {}},
        {"side": "sell", "amount_usd": 820_000.0, "raw": {}},
    ]
    assert coin_skew(rows) == ("SHORT 82%", "side-short", "")


def test_coin_skew_returns_empty_for_no_rows():
    assert coin_skew([]) == ("", "", "")


def test_coin_skew_computes_weighted_average_entry_for_dominant_long_side():
    rows = [
        {"side": "buy", "amount_usd": 410_000.0, "raw": {"entryPx": "100"}},
        {"side": "buy", "amount_usd": 410_000.0, "raw": {"entryPx": "200"}},
        {"side": "sell", "amount_usd": 180_000.0, "raw": {"entryPx": "9999"}},
    ]
    assert coin_skew(rows) == ("LONG 82%", "side-long", "150.0000")


def test_coin_skew_computes_weighted_average_entry_for_dominant_short_side():
    rows = [
        {"side": "sell", "amount_usd": 410_000.0, "raw": {"entryPx": "50"}},
        {"side": "sell", "amount_usd": 410_000.0, "raw": {"entryPx": "70"}},
        {"side": "buy", "amount_usd": 180_000.0, "raw": {"entryPx": "9999"}},
    ]
    assert coin_skew(rows) == ("SHORT 82%", "side-short", "60.0000")


def test_coin_skew_ignores_rows_with_missing_or_invalid_entry_price():
    rows = [
        {"side": "buy", "amount_usd": 820_000.0, "raw": {"entryPx": "not-a-number"}},
        {"side": "sell", "amount_usd": 180_000.0, "raw": {}},
    ]
    assert coin_skew(rows) == ("LONG 82%", "side-long", "")
