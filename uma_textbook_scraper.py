#!/usr/bin/env python3
"""
uma_textbook_scraper.py — Parse Ultimate Medical Academy's textbook list PDF
into a standardized CSV.

The PDF is an Excel-to-PDF export with structured table columns.
Pages 0-1 (Online Campus): 9 lines per entry (separate format and title lines)
Page 2 (Clearwater Campus): 7 lines per entry (format and title merged)

Source: https://www.ultimatemedical.edu/pdfs/Textbook_List.pdf

Usage:
    python3 uma_textbook_scraper.py
"""

import csv
import os
import re
import sys

import fitz  # pymupdf
import requests

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCHOOL_NAME = "ultimate_medical_academy"
SCHOOL_ID = "3012793"
SOURCE_URL = "https://www.ultimatemedical.edu/pdfs/Textbook_List.pdf"
TERM = "Spring 2026"
CRAWLED_ON = "2026-03-25 00:00:00"

CSV_FIELDS = [
    "source_url",
    "school_id",
    "department_code",
    "course_code",
    "course_title",
    "section",
    "section_instructor",
    "term",
    "isbn",
    "title",
    "author",
    "material_adoption_code",
    "crawled_on",
    "updated_on",
]

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    f"{SCHOOL_NAME}__{SCHOOL_ID}__bks",
)
CSV_PATH = os.path.join(OUTPUT_DIR, f"{SCHOOL_NAME}__{SCHOOL_ID}__bks.csv")
PDF_PATH = os.path.join(OUTPUT_DIR, "Textbook_List.pdf")

# Course code pattern: 2-5 letters + 3-5 digits + optional 1-2 letter suffix
# Examples: BC2025, AC1000, MC1110MA, MC2015PC, EMS1100, ME1105
COURSE_CODE_RE = re.compile(r"^(?:\*{3})?([A-Z]{2,5}\d{3,5}[A-Z]{0,2})\b")
DEPT_RE = re.compile(r"^([A-Z]+)")

# Known book format prefixes on page 2 (Clearwater) where format+title are merged
FORMAT_PREFIXES = [
    "Physical/hard copy only",
    "eBook/ electronic access only",
    "eBook/electronic access only",
    "No Materials Needed",
]


# ---------------------------------------------------------------------------
# PDF download
# ---------------------------------------------------------------------------
def download_pdf():
    """Download the textbook list PDF if not already cached."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if os.path.exists(PDF_PATH):
        print(f"[*] PDF already exists at {PDF_PATH}")
        return
    print(f"[*] Downloading PDF from {SOURCE_URL}...")
    resp = requests.get(SOURCE_URL, timeout=60)
    resp.raise_for_status()
    with open(PDF_PATH, "wb") as f:
        f.write(resp.content)
    print(f"    Saved to {PDF_PATH} ({len(resp.content)} bytes)")


# ---------------------------------------------------------------------------
# PDF parsing helpers
# ---------------------------------------------------------------------------
def is_course_code(line):
    """Check if a line looks like a course code."""
    return bool(COURSE_CODE_RE.match(line))


def extract_course_code(line):
    """Extract the clean course code from a line (strip *** prefix)."""
    m = COURSE_CODE_RE.match(line)
    return m.group(1) if m else line


def is_skip_line(line):
    """Check if a line is a header, footer, or metadata to skip."""
    return (line in ("Course Code", "Course Name", "Book Format",
                     "MaterialName", "UMA ISBN", "Publisher",
                     "UMA Cost", "List Price")
            or line.startswith("National ISBN")
            or line.startswith("Monday,")
            or line.startswith("UMA Book Materials"))


def make_row(dept_code, course_code, course_name, campus, isbn, title, adoption):
    """Build a CSV row dict."""
    return {
        "source_url": SOURCE_URL,
        "school_id": SCHOOL_ID,
        "department_code": dept_code,
        "course_code": f"|{course_code}",
        "course_title": course_name,
        "section": f"|{campus}" if campus else "",
        "section_instructor": "",
        "term": TERM,
        "isbn": isbn,
        "title": title,
        "author": "",
        "material_adoption_code": adoption,
        "crawled_on": CRAWLED_ON,
        "updated_on": CRAWLED_ON,
    }


def clean_isbn(text):
    """Extract and clean a 13-digit ISBN from text."""
    digits = re.sub(r"\D", "", text)
    return digits if len(digits) == 13 else ""


def clean_title(title):
    """Strip eBook prefix from title."""
    title = title.strip()
    if title.startswith("eBook "):
        title = title[6:].strip()
    return title


def get_dept(course_code):
    """Extract department prefix from course code."""
    m = DEPT_RE.match(course_code)
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# Page 0-1 parser: Online Campus (9 lines per entry)
# ---------------------------------------------------------------------------
def parse_online_pages(doc):
    """Parse pages 0-1 (Online Campus). Each entry is 9 lines:
    course_code, course_name, book_format, material_name,
    uma_isbn, national_isbn, list_price, uma_cost, publisher
    """
    rows = []
    campus = "Online"

    for page_num in range(min(2, len(doc))):
        page = doc[page_num]
        lines = [l.strip() for l in page.get_text().split("\n") if l.strip()]

        i = 0
        while i < len(lines):
            line = lines[i]

            if is_skip_line(line) or "Campus" in line:
                i += 1
                continue

            if not is_course_code(line):
                i += 1
                continue

            # Found a course code
            course_code_raw = line
            course_code = extract_course_code(course_code_raw)
            dept = get_dept(course_code)

            # Need at least 8 more lines
            if i + 8 >= len(lines):
                break

            course_name = lines[i + 1]
            book_format = lines[i + 2]
            material_name = lines[i + 3]
            uma_isbn_line = lines[i + 4]
            national_isbn_line = lines[i + 5]
            # lines[i+6] = list_price, lines[i+7] = uma_cost
            # lines[i+8] = publisher

            # Handle *** entries where course_code_raw includes "- Course Name"
            # and the next line is actually book_format
            if course_name in FORMAT_PREFIXES or any(
                course_name.startswith(fp) for fp in FORMAT_PREFIXES
            ):
                name_match = re.search(r"\s*[-–]\s*(.+)$", course_code_raw)
                course_name_clean = name_match.group(1).strip() if name_match else ""
                book_format = course_name
                material_name = lines[i + 2]
                uma_isbn_line = lines[i + 3]
                national_isbn_line = lines[i + 4]
                i += 8
            else:
                course_name_clean = course_name.lstrip("* -").strip()
                i += 9

            if "No Materials Needed" in book_format:
                rows.append(make_row(dept, course_code, course_name_clean, campus,
                                     "", "", "This course does not require any course materials"))
                continue

            isbn = clean_isbn(national_isbn_line)
            if not isbn:
                isbn = clean_isbn(uma_isbn_line)
            title = clean_title(material_name)

            rows.append(make_row(dept, course_code, course_name_clean, campus,
                                 isbn, title, "Required"))

    return rows


# ---------------------------------------------------------------------------
# Page 2 parser: Clearwater Campus (mixed 7-line and 9-line entries)
# ---------------------------------------------------------------------------
def parse_clearwater_page(doc):
    """Parse page 2 (Clearwater Campus).

    eBook entries: 7 lines (format+title merged on one line)
    Physical entries: 9 lines (format and title on separate lines)
    No Materials entries: 9 lines

    Detection: if line after course_name starts with "Physical/" or
    "No Materials", it's a 9-line entry. If it starts with "eBook/",
    it's 7 lines (format+title merged).
    """
    rows = []
    campus = "Clearwater"

    if len(doc) < 3:
        return rows

    page = doc[2]
    lines = [l.strip() for l in page.get_text().split("\n") if l.strip()]

    i = 0
    while i < len(lines):
        line = lines[i]

        if is_skip_line(line) or "Campus" in line:
            i += 1
            continue

        if not is_course_code(line):
            i += 1
            continue

        course_code = extract_course_code(line)
        dept = get_dept(course_code)

        if i + 2 >= len(lines):
            break

        course_name = lines[i + 1].lstrip("* -").strip()
        format_line = lines[i + 2]

        # No Materials Needed — 9 lines
        if "No Materials Needed" in format_line:
            rows.append(make_row(dept, course_code, course_name, campus,
                                 "", "", "This course does not require any course materials"))
            i += 9
            continue

        # Physical/hard copy — 9 lines (separate format and title lines)
        if format_line.startswith("Physical/hard copy"):
            if i + 8 >= len(lines):
                break
            material_name = lines[i + 3]
            uma_isbn_line = lines[i + 4]
            national_isbn_line = lines[i + 5]
            isbn = clean_isbn(national_isbn_line)
            if not isbn:
                isbn = clean_isbn(uma_isbn_line)
            title = clean_title(material_name)
            rows.append(make_row(dept, course_code, course_name, campus,
                                 isbn, title, "Required"))
            i += 9
            continue

        # eBook — 7 lines (format+title merged)
        if format_line.startswith("eBook/") or format_line.startswith("eBook/ "):
            # Extract title from merged line
            title = format_line
            for prefix in FORMAT_PREFIXES:
                if format_line.startswith(prefix):
                    title = format_line[len(prefix):].strip()
                    break
            title = clean_title(title)

            uma_isbn_line = lines[i + 3] if i + 3 < len(lines) else ""
            national_isbn_line = lines[i + 4] if i + 4 < len(lines) else ""
            isbn = clean_isbn(national_isbn_line)
            if not isbn:
                isbn = clean_isbn(uma_isbn_line)
            rows.append(make_row(dept, course_code, course_name, campus,
                                 isbn, title, "Required"))
            i += 7
            continue

        # Unknown format — skip
        i += 1

    return rows


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------
def extract_rows_from_pdf():
    """Extract all textbook rows from the PDF."""
    doc = fitz.open(PDF_PATH)
    online_rows = parse_online_pages(doc)
    clearwater_rows = parse_clearwater_page(doc)
    doc.close()

    print(f"    Online campus:    {len(online_rows)} rows")
    print(f"    Clearwater campus: {len(clearwater_rows)} rows")

    return online_rows + clearwater_rows


# ---------------------------------------------------------------------------
# CSV writing
# ---------------------------------------------------------------------------
def write_csv(rows):
    """Write all rows to CSV (overwrite mode)."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[*] Wrote {len(rows)} rows to {CSV_PATH}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print(f"{'='*60}")
    print(f"Ultimate Medical Academy Textbook Scraper")
    print(f"{'='*60}")

    download_pdf()
    rows = extract_rows_from_pdf()

    if not rows:
        print("[!] No rows extracted from PDF. Check parsing logic.")
        return

    write_csv(rows)

    # Summary
    depts = set(r["department_code"] for r in rows)
    courses = set(r["course_code"] for r in rows)
    no_materials = sum(
        1 for r in rows
        if r["material_adoption_code"] == "This course does not require any course materials"
    )
    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE")
    print(f"{'='*60}")
    print(f"Total rows:     {len(rows)}")
    print(f"Departments:    {len(depts)} ({', '.join(sorted(depts))})")
    print(f"Courses:        {len(courses)}")
    print(f"No materials:   {no_materials}")
    print(f"CSV: {CSV_PATH}")


if __name__ == "__main__":
    main()
