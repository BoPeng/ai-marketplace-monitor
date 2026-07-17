# Design: Export CSV of found items (Web UI)

**Issue:** [#334](https://github.com/BoPeng/ai-marketplace-monitor/issues/334) — "List of all found items"
**Date:** 2026-07-16
**Status:** Approved (brainstorm), pending implementation plan

## Summary

Add an **"Export CSV"** button to the Web UI that downloads the list of items the
monitor has **found and notified users about**, with link, price, rating, and the
core listing fields. The data already exists on disk in the `diskcache`; this feature
only reads and joins it — it performs no scraping and adds no new persistent storage.

## Scope decision: which items?

"Found items" means the **matched/notified** listings — the ones the monitor decided
were worth surfacing to a user — **not** every listing the crawler scraped. Rationale:

- The issue explicitly requests a `rating` column. Ratings only exist for
  AI‑evaluated listings, which are exactly the ones that get notified. Exporting all
  scraped listings would leave most `rating` cells blank and include filtered‑out noise.
- The notified set joins cleanly: `USER_NOTIFIED` stores `listing.hash`, which keys
  `AI_INQUIRY` directly, so the rating join needs no fragile hash recomputation.

**Out of scope (YAGNI):** in‑UI table/browse view, filtering / date‑range params,
per‑user files, configurable columns, exporting all scraped listings.

## Data sources (existing cache)

Single on‑disk cache: `cache = Cache(amm_home)` in `utils.py`. Entries are tagged by
`CacheType` and enumerable via `cache.iterkeys()` (the counters code in `utils.py`
already uses this pattern, filtering on `key[0]`).

| `CacheType`       | Key                                              | Value                                  | Provides                                              |
| ----------------- | ------------------------------------------------ | -------------------------------------- | ---------------------------------------------------- |
| `USER_NOTIFIED`   | `(tag, marketplace, id, user)`                   | `(date, listing_hash, price)`¹         | row spine: found‑timestamp, user, price, listing hash |
| `LISTING_DETAILS` | `(tag, post_url_without_query)`                  | full `Listing` dict                    | title, url, location, seller, condition, item name    |
| `AI_INQUIRY`      | `(tag, item_hash, mkt_hash, listing_hash)`       | `{score, comment, name}` (asdict)      | rating (`score` 1–5) and AI `comment`                 |

¹ Legacy `USER_NOTIFIED` values may be a bare `str` (date only) or a 2‑tuple
`(date, hash)`. Normalized the same way `User.notification_status` in `user.py`
already does.

`Listing` fields (from `listing.py`): `marketplace, name, id, title, image, price,
post_url, location, seller, condition, description`. `Listing.name` is the **item
config name** (set at `facebook.py`: `listing.name = item_config.name`).

## Architecture

Two small, independently testable units plus one wiring change:

1. **`webui/found_export.py`** — pure logic, no HTTP, no FastAPI.
   - `build_found_rows(cache) -> list[dict]`: enumerate + join the three cache
     namespaces, return sorted row dicts (one per notified record).
   - `rows_to_csv(rows) -> str`: serialize rows to CSV text with a fixed column order,
     using the stdlib `csv` module.
   - `CSV_COLUMNS`: the canonical ordered column list (single source of truth, shared
     by `rows_to_csv` and tests).
2. **`GET /api/found.csv`** endpoint in `webui/server.py` — thin wrapper: build rows →
   CSV → return `Response` with download headers. Auth only (no CSRF; it's a read).
3. **Frontend** — one button in the header + a click handler in `app.js` that fetches
   with credentials and saves the resulting blob.

## Backend detail

### Join algorithm (`build_found_rows`)

```
details_by_key = {}          # (marketplace, id) -> Listing dict
rating_by_hash = {}          # listing_hash -> {score, comment}
notified = []                # (marketplace, id, user, date, listing_hash, price)

for key in cache.iterkeys():
    tag = key[0]
    if tag == LISTING_DETAILS:  index cache[key] by (value["marketplace"], value["id"])
    elif tag == AI_INQUIRY:     rating_by_hash[key[3]] = cache[key]   # last wins
    elif tag == USER_NOTIFIED:  normalize value -> (date, hash, price); collect with key[1:]

for each notified record:
    d = details_by_key.get((marketplace, id))          # may be None
    r = rating_by_hash.get(listing_hash)               # may be None
    row = {
        found_at:      date,
        item:          d["name"] if d else "",
        marketplace:   marketplace,
        title:         d["title"] if d else "",
        price:         price (from notified record; fall back to d["price"]),
        rating:        r["score"] if r else "",
        ai_comment:    r["comment"] if r else "",
        location:      d["location"] if d else "",
        seller:        d["seller"] if d else "",
        condition:     d["condition"] if d else "",
        notified_user: user,
        url:           d["post_url"] if d else fallback_url(marketplace, id),
    }

sort rows by found_at descending
```

`fallback_url(marketplace, id)`: for `facebook`, `https://www.facebook.com/marketplace/item/<id>/`;
otherwise empty string. (Lets a row survive detail eviction without losing the link.)

**Columns (fixed order):**
`found_at, item, marketplace, title, price, rating, ai_comment, location, seller, condition, notified_user, url`

**Row cardinality:** one row per `USER_NOTIFIED` entry, i.e. per (listing, user). A
listing notified to two users yields two rows; `notified_user` disambiguates. This is
lossless and matches the stored data.

**Robustness:** each cache entry is processed defensively — a single malformed/legacy
entry is skipped (and logged at debug), never aborting the whole export.

### Endpoint

```python
@app.get("/api/found.csv")
async def export_found(_: str = Depends(require_session)) -> Response:
    csv_text = rows_to_csv(build_found_rows(cache))
    filename = f"found-items-{now:%Y%m%d-%H%M%S}.csv"
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

- `Depends(require_session)` only — mirrors `/api/status` and `/api/logs` (both reads).
  No `require_csrf` (that guards state changes).
- Empty cache / no users → 200 with a header‑only CSV.
- `cache` and `CacheType` imported from `..utils`.

## Frontend detail

- **Button:** a small ghost button in the header toolbar (next to the `Browser` /
  `Logout` buttons in `index.html`), e.g. `<button id="export-csv-btn" class="ghost">⬇ Export CSV</button>`.
- **Handler (`app.js`):** on click, `fetch("/api/found.csv", {credentials:"same-origin"})`;
  on success read `blob()`, create an object URL, click a temporary
  `<a download="found-items-YYYYMMDD-HHMMSS.csv">`, then revoke the URL. Disable the
  button while the request is in flight.
- Using fetch+blob (not a bare `<a href>`) so a `401` surfaces as a handled error
  instead of navigating the browser to a JSON error body.

## Error handling

| Condition                        | Behavior                                                        |
| -------------------------------- | -------------------------------------------------------------- |
| No session                       | `401` (via `require_session`); frontend shows an error, no file |
| Empty / no notified items        | `200`, CSV with only the header row                            |
| Malformed/legacy cache entry     | Entry skipped, logged at debug; export continues               |
| Missing `LISTING_DETAILS`        | Row emitted with blanks + fallback URL                         |
| Missing `AI_INQUIRY`             | Row emitted with blank `rating`/`ai_comment`                   |

## Testing

**Unit — `build_found_rows` / `rows_to_csv`** (against a temporary `diskcache.Cache`,
matching the temp‑cache style already used in the suite):
- Happy path: all three caches populated → one fully‑joined row, correct field mapping.
- Missing details → row present with blanks and Facebook fallback URL.
- Missing rating → blank `rating`/`ai_comment`.
- Legacy `USER_NOTIFIED` value shapes (bare str, 2‑tuple) normalized without error.
- Same listing notified to two users → two rows, distinct `notified_user`.
- Sorting: rows ordered by `found_at` descending.
- `rows_to_csv`: header row equals `CSV_COLUMNS`; values comma/quote‑escaped correctly.

**Endpoint — FastAPI `TestClient`** (mirrors existing webui tests):
- Seeded cache → `GET /api/found.csv` returns `200`, `text/csv` content type,
  `attachment` disposition, body parses to the expected rows.
- Without a session cookie → `401`.

## Documentation

- `CHANGELOG.md`: `[Unreleased] › Added` entry referencing #334.
- Brief mention in the Web UI section of the docs that an "Export CSV" of found items
  is available.

## Non‑goals / future

- In‑UI sortable table of found items (a possible follow‑up; the export button is the
  concrete ask).
- Exporting all scraped listings, filtering, or date ranges.
