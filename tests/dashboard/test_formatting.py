from datetime import UTC, datetime

from hello_coin.dashboard.formatting import (
    coin_panel_id,
    format_age,
    format_direction,
    format_event_leverage,
    format_number,
    format_position_leverage,
    format_wallet,
    position_side_label,
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
