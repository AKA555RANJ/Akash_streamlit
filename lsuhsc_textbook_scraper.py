#!/usr/bin/env python3

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

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None

SCHOOL_NAME = "louisiana_state_university_health_sciences_center_new_orleans"
SCHOOL_ID = "3035071"
SOURCE_URL = "https://innopac.lsuhsc.edu/search~S6"
BASE_URL = "https://innopac.lsuhsc.edu"
BROWSE_URL = BASE_URL + "/search~S6?/r*/r*/{offset}%2C1091%2C1093%2CB/browse/indexsort=-"

REQUEST_DELAY = 0.3

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

def http_get(session, url, retries=3):
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

def clean_title(raw):
    t = raw.strip()
    t = re.sub(r"\s*\[electronic resource\]\s*", " ", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*/\s*\[.*$", "", t)
    t = re.sub(r"\s*/\s*$", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def clean_author(raw):
    a = raw.strip()
    if a.lower() in ("(no author)", "no author", ""):
        return ""
    if a.endswith("."):
        a = a[:-1].strip()
    return a

def fetch_browse_page(session, offset):
    url = BROWSE_URL.format(offset=offset)
    html = http_get(session, url)
    soup = BeautifulSoup(html, "html.parser")

    courses = []
    for anchor in soup.find_all("a", attrs={"name": True}):
        name_val = anchor.get("name", "")
        if not name_val.startswith("anchor_"):
            continue
        link = anchor.find_next_sibling("a")
        if link and link.get("href") and "frameset&FF=r" in link["href"]:
            name = link.get_text(strip=True)
            if name:
                full_url = urljoin(BASE_URL, link["href"])
                courses.append({"name": name, "url": full_url})

    return courses

def fetch_all_courses(session):
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

def parse_course_field(all_course_data):
    if not all_course_data:
        return "", "", ""

    for entry in all_course_data:
        m = re.match(r"([A-Za-z]+)\s+([\d]+[\w\s+]*?)\s*[-–]\s*(.+)", entry)
        if m:
            dept = m.group(1).strip().upper()
            code = m.group(2).strip()
            title = m.group(3).strip()
            return dept, code, title

    dept = ""
    code = ""
    title = ""

    for entry in all_course_data:
        entry = entry.strip()
        if re.match(r"^\d+\w*$", entry):
            code = entry
        elif re.match(r"^[A-Za-z]+\s+\d+\w*$", entry, re.IGNORECASE):
            parts = entry.split(None, 1)
            dept = parts[0].upper()
            code = parts[1]
        elif re.match(r"^[A-Za-z]", entry) and not re.match(r"^[A-Za-z]+\s+\d+", entry):
            if "book info" not in entry.lower():
                title = entry

    return dept, code, title

def fetch_course_detail(session, course_url):
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

    course_entries = []
    collecting_course = False

    for row in soup.find_all("tr"):
        label_td = row.find("td", class_="bibInfoLabel")
        data_td = row.find("td", class_="bibInfoData")
        if not data_td:
            continue

        label = label_td.get_text(strip=True).lower() if label_td else ""
        data = data_td.get_text(strip=True)

        if label:
            collecting_course = False

        if "prof" in label:
            result["instructor"] = data
        elif label in ("course", "course:"):
            course_entries.append(data)
            collecting_course = True
        elif not label and data and collecting_course:
            course_entries.append(data)
            collecting_course = False
        elif "cour note" in label:
            if re.search(r"(Spring|Summer|Fall|Winter)\s+\d{4}", data, re.IGNORECASE):
                result["term"] = data

    dept, code, title = parse_course_field(course_entries)
    result["department_code"] = dept
    result["course_code"] = code
    result["course_title"] = title

    seen_records = set()
    reserve_table = soup.find("table", class_="reserveBibs")
    if reserve_table:
        for tr in reserve_table.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 2:
                continue

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

            author = clean_author(cells[1].get_text(strip=True)) if len(cells) > 1 else ""

            result["materials"].append({
                "title": title_text,
                "author": author,
                "record_id": record_id,
            })

    return result

def fetch_book_isbn(session, record_id, isbn_cache):
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

    for row in soup.find_all("tr"):
        label_td = row.find("td", class_="bibInfoLabel")
        data_td = row.find("td", class_="bibInfoData")
        if not data_td:
            continue

        label = label_td.get_text(strip=True).lower() if label_td else ""
        if "isbn" in label or (not label and isbns):
            raw = data_td.get_text(strip=True)
            cleaned = raw.replace("-", "").strip()
            for part in re.split(r"[;,\s]+", cleaned):
                part = part.strip()
                if len(part) == 13 and part.isdigit():
                    isbns.append(part)
                elif len(part) == 10 and re.match(r"^\d{9}[\dXx]$", part):
                    isbns.append(part)
            if isbns:
                break

    isbn = ""
    for candidate in isbns:
        if len(candidate) == 13:
            isbn = candidate
            break
    if not isbn and isbns:
        isbn = isbns[0]

    isbn_cache[record_id] = isbn
    return isbn

def append_csv(rows, filepath):
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

def scrape(fresh=False):
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run — deleted existing CSV.")

    done_courses = get_scraped_courses(CSV_PATH)
    if done_courses:
        print(f"[*] {len(done_courses)} courses already scraped, will skip them.")

    session = requests.Session()
    isbn_cache = {}
    total_rows = 0

    print("[*] Fetching browse pages...")
    all_courses = fetch_all_courses(session)
    print(f"[*] Found {len(all_courses)} courses total.")

    if not all_courses:
        print("[!] No courses found. Exiting.")
        return

    for course in tqdm(all_courses, desc="Courses"):
        detail = fetch_course_detail(session, course["url"])
        if not detail:
            continue

        dept_code = detail["department_code"]
        course_code = detail["course_code"]

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

    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE")
    print(f"{'='*60}")
    print(f"Total rows written: {total_rows}")
    print(f"ISBN cache hits: {len(isbn_cache)} unique records cached")
    print(f"CSV: {CSV_PATH}")

if __name__ == "__main__":
    fresh = "--fresh" in sys.argv
    scrape(fresh=fresh)
