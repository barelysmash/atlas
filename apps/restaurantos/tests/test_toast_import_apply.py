"""Approving a staged Toast night, and how the ledger and API then read it.

Every figure in this file is invented.
"""

import io
import json
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from restaurantos.api import operating_summary, read_partial_nights
from restaurantos.nightly_history import read_history_jsonl
from restaurantos.nightly_refresh import rebuild_nightly_history
from restaurantos.toast_email_intake import preview_sales_summary
from restaurantos.toast_import_apply import (
    TOAST_SOURCE,
    approve_staged_import,
    approved_reports,
    read_approved_nights,
)

RESTAURANT = "Fonda San Miguel"
NIGHT = date(2026, 6, 3)
FILENAME = "SalesSummary_2026-06-03_2026-06-03.zip"
WHEN = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)


def toast_zip(*, sales: str = "1000.00", voids: str | None = "25.00") -> bytes:
    files = {
        "Revenue summary.csv": f"Net sales\n{sales}\n",
        "Net sales summary.csv": (
            "Gross sales,Sales discounts,Sales refunds,Net sales\n"
            f"{float(sales) + 50:.2f},-50.00,0.00,{sales}\n"
        ),
        "Sales by day.csv": (
            f"yyyyMMdd,Net sales,Total orders,Total guests\n20260603,{sales},12,40\n"
        ),
        "Service mode summary.csv": (
            f"Service mode,Net sales,Total guests,Total orders\nTotal,{sales},40,12\n"
        ),
    }
    if voids is not None:
        files["Void summary.csv"] = (
            "Void amount,Void order count,Void item count,Void amount %\n"
            f"{voids},2,3,2.5\n"
        )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return output.getvalue()


def stage(root: Path, data: bytes, filename: str = FILENAME) -> str:
    preview = preview_sales_summary(filename, data)
    item = root / preview.source_sha256
    item.mkdir(parents=True)
    (item / "source.zip").write_bytes(data)
    (item / "review.json").write_text(
        json.dumps(
            {
                "status": "pending_review",
                "filename": filename,
                "service_date": preview.service_date,
                "sha256": preview.source_sha256,
            }
        ),
        encoding="utf-8",
    )
    return preview.source_sha256


EOD_BODY = """
SPLH: $80.00
Labor (actual): $4,000.00
Horas (actual): 250.00
Reservations: 200
Dining Room: 240
Bar/Atrium: 160
Total: 400
Total Comps: $500.00
Total Voids: $100.00
"""


def write_messages(path: Path, nights: list[date]) -> Path:
    rows = [
        {
            "message_id": f"m{index}",
            "subject": f"EOD {night.month}/{night.day}/{night.year}",
            "body": EOD_BODY,
            "sent_at": f"{night.isoformat()}T23:30:00-05:00",
        }
        for index, night in enumerate(nights)
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", "utf-8")
    return path


def rebuild(tmp_path: Path, nights: list[date], approved: Path | None) -> Path:
    history = tmp_path / "history.jsonl"
    rebuild_nightly_history(
        write_messages(tmp_path / "messages.jsonl", nights),
        history,
        tmp_path / "manifest.json",
        restaurant=RESTAURANT,
        approved_imports_path=approved,
    )
    return history


# ── the preview now carries voids and discounts ──────────────────────────


def test_preview_reads_void_amount_and_discounts():
    preview = preview_sales_summary(FILENAME, toast_zip())
    assert preview.void_amount == 25.0
    assert preview.sales_discounts == -50.0


def test_preview_without_a_void_report_has_no_void_amount():
    assert preview_sales_summary(FILENAME, toast_zip(voids=None)).void_amount is None


def test_preview_rejects_a_negative_void_amount():
    with pytest.raises(ValueError):
        preview_sales_summary(FILENAME, toast_zip(voids="-1"))


# ── approval ─────────────────────────────────────────────────────────────


def test_approval_writes_one_private_file_per_night(tmp_path: Path):
    digest = stage(tmp_path / "review", toast_zip())
    night = approve_staged_import(
        tmp_path / "review", tmp_path / "approved", NIGHT, now=WHEN
    )
    assert night.sha256 == digest
    path = tmp_path / "approved" / "2026-06-03.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["source"] == TOAST_SOURCE
    assert payload["net_sales"] == 1000.0
    assert payload["void_amount"] == 25.0
    assert payload["approved_at"] == "2026-06-10T12:00:00+00:00"
    assert path.stat().st_mode & 0o777 == 0o600


def test_guests_and_discounts_are_kept_aside_not_applied(tmp_path: Path):
    stage(tmp_path / "review", toast_zip())
    approve_staged_import(tmp_path / "review", tmp_path / "approved", NIGHT)
    payload = json.loads((tmp_path / "approved" / "2026-06-03.json").read_text("utf-8"))
    assert payload["unapplied"] == {
        "guests": 40,
        "orders": 12,
        "sales_discounts": -50.0,
    }
    [report] = approved_reports(read_approved_nights(tmp_path / "approved"), RESTAURANT)
    assert report.net_sales == 1000.0
    assert report.voids == 25.0
    assert report.effective_total_covers is None
    assert report.effective_total_comps is None
    assert report.labor_hours_actual is None


def test_the_audit_log_has_dates_and_hashes_but_no_figures(tmp_path: Path):
    digest = stage(tmp_path / "review", toast_zip(sales="1234.56"))
    approve_staged_import(tmp_path / "review", tmp_path / "approved", NIGHT, now=WHEN)
    text = (tmp_path / "approved" / "audit.jsonl").read_text(encoding="utf-8")
    assert json.loads(text) == {
        "action": "approved",
        "service_date": "2026-06-03",
        "sha256": digest,
        "at": "2026-06-10T12:00:00+00:00",
    }
    assert "1234" not in text


def test_nothing_staged_for_the_date_is_an_error(tmp_path: Path):
    stage(tmp_path / "review", toast_zip())
    with pytest.raises(ValueError, match="no staged Toast summary"):
        approve_staged_import(
            tmp_path / "review", tmp_path / "approved", date(2026, 6, 4)
        )
    assert not (tmp_path / "approved").exists()


def test_two_different_files_for_one_night_need_a_choice(tmp_path: Path):
    first = stage(tmp_path / "review", toast_zip(sales="1000.00"))
    stage(tmp_path / "review", toast_zip(sales="1100.00"))
    with pytest.raises(ValueError, match="several staged files"):
        approve_staged_import(tmp_path / "review", tmp_path / "approved", NIGHT)
    night = approve_staged_import(
        tmp_path / "review", tmp_path / "approved", NIGHT, sha256=first
    )
    assert night.net_sales == 1000.0


def test_a_second_file_does_not_replace_the_first_unless_asked(tmp_path: Path):
    first = stage(tmp_path / "review", toast_zip(sales="1000.00"))
    second = stage(tmp_path / "review", toast_zip(sales="1100.00"))
    approve_staged_import(
        tmp_path / "review", tmp_path / "approved", NIGHT, sha256=first
    )
    with pytest.raises(ValueError, match="already approved"):
        approve_staged_import(
            tmp_path / "review", tmp_path / "approved", NIGHT, sha256=second
        )
    approve_staged_import(
        tmp_path / "review", tmp_path / "approved", NIGHT, sha256=second, replace=True
    )
    [night] = read_approved_nights(tmp_path / "approved")
    assert night.net_sales == 1100.0
    actions = [
        json.loads(line)["action"]
        for line in (tmp_path / "approved" / "audit.jsonl").read_text().splitlines()
    ]
    assert actions == ["approved", "replaced"]


def test_a_staged_zip_altered_after_staging_is_refused(tmp_path: Path):
    digest = stage(tmp_path / "review", toast_zip())
    (tmp_path / "review" / digest / "source.zip").write_bytes(
        toast_zip(sales="9999.00")
    )
    with pytest.raises(ValueError, match="does not match its recorded sha256"):
        approve_staged_import(tmp_path / "review", tmp_path / "approved", NIGHT)


def test_figures_in_review_json_are_not_trusted(tmp_path: Path):
    digest = stage(tmp_path / "review", toast_zip(sales="1000.00"))
    metadata = tmp_path / "review" / digest / "review.json"
    review = json.loads(metadata.read_text(encoding="utf-8"))
    review["net_sales"] = 5.0
    metadata.write_text(json.dumps(review), encoding="utf-8")
    night = approve_staged_import(tmp_path / "review", tmp_path / "approved", NIGHT)
    assert night.net_sales == 1000.0


def test_a_malformed_approval_file_stops_the_rebuild(tmp_path: Path):
    approved = tmp_path / "approved"
    approved.mkdir()
    (approved / "2026-06-03.json").write_text('{"source": "other"}', "utf-8")
    with pytest.raises(ValueError, match="not an approved Toast night"):
        read_approved_nights(approved)


def test_no_approval_folder_means_no_nights(tmp_path: Path):
    assert read_approved_nights(tmp_path / "absent") == []


# ── the ledger ───────────────────────────────────────────────────────────


def approved_folder(tmp_path: Path) -> Path:
    stage(tmp_path / "review", toast_zip())
    approve_staged_import(tmp_path / "review", tmp_path / "approved", NIGHT)
    return tmp_path / "approved"


def test_an_approved_night_enters_the_ledger_as_sales_and_voids_only(tmp_path: Path):
    history = rebuild(
        tmp_path, [date(2026, 6, 2), date(2026, 6, 4)], approved_folder(tmp_path)
    )
    night = [r for r in read_history_jsonl(history) if r.period == "2026-06-03"]
    values = {record.metric: record.value for record in night}
    # void_pct is derived from the two facts; nothing else exists for the night.
    assert set(values) == {"net_sales", "voids", "void_pct"}
    assert values["net_sales"] == 1000.0
    assert values["voids"] == 25.0
    assert {r.source for r in night if r.metric != "void_pct"} == {TOAST_SOURCE}


def test_the_manifest_names_the_partial_night(tmp_path: Path):
    rebuild(tmp_path, [date(2026, 6, 2), date(2026, 6, 4)], approved_folder(tmp_path))
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["partial_nights"] == ["2026-06-03"]
    assert manifest["service_nights"] == 3
    assert "1000" not in json.dumps(manifest)


def test_a_nightly_email_always_wins_over_an_approved_import(tmp_path: Path):
    history = rebuild(tmp_path, [date(2026, 6, 2), NIGHT], approved_folder(tmp_path))
    night = [r for r in read_history_jsonl(history) if r.period == "2026-06-03"]
    assert {record.source for record in night} == {"nightly_email"}
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["partial_nights"] == []
    assert manifest["service_nights"] == 2


def test_a_rebuild_without_the_folder_is_unchanged(tmp_path: Path):
    history = rebuild(tmp_path, [date(2026, 6, 2), date(2026, 6, 4)], None)
    periods = {record.period for record in read_history_jsonl(history)}
    assert periods == {"2026-06-02", "2026-06-04"}
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["partial_nights"] == []


def test_the_approval_survives_every_later_rebuild(tmp_path: Path):
    approved = approved_folder(tmp_path)
    for _ in range(2):
        history = rebuild(tmp_path, [date(2026, 6, 2), date(2026, 6, 4)], approved)
    periods = {record.period for record in read_history_jsonl(history)}
    assert "2026-06-03" in periods


# ── the peer API ─────────────────────────────────────────────────────────


def test_the_summary_counts_partial_nights_and_keeps_ratios_clean(tmp_path: Path):
    nights = [date(2026, 5, 2), date(2026, 5, 4), date(2026, 6, 2), date(2026, 6, 4)]
    with_import = rebuild(tmp_path, nights, approved_folder(tmp_path))
    partial = read_partial_nights(tmp_path / "manifest.json")
    assert partial == {NIGHT}
    payload = {
        "start_date": "2026-06-01",
        "end_date": "2026-06-05",
        "compare_start_date": "2026-05-01",
        "compare_end_date": "2026-05-05",
    }
    result = operating_summary(
        read_history_jsonl(with_import), payload, partial_nights=partial
    )
    assert result["current"]["nights_partial"] == 1
    assert result["previous"]["nights_partial"] == 0
    assert "nights_partial" in result["notes"][-1]

    other = tmp_path / "plain"
    other.mkdir()
    without = operating_summary(
        read_history_jsonl(rebuild(other, nights, None)), payload
    )

    def changes(summary: dict) -> dict:
        return {item["metric"]: item for item in summary["changes"]}

    before, after = changes(without), changes(result)
    # Sales moved because a night was added; rates built on labor or covers
    # did not, because the partial night has neither.
    assert after["net_sales"] != before["net_sales"]
    for metric in ("splh", "average_check", "labor_cost_pct", "reservation_share"):
        assert after[metric] == before[metric]


def test_partial_nights_are_unknown_for_an_older_manifest(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"reviews": []}', encoding="utf-8")
    assert read_partial_nights(manifest) is None
    assert read_partial_nights(tmp_path / "absent.json") is None
