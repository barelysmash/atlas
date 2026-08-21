import json
import sys
from pathlib import Path

from restaurantos.__main__ import main


def write_history(path: Path) -> Path:
    rows = [
        ("net_sales", "sales", 4000.0),
        ("labor_hours", "labor", 100.0),
        ("labor_cost", "labor", 1000.0),
        ("guest_count", "demand", 100.0),
    ]
    payloads = [
        {
            "source": "nightly_email",
            "entity": "Test Restaurant",
            "period": "2026-06-01",
            "category": category,
            "metric": metric,
            "value": value,
            "dimensions": {},
            "grain": "daily",
            "aggregation": "sum",
        }
        for metric, category, value in rows
    ]
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in payloads) + "\n",
        encoding="utf-8",
    )
    return path


def test_operating_brief_cli_writes_requested_private_output(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    history = write_history(tmp_path / "history.jsonl")
    output = tmp_path / "private" / "brief.md"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "restaurantos",
            "operating-brief",
            "--history",
            str(history),
            "--start",
            "2026-06-01",
            "--end",
            "2026-06-01",
            "--output",
            str(output),
        ],
    )

    main()

    assert output.exists()
    assert "# Test Restaurant Operating Brief" in output.read_text(encoding="utf-8")
    assert capsys.readouterr().out.strip() == str(output)


def test_operating_brief_cli_prints_when_output_is_omitted(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    history = write_history(tmp_path / "history.jsonl")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "restaurantos",
            "operating-brief",
            "--history",
            str(history),
            "--start",
            "2026-06-01",
            "--end",
            "2026-06-01",
        ],
    )

    main()

    assert "# Test Restaurant Operating Brief" in capsys.readouterr().out
