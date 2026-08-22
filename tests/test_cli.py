from hello_coin.cli import build_parser


def test_ingest_run_parses():
    parser = build_parser()

    args = parser.parse_args(["ingest", "run"])

    assert args.command == "ingest"
    assert args.ingest_command == "run"


def test_ingest_test_parses_source():
    parser = build_parser()

    args = parser.parse_args(["ingest", "test", "hyperliquid"])

    assert args.command == "ingest"
    assert args.ingest_command == "test"
    assert args.source == "hyperliquid"


def test_technical_run_parses():
    parser = build_parser()

    args = parser.parse_args(["technical", "run"])

    assert args.command == "technical"
    assert args.technical_command == "run"


def test_technical_test_parses_symbol():
    parser = build_parser()

    args = parser.parse_args(["technical", "test", "BTCUSDT"])

    assert args.command == "technical"
    assert args.technical_command == "test"
    assert args.symbol == "BTCUSDT"


def test_liquidation_run_parses():
    parser = build_parser()

    args = parser.parse_args(["liquidation", "run"])

    assert args.command == "liquidation"
    assert args.liquidation_command == "run"


def test_liquidation_test_parses_symbol():
    parser = build_parser()

    args = parser.parse_args(["liquidation", "test", "BTCUSDT"])

    assert args.command == "liquidation"
    assert args.liquidation_command == "test"
    assert args.symbol == "BTCUSDT"


def test_decision_run_parses():
    parser = build_parser()

    args = parser.parse_args(["decision", "run"])

    assert args.command == "decision"
    assert args.decision_command == "run"


def test_decision_test_parses_symbol():
    parser = build_parser()

    args = parser.parse_args(["decision", "test", "BTCUSDT"])

    assert args.command == "decision"
    assert args.decision_command == "test"
    assert args.symbol == "BTCUSDT"
