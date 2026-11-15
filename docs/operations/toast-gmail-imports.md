# Toast Gmail intake (review-only first release)

This workflow is separate from the production RestaurantOS nightly EOD pipeline.
It does **not** modify `nightly-history.jsonl`, `nightly-manifest.json`, or the
operating brief. Do not run it automatically until validation and review have
been completed.

## First-run procedure on Guildenstern

1. Forward or send the original Toast SalesSummary ZIP to the Gmail mailbox
   already authorized for Atlas; apply the Gmail label `Atlas/Imports`.
2. With the active Atlas release installed, run:

```bash
~/atlas/.venv/bin/python ~/atlas/deploy/bin/restaurantos_toast_email_intake.py \
  --credentials ~/atlas-data/google/gmail-token.json \
  --output-dir ~/atlas-data/restaurantos/fonda/toast-import-review
```

3. Review JSON output and inspect each private
   `toast-import-review/<sha256>/review.json`. The original is retained as
   `source.zip` with owner-only permissions.
4. For November 5, expect service date `2026-11-05`, net sales
   `38263.87`, guests `524`, and orders `150`. Labor and reservation
   data are **not** provided by this export.
5. Apply/reconciliation into the canonical ledger is **not implemented in this
   PR**. Approval and an explicit, audited apply phase are required before a
   recovered date can enter the operating brief.

## Safeguards and limitations

- Exact single-day ZIP naming required.
- Cross-checks four independent Toast report summaries.
- Rejects date mismatch, inconsistent totals, missing reports, path traversal,
  unexpected file types, too many ZIP members, and excess file sizes.
- Stores by attachment SHA-256 for idempotent review.
- Does not parse product-mix XLSX files yet. They are marked unsupported.
- Requires `Atlas/Imports` labeling of received Gmail; this query is
  independent of the existing `{EOD SPLH}` nightly ingestion.
- No private source, Gmail content, OAuth token, or actual ZIP is committed
  to GitHub.

Future PRs: tests for Gmail MIME attachment pagination and embedded data,
type-specific XLSX import, deterministic conflict review + explicit apply,
manifest/brief source confidence and reconciliation.
