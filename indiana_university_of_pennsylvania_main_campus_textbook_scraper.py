#!/usr/bin/env python3
"""
Indiana University of Pennsylvania - Main Campus Bookstore Textbook Scraper
Platform: Timber e-Commerce (Drupal 6, Herkimer Media / bookstorewebsoftware.com)
URL: https://www.iupstore.com/timber/college

API flow (all unauthenticated GET requests, HTML fragment responses):
  1. GET /timber/college
       → parse .tcc-item-link[url^='/college_term/'] for terms
  2. GET /timber/college/ajax?l=/college_term/{termId}
       → parse .tcc-item-link[url^='/college_dept/'] for departments
  3. GET /timber/college/ajax?l=/college_dept/{deptId}
       → parse .tcc-item-link[url^='/college_course/'] for courses
         (text format: "201 - Accounting Principles I")
  4. GET /timber/college/ajax?l=/college_course/{courseId}
       → parse .tcc-item-link[url^='/college_section/'] for sections
         (text format: "001 - DZIELSKI, SAMANTHA")
  5. GET /timber/college/ajax?l=/college_section/{sectionId}
       → parse div.tcc-product for materials (title, author, ISBN, adoption code)
         Books are embedded directly in this HTML — no separate /details/ call needed.

No FlareSolverr or Cloudflare handling needed; the site serves plain HTML
to standard HTTP clients (session cookie required).
"""

import csv
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHOOL_NAME = "indiana_university_of_pennsylvania_main_campus"
SCHOOL_ID   = "3083583"
BASE_URL    = "https://www.iupstore.com"
COLLEGE_URL = f"{BASE_URL}/timber/college"
AJAX_URL    = f"{BASE_URL}/timber/college/ajax"

REQUEST_DELAY = 0.6   # seconds between requests

ADOPTION_CLASS_MAP = {
    "req-group-r": "Required",
    "req-group-o": "Optional",
    "req-group-c": "Choice",
    "req-group-n": "Not Required",
}

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

# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def make_session() -> requests.Session:
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": COLLEGE_URL,
    })
    return sess


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def parse_tcc_items(html: str) -> list[dict]:
    """
    Return a list of {url, text} dicts from all a.tcc-item-link elements.
    The 'url' attribute (not href) holds the path like /college_term/65576.
    Uses separator=" " so <span>CODE</span>-<span>Name</span> becomes "CODE - Name".
    """
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for a in soup.find_all("a", class_="tcc-item-link"):
        url_attr = a.get("url", "").strip()
        text = a.get_text(separator=" ", strip=True)
        if url_attr:
            items.append({"url": url_attr, "text": text})
    return items


def extract_id(url_path: str) -> str:
    """Return the trailing numeric ID from a path like /college_term/65576 → '65576'."""
    return url_path.rstrip("/").rsplit("/", 1)[-1]


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

def timber_ajax_get(sess: requests.Session, path: str) -> str:
    """GET /timber/college/ajax?l={path} and return response text."""
    time.sleep(REQUEST_DELAY)
    url = f"{AJAX_URL}?l={quote(path, safe='')}"
    resp = sess.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text


def fetch_terms(sess: requests.Session) -> list[dict]:
    """Fetch the main /timber/college page and return list of {id, name} terms."""
    time.sleep(REQUEST_DELAY)
    resp = sess.get(COLLEGE_URL, timeout=30)
    resp.raise_for_status()
    items = parse_tcc_items(resp.text)
    return [
        {"id": extract_id(item["url"]), "name": item["text"]}
        for item in items if "/college_term/" in item["url"]
    ]


def fetch_departments(sess: requests.Session, term_id: str) -> list[dict]:
    """Return list of {id, code, name} depts for a term."""
    html = timber_ajax_get(sess, f"/college_term/{term_id}")
    items = parse_tcc_items(html)
    depts = []
    for item in items:
        if "/college_dept/" in item["url"]:
            code, name = _split_dept(item["text"])
            depts.append({"id": extract_id(item["url"]), "code": code, "name": name})
    return depts


def fetch_courses(sess: requests.Session, dept_id: str) -> list[dict]:
    """Return list of {id, text} courses for a department."""
    html = timber_ajax_get(sess, f"/college_dept/{dept_id}")
    items = parse_tcc_items(html)
    return [
        {"id": extract_id(item["url"]), "text": item["text"]}
        for item in items if "/college_course/" in item["url"]
    ]


def fetch_sections(sess: requests.Session, course_id: str) -> list[dict]:
    """
    Return list of {id, section_num, instructor} for a course.
    IUP section text format: "001 - DZIELSKI, SAMANTHA"
    """
    html = timber_ajax_get(sess, f"/college_course/{course_id}")
    items = parse_tcc_items(html)
    sections = []
    for item in items:
        if "/college_section/" in item["url"]:
            section_num, instructor = _parse_section_text(item["text"])
            sections.append({
                "id":         extract_id(item["url"]),
                "section_num": section_num,
                "instructor": instructor,
                "raw_text":   item["text"],
            })
    return sections


def fetch_materials(sess: requests.Session, section_id: str) -> list[dict]:
    """
    GET /timber/college/ajax?l=/college_section/{sectionId}
    Parse the tcc-product div for all books in this section.

    Returns list of {title, isbn, author, adoption_code}.
    Empty list means no required materials.

    HTML structure:
      <div class='req-group req-group-R ...'>
        <div class='item group timber-item-group'>
          <span class='tcc-product-title'>BOOK TITLE</span>
          [<em class="author-data">AUTHOR</em>]
          <span class='tcc-sku-number'>(9781265745349)</span>
        </div>
      </div>
    """
    html = timber_ajax_get(sess, f"/college_section/{section_id}")
    return _parse_materials_html(html)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_materials_html(html: str) -> list[dict]:
    """Parse tcc-product div for all book items with adoption codes."""
    soup = BeautifulSoup(html, "html.parser")
    books = []

    for req_group in soup.find_all("div", class_=re.compile(r"\breq-group\b")):
        # Determine adoption code from CSS class
        adoption = ""
        for cls in req_group.get("class", []):
            adoption = ADOPTION_CLASS_MAP.get(cls.lower(), "")
            if adoption:
                break

        for item_div in req_group.find_all("div", class_="timber-item-group"):
            title_span = item_div.find("span", class_="tcc-product-title")
            author_em  = item_div.find("em", class_="author-data")
            sku_span   = item_div.find("span", class_="tcc-sku-number")

            title  = title_span.get_text(strip=True) if title_span else ""
            author = author_em.get_text(strip=True)  if author_em  else ""
            isbn   = ""
            if sku_span:
                raw_sku = sku_span.get_text(strip=True)
                # Format: "(9781265745349)" — strip parens then clean
                isbn = _clean_isbn(raw_sku.strip("()"))

            if title or isbn:
                books.append({
                    "title":         title,
                    "isbn":          isbn,
                    "author":        author,
                    "adoption_code": adoption,
                })

    return books


def _split_dept(text: str) -> tuple[str, str]:
    """
    'ACCT - Accounting' → ('ACCT', 'Accounting')
    get_text(separator=" ") turns <span>ACCT</span>-<span>Accounting</span>
    into 'ACCT - Accounting' (spaces added around the bare hyphen by the separator).
    Falls back to (text, text) if no ' - ' separator.
    """
    if " - " in text:
        code, _, name = text.partition(" - ")
        return code.strip(), name.strip()
    return text.strip(), text.strip()


def _parse_course_text(text: str) -> tuple[str, str, str]:
    """
    Parse course item text into (dept_code, course_code, course_title).

    IUP format: "201 - Accounting Principles I" (number first, no dept prefix)
    Also handles Parker-style: "ACCT2301 - TITLE" or "ACCT 2301 TITLE"
    """
    t = text.strip()

    # Format 1: LETTERS+DIGITS - TITLE (e.g. "BASC5101 - BIOLOGY OF CELLS")
    m = re.match(r"^([A-Za-z]{2,10})(\d[\w\-]*)\s*[-–]\s*(.*)", t)
    if m:
        return m.group(1).upper(), fmt(m.group(2)), m.group(3).strip()

    # Format 2: LETTERS SPACE DIGITS SPACE/DASH TITLE (e.g. "ACCT 2301 - Title")
    m = re.match(r"^([A-Za-z]{2,10})\s+(\d[\w\-]*)\s*(?:[-–]\s*)?(.*)", t)
    if m:
        return m.group(1).upper(), fmt(m.group(2)), m.group(3).strip()

    # Format 3: DIGITS - TITLE (IUP format, e.g. "201 - Accounting Principles I")
    m = re.match(r"^(\d[\w\-]*)\s*[-–]\s*(.*)", t)
    if m:
        return "", fmt(m.group(1)), m.group(2).strip()

    return "", "", t


def _parse_section_text(text: str) -> tuple[str, str]:
    """
    Parse section item text into (section_num, instructor).
    IUP format: "001 - DZIELSKI, SAMANTHA"
    """
    t = text.strip()
    m = re.match(r"^(\w+)\s*[-–]\s*(.*)", t)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return t, ""


def _clean_isbn(value: str) -> str:
    return re.sub(r"[-\s]", "", value).strip()


def fmt(code: str) -> str:
    """Prefix code with | to preserve leading zeros."""
    code = (code or "").strip()
    return f"|{code}" if code and not code.startswith("|") else code


def normalize_term(s: str) -> str:
    """Strip ordering suffixes like '(Order Now)', '(Pre-Order)', etc."""
    return re.sub(r"\s*\(.*?\)\s*", " ", s or "").strip().upper()


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def append_csv(rows: list[dict], filepath: str) -> None:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    new_file = not os.path.exists(filepath) or os.path.getsize(filepath) == 0
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def get_scraped_keys(filepath: str) -> set:
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return set()
    with open(filepath, "r", encoding="utf-8") as f:
        return {
            (r.get("term", ""), r.get("department_code", ""),
             r.get("course_code", ""), r.get("section", ""))
            for r in csv.DictReader(f)
        }


# ---------------------------------------------------------------------------
# Main scrape
# ---------------------------------------------------------------------------

def scrape(fresh: bool = False) -> None:
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run — deleted existing CSV.")

    done_keys = get_scraped_keys(CSV_PATH)
    if done_keys:
        print(f"[*] Resuming: {len(done_keys)} combo(s) already scraped.")

    sess = make_session()

    # Step 1: terms
    print(f"[*] Fetching terms from {COLLEGE_URL} ...")
    terms = fetch_terms(sess)
    if not terms:
        print("[!] No terms found. Exiting.")
        return
    print(f"[*] Found {len(terms)} term(s): {[t['name'] for t in terms]}")

    total_rows = 0
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for term in terms:
        term_id   = term["id"]
        term_name = normalize_term(term["name"])
        print(f"\n[*] Term: {term_name} (id={term_id})")

        # Step 2: departments
        depts = fetch_departments(sess, term_id)
        if not depts:
            print(f"    [!] No departments found for {term_name}.")
            continue
        print(f"    {len(depts)} department(s)")

        for dept in tqdm(depts, desc=f"  {term_name} depts"):
            dept_id   = dept["id"]
            dept_code = dept["code"]

            # Step 3: courses
            courses = fetch_courses(sess, dept_id)
            if not courses:
                tqdm.write(f"    [!] {term_name} / {dept_code}: 0 courses, skipping.")
                continue

            dept_rows = 0

            for course in courses:
                course_id  = course["id"]
                raw_course = course["text"]
                inferred_dept, course_code, course_title = _parse_course_text(raw_course)
                if not course_code:
                    course_code = fmt(course_id)
                effective_dept = inferred_dept or dept_code

                # Step 4: sections
                sections = fetch_sections(sess, course_id)
                if not sections:
                    check_key = (term_name, effective_dept, course_code, "")
                    if check_key not in done_keys:
                        row = _build_row(
                            term_name, effective_dept, course_code, course_title,
                            section="", instructor="", isbn="", title="", author="",
                            adoption_code="This course does not require any course materials",
                            crawled_on=crawled_on,
                        )
                        append_csv([row], CSV_PATH)
                        done_keys.add(check_key)
                        total_rows += 1
                        dept_rows  += 1
                    continue

                for sec in sections:
                    section_id  = sec["id"]
                    section_num = fmt(sec["section_num"])
                    instructor  = sec["instructor"]

                    check_key = (term_name, effective_dept, course_code, section_num)
                    if check_key in done_keys:
                        continue

                    # Step 5: materials for this section
                    books = fetch_materials(sess, section_id)

                    if not books:
                        row = _build_row(
                            term_name, effective_dept, course_code, course_title,
                            section=section_num, instructor=instructor,
                            isbn="", title="", author="",
                            adoption_code="This course does not require any course materials",
                            crawled_on=crawled_on,
                        )
                        append_csv([row], CSV_PATH)
                        done_keys.add(check_key)
                        total_rows += 1
                        dept_rows  += 1
                        continue

                    for book in books:
                        row = _build_row(
                            term_name, effective_dept, course_code, course_title,
                            section=section_num, instructor=instructor,
                            isbn=book["isbn"], title=book["title"], author=book["author"],
                            adoption_code=book["adoption_code"],
                            crawled_on=crawled_on,
                        )
                        append_csv([row], CSV_PATH)
                        total_rows += 1
                        dept_rows  += 1

                    done_keys.add(check_key)

            if dept_rows:
                tqdm.write(f"    [{dept_code}] +{dept_rows} rows (total so far: {total_rows})")

    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE — {total_rows} rows written")
    print(f"CSV: {CSV_PATH}")
    if total_rows == 0:
        print("[!] No data collected. The active term may not have course adoptions yet.")
        if not os.path.exists(CSV_PATH) or os.path.getsize(CSV_PATH) == 0:
            append_csv([], CSV_PATH)
            print(f"    (Header-only CSV written to {CSV_PATH})")


def _build_row(
    term: str, dept_code: str, course_code: str, course_title: str,
    section: str, instructor: str, isbn: str, title: str, author: str,
    adoption_code: str, crawled_on: str,
) -> dict:
    return {
        "source_url":             COLLEGE_URL,
        "school_id":              SCHOOL_ID,
        "department_code":        dept_code,
        "course_code":            course_code,
        "course_title":           course_title,
        "section":                section,
        "section_instructor":     instructor,
        "term":                   term,
        "isbn":                   isbn,
        "title":                  title,
        "author":                 author,
        "material_adoption_code": adoption_code,
        "crawled_on":             crawled_on,
        "updated_on":             crawled_on,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    scrape(fresh="--fresh" in sys.argv)
