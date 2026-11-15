import csv
import io
import zipfile

import pytest

from restaurantos.toast_email_intake import preview_sales_summary


def _zip(*, sales="38263.87", guests="524", day="20261105", mismatch=False):
    files = {
        "Revenue summary.csv": "Net sales\n38263.87\n",
        "Net sales summary.csv": (
            "Gross sales,Sales discounts,Sales refunds,Net sales\n"
            f"38878.27,-614.40,0.00,{sales}\n"
        ),
        "Sales by day.csv": f"yyyyMMdd,Net sales,Total orders,Total guests\n{day},38263.87,150,{guests}\n",
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
    summary = preview_sales_summary(
        "SalesSummary_2026-11-05_2026-11-05.zip", _zip()
    )
    assert summary.service_date == "2026-11-05"
    assert summary.net_sales == 38263.87
    assert summary.guests == 524
    assert summary.orders == 150
    assert len(summary.source_sha256) == 64


@pytest.mark.parametrize("kwargs", [
    {"sales": "1"}, {"guests": "100"}, {"day": "20261106"}, {"mismatch": True},
])
def test_conflicting_report_is_rejected(kwargs):
    with pytest.raises(ValueError):
        preview_sales_summary("SalesSummary_2026-11-05_2026-11-05.zip", _zip(**kwargs))


def test_filename_must_be_one_day():
    with pytest.raises(ValueError):
        preview_sales_summary(
            "SalesSummary_2026-11-05_2026-11-06.zip", _zip()
        )


def test_zip_traversal_rejected():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as z:
        z.writestr("../outside.csv", "unsafe")
    with pytest.raises(ValueError):
        preview_sales_summary("SalesSummary_2026-11-05_2026-11-05.zip", output.getvalue())
