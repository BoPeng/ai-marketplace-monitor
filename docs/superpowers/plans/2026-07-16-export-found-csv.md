# Export CSV of Found Items — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Web UI "Export CSV" button that downloads the matched/notified listings (link, price, rating, etc.) by reading and joining the existing on-disk cache.

**Architecture:** A new pure-logic module `webui/found_export.py` enumerates and joins three `diskcache` namespaces (`USER_NOTIFIED`, `LISTING_DETAILS`, `AI_INQUIRY`) into CSV-ready rows. A thin authenticated `GET /api/found.csv` route in `webui/server.py` serializes those rows and returns them as a file download. The frontend adds one header button whose handler fetches the CSV with credentials and saves the blob. No scraping and no new persistent storage.

**Tech Stack:** Python 3.10+, FastAPI, diskcache, stdlib `csv`; vanilla JS frontend (`app.js`); pytest + FastAPI `TestClient` for tests.

**Reference spec:** `docs/superpowers/specs/2026-07-16-export-found-csv-design.md`

## Global Constraints

- **Lint:** ruff + black + isort via pre-commit, `line-length = 99`. `BLE001` (blind `except`), `E501` (line length), `D100–D103/D107/D415` (missing docstrings) are ignored; but `D205` (blank line after a docstring summary) is enforced — any docstring you write must be well-formed. Docstring convention is **google**.
- **Types:** ruff `ANN` is enforced (except `ANN002/003/202/401`) and `mypy` runs over `src`, `tests`, `noxfile.py`, `tasks.py`, `docs/conf.py`. **Every function — including test functions and helpers — needs parameter and return type annotations.**
- **Broad excepts** must re-raise `KeyboardInterrupt` before catching `Exception`, matching the existing pattern in `listing.py`/`ai.py`.
- **Auth:** reads use `Depends(require_session)` only (no `require_csrf`), matching `/api/status` and `/api/logs`.
- **Pre-existing debt:** `main` currently carries lint debt from earlier merges (#336 `'Enter'` quoting, #326 `FacebookFlexItemPage` D205 docstrings) that makes `pre-commit run --all-files` fail on any branch off `main`. This is fixed on branch `feat/sort-by-323` (PR #340). Before opening this PR, rebase onto `main` once #340 has merged, or cherry-pick its lint-fix commit (`9a0dd09`). See Task 5.
- **Branch:** work happens on `feat/export-found-csv-334` (already created off `main`).

## File Structure

- **Create** `src/ai_marketplace_monitor/webui/found_export.py` — pure join + CSV serialization. No FastAPI, no HTTP, no global-cache import. One responsibility: turn a `Cache` into CSV text.
- **Modify** `src/ai_marketplace_monitor/webui/server.py` — add imports and one `GET /api/found.csv` route inside `create_app`.
- **Modify** `src/ai_marketplace_monitor/webui/static/index.html` — add the export button to the header.
- **Modify** `src/ai_marketplace_monitor/webui/static/app.js` — wire the button click to a download handler.
- **Create** `tests/test_found_export.py` — unit tests for the module + one endpoint test via `TestClient`.
- **Modify** `CHANGELOG.md` — `[Unreleased] › Added` entry.
- **Modify** `docs/README.md` — one-line mention in the Web UI section (optional copy; see Task 4).

---

### Task 1: CSV serializer + column schema

**Files:**
- Create: `src/ai_marketplace_monitor/webui/found_export.py`
- Test: `tests/test_found_export.py`

**Interfaces:**
- Produces: `CSV_COLUMNS: List[str]` (canonical ordered columns) and `rows_to_csv(rows: List[Dict[str, str]]) -> str`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_found_export.py`:

```python
"""Tests for the Web UI found-items CSV export."""

from __future__ import annotations

import csv
import io
from typing import Dict, List

from ai_marketplace_monitor.webui.found_export import CSV_COLUMNS, rows_to_csv


def _parse(text: str) -> List[Dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def test_rows_to_csv_empty_has_header_only() -> None:
    text = rows_to_csv([])
    lines = text.splitlines()
    assert lines[0].split(",") == CSV_COLUMNS
    assert len(lines) == 1


def test_rows_to_csv_writes_row_and_escapes() -> None:
    row = {c: "" for c in CSV_COLUMNS}
    row["title"] = 'Chair, "comfy"'
    row["price"] = "$40"
    text = rows_to_csv([row])
    parsed = _parse(text)
    assert len(parsed) == 1
    assert parsed[0]["title"] == 'Chair, "comfy"'
    assert parsed[0]["price"] == "$40"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra test pytest tests/test_found_export.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ai_marketplace_monitor.webui.found_export'`

- [ ] **Step 3: Write minimal implementation**

Create `src/ai_marketplace_monitor/webui/found_export.py`:

```python
"""Build and serialize the "found items" export from the on-disk cache.

Reads the notified/matched listings out of the diskcache and joins them with
cached listing details and AI ratings to produce CSV-ready rows.  Read-only:
no scraping and no new persistence.
"""

from __future__ import annotations

import csv
import io
from typing import Dict, List

CSV_COLUMNS: List[str] = [
    "found_at",
    "item",
    "marketplace",
    "title",
    "price",
    "rating",
    "ai_comment",
    "location",
    "seller",
    "condition",
    "notified_user",
    "url",
]


def rows_to_csv(rows: List[Dict[str, str]]) -> str:
    """Serialize rows to CSV text with a fixed header and column order."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra test pytest tests/test_found_export.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ai_marketplace_monitor/webui/found_export.py tests/test_found_export.py
git commit -m "feat: CSV serializer + column schema for found-items export (#334)"
```

---

### Task 2: Join builder (`build_found_rows`)

**Files:**
- Modify: `src/ai_marketplace_monitor/webui/found_export.py`
- Test: `tests/test_found_export.py`

**Interfaces:**
- Consumes: `CacheType` from `ai_marketplace_monitor.utils`; `diskcache.Cache`.
- Produces: `build_found_rows(local_cache: Cache) -> List[Dict[str, str]]` — one row dict (keyed by `CSV_COLUMNS`) per `USER_NOTIFIED` entry, sorted by `found_at` descending.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_found_export.py`:

```python
from pathlib import Path  # noqa: E402
from typing import Iterator  # noqa: E402

import pytest  # noqa: E402
from diskcache import Cache  # type: ignore  # noqa: E402

from ai_marketplace_monitor.listing import Listing  # noqa: E402
from ai_marketplace_monitor.utils import CacheType  # noqa: E402
from ai_marketplace_monitor.webui.found_export import build_found_rows  # noqa: E402


def _listing(listing_id: str = "123", price: str = "$100") -> Listing:
    return Listing(
        marketplace="facebook",
        name="iphone",
        id=listing_id,
        title="iPhone 13",
        image="http://img/x.jpg",
        price=price,
        post_url=f"https://www.facebook.com/marketplace/item/{listing_id}/?ref=search",
        location="Houston, TX",
        seller="Jane Doe",
        condition="used_good",
        description="great phone",
    )


@pytest.fixture
def temp_cache(tmp_path: Path) -> Iterator[Cache]:
    cache = Cache(str(tmp_path / "cache"))
    yield cache
    cache.close()


def _seed_notified(cache: Cache, listing: Listing, user: str = "me",
                   date: str = "2026-07-16 10:00:00") -> None:
    cache.set(
        (CacheType.USER_NOTIFIED.value, listing.marketplace, listing.id, user),
        (date, listing.hash, listing.price),
        tag=CacheType.USER_NOTIFIED.value,
    )


def _seed_rating(cache: Cache, listing: Listing, score: int = 5,
                 comment: str = "Great deal") -> None:
    cache.set(
        (CacheType.AI_INQUIRY.value, "itemhash", "mkthash", listing.hash),
        {"score": score, "comment": comment, "name": ""},
        tag=CacheType.AI_INQUIRY.value,
    )


def test_build_rows_full_join(temp_cache: Cache) -> None:
    listing = _listing()
    listing.to_cache(listing.post_url, local_cache=temp_cache)
    _seed_rating(temp_cache, listing)
    _seed_notified(temp_cache, listing)

    rows = build_found_rows(temp_cache)
    assert len(rows) == 1
    row = rows[0]
    assert row["found_at"] == "2026-07-16 10:00:00"
    assert row["item"] == "iphone"
    assert row["marketplace"] == "facebook"
    assert row["title"] == "iPhone 13"
    assert row["price"] == "$100"
    assert row["rating"] == "5"
    assert row["ai_comment"] == "Great deal"
    assert row["location"] == "Houston, TX"
    assert row["seller"] == "Jane Doe"
    assert row["condition"] == "used_good"
    assert row["notified_user"] == "me"
    assert row["url"] == "https://www.facebook.com/marketplace/item/123/?ref=search"


def test_build_rows_missing_details_uses_fallback_url(temp_cache: Cache) -> None:
    listing = _listing()
    _seed_notified(temp_cache, listing)  # no LISTING_DETAILS, no rating

    rows = build_found_rows(temp_cache)
    assert len(rows) == 1
    assert rows[0]["title"] == ""
    assert rows[0]["rating"] == ""
    assert rows[0]["url"] == "https://www.facebook.com/marketplace/item/123/"


def test_build_rows_legacy_notified_value_shapes(temp_cache: Cache) -> None:
    listing = _listing()
    # legacy: bare date string
    temp_cache.set(
        (CacheType.USER_NOTIFIED.value, "facebook", "aaa", "me"),
        "2026-07-15 09:00:00",
        tag=CacheType.USER_NOTIFIED.value,
    )
    # legacy: 2-tuple (date, hash)
    temp_cache.set(
        (CacheType.USER_NOTIFIED.value, "facebook", "bbb", "me"),
        ("2026-07-15 09:30:00", listing.hash),
        tag=CacheType.USER_NOTIFIED.value,
    )
    rows = build_found_rows(temp_cache)
    assert len(rows) == 2
    assert {r["found_at"] for r in rows} == {"2026-07-15 09:00:00", "2026-07-15 09:30:00"}


def test_build_rows_multi_user_two_rows(temp_cache: Cache) -> None:
    listing = _listing()
    listing.to_cache(listing.post_url, local_cache=temp_cache)
    _seed_notified(temp_cache, listing, user="alice")
    _seed_notified(temp_cache, listing, user="bob")
    rows = build_found_rows(temp_cache)
    assert len(rows) == 2
    assert {r["notified_user"] for r in rows} == {"alice", "bob"}


def test_build_rows_sorted_by_found_at_desc(temp_cache: Cache) -> None:
    old, new = _listing("111"), _listing("222")
    _seed_notified(temp_cache, old, date="2026-07-10 08:00:00")
    _seed_notified(temp_cache, new, date="2026-07-16 08:00:00")
    rows = build_found_rows(temp_cache)
    assert [r["found_at"] for r in rows] == ["2026-07-16 08:00:00", "2026-07-10 08:00:00"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra test pytest tests/test_found_export.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_found_rows'`

- [ ] **Step 3: Write the implementation**

Edit `src/ai_marketplace_monitor/webui/found_export.py`. Change the imports block and append the join logic:

Replace the import block:

```python
from __future__ import annotations

import csv
import io
from typing import Any, Dict, List, Optional, Tuple

from diskcache import Cache  # type: ignore

from ..utils import CacheType
```

Append after `CSV_COLUMNS`:

```python
def _normalize_notified(value: Any) -> Tuple[str, Optional[str], Optional[str]]:
    """Return (date, listing_hash, price) from a USER_NOTIFIED cache value.

    Handles legacy shapes: a bare date string, a 2-tuple (date, hash), or the
    current 3-tuple (date, hash, price).
    """
    if isinstance(value, str):
        return value, None, None
    if isinstance(value, (tuple, list)):
        if len(value) == 2:
            return value[0], value[1], None
        if len(value) >= 3:
            return value[0], value[1], value[2]
    return "", None, None


def _fallback_url(marketplace: str, listing_id: str) -> str:
    """Reconstruct a listing URL when its details are no longer cached."""
    if marketplace == "facebook":
        return f"https://www.facebook.com/marketplace/item/{listing_id}/"
    return ""


def build_found_rows(local_cache: Cache) -> List[Dict[str, str]]:
    """Join notified items with details and ratings into CSV-ready rows.

    Emits one row per USER_NOTIFIED entry (i.e. per listing per user), sorted
    by found_at descending.  Malformed or legacy cache entries are skipped.
    """
    details_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    rating_by_hash: Dict[str, Dict[str, Any]] = {}
    notified: List[Tuple[str, str, str, str, Optional[str], Optional[str]]] = []

    for key in local_cache.iterkeys():
        if not isinstance(key, tuple) or not key:
            continue
        tag = key[0]
        try:
            if tag == CacheType.LISTING_DETAILS.value:
                value = local_cache.get(key)
                if isinstance(value, dict) and "id" in value and "marketplace" in value:
                    details_by_key[(value["marketplace"], value["id"])] = value
            elif tag == CacheType.AI_INQUIRY.value and len(key) >= 4:
                value = local_cache.get(key)
                if isinstance(value, dict):
                    rating_by_hash[key[3]] = value
            elif tag == CacheType.USER_NOTIFIED.value and len(key) >= 4:
                date, listing_hash, price = _normalize_notified(local_cache.get(key))
                notified.append((key[1], key[2], key[3], date, listing_hash, price))
        except KeyboardInterrupt:
            raise
        except Exception:
            continue

    rows: List[Dict[str, str]] = []
    for marketplace, listing_id, user, date, listing_hash, price in notified:
        details = details_by_key.get((marketplace, listing_id)) or {}
        rating = (rating_by_hash.get(listing_hash) if listing_hash else None) or {}
        rows.append(
            {
                "found_at": date or "",
                "item": details.get("name", "") or "",
                "marketplace": marketplace,
                "title": details.get("title", "") or "",
                "price": (price if price is not None else details.get("price", "")) or "",
                "rating": str(rating["score"]) if "score" in rating else "",
                "ai_comment": rating.get("comment", "") or "",
                "location": details.get("location", "") or "",
                "seller": details.get("seller", "") or "",
                "condition": details.get("condition", "") or "",
                "notified_user": user,
                "url": details.get("post_url") or _fallback_url(marketplace, listing_id),
            }
        )

    rows.sort(key=lambda r: r["found_at"], reverse=True)
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra test pytest tests/test_found_export.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Run mypy on the new module + tests**

Run: `uv run --with mypy --extra test mypy src/ai_marketplace_monitor/webui/found_export.py tests/test_found_export.py`
Expected: `Success: no issues found`

- [ ] **Step 6: Commit**

```bash
git add src/ai_marketplace_monitor/webui/found_export.py tests/test_found_export.py
git commit -m "feat: join notified items into found-items rows (#334)"
```

---

### Task 3: `GET /api/found.csv` endpoint

**Files:**
- Modify: `src/ai_marketplace_monitor/webui/server.py` (add imports near the other `.`/`..` imports around lines 37–50; add the route inside `create_app`, just before `return app` at line 468)
- Modify: `CHANGELOG.md`
- Test: `tests/test_found_export.py`

**Interfaces:**
- Consumes: `build_found_rows`, `rows_to_csv` from `.found_export`; module-global `cache` from `..utils`; the `create_app`-local `require_session` dependency; `Response` (already imported at server.py line 30); `time` (already imported line 17).
- Produces: HTTP `GET /api/found.csv` → `200 text/csv` attachment, or `401` when exposed without a session.

- [ ] **Step 1: Write the failing endpoint tests**

Append to `tests/test_found_export.py`:

```python
from fastapi.testclient import TestClient  # noqa: E402

from ai_marketplace_monitor.webui import server as webui_server  # noqa: E402
from ai_marketplace_monitor.webui.config_api import ConfigFileService  # noqa: E402
from ai_marketplace_monitor.webui.log_handler import LogBroadcastHandler  # noqa: E402
from ai_marketplace_monitor.webui.server import AuthState, WebUIConfig, create_app  # noqa: E402


def _make_client(tmp_path: Path, temp_cache: Cache, monkeypatch: pytest.MonkeyPatch,
                 exposed: bool = False) -> TestClient:
    monkeypatch.setattr(webui_server, "cache", temp_cache)
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("[marketplace.facebook]\nsearch_city = 'dallas'\n", encoding="utf-8")
    handler = LogBroadcastHandler()
    config = WebUIConfig(config_files=[cfg_file], log_handler=handler)
    state = AuthState()
    state.exposed = exposed
    service = ConfigFileService([cfg_file])
    app = create_app(config, state, service, handler)
    return TestClient(app)


def test_endpoint_returns_csv(
    tmp_path: Path, temp_cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    listing = _listing()
    listing.to_cache(listing.post_url, local_cache=temp_cache)
    _seed_rating(temp_cache, listing)
    _seed_notified(temp_cache, listing)

    client = _make_client(tmp_path, temp_cache, monkeypatch)
    resp = client.get("/api/found.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    parsed = list(csv.DictReader(io.StringIO(resp.text)))
    assert len(parsed) == 1
    assert parsed[0]["rating"] == "5"
    assert parsed[0]["url"].startswith("https://www.facebook.com/marketplace/item/123/")


def test_endpoint_requires_session_when_exposed(
    tmp_path: Path, temp_cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _make_client(tmp_path, temp_cache, monkeypatch, exposed=True)
    resp = client.get("/api/found.csv")
    assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra test pytest tests/test_found_export.py -k endpoint -q`
Expected: FAIL — the CSV test gets `404` (route not registered); import of `webui_server.cache` may also fail until the import is added in Step 3.

- [ ] **Step 3: Add imports to `server.py`**

After the existing `from .log_handler import LogBroadcastHandler` line (around line 50), add:

```python
from ..utils import cache
from .found_export import build_found_rows, rows_to_csv
```

- [ ] **Step 4: Register the route in `create_app`**

Immediately before `return app` (server.py line 468), add:

```python
    @app.get("/api/found.csv")
    async def export_found_csv(_: str = Depends(require_session)) -> Response:
        csv_text = rows_to_csv(build_found_rows(cache))
        filename = f"found-items-{time.strftime('%Y%m%d-%H%M%S')}.csv"
        return Response(
            content=csv_text,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --extra test pytest tests/test_found_export.py -q`
Expected: PASS (9 passed)

- [ ] **Step 6: Add CHANGELOG entry**

In `CHANGELOG.md`, under `## [Unreleased]`, add an `### Added` block (create it if absent):

```markdown
### Added
- Web UI "Export CSV" button that downloads all found (notified) listings with link, price, rating, and details ([#334](https://github.com/BoPeng/ai-marketplace-monitor/issues/334))
```

- [ ] **Step 7: Commit**

```bash
git add src/ai_marketplace_monitor/webui/server.py tests/test_found_export.py CHANGELOG.md
git commit -m "feat: add GET /api/found.csv export endpoint (#334)"
```

---

### Task 4: Frontend button + download handler

**Files:**
- Modify: `src/ai_marketplace_monitor/webui/static/index.html` (header-right block, around line 34–38)
- Modify: `src/ai_marketplace_monitor/webui/static/app.js` (add a `wireClick` handler near the `#restart-btn` handler at line 538)
- Modify: `docs/README.md` (Web UI section — one line)

**Interfaces:**
- Consumes: existing `wireClick(sel, fn)`, `$(sel)`, `api(path, opts)` (returns `Response`, redirects to login on 401), `setEditorStatus(msg, kind)` from `app.js`; the `GET /api/found.csv` route from Task 3.

- [ ] **Step 1: Add the button to `index.html`**

In the `<div class="header-right">` block, insert before the `#logout-btn` button:

```html
        <button id="export-csv-btn" class="ghost small" title="Download all found items as CSV" aria-label="Download all found items as CSV">⬇ Export CSV</button>
```

- [ ] **Step 2: Add the click handler to `app.js`**

After the `wireClick("#restart-btn", …)` block (which ends around line 552), add:

```javascript
  wireClick("#export-csv-btn", async () => {
    const btn = $("#export-csv-btn");
    if (btn) btn.disabled = true;
    try {
      const res = await api("/api/found.csv");
      if (!res.ok) {
        setEditorStatus("⬇ Export failed: " + res.status, "err");
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const stamp = new Date()
        .toISOString()
        .slice(0, 19)
        .replace(/[-:T]/g, "")
        .replace(/(\d{8})(\d{6})/, "$1-$2");
      const a = document.createElement("a");
      a.href = url;
      a.download = `found-items-${stamp}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setEditorStatus("⬇ Export failed: " + err.message, "err");
    } finally {
      if (btn) btn.disabled = false;
    }
  });
```

- [ ] **Step 3: Add a docs mention**

In `docs/README.md`, in the Web UI section, add one sentence (adapt wording to the surrounding prose): "An **Export CSV** button in the header downloads all found (notified) listings — link, price, rating, and details — as a CSV file."

- [ ] **Step 4: Manual verification (no JS test harness in this repo)**

Run the Web UI against a config that has produced notifications (or seed the cache), then:

```bash
uv run ai-marketplace-monitor --webui --config <your-config.toml>
```

- Open the UI, confirm the **⬇ Export CSV** button appears in the header.
- Click it; confirm a `found-items-YYYYMMDD-HHMMSS.csv` downloads.
- Open the CSV; confirm the header row matches `found_at,item,marketplace,title,price,rating,ai_comment,location,seller,condition,notified_user,url` and that rows contain your notified items.
- Confirm the button briefly disables during the request and re-enables after.

If you have no real notifications yet, verify at least that the button downloads a header-only CSV without error.

- [ ] **Step 5: Commit**

```bash
git add src/ai_marketplace_monitor/webui/static/index.html src/ai_marketplace_monitor/webui/static/app.js docs/README.md
git commit -m "feat: Export CSV button in Web UI header (#334)"
```

---

### Task 5: Full verification + PR

**Files:** none (verification + git/gh only)

- [ ] **Step 1: Resolve pre-existing lint debt if present**

`pre-commit run --all-files` lints the whole repo, including the #336/#326 debt still on `main`. If PR #340 (`feat/sort-by-323`) has merged, rebase:

```bash
git fetch origin && git rebase origin/main
```

If #340 has **not** merged, cherry-pick its lint-fix commit so this branch is green on its own:

```bash
git cherry-pick 9a0dd09   # style: fix pre-existing black/ruff lint errors in facebook.py
```

- [ ] **Step 2: Run the full pre-commit suite**

Run: `uv run --with pre-commit pre-commit run --all-files`
Expected: all hooks pass (black, ruff, isort, etc.).

- [ ] **Step 3: Run mypy over all targets (matches CI)**

Run: `uv run --with mypy --extra test mypy src tests`
Expected: `Success: no issues found`

- [ ] **Step 4: Run the full test suite (matches CI)**

Run: `uv run --extra test pytest -q`
Expected: all pass (previous baseline 157 passed, 1 skipped; +9 new = 166 passed, 1 skipped).

- [ ] **Step 5: Push and open the PR**

```bash
gh auth switch --user BoPeng
GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=credential.helper GIT_CONFIG_VALUE_0="!gh auth git-credential" \
  git push -u origin feat/export-found-csv-334
gh pr create --repo BoPeng/ai-marketplace-monitor --base main \
  --title "feat: Web UI Export CSV of found items (#334)" \
  --body "Closes #334. Adds an authenticated GET /api/found.csv endpoint and a header button that downloads all found (notified) listings — link, price, rating, and details — by reading and joining the existing diskcache. No scraping, no new storage."
```

- [ ] **Step 6: Confirm CI is green**

Run: `gh pr checks <PR#> --repo BoPeng/ai-marketplace-monitor`
Expected: Linting, all test-matrix jobs, CodeQL, Analyze all pass. Do not report done until green.

---

## Self-Review

**Spec coverage:**
- Scope = notified items → Task 2 spine is `USER_NOTIFIED`. ✅
- Three-cache join, enumerate by tag → Task 2 `build_found_rows`. ✅
- Columns (12, fixed order) → Task 1 `CSV_COLUMNS`, asserted in tests. ✅
- Legacy `USER_NOTIFIED` normalization → Task 2 `_normalize_notified` + test. ✅
- Missing details / missing rating fallbacks → Task 2 tests. ✅
- Facebook fallback URL → Task 2 `_fallback_url` + test. ✅
- One row per (listing, user) → Task 2 multi-user test. ✅
- Sorted by found_at desc → Task 2 test. ✅
- Endpoint, `require_session` only, CSV headers → Task 3 + tests (200 + 401). ✅
- Frontend button + fetch/blob download, disable-in-flight → Task 4. ✅
- Empty cache → header-only CSV → covered by Task 1 empty test + Task 4 manual note. ✅
- Docs/CHANGELOG → Tasks 3 & 4. ✅
- Testing (unit + endpoint) → Tasks 1–3. ✅

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every command has expected output. ✅

**Type consistency:** `CSV_COLUMNS`, `rows_to_csv(rows)`, `build_found_rows(local_cache)`, `_normalize_notified(value)`, `_fallback_url(marketplace, listing_id)` are used with identical names/signatures across tasks. Endpoint reads module-global `cache` (monkeypatched in tests via `webui_server.cache`). ✅
