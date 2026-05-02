import csv
import io
import os
import re
import sys
from datetime import datetime, timezone

import requests

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

SCHOOL_NAME = "oakton_community_college"
SCHOOL_ID   = "3023814"
TERM        = "SPRING 26"

SHEET_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vRZUlo0QLcSTMdpA_kzew7OBXuDjIQ0maCEFGzSPXaTu_heIZTWdAr9sLFjCBzXxIz7QHK_xkqFV9c0"
    "/pub?output=csv"
)

CSV_FIELDS = [
    "source_url", "school_id", "department_code", "course_code", "course_title",
    "section", "section_instructor", "term", "isbn", "title", "author",
    "material_adoption_code", "crawled_on", "updated_on",
]

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    f"{SCHOOL_NAME}__{SCHOOL_ID}__bks",
)
CSV_PATH = os.path.join(OUTPUT_DIR, f"{SCHOOL_NAME}__{SCHOOL_ID}__bks.csv")

# Matches e.g. "ACC153-0C1", "EDN201 -001" (optional space around dash)
COURSE_RE = re.compile(r'^([A-Za-z]+)(\d+)\s*-\s*(.+)$')


def parse_course(course_str):
    """Return (dept, course_code, section) with pipe-prefixed codes, or None."""
    m = COURSE_RE.match(course_str.strip())
    if not m:
        return None
    dept   = m.group(1).upper()
    course = f"|{m.group(2)}"
    section = f"|{m.group(3).strip()}"
    return dept, course, section


def fetch_sheet():
    print(f"[*] Downloading Google Sheet CSV from:\n    {SHEET_CSV_URL}")
    resp = requests.get(SHEET_CSV_URL, timeout=60)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    print(f"    {len(resp.text.splitlines())} lines downloaded.")
    return resp.text


def parse_sheet(raw_csv, crawled_on):
    reader = csv.DictReader(io.StringIO(raw_csv))
    rows = []

    current_dept    = ""
    current_course  = ""
    current_section = ""

    for raw in reader:
        course_cell = (raw.get("Course") or "").strip()
        title_cell  = (raw.get("Text Information") or "").strip()
        req_cell    = (raw.get("Req") or "").strip()
        isbn_cell   = (raw.get("ISBN") or "").strip().replace("-", "")
        if isbn_cell in ("None", "nan", "0"):
            isbn_cell = ""

        # Update current course context when the Course cell is non-empty
        if course_cell:
            parsed = parse_course(course_cell)
            if parsed:
                current_dept, current_course, current_section = parsed
            else:
                # Unrecognised format — use raw string as dept, blank course/section
                current_dept    = course_cell
                current_course  = ""
                current_section = ""

        if not current_dept:
            continue  # Skip rows before any valid course header

        # Skip completely empty rows (no title, no isbn, no req — sheet padding)
        if not title_cell and not isbn_cell and not req_cell:
            continue

        # Normalise adoption code: keep source value but title-case it
        adoption = req_cell.capitalize() if req_cell else "Required"

        rows.append({
            "source_url":           SHEET_CSV_URL,
            "school_id":            SCHOOL_ID,
            "department_code":      current_dept,
            "course_code":          current_course,
            "course_title":         "",
            "section":              current_section,
            "section_instructor":   "",
            "term":                 TERM,
            "isbn":                 isbn_cell,
            "title":                title_cell,
            "author":               "",
            "material_adoption_code": adoption,
            "crawled_on":           crawled_on,
            "updated_on":           crawled_on,
        })

    return rows


def write_csv(rows, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def scrape():
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    raw = fetch_sheet()
    rows = parse_sheet(raw, crawled_on)

    if not rows:
        print("[!] No rows parsed. Check the sheet URL or structure.")
        sys.exit(1)

    write_csv(rows, CSV_PATH)

    with_isbn    = sum(1 for r in rows if r["isbn"])
    without_isbn = sum(1 for r in rows if not r["isbn"])
    unique_isbn  = len(set(r["isbn"] for r in rows if r["isbn"]))

    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE — {len(rows)} rows written")
    print(f"  Rows with ISBN  : {with_isbn}")
    print(f"  Rows without    : {without_isbn}")
    print(f"  Unique ISBNs    : {unique_isbn}")
    print(f"  CSV             : {CSV_PATH}")


if __name__ == "__main__":
    scrape()
