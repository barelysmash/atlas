import json
import sys
from pathlib import Path

from restaurantos.__main__ import main


BODY = """
SPLH: $90.00
Labor (actual): $4,200.00
Horas (actual): 260.00
Reservations: 220
Dining Room: 260
Bar/Atrium: 170
Total: 430
Total Comps: $450.00
Total Voids: $75.00
"""


def _write_messages(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "message_id": "synthetic-cli",
                "subject": "EOD 8/20/2026",
                "body": BODY,
                "sent_at": "2026-08-20T23:30:00-05:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_nightly_refresh_cli_rebuilds_private_outputs(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    messages = _write_messages(tmp_path / "messages.jsonl")
    history = tmp_path / "private" / "history.jsonl"
    manifest = tmp_path / "private" / "manifest.json"
    brief = tmp_path / "private" / "brief.md"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "restaurantos",
            "nightly-refresh",
            "--messages",
            str(messages),
            "--history",
            str(history),
            "--manifest",
            str(manifest),
            "--restaurant",
            "Test Restaurant",
            "--brief-output",
            str(brief),
            "--brief-start",
            "2026-08-20",
            "--brief-end",
            "2026-08-20",
        ],
    )

    main()

    assert history.exists()
    assert manifest.exists()
    assert brief.exists()
    output = capsys.readouterr().out
    assert "service_nights=1" in output
    assert f"history={history}" in output
    assert f"manifest={manifest}" in output
    assert f"brief={brief}" in output


def test_nightly_refresh_cli_requires_complete_brief_window(
    tmp_path: Path,
    monkeypatch,
):
    messages = _write_messages(tmp_path / "messages.jsonl")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "restaurantos",
            "nightly-refresh",
            "--messages",
            str(messages),
            "--history",
            str(tmp_path / "history.jsonl"),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--restaurant",
            "Test Restaurant",
            "--brief-start",
            "2026-08-20",
        ],
    )

    try:
        main()
    except SystemExit as error:
        assert error.code == 2
    else:
        raise AssertionError("expected argparse to reject incomplete brief window")
