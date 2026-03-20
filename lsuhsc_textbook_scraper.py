#!/usr/bin/env python3
"""
lsuhsc_textbook_scraper.py — Scrape course reserve/textbook data from
Louisiana State University Health Sciences Center-New Orleans.

Their "bookstore" is an INNOPAC/III library catalog at innopac.lsuhsc.edu
that lists course reserves. Plain requests (no Cloudflare bypass needed).

Usage:
    python lsuhsc_textbook_scraper.py           # scrape only missing courses
    python lsuhsc_textbook_scraper.py --fresh   # delete CSV and scrape everything
"""

import csv
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

# Force unbuffered stdout so prints appear immediately in log files
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCHOOL_NAME = "louisiana_state_university_health_sciences_center_new_orleans"
SCHOOL_ID = "3035071"
SOURCE_URL = "https://innopac.lsuhsc.edu/search~S6"
BASE_URL = "https://innopac.lsuhsc.edu"
BROWSE_URL = BASE_URL + "/search~S6?/r*/r*/{offset}%2C1091%2C1093%2CB/browse/indexsort=-"

REQUEST_DELAY = 0.3  # seconds between requests

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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; textbook-scraper/1.0)",
    "Accept": "text/html,application/xhtml+xml",
}


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------
def http_get(session, url, retries=3):
    """GET a URL with retry logic. Returns response text."""
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = session.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
            else:
                raise


# ---------------------------------------------------------------------------
# Title / author cleanup helpers
# ---------------------------------------------------------------------------
def clean_title(raw):
    """Remove '[electronic resource]', trailing '/ [edited...' etc."""
    t = raw.strip()
    t = re.sub(r"\s*\[electronic resource\]\s*", " ", t, flags=re.IGNORECASE)
    # Remove trailing " / [edited by..." or " / [by]..." truncations
    t = re.sub(r"\s*/\s*\[.*$", "", t)
    # Remove trailing " / " leftover
    t = re.sub(r"\s*/\s*$", "", t)
    # Collapse whitespace
    t = re.sub(r"\s+", " ", t).strip()
    # Remove trailing period if present after cleanup
    return t


def clean_author(raw):
    """Clean author text. Return empty string for '(no author)'."""
    a = raw.strip()
    if a.lower() in ("(no author)", "no author", ""):
        return ""
    # Remove trailing period
    if a.endswith("."):
        a = a[:-1].strip()
    return a


# ---------------------------------------------------------------------------
# Level 1: Browse pages
# ---------------------------------------------------------------------------
def fetch_browse_page(session, offset):
    """Parse one browse page, return list of {'name': ..., 'url': ...} dicts."""
    url = BROWSE_URL.format(offset=offset)
    html = http_get(session, url)
    soup = BeautifulSoup(html, "html.parser")

    courses = []
    # Browse entries are anchor tags preceded by <a name='anchor_N'>
    # They contain "frameset&FF=r" in href
    # Filter out prev/next navigation links (which have "frameset&FF=" but not
    # the browse result pattern with anchor_ siblings)
    for anchor in soup.find_all("a", attrs={"name": True}):
        name_val = anchor.get("name", "")
        if not name_val.startswith("anchor_"):
            continue
        # The course link is the next sibling <a> tag
        link = anchor.find_next_sibling("a")
        if link and link.get("href") and "frameset&FF=r" in link["href"]:
            name = link.get_text(strip=True)
            if name:
                full_url = urljoin(BASE_URL, link["href"])
                courses.append({"name": name, "url": full_url})

    return courses


def fetch_all_courses(session):
    """Paginate through all browse pages. Return full course list."""
    all_courses = []
    offset = 1
    page = 1

    while True:
        print(f"  Browse page {page} (offset={offset})...")
        courses = fetch_browse_page(session, offset)
        if not courses:
            break
        all_courses.extend(courses)
        if len(courses) < 50:
            break
        offset += 50
        page += 1

    return all_courses


# ---------------------------------------------------------------------------
# Level 2: Course detail page
# ---------------------------------------------------------------------------
def parse_course_field(all_course_data):
    """Parse course data which may be in one or two rows.

    Cases:
      - "NURS 7369 - Academic Teaching"  → (NURS, 7369, Academic Teaching)
      - "Dent 3105 - Advanced Clinical Operative" → (DENT, 3105, Advanced Clinical Operative)
      - "NURS 3355 + CARE - Child Health Nursing Theory" → (NURS, 3355 + CARE, Child Health Nursing Theory)
      - ["4103", "Professional Development IV"] → ("", 4103, Professional Development IV)
    """
    if not all_course_data:
        return "", "", ""

    # Try combined format: "DEPT CODE - Title" (case-insensitive dept, flexible code)
    for entry in all_course_data:
        m = re.match(r"([A-Za-z]+)\s+([\d]+[\w\s+]*?)\s*[-–]\s*(.+)", entry)
        if m:
            dept = m.group(1).strip().upper()
            code = m.group(2).strip()
            title = m.group(3).strip()
            return dept, code, title

    # Otherwise try to piece together from multiple entries
    dept = ""
    code = ""
    title = ""

    for entry in all_course_data:
        entry = entry.strip()
        # Pure number = course code
        if re.match(r"^\d+\w*$", entry):
            code = entry
        # "DEPT CODE" format (case-insensitive)
        elif re.match(r"^[A-Za-z]+\s+\d+\w*$", entry, re.IGNORECASE):
            parts = entry.split(None, 1)
            dept = parts[0].upper()
            code = parts[1]
        # Alphabetic text = title (skip librarian notes)
        elif re.match(r"^[A-Za-z]", entry) and not re.match(r"^[A-Za-z]+\s+\d+", entry):
            if "book info" not in entry.lower():
                title = entry

    return dept, code, title


def fetch_course_detail(session, course_url):
    """Fetch course detail page, parse course info + materials.

    Returns:
        dict with keys: instructor, department_code, course_code, course_title,
                        term, materials (list of dicts with title, author, record_id)
    Returns None on failure.
    """
    try:
        html = http_get(session, course_url)
    except Exception as e:
        tqdm.write(f"  [ERROR] fetch_course_detail {course_url}: {e}")
        return None

    soup = BeautifulSoup(html, "html.parser")

    result = {
        "instructor": "",
        "department_code": "",
        "course_code": "",
        "course_title": "",
        "term": "",
        "materials": [],
    }

    # Collect Course field entries (the labeled row + one continuation row)
    course_entries = []
    collecting_course = False  # True right after seeing a Course label

    # Parse bibDetail tables for course metadata
    for row in soup.find_all("tr"):
        label_td = row.find("td", class_="bibInfoLabel")
        data_td = row.find("td", class_="bibInfoData")
        if not data_td:
            continue

        label = label_td.get_text(strip=True).lower() if label_td else ""
        data = data_td.get_text(strip=True)

        if label:
            # Any new label stops course continuation collection
            collecting_course = False

        if "prof" in label:
            result["instructor"] = data
        elif label in ("course", "course:"):
            course_entries.append(data)
            collecting_course = True
        elif not label and data and collecting_course:
            # Continuation row for Course field (reversed format)
            course_entries.append(data)
            collecting_course = False  # Only collect one continuation
        elif "cour note" in label:
            if re.search(r"(Spring|Summer|Fall|Winter)\s+\d{4}", data, re.IGNORECASE):
                result["term"] = data

    # Parse collected course entries
    dept, code, title = parse_course_field(course_entries)
    result["department_code"] = dept
    result["course_code"] = code
    result["course_title"] = title

    # Parse materials from reserveBibs table (deduplicate by record_id)
    seen_records = set()
    reserve_table = soup.find("table", class_="reserveBibs")
    if reserve_table:
        for tr in reserve_table.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 2:
                continue

            # First cell: title with link
            link = cells[0].find("a", href=True)
            if not link:
                continue
            href = link["href"]
            m = re.search(r"frameset~(\d+)", href)
            if not m:
                continue

            record_id = m.group(1)
            if record_id in seen_records:
                continue
            seen_records.add(record_id)

            title_text = clean_title(link.get_text(strip=True))

            # Second cell: author
            author = clean_author(cells[1].get_text(strip=True)) if len(cells) > 1 else ""

            result["materials"].append({
                "title": title_text,
                "author": author,
                "record_id": record_id,
            })

    return result


# ---------------------------------------------------------------------------
# Level 3: Book record (for ISBN)
# ---------------------------------------------------------------------------
def fetch_book_isbn(session, record_id, isbn_cache):
    """Fetch ISBN from a book record page. Uses cache to avoid re-fetching."""
    if record_id in isbn_cache:
        return isbn_cache[record_id]

    url = f"{BASE_URL}/record=b{record_id}~S6"
    try:
        html = http_get(session, url)
    except Exception as e:
        tqdm.write(f"  [ERROR] fetch_book_isbn record={record_id}: {e}")
        isbn_cache[record_id] = ""
        return ""

    soup = BeautifulSoup(html, "html.parser")
    isbns = []

    # ISBN may be spread across multiple rows (each row has one ISBN)
    for row in soup.find_all("tr"):
        label_td = row.find("td", class_="bibInfoLabel")
        data_td = row.find("td", class_="bibInfoData")
        if not data_td:
            continue

        label = label_td.get_text(strip=True).lower() if label_td else ""
        if "isbn" in label or (not label and isbns):
            raw = data_td.get_text(strip=True)
            cleaned = raw.replace("-", "").strip()
            # Might have multiple ISBNs separated by semicolons or commas
            for part in re.split(r"[;,\s]+", cleaned):
                part = part.strip()
                if len(part) == 13 and part.isdigit():
                    isbns.append(part)
                elif len(part) == 10 and re.match(r"^\d{9}[\dXx]$", part):
                    isbns.append(part)
            if isbns:
                break  # Got ISBNs from this row, done

    # Prefer 13-digit ISBN
    isbn = ""
    for candidate in isbns:
        if len(candidate) == 13:
            isbn = candidate
            break
    if not isbn and isbns:
        isbn = isbns[0]

    isbn_cache[record_id] = isbn
    return isbn


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------
def append_csv(rows, filepath):
    """Append rows to CSV (create with header if new)."""
    if not rows:
        return
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    file_exists = os.path.exists(filepath) and os.path.getsize(filepath) > 0
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def get_scraped_courses(filepath):
    """Read existing CSV and return set of (dept_code, course_code) already scraped."""
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return set()
    scraped = set()
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dept = row.get("department_code", "").strip()
            code = row.get("course_code", "").strip()
            if dept or code:
                scraped.add((dept, code))
    return scraped


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------
def scrape(fresh=False):
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # Fresh run — delete existing CSV
    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run — deleted existing CSV.")

    done_courses = get_scraped_courses(CSV_PATH)
    if done_courses:
        print(f"[*] {len(done_courses)} courses already scraped, will skip them.")

    session = requests.Session()
    isbn_cache = {}
    total_rows = 0

    # Level 1: Get all courses from browse pages
    print("[*] Fetching browse pages...")
    all_courses = fetch_all_courses(session)
    print(f"[*] Found {len(all_courses)} courses total.")

    if not all_courses:
        print("[!] No courses found. Exiting.")
        return

    # Level 2 + 3: Process each course
    for course in tqdm(all_courses, desc="Courses"):
        detail = fetch_course_detail(session, course["url"])
        if not detail:
            continue

        dept_code = detail["department_code"]
        course_code = detail["course_code"]

        # Skip if already scraped (incremental)
        if (dept_code, course_code) in done_courses:
            continue

        base_row = {
            "source_url": SOURCE_URL,
            "school_id": SCHOOL_ID,
            "department_code": dept_code,
            "course_code": course_code,
            "course_title": detail["course_title"],
            "section": "",
            "section_instructor": detail["instructor"],
            "term": detail["term"],
            "crawled_on": crawled_on,
            "updated_on": crawled_on,
        }

        rows = []

        if not detail["materials"]:
            # No materials for this course
            rows.append({
                **base_row,
                "isbn": "",
                "title": "",
                "author": "",
                "material_adoption_code": "This course does not require any course materials",
            })
        else:
            for mat in detail["materials"]:
                isbn = ""
                if mat["record_id"]:
                    isbn = fetch_book_isbn(session, mat["record_id"], isbn_cache)

                rows.append({
                    **base_row,
                    "isbn": isbn,
                    "title": mat["title"],
                    "author": mat["author"],
                    "material_adoption_code": "Required",
                })

        if rows:
            append_csv(rows, CSV_PATH)
            total_rows += len(rows)

    # Final summary
    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE")
    print(f"{'='*60}")
    print(f"Total rows written: {total_rows}")
    print(f"ISBN cache hits: {len(isbn_cache)} unique records cached")
    print(f"CSV: {CSV_PATH}")


if __name__ == "__main__":
    fresh = "--fresh" in sys.argv
    scrape(fresh=fresh)
