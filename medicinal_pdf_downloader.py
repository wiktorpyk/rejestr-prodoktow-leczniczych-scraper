"""
Downloader for rejestry.ezdrowie.gov.pl medicinal product PDFs.
Saves: {id}/characteristic.pdf, {id}/leaflet.pdf, {id}/packagings.pdf
Runs indefinitely from ID=1 upward; stops after a configurable streak of
consecutive empty IDs (all three endpoints 404/empty).
"""

import os
import time
import logging
import argparse
import requests
from pathlib import Path

# ── configuration ────────────────────────────────────────────────────────────
BASE_URL   = "https://rejestry.ezdrowie.gov.pl/api/rpl/medicinal-products"
ENDPOINTS  = ["characteristic", "leaflet"]
OUT_DIR    = Path("data")           # root output directory
DELAY      = 0.5                    # seconds between requests
TIMEOUT    = 30                     # request timeout in seconds
MAX_EMPTY  = 200                    # stop after this many consecutive all-empty IDs
START_ID   = 1

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; medicinal-dl/1.0)",
    "Accept": "application/pdf,*/*",
})

# ── helpers ───────────────────────────────────────────────────────────────────

def fetch_pdf(product_id: int, endpoint: str, max_retries: int = 3) -> bytes | None:
    """
    Download one PDF.  Returns raw bytes on success, None on 404/empty.
    Raises for other HTTP errors.
    """
    url = f"{BASE_URL}/{product_id}/{endpoint}"
    
    for attempt in range(max_retries):
        try:
            r = SESSION.get(url, timeout=TIMEOUT)
            break
        except requests.RequestException as exc:
            if attempt == max_retries - 1:
                log.warning("  network error [%s] %s: %s (after %d retries)", product_id, endpoint, exc, max_retries)
                return None
            wait_time = (2 ** attempt) * DELAY
            log.warning("  network error [%s] %s: %s (retry %d/%d in %.1fs)", 
                       product_id, endpoint, exc, attempt + 1, max_retries, wait_time)
            time.sleep(wait_time)

    if r.status_code == 404:
        return None
    if r.status_code != 200:
        log.warning("  HTTP %d [%s] %s", r.status_code, product_id, endpoint)
        return None

    content = r.content
    # Treat suspiciously small responses as empty (some APIs return 200 + empty body)
    if len(content) < 64:
        return None

    # Verify PDF magic bytes
    # if not content.startswith(b"%PDF"):
    #     log.warning("  not a PDF [%s] %s (got %r…)", product_id, endpoint, content[:12])
    #     return None

    return content


def save(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def already_done(product_id: int) -> bool:
    """True only if ALL three files exist and are non-empty for this ID."""
    product_dir = OUT_DIR / str(product_id)
    return all(
        (product_dir / f"{ep}.pdf").exists() and
        (product_dir / f"{ep}.pdf").stat().st_size > 64
        for ep in ENDPOINTS
    )

# ── main loop ─────────────────────────────────────────────────────────────────

def run(start_id: int = START_ID, max_empty: int = MAX_EMPTY) -> None:
    empty_streak = 0
    product_id   = start_id

    log.info("Starting download from ID=%d  (stop after %d consecutive empty IDs)",
             start_id, max_empty)

    while True:
        # ── skip if already fully downloaded ──────────────────────────────────
        if already_done(product_id):
            log.debug("  [%d] already complete, skipping", product_id)
            product_id += 1
            continue

        log.info("[%d] fetching …", product_id)

        any_saved = False
        for endpoint in ENDPOINTS:
            dest = OUT_DIR / str(product_id) / f"{endpoint}.pdf"

            # skip individual file if it already exists
            if dest.exists() and dest.stat().st_size > 64:
                log.debug("  [%d] %s already exists", product_id, endpoint)
                any_saved = True
                continue

            data = fetch_pdf(product_id, endpoint)
            time.sleep(DELAY)

            if data is None:
                log.debug("  [%d] %s → not found / empty", product_id, endpoint)
            else:
                save(dest, data)
                log.info("  [%d] %s → %s  (%d KB)",
                         product_id, endpoint, dest, len(data) // 1024)
                any_saved = True

        # ── track consecutive-empty streak ────────────────────────────────────
        if any_saved:
            empty_streak = 0
        else:
            empty_streak += 1
            log.info("[%d] nothing found  (empty streak: %d / %d)",
                     product_id, empty_streak, max_empty)
            if empty_streak >= max_empty:
                log.info("Reached %d consecutive empty IDs — stopping.", max_empty)
                break

        product_id += 1


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download medicinal-product PDFs from rejestry.ezdrowie.gov.pl"
    )
    parser.add_argument(
        "--start", type=int, default=START_ID,
        help=f"First product ID to try (default: {START_ID})"
    )
    parser.add_argument(
        "--out", type=str, default=str(OUT_DIR),
        help=f"Root output directory (default: {OUT_DIR})"
    )
    parser.add_argument(
        "--delay", type=float, default=DELAY,
        help=f"Seconds between requests (default: {DELAY})"
    )
    parser.add_argument(
        "--max-empty", type=int, default=MAX_EMPTY,
        help=f"Stop after N consecutive all-empty IDs (default: {MAX_EMPTY})"
    )
    parser.add_argument(
        "--infinite", action="store_true",
        help="Never stop on empty streaks — run truly forever"
    )
    args = parser.parse_args()

    OUT_DIR = Path(args.out)
    DELAY   = args.delay

    run(
        start_id  = args.start,
        max_empty = 10**9 if args.infinite else args.max_empty,
    )