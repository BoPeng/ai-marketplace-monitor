"""Human-like browser actions to avoid bot detection.

The Facebook captcha trigger is usually one of:
  1. `navigator.webdriver === true`  (Playwright default — instant flag)
  2. Headless fingerprint (missing plugins/languages/UA-CH, no chrome.runtime)
  3. Uniform per-key typing delay (`page.fill` is instant, `type(delay=250)` is too regular)
  4. No mouse movement, no scrolling, no idle time between actions

This module bundles the mitigations:
  - HUMAN_LAUNCH_ARGS   : Chromium flags that strip the automation banner
  - HUMAN_CONTEXT_OPTS  : sensible UA/viewport/locale/timezone for AKL traffic
  - STEALTH_INIT_SCRIPT : JS executed on every new doc to undo webdriver tells
  - human_sleep         : random sleep with jitter
  - human_type          : per-char typing with variable delay + occasional pauses
  - human_mouse_jitter  : small idle mouse path
  - apply_stealth(ctx)  : one-shot setup for a Playwright context
"""

import random
import time
from typing import Any, Dict


# --- Stealth knobs ---------------------------------------------------------

# Chromium launch args. Removes the "Chrome is being controlled by automated
# test software" banner and a couple of headless tells.
HUMAN_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--no-default-browser-check",
    "--no-first-run",
    "--password-store=basic",
    "--use-mock-keychain",
]

# Recent real Chrome UA. Refresh this every few months.
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Per-call context options. Slight viewport randomisation keeps fingerprints
# from being byte-identical across runs.
def human_context_opts(locale: str = "en-NZ", timezone: str = "Pacific/Auckland") -> Dict[str, Any]:
    viewports = [
        {"width": 1366, "height": 768},
        {"width": 1440, "height": 900},
        {"width": 1536, "height": 864},
        {"width": 1600, "height": 900},
        {"width": 1920, "height": 1080},
    ]
    return {
        "user_agent": DEFAULT_UA,
        "viewport": random.choice(viewports),
        "locale": locale,
        "timezone_id": timezone,
        "device_scale_factor": random.choice([1, 1, 2]),  # mostly 1
        "is_mobile": False,
        "has_touch": False,
        "java_script_enabled": True,
        "color_scheme": "light",
        "extra_http_headers": {
            "Accept-Language": f"{locale},en;q=0.9",
            "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
        },
    }


# Run-on-new-document script that removes the obvious webdriver tells.
STEALTH_INIT_SCRIPT = r"""
(() => {
  // 1. navigator.webdriver -> undefined
  try {
    Object.defineProperty(Navigator.prototype, 'webdriver', {get: () => undefined});
  } catch (e) {}

  // 2. Plugins & mimeTypes — Playwright/Chromium-headless leaves these empty.
  try {
    Object.defineProperty(navigator, 'plugins', {
      get: () => [{name: 'PDF Viewer'}, {name: 'Chrome PDF Viewer'}, {name: 'Native Client'}],
    });
    Object.defineProperty(navigator, 'mimeTypes', {get: () => [1, 2, 3]});
  } catch (e) {}

  // 3. Languages
  try {
    Object.defineProperty(navigator, 'languages', {get: () => ['en-NZ', 'en']});
  } catch (e) {}

  // 4. chrome.runtime — present in real Chrome, missing in headless
  if (!window.chrome) { window.chrome = {}; }
  if (!window.chrome.runtime) { window.chrome.runtime = {}; }

  // 5. permissions query — headless reports 'denied' for notifications even when default
  try {
    const orig = window.navigator.permissions.query.bind(window.navigator.permissions);
    window.navigator.permissions.query = (p) => (
      p && p.name === 'notifications'
        ? Promise.resolve({state: Notification.permission})
        : orig(p)
    );
  } catch (e) {}

  // 6. WebGL vendor & renderer — return realistic strings
  try {
    const getParam = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function (p) {
      if (p === 37445) return 'Intel Inc.';                       // UNMASKED_VENDOR_WEBGL
      if (p === 37446) return 'Intel Iris OpenGL Engine';         // UNMASKED_RENDERER_WEBGL
      return getParam.call(this, p);
    };
  } catch (e) {}
})();
"""


def apply_stealth(context) -> None:
    """Attach the init script to a Playwright BrowserContext."""
    try:
        context.add_init_script(STEALTH_INIT_SCRIPT)
    except Exception:
        pass


# --- Action helpers --------------------------------------------------------

def human_sleep(low: float = 0.4, high: float = 1.2) -> None:
    """Sleep a random fraction of a second. Use between user-facing actions."""
    time.sleep(random.uniform(low, high))


def human_type(selector_or_locator, text: str, *, base_delay_ms: int = 80) -> None:
    """Type into a Playwright locator with variable per-char delay + occasional pauses.

    Real humans don't type with a fixed 250ms cadence. Mean ~80ms, jitter ±50ms,
    plus a 10% chance of a 200–500ms "think" pause between characters.
    """
    # Click first to focus, with a tiny pre-click pause.
    try:
        selector_or_locator.click()
    except Exception:
        pass
    human_sleep(0.15, 0.4)

    for ch in text:
        delay = max(20, int(random.gauss(base_delay_ms, 35)))
        try:
            selector_or_locator.type(ch, delay=delay)
        except Exception:
            # Fallback: PressSequence via keyboard
            try:
                selector_or_locator.press(ch)
            except Exception:
                pass
        # Occasional thinking pause
        if random.random() < 0.10:
            time.sleep(random.uniform(0.2, 0.5))


def human_mouse_jitter(page, *, moves: int = 3) -> None:
    """Wiggle the mouse to a few random points within the viewport."""
    try:
        vp = page.viewport_size or {"width": 1366, "height": 768}
        for _ in range(moves):
            x = random.randint(50, max(60, vp["width"] - 50))
            y = random.randint(50, max(60, vp["height"] - 50))
            page.mouse.move(x, y, steps=random.randint(8, 20))
            time.sleep(random.uniform(0.05, 0.2))
    except Exception:
        pass


def human_scroll(page, *, steps: int = None) -> None:
    """Scroll the page like a human reading results."""
    n = steps if steps is not None else random.randint(2, 5)
    try:
        for _ in range(n):
            dy = random.randint(200, 700)
            page.mouse.wheel(0, dy)
            time.sleep(random.uniform(0.3, 1.1))
        # Occasionally scroll back up a bit
        if random.random() < 0.3:
            page.mouse.wheel(0, -random.randint(100, 300))
            time.sleep(random.uniform(0.2, 0.5))
    except Exception:
        pass
