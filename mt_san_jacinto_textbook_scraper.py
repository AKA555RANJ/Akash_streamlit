#!/usr/bin/env python3
"""Textbook scraper for Mt San Jacinto Community College District (bncvirtual.com)."""

import os
import sys

from bnc_textbook_scraper import scrape, write_csv

FVCUSNO = "3984"
SCHOOL_ID = "2996016"
SCHOOL_SLUG = "mt_san_jacinto_community_college_district"
FLARESOLVERR_URL = "http://localhost:8191/v1"
OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    f"{SCHOOL_SLUG}__{SCHOOL_ID}__bks",
)
CSV_FILENAME = f"{SCHOOL_SLUG}__{SCHOOL_ID}__bks.csv"


def main():
    rows = scrape(
        fvcusno=FVCUSNO,
        school_id=SCHOOL_ID,
        output_dir=OUTPUT_DIR,
        flaresolverr_url=FLARESOLVERR_URL,
    )
    if not rows:
        print("[!] No data collected.")
        sys.exit(1)

    csv_path = os.path.join(OUTPUT_DIR, CSV_FILENAME)
    write_csv(rows, csv_path)

    courses_with_isbn = sum(1 for r in rows if r.get("isbn"))
    courses_without = sum(1 for r in rows if not r.get("isbn"))
    unique_isbns = len(set(r["isbn"] for r in rows if r.get("isbn")))

    print(f"\n[+] Done! {len(rows)} rows → {csv_path}")
    print(f"    Rows with ISBN : {courses_with_isbn}")
    print(f"    Rows without   : {courses_without}")
    print(f"    Unique ISBNs   : {unique_isbns}")


if __name__ == "__main__":
    main()
