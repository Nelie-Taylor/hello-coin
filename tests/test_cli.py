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
