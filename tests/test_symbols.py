from hello_coin.symbols import base_asset


def test_base_asset_strips_usdt():
    assert base_asset("BTCUSDT") == "BTC"


def test_base_asset_strips_usd():
    assert base_asset("ethusd") == "ETH"


def test_base_asset_leaves_plain_symbol():
    assert base_asset("HYPE") == "HYPE"


def test_base_asset_does_not_strip_whole_symbol():
    assert base_asset("USDT") == "USDT"
