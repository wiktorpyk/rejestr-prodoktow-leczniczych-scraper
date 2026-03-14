#!/usr/bin/env python3
"""
Download all pages from the Polish medicines registry (Rejestr Produktów Leczniczych)
and combine into a single JSON file sorted by "id".
"""

import json
import time
import sys
import urllib.request
import urllib.error

BASE_URL = (
    "https://rejestry.ezdrowie.gov.pl/api/rpl/medicinal-products/search/public"
    "?subjectRolesIds=1&size=2000&page={page}"
)
OUTPUT_FILE = "medicines.json"
DELAY = 0.3  # seconds between requests — be polite to the server


def fetch_page(page: int) -> dict:
    url = BASE_URL.format(page=page)
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (medicines-downloader/1.0)",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    print("Fetching page 0 to determine total pages...")
    first = fetch_page(0)

    total_pages = first.get("totalPages")
    total_elements = first.get("totalElements")
    if total_pages is None:
        print("ERROR: Could not determine totalPages from response.")
        print("Response keys:", list(first.keys()))
        sys.exit(1)

    print(f"Total elements: {total_elements}, total pages: {total_pages}")

    all_records = list(first.get("content", []))
    print(f"  Page 0: {len(all_records)} records")

    for page in range(1, total_pages):
        time.sleep(DELAY)
        try:
            data = fetch_page(page)
            content = data.get("content", [])
            all_records.extend(content)
            print(f"  Page {page}/{total_pages - 1}: {len(content)} records  "
                  f"(running total: {len(all_records)})")
        except urllib.error.URLError as e:
            print(f"  ERROR on page {page}: {e} — retrying once...")
            time.sleep(2)
            data = fetch_page(page)
            content = data.get("content", [])
            all_records.extend(content)

    print(f"\nDownloaded {len(all_records)} records total.")

    all_records.sort(key=lambda r: r.get("id", 0))
    print(f"Sorted by id. First id: {all_records[0]['id']}, "
          f"last id: {all_records[-1]['id']}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_records, f, ensure_ascii=False, indent=2)

    print(f"\nSaved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()