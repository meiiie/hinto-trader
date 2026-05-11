from scripts.run_research_matrix import _base_args


def test_research_matrix_base_args_can_match_paper_runtime():
    args = _base_args(
        days=None,
        start="2026-05-07",
        end="2026-05-11",
        symbols="ETHUSDT,BNBUSDT,XRPUSDT",
        top=50,
        balance=100.0,
        risk=0.01,
        leverage=20.0,
        max_pos=3,
    )

    assert args[:6] == [
        "--symbols",
        "ETHUSDT,BNBUSDT,XRPUSDT",
        "--start",
        "2026-05-07",
        "--end",
        "2026-05-11",
    ]
    assert args[args.index("--max-pos") + 1] == "3"
    assert "--top" not in args


def test_research_matrix_base_args_supports_dynamic_top_n():
    args = _base_args(
        days=30,
        start=None,
        end=None,
        symbols=None,
        top=50,
        balance=250.0,
        risk=0.02,
        leverage=10.0,
        max_pos=5,
    )

    assert args[:2] == ["--top", "50"]
    assert args[args.index("--balance") + 1] == "250.0"
    assert args[args.index("--risk") + 1] == "0.02"
    assert args[args.index("--leverage") + 1] == "10.0"
    assert args[args.index("--max-pos") + 1] == "5"
