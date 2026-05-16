"""Detect & OCR license plates from listing images.

Pipeline:
  1. open-image-models  → YOLO v9 ONNX plate detector  (returns bounding boxes)
  2. fast-plate-ocr     → CCT ONNX plate recogniser   (reads text from each crop)

Both run on CPU via onnxruntime (typically 50–150 ms / image after warm-up).
Models are auto-downloaded on first use into the user-cache dir; subsequent runs
load from disk. No GPU / no internet needed after the first run.

Install:
    pip install fast-plate-ocr open-image-models pillow numpy

Pre-warm:
    python -m ai_marketplace_monitor.plate_ocr --warmup
"""

import io
import os
import pathlib
import re
import urllib.request
from logging import Logger
from typing import List, Optional

# Heavy deps are lazy-imported so the rest of the app starts fast.
_detector = None
_recognizer = None

# NZ plate sanity filter: 2–3 letters + 2–4 digits.
_NZ_PLATE_RE = re.compile(r"^[A-Z]{2,3}\d{2,4}$")

# Defaults — the BIGGEST available ONNX models from each library.
#   Detector: yolo-v9-s (small, 27MB) at 608px input — much better recall on
#             small/angled plates than the t-384 tiny variant.
#   OCR:      global-plates-mobile-vit-v2 (4.8MB) — newer MobileViT v2 arch,
#             stronger than the CCT-XS we used initially.
DEFAULT_DETECTION_MODEL = "yolo-v9-s-608-license-plate-end2end"
DEFAULT_RECOGNIZER_MODEL = "global-plates-mobile-vit-v2-model"

# Lower the detector confidence threshold so we catch small plates in
# distant/angled shots. The OCR step + NZ-format regex filter out garbage.
DEFAULT_DETECTOR_CONF = 0.15

# Project-local model directory — checked in alongside the code so we don't
# depend on a hidden ~/.cache directory the user can't see.
# Override via AIMM_MODELS_DIR env var.
_PKG_ROOT = pathlib.Path(__file__).resolve().parents[2]
MODELS_DIR = pathlib.Path(os.environ.get("AIMM_MODELS_DIR") or (_PKG_ROOT / "models"))

DETECTOR_ONNX = MODELS_DIR / "yolo-v9-s-608-license-plates-end2end.onnx"
RECOGNIZER_ONNX = MODELS_DIR / "global_mobile_vit_v2_ocr.onnx"
RECOGNIZER_CONFIG = MODELS_DIR / "global_mobile_vit_v2_ocr_config.yaml"


def _ensure_models(logger: Logger | None = None):
    global _detector, _recognizer
    if _detector is not None and _recognizer is not None:
        return _detector, _recognizer
    try:
        from fast_plate_ocr import LicensePlateRecognizer  # type: ignore
        from open_image_models import LicensePlateDetector  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "Plate OCR deps missing. Install with:\n"
            "    pip install fast-plate-ocr open-image-models pillow numpy"
        ) from e

    if logger:
        logger.info(f"[PlateOCR] Loading models from {MODELS_DIR}...")

    # --- Recognizer: native path support ---
    if RECOGNIZER_ONNX.is_file() and RECOGNIZER_CONFIG.is_file():
        _recognizer = LicensePlateRecognizer(
            onnx_model_path=str(RECOGNIZER_ONNX),
            plate_config_path=str(RECOGNIZER_CONFIG),
        )
    else:
        if logger:
            logger.warning(
                f"[PlateOCR] Recognizer ONNX missing at {RECOGNIZER_ONNX}, "
                "falling back to hub download."
            )
        _recognizer = LicensePlateRecognizer(DEFAULT_RECOGNIZER_MODEL)

    # --- Detector: no path arg, so monkey-patch download_model to return the
    # local file. open-image-models' download_model just no-ops if the file
    # already exists, so this is safe and idempotent.
    if DETECTOR_ONNX.is_file():
        try:
            from open_image_models.detection.pipeline import license_plate as _lp_mod  # type: ignore
            _original_dl = _lp_mod.download_model
            def _local_download(name, *a, **kw):
                if str(name) == DEFAULT_DETECTION_MODEL:
                    return DETECTOR_ONNX
                return _original_dl(name, *a, **kw)
            _lp_mod.download_model = _local_download
        except Exception as e:
            if logger:
                logger.debug(f"[PlateOCR] Could not patch detector loader: {e}")
    elif logger:
        logger.warning(
            f"[PlateOCR] Detector ONNX missing at {DETECTOR_ONNX}, "
            "falling back to hub download."
        )

    _detector = LicensePlateDetector(
        detection_model=DEFAULT_DETECTION_MODEL,
        conf_thresh=DEFAULT_DETECTOR_CONF,
    )

    if logger:
        logger.info("[PlateOCR] Models ready.")
    return _detector, _recognizer


def _load_image_bytes_to_np(image_bytes: bytes):
    import numpy as np  # type: ignore
    from PIL import Image  # type: ignore

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    return np.array(img)


def _bbox_xyxy(det) -> Optional[tuple[int, int, int, int]]:
    """Normalise bbox across open-image-models versions."""
    bb = getattr(det, "bounding_box", None) or getattr(det, "bbox", None)
    if bb is None:
        return None
    if hasattr(bb, "x1"):
        return int(bb.x1), int(bb.y1), int(bb.x2), int(bb.y2)
    try:
        x1, y1, x2, y2 = bb
        return int(x1), int(y1), int(x2), int(y2)
    except Exception:
        return None


def detect_plates_from_image(
    image_bytes: bytes, logger: Logger | None = None, nz_only: bool = True
) -> List[str]:
    """Detect plates in an image. Returns plate strings (filtered to NZ-format by default)."""
    try:
        detector, recognizer = _ensure_models(logger)
    except RuntimeError as e:
        if logger:
            logger.debug(f"[PlateOCR] {e}")
        return []

    try:
        img = _load_image_bytes_to_np(image_bytes)
    except Exception as e:
        if logger:
            logger.debug(f"[PlateOCR] Image decode failed: {e}")
        return []

    plates: List[str] = []
    raw_reads: List[str] = []
    try:
        detections = detector.predict(img)
    except Exception as e:
        if logger:
            logger.debug(f"[PlateOCR] Detector error: {e}")
        return []

    if logger:
        h, w = img.shape[:2]
        logger.info(f"[PlateOCR] Image {w}x{h} → {len(detections)} detection(s)")

    for det in detections:
        bbox = _bbox_xyxy(det)
        if bbox is None:
            continue
        x1, y1, x2, y2 = bbox
        h, w = img.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            continue
        crop = img[y1:y2, x1:x2]
        # fast-plate-ocr's global ViT model expects a 1-channel (grayscale) input.
        # Our img is RGB (H, W, 3), so collapse to luminance.
        try:
            import numpy as np  # type: ignore
            if crop.ndim == 3 and crop.shape[2] == 3:
                # Rec.601 luminance weights — cheap and matches typical OCR preprocessing.
                crop_gray = (
                    0.299 * crop[..., 0] + 0.587 * crop[..., 1] + 0.114 * crop[..., 2]
                ).astype(np.uint8)
            else:
                crop_gray = crop
        except Exception:
            crop_gray = crop

        try:
            result = recognizer.run(crop_gray)
        except Exception as e:
            if logger:
                logger.warning(f"[PlateOCR] Recognizer error: {e}")
            continue

        # fast-plate-ocr returns list[PlatePrediction] — extract .plate string.
        text = ""
        if isinstance(result, (list, tuple)) and result:
            first = result[0]
            text = getattr(first, "plate", None) or str(first)
        elif result is not None:
            text = getattr(result, "plate", None) or str(result)

        cleaned = re.sub(r"[^A-Za-z0-9]", "", text).upper()
        if not cleaned:
            if logger:
                logger.info(f"[PlateOCR] OCR returned empty text for a {x2-x1}x{y2-y1} crop")
            continue
        raw_reads.append(cleaned)
        if nz_only and not _NZ_PLATE_RE.match(cleaned):
            if logger:
                logger.info(f"[PlateOCR] Read '{cleaned}' — not NZ format, skipping")
            continue
        if logger:
            logger.info(f"[PlateOCR] Read '{cleaned}' ✓")
        plates.append(cleaned)

    # De-dupe while preserving order
    seen, unique = set(), []
    for p in plates:
        if p not in seen:
            seen.add(p)
            unique.append(p)

    if logger:
        if unique:
            logger.info(f"[PlateOCR] Detected (NZ format): {unique}")
        elif raw_reads:
            logger.info(f"[PlateOCR] Read text but no NZ-format match: {raw_reads}")
    return unique


def detect_plates_from_url(
    url: str, logger: Logger | None = None, nz_only: bool = True, timeout: float = 10.0
) -> List[str]:
    """Download an image URL and run plate detection on it."""
    if not url:
        return []
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                )
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
    except Exception as e:
        if logger:
            logger.debug(f"[PlateOCR] Failed to fetch {url}: {e}")
        return []
    return detect_plates_from_image(data, logger=logger, nz_only=nz_only)


def fetch_listing_photos(post_url: str, browser, logger=None, max_photos: int = 12) -> list[str]:
    """Open a Facebook Marketplace listing URL and pull every product photo URL.

    Facebook tags listing photos with `alt="Product photo of <title>"`.
    Both the main image and every thumbnail use the same alt pattern, so a
    single CSS selector covers the gallery.
    """
    if not post_url or not browser:
        return []
    page = None
    try:
        page = browser.new_page()
        page.set_default_timeout(20000)
        page.goto(post_url, wait_until="domcontentloaded", timeout=20000)
        try:
            page.wait_for_selector('img[alt^="Product photo"]', timeout=10000)
        except Exception:
            # Fallback: any img inside the listing viewer dialog
            page.wait_for_selector(
                'div[aria-label="Marketplace listing viewer"] img', timeout=10000
            )
        # Let lazy-loaded thumbnails populate
        page.wait_for_timeout(900)
        # Deduplicate src URLs, preserve order.
        urls = page.eval_on_selector_all(
            'img[alt^="Product photo"], div[aria-label="Marketplace listing viewer"] img',
            "els => Array.from(new Set(els.map(e => e.currentSrc || e.src).filter(Boolean)))",
        )
        # Filter out obvious non-photo assets (profile pics, sponsored ads).
        urls = [u for u in urls if "fbcdn" in u and "static_map" not in u]
        if logger:
            logger.info(f"[PlateOCR] Fetched {len(urls)} photos from listing.")
        return urls[:max_photos]
    except Exception as e:
        if logger:
            logger.debug(f"[PlateOCR] fetch_listing_photos failed: {e}")
        return []
    finally:
        if page:
            try:
                page.close()
            except Exception:
                pass


def detect_plates_from_listing(
    post_url: str, browser, logger=None, nz_only: bool = True, max_photos: int = 12
) -> list[str]:
    """Visit a listing page, pull every product photo, OCR them all.

    Returns the de-duplicated list of plates found across all images, in the
    order they appeared (so the first plate is from the hero image).
    """
    photos = fetch_listing_photos(post_url, browser, logger=logger, max_photos=max_photos)
    all_plates: list[str] = []
    seen = set()
    for i, url in enumerate(photos):
        plates = detect_plates_from_url(url, logger=logger, nz_only=nz_only)
        for p in plates:
            if p not in seen:
                seen.add(p)
                all_plates.append(p)
        if all_plates:
            if logger:
                logger.info(
                    f"[PlateOCR] Found plate(s) after {i + 1}/{len(photos)} photos: {all_plates}"
                )
            # Early-exit: we have a plate, no need to OCR the rest
            break
    return all_plates


if __name__ == "__main__":
    import argparse
    import logging
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = logging.getLogger("plate_ocr")

    p = argparse.ArgumentParser()
    p.add_argument("--warmup", action="store_true", help="Download & load models, then exit.")
    p.add_argument("--url", help="Run OCR on an image URL.")
    p.add_argument("--file", help="Run OCR on a local image path.")
    p.add_argument("--no-nz-filter", action="store_true")
    args = p.parse_args()

    if args.warmup:
        _ensure_models(log)
        print("Models ready.")
        sys.exit(0)
    if args.url:
        print(detect_plates_from_url(args.url, logger=log, nz_only=not args.no_nz_filter))
    elif args.file:
        with open(args.file, "rb") as f:
            print(detect_plates_from_image(f.read(), logger=log, nz_only=not args.no_nz_filter))
    else:
        p.print_help()
