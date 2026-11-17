# Toast Gmail intake: stage, review, approve

Staging is separate from the production RestaurantOS nightly EOD pipeline and
does **not** modify `nightly-history.jsonl`, `nightly-manifest.json`, or the
operating brief. Only an explicit approval, one night at a time, lets a
staged night into the ledger. Do not automate staging or approval.

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
4. Check each `review.json` against the Toast report it came from: service
   date, net sales, guests and orders should match. Figures stay in the
   private review folder and are never written into this repository. Labor
   and reservation data are **not** provided by this export.
5. Nothing reaches the ledger until a night is approved (next section).

## Approving a staged night

Approval is a separate, explicit command, one service date at a time:

```bash
~/atlas/.venv/bin/python -m restaurantos toast-approve \
  --review-dir ~/atlas-data/restaurantos/fonda/toast-import-review \
  --approved-dir ~/atlas-data/restaurantos/fonda/toast-approved \
  --service-date YYYY-MM-DD
```

- The staged ZIP is validated again from its bytes; `review.json` is not
  trusted.
- It writes `toast-approved/YYYY-MM-DD.json` (owner-only) and appends a line
  to `toast-approved/audit.jsonl` (date, hash, action, time; no figures).
- The command prints the date and hash only.
- The next nightly refresh adds the night to the ledger. The approval file is
  re-read on every rebuild, so the night stays.

### What an approved night contains

A **partial night**: net sales and voids, with source `toast_sales_summary`.

- No labor and no reservations: the export does not have them.
- No covers: Toast's guest total spans every service mode and has not been
  checked against the cover count the nightly emails report.
- No comps: Toast's discount total has not been checked against the emails'
  comps.

Guests, orders and discounts are kept in the approval file under `unapplied`
for a later release. Period rates (SPLH, average check, labor percent,
reservation share) are computed only over nights that have both inputs, so a
partial night does not skew them.

A night that has a readable nightly email is never overridden: the email
wins and the approval is ignored for that date. The manifest lists
`partial_nights`, and the peer API reports `nights_partial` per period.

To switch a night to a different staged file, pass `--sha256` and
`--replace`. To withdraw an approval, delete its file from `toast-approved/`
and run the nightly refresh.

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
type-specific XLSX import, and checking Toast guests against email covers
and Toast discounts against email comps so those can be applied too.
