import base64
import io
import zipfile

import pytest
from restaurantos.gmail_mailbox import GmailApiMailbox
from restaurantos.toast_email_intake import (
    preview_sales_summary,
    stage_toast_gmail_imports,
)


def _zip(*, sales="38263.87", guests="524", day="20261105", mismatch=False):
    files = {
        "Revenue summary.csv": "Net sales\n38263.87\n",
        "Net sales summary.csv": (
            "Gross sales,Sales discounts,Sales refunds,Net sales\n"
            f"38878.27,-614.40,0.00,{sales}\n"
        ),
        "Sales by day.csv": (
            "yyyyMMdd,Net sales,Total orders,Total guests\n"
            f"{day},38263.87,150,{guests}\n"
        ),
        "Service mode summary.csv": (
            "Service mode,Net sales,Total guests,Total orders\n"
            f"Total,{38263.87 if not mismatch else 1},524,150\n"
        ),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
        for name, value in files.items():
            z.writestr(name, value)
    return output.getvalue()


def test_november_5_reconciles():
    summary = preview_sales_summary("SalesSummary_2026-11-05_2026-11-05.zip", _zip())
    assert summary.service_date == "2026-11-05"
    assert summary.net_sales == 38263.87
    assert summary.guests == 524
    assert summary.orders == 150
    assert len(summary.source_sha256) == 64


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sales": "1"},
        {"guests": "100"},
        {"day": "20261106"},
        {"mismatch": True},
    ],
)
def test_conflicting_report_is_rejected(kwargs):
    with pytest.raises(ValueError):
        preview_sales_summary("SalesSummary_2026-11-05_2026-11-05.zip", _zip(**kwargs))


def test_filename_must_be_one_day():
    with pytest.raises(ValueError):
        preview_sales_summary("SalesSummary_2026-11-05_2026-11-06.zip", _zip())


def test_zip_traversal_rejected():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as z:
        z.writestr("../outside.csv", "unsafe")
    with pytest.raises(ValueError):
        preview_sales_summary(
            "SalesSummary_2026-11-05_2026-11-05.zip", output.getvalue()
        )


def test_gmail_download_and_retry(tmp_path):
    filename = "SalesSummary_2026-11-05_2026-11-05.zip"
    data = _zip()
    encoded = base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")
    paths = []

    class TokenProvider:
        def access_token(self):
            return "test-token"

    def request_json(request):
        path = request.selector.split("?")[0]
        paths.append(path)
        assert request.get_header("Authorization") == "Bearer test-token"
        if path.endswith("/attachments/export"):
            return {"data": encoded}
        if path.endswith("/messages/report"):
            return {
                "payload": {
                    "parts": [
                        {
                            "filename": filename,
                            "body": {"attachmentId": "export", "size": len(data)},
                        },
                        {"filename": "unsupported.xlsx", "body": {}},
                    ]
                }
            }
        assert path.endswith("/messages")
        assert "Atlas%2FImports" in request.selector
        return {"messages": [{"id": "report"}]}

    mailbox = GmailApiMailbox(
        token_provider=TokenProvider(), query="unused", request_json=request_json
    )
    results = stage_toast_gmail_imports(mailbox, tmp_path)
    assert [item["status"] for item in results] == [
        "pending_review",
        "unsupported_review",
    ]
    assert paths[-1].endswith("/messages/report/attachments/export")
    archive = tmp_path / results[0]["sha256"] / "source.zip"
    assert archive.read_bytes() == data
    assert stage_toast_gmail_imports(mailbox, tmp_path) == results
    assert list(tmp_path.glob("*/source.zip")) == [archive]
