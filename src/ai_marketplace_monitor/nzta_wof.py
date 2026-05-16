"""NZTA WOF/Rego expiry checker via transact.nzta.govt.nz.

Drives the Blazor "Check expiry" form with Playwright and parses the result page.

Confirmed page structure (from live capture):
  - Form input:   <input id="plate" type="text" maxlength="6">
  - Submit:       <button class="button-primary-1" type="submit">Continue</button>
  - Results:
      <table>
        <tr><td>Plate number</td><td><strong>DYS664</strong></td></tr>
        <tr><td>Vehicle details</td><td><strong>1996 TOYOTA CELICA</strong></td></tr>
        <tr><td>Vehicle colour</td><td><strong>WHITE</strong></td></tr>
      </table>
      <dl><dt><b>Warrant of fitness expiry date</b></dt><dd>23 August 2026</dd></dl>
      <dl><dt><b>Licence expiry date</b></dt><dd>25 August 2026</dd></dl>
"""

import re
from dataclasses import dataclass
from datetime import datetime
from logging import Logger
from typing import Optional

from playwright.sync_api import Browser, Page

from .utils import hilight

NZ_PLATE_PATTERN = re.compile(r"\b([A-Z]{2,3}\d{2,4})\b", re.IGNORECASE)
NZTA_CHECK_URL = "https://transact.nzta.govt.nz/v2/Check-Expiry"


@dataclass
class WOFResult:
    plate: str
    vehicle: str             # "1996 TOYOTA CELICA"
    colour: str              # "WHITE"
    wof_expiry: str          # "23 August 2026"
    rego_expiry: str         # "25 August 2026"
    wof_status: str          # "Current" | "Expired" | "Unknown"
    rego_status: str         # "Current" | "Expired" | "Unknown"
    wof_days_remaining: Optional[int] = None
    rego_days_remaining: Optional[int] = None

    @property
    def summary(self) -> str:
        wof_icon = {"Current": "✅", "Expired": "❌"}.get(self.wof_status, "❓")
        rego_icon = {"Current": "✅", "Expired": "❌"}.get(self.rego_status, "❓")
        wof_extra = (
            f" ({self.wof_days_remaining}d left)"
            if self.wof_days_remaining is not None and self.wof_status == "Current"
            else ""
        )
        rego_extra = (
            f" ({self.rego_days_remaining}d left)"
            if self.rego_days_remaining is not None and self.rego_status == "Current"
            else ""
        )
        head = f"Plate: {self.plate}"
        if self.vehicle:
            head += f" — {self.vehicle}"
        if self.colour:
            head += f" ({self.colour.title()})"
        return (
            f"{head}\n"
            f"{wof_icon} WOF: {self.wof_expiry}{wof_extra}\n"
            f"{rego_icon} Rego: {self.rego_expiry}{rego_extra}"
        )


# --- Description-level WOF/rego text scanning ---------------------------

_NO_WOF_RE = re.compile(r"\bno\s*(?:current\s*)?wof\b|\bwof\s*expired\b", re.I)
_FRESH_WOF_RE = re.compile(
    r"\b(?:new|fresh|full|long|just\s*passed)\s*wof\b"
    r"|\bwof\s*(?:until|till|to|valid|good)\b"
    r"|\b12\s*months?\s*wof\b",
    re.I,
)
_NO_REGO_RE = re.compile(r"\bno\s*(?:current\s*)?rego\b|\brego\s*expired\b", re.I)
_FRESH_REGO_RE = re.compile(
    r"\b(?:new|fresh|full|long)\s*rego\b|\brego\s*(?:until|till|to|valid)\b"
    r"|\b12\s*months?\s*rego\b",
    re.I,
)


def scan_wof_text(text: str) -> dict:
    """Look for seller-stated WOF/rego info in a title or description.

    Returns dict with keys:
      - wof_claim: 'fresh' | 'no' | None
      - rego_claim: 'fresh' | 'no' | None
    """
    text = text or ""
    return {
        "wof_claim": "no" if _NO_WOF_RE.search(text) else ("fresh" if _FRESH_WOF_RE.search(text) else None),
        "rego_claim": "no" if _NO_REGO_RE.search(text) else ("fresh" if _FRESH_REGO_RE.search(text) else None),
    }


# --- Notification gating --------------------------------------------------

def should_notify(
    wof: Optional[WOFResult],
    text_claims: Optional[dict] = None,
    min_wof_days: int = 30,
    max_rego_days_overdue: int = 365,
) -> tuple[bool, str]:
    """Decide whether to push this listing to the phone.

    Rules (per user spec):
      - WOF expired                        → SKIP
      - WOF expires in < min_wof_days days → SKIP
      - Rego expired more than max_rego_days_overdue days → SKIP
      - Anything else                       → NOTIFY

    If we got NO data from NZTA (no plate / scrape failed), fall back to
    seller-stated text claims: "no WOF" → SKIP, otherwise NOTIFY (we don't
    have proof but the seller hasn't admitted to no WOF).
    """
    if wof is None:
        if text_claims and text_claims.get("wof_claim") == "no":
            return False, "seller stated: no WOF"
        if text_claims and text_claims.get("rego_claim") == "no":
            return False, "seller stated: no rego"
        return True, "no plate / no NZTA data — notifying anyway"

    # WOF gating
    if wof.wof_status == "Expired":
        return False, f"WOF expired ({wof.wof_expiry})"
    if (
        wof.wof_status == "Current"
        and wof.wof_days_remaining is not None
        and wof.wof_days_remaining < min_wof_days
    ):
        return False, f"WOF expires in {wof.wof_days_remaining} days (<{min_wof_days})"

    # Rego gating — only block if very overdue
    if (
        wof.rego_status == "Expired"
        and wof.rego_days_remaining is not None
        and wof.rego_days_remaining < -max_rego_days_overdue
    ):
        return False, f"rego expired {-wof.rego_days_remaining} days ago"

    return True, "WOF/rego OK"


def extract_plate_from_text(text: str) -> Optional[str]:
    """Try to find a NZ plate number in a listing title or description."""
    if not text:
        return None
    match = NZ_PLATE_PATTERN.search(text.upper())
    return match.group(1).upper() if match else None


def _parse_date(date_str: str) -> Optional[datetime]:
    """Parse '23 August 2026' style date."""
    if not date_str:
        return None
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


def _status_from_date(date_str: str) -> tuple[str, Optional[int]]:
    parsed = _parse_date(date_str)
    if parsed is None:
        return "Unknown", None
    delta = (parsed - datetime.now()).days
    return ("Current" if delta >= 0 else "Expired"), delta


def _safe_inner_text(page: Page, selector: str) -> str:
    try:
        loc = page.locator(selector).first
        loc.wait_for(state="attached", timeout=3000)
        return (loc.inner_text() or "").strip()
    except Exception:
        return ""


def check_wof(plate: str, browser: Browser, logger: Logger | None = None) -> Optional[WOFResult]:
    """Submit the plate to NZTA Check-Expiry and parse the result."""
    plate = (plate or "").strip().upper()
    if not plate:
        return None

    page: Page | None = None
    try:
        page = browser.new_page()
        page.set_default_timeout(20000)

        if logger:
            logger.info(f"{hilight('[WOF]', 'info')} Checking plate {hilight(plate)}...")

        page.goto(NZTA_CHECK_URL, wait_until="networkidle")

        # Wait for the Blazor form to mount
        page.wait_for_selector("#plate", state="visible", timeout=15000)
        page.fill("#plate", plate)

        # Click the "Continue" submit button
        page.locator('button[type="submit"]:has-text("Continue")').first.click()

        # Wait for the SPA to swap in the results section (no navigation)
        page.wait_for_selector('h3:has-text("Expiry details")', timeout=20000)
        page.wait_for_selector(
            'dt:has-text("Warrant of fitness expiry date")', timeout=10000
        )

        # ---- Parse table rows by label ----
        vehicle = _safe_inner_text(
            page, 'xpath=//td[contains(., "Vehicle details")]/following-sibling::td[1]'
        )
        colour = _safe_inner_text(
            page, 'xpath=//td[contains(., "Vehicle colour")]/following-sibling::td[1]'
        )

        # ---- Parse <dl> sections ----
        wof_expiry = _safe_inner_text(
            page,
            'xpath=//dt[contains(., "Warrant of fitness expiry date")]/following-sibling::dd[1]',
        )
        rego_expiry = _safe_inner_text(
            page,
            'xpath=//dt[contains(., "Licence expiry date")]/following-sibling::dd[1]',
        )

        wof_status, wof_days = _status_from_date(wof_expiry)
        rego_status, rego_days = _status_from_date(rego_expiry)

        # Fallback: if dates didn't parse, look for inline "expired" phrases
        body_text = ""
        try:
            body_text = page.inner_text("#nzta-main-content")
        except Exception:
            pass
        if wof_status == "Unknown" and re.search(r"warrant.*expired", body_text, re.I):
            wof_status = "Expired"
        if rego_status == "Unknown" and re.search(r"licence.*expired", body_text, re.I):
            rego_status = "Expired"

        result = WOFResult(
            plate=plate,
            vehicle=vehicle,
            colour=colour,
            wof_expiry=wof_expiry or "Unknown",
            rego_expiry=rego_expiry or "Unknown",
            wof_status=wof_status,
            rego_status=rego_status,
            wof_days_remaining=wof_days,
            rego_days_remaining=rego_days,
        )

        if logger:
            logger.info(f"{hilight('[WOF]', 'succ')} {result.summary}")
        return result

    except KeyboardInterrupt:
        raise
    except Exception as e:
        if logger:
            logger.error(f"{hilight('[WOF]', 'fail')} Failed to check plate {plate}: {e}")
        return None
    finally:
        if page:
            try:
                page.close()
            except Exception:
                pass
