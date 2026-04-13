"""
Chaffey College Bookstore Textbook Scraper
Platform: Barnes & Noble College CampusHub v4.0 (ASP, custom domain)
URL: https://books.chaffey.edu/buy_textbooks.asp

No FlareSolverr required — plain requests.Session() with CSRF token.

API flow:
  GET  /buy_textbooks.asp                                          → session cookies + CSRF + term list
  GET  /textbooks_xml.asp?control=campus&campus={c}&term={t}      → XML departments
  GET  /textbooks_xml.asp?control=department&dept={d}&term={t}    → XML courses
  GET  /textbooks_xml.asp?control=course&course={c}&term={t}      → XML sections (CRNs + instructors)
  POST /textbook_express.asp?mode=2&step=2  (sectionIds={id})     → HTML with book rows

No type-checker configured — plain Python scripts only.
"""

import csv
import os
import re
import sys
import time
from datetime import datetime, timezone
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None

SCHOOL_NAME = "chaffey_college"
SCHOOL_ID   = "2995976"
BASE_URL    = "https://books.chaffey.edu"
STORE_HOME  = f"{BASE_URL}/buy_textbooks.asp"
BOOKS_POST  = f"{BASE_URL}/textbook_express.asp?mode=2&step=2"
XML_URL     = f"{BASE_URL}/textbooks_xml.asp"

REQUEST_DELAY = 1.0   # seconds between requests

SEASON_MAP = {"SP": "SPRING", "FA": "FALL", "SU": "SUMMER", "WI": "WINTER"}

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

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt(code):
    """Pipe-prefix a code string to preserve leading zeros."""
    code = (code or "").strip()
    return f"|{code}" if code and not code.startswith("|") else code


def normalize_term(raw_label):
    """'Chaffey Coll Campus - 2026/SP' → 'SPRING 2026'."""
    part = raw_label.split(" - ")[-1].strip()   # '2026/SP'
    if "/" in part:
        year, code = part.split("/", 1)
        return f"{SEASON_MAP.get(code.upper(), code.upper())} {year}"
    return part.upper()


def extract_csrf(html):
    """Extract CSRF token from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("input", {"name": "__CSRFToken"})
    return tag["value"] if tag else ""


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def make_session():
    sess = requests.Session()
    sess.headers.update({
        "User-Agent":      USER_AGENT,
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer":         STORE_HOME,
    })
    return sess


def bootstrap(sess):
    """GET /buy_textbooks.asp → return (csrf, terms_list).

    Each term dict: {campus_id, term_id, term_label, term_normalized}
    """
    print(f"[*] Bootstrapping session from {STORE_HOME}")
    resp = sess.get(STORE_HOME, timeout=30)
    resp.raise_for_status()
    html = resp.text

    csrf = extract_csrf(html)
    print(f"    CSRF: {csrf[:30]}...")

    soup = BeautifulSoup(html, "html.parser")
    select = soup.find("select", {"id": "fTerm"})
    terms = []
    if select:
        for opt in select.find_all("option"):
            val = opt.get("value", "")
            if val == "0|0" or "|" not in val:
                continue
            campus_id, term_id = val.split("|", 1)
            label = opt.get_text(strip=True)
            terms.append({
                "campus_id":       campus_id,
                "term_id":         term_id,
                "term_label":      label,
                "term_normalized": normalize_term(label),
            })

    print(f"    Found {len(terms)} term(s): {[t['term_normalized'] for t in terms]}")
    return csrf, terms


# ---------------------------------------------------------------------------
# XML fetches
# ---------------------------------------------------------------------------

def xml_get(sess, params, retries=3):
    """GET /textbooks_xml.asp with params; parse and return XML root."""
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.get(XML_URL, params=params, timeout=30)
            resp.raise_for_status()
            text = resp.text.strip()
            if not text.startswith("<?xml") and not text.startswith("<"):
                print(f"  [WARN] Non-XML response (attempt {attempt+1}): {text[:120]}")
                if attempt < retries - 1:
                    time.sleep(3 * (attempt + 1))
                    continue
                return None
            return ElementTree.fromstring(text)
        except Exception as e:
            print(f"  [WARN] xml_get attempt {attempt+1}: {e}")
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
            else:
                return None
    return None


def fetch_departments(sess, campus_id, term_id):
    root = xml_get(sess, {"control": "campus", "campus": campus_id, "term": term_id})
    if root is None:
        return []
    return [
        {"dept_id": el.get("id"), "abrev": el.get("abrev"), "name": el.get("name")}
        for el in root.findall("department")
    ]


def fetch_courses(sess, dept_id, term_id):
    root = xml_get(sess, {"control": "department", "dept": dept_id, "term": term_id})
    if root is None:
        return []
    return [
        {"course_id": el.get("id"), "name": el.get("name")}
        for el in root.findall("course")
    ]


def fetch_sections(sess, course_id, term_id):
    root = xml_get(sess, {"control": "course", "course": course_id, "term": term_id})
    if root is None:
        return []
    return [
        {
            "section_id":   el.get("id"),
            "name":         el.get("name"),        # CRN
            "instructor":   el.get("instructor", ""),
        }
        for el in root.findall("section")
    ]


# ---------------------------------------------------------------------------
# Books HTML POST
# ---------------------------------------------------------------------------

def post_books(sess, csrf, section_id, retries=3):
    """POST to textbook_express.asp; return (html_text, new_csrf)."""
    url = BOOKS_POST
    payload = {"__CSRFToken": csrf, "sectionIds": str(section_id)}
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.post(url, data=payload, timeout=60)
            resp.raise_for_status()
            html = resp.text
            new_csrf = extract_csrf(html)
            return html, (new_csrf or csrf)
        except Exception as e:
            print(f"  [WARN] post_books attempt {attempt+1}: {e}")
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
            else:
                return "", csrf
    return "", csrf


def parse_books(html, section_id, dept_code, course_name, crn, instructor, term_normalized):
    """Parse HTML response from textbook_express.asp.

    Returns list of row dicts (one per book, or one 'no materials' row).
    """
    source_url = (
        f"{BOOKS_POST}&dept={dept_code}&course={course_name}"
        f"&section={crn}&sectionId={section_id}"
    )
    base = {
        "source_url":       source_url,
        "school_id":        SCHOOL_ID,
        "department_code":  dept_code,
        "course_code":      fmt(course_name),
        "course_title":     "",
        "section":          fmt(crn),
        "section_instructor": instructor,
        "term":             term_normalized,
    }

    soup = BeautifulSoup(html, "html.parser")
    # Each book row: <tr class="book book-container"> or with extra class like "course-choice"
    book_rows = soup.find_all("tr", class_=lambda c: c and "book-container" in c)

    if not book_rows:
        return [{
            **base,
            "isbn":                  "",
            "title":                 "",
            "author":                "",
            "material_adoption_code": "This course does not require any course materials",
        }]

    rows = []
    for tr in book_rows:
        isbn_tag   = tr.find("span", class_="isbn")
        title_tag  = tr.find("span", class_="book-title")
        author_tag = tr.find("span", class_="book-author")
        req_tag    = tr.find("p", class_="book-req")

        isbn   = isbn_tag.get_text(strip=True).replace("-", "") if isbn_tag else ""
        title  = title_tag.get_text(strip=True) if title_tag else ""
        author = author_tag.get_text(strip=True) if author_tag else ""
        adoption = req_tag.get_text(strip=True) if req_tag else ""

        if not isbn and not title:
            continue

        # "No Text Required Or Provided By Instructor" is a Chaffey placeholder
        # entry, not a real book — treat it as a no-materials row.
        if "No Text Required Or Provided By Instructor" in title:
            rows.append({
                **base,
                "isbn":                  "",
                "title":                 "",
                "author":                "",
                "material_adoption_code": "No Text Required Or Provided By Instructor",
            })
            continue

        # Author "." is a Chaffey placeholder for free OER/online material entries.
        if author == ".":
            author = ""

        rows.append({
            **base,
            "isbn":                  isbn,
            "title":                 title,
            "author":                author,
            "material_adoption_code": adoption,
        })

    if not rows:
        rows.append({
            **base,
            "isbn":                  "",
            "title":                 "",
            "author":                "",
            "material_adoption_code": "This course does not require any course materials",
        })
    return rows


# ---------------------------------------------------------------------------
# CSV I/O
# ---------------------------------------------------------------------------

def append_csv(rows, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    new_file = not os.path.exists(filepath) or os.path.getsize(filepath) == 0
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def get_scraped_keys(filepath):
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

def scrape(fresh=False):
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run — deleted existing CSV.")

    done_keys = get_scraped_keys(CSV_PATH)
    if done_keys:
        print(f"[*] {len(done_keys)} combos already scraped — resuming.")

    sess = make_session()
    csrf, terms = bootstrap(sess)

    if not terms:
        print("[!] No terms found. Exiting.")
        return

    total_rows  = 0
    debug_saved = False
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for term in terms:
        campus_id      = term["campus_id"]
        term_id        = term["term_id"]
        term_label     = term["term_label"]
        term_norm      = term["term_normalized"]

        print(f"\n[*] Term: {term_label} → {term_norm}")
        depts = fetch_departments(sess, campus_id, term_id)
        if not depts:
            print("    No departments found.")
            continue
        print(f"    {len(depts)} departments")

        for dept in tqdm(depts, desc=f"  {term_norm}"):
            dept_id   = dept["dept_id"]
            dept_code = dept["abrev"]

            courses = fetch_courses(sess, dept_id, term_id)
            if not courses:
                continue

            dept_rows = 0
            for course in courses:
                course_id   = course["course_id"]
                course_name = course["name"]

                sections = fetch_sections(sess, course_id, term_id)
                if not sections:
                    continue

                for sec in sections:
                    section_id = sec["section_id"]
                    crn        = sec["name"]
                    instructor = sec["instructor"]

                    check_key = (term_norm, dept_code, fmt(course_name), fmt(crn))
                    if check_key in done_keys:
                        continue

                    html, csrf = post_books(sess, csrf, section_id)

                    if not html:
                        # Session likely dropped — re-bootstrap
                        tqdm.write(f"  [WARN] Empty response for {dept_code}/{course_name}/{crn} — re-bootstrapping")
                        try:
                            csrf, _ = bootstrap(sess)
                            html, csrf = post_books(sess, csrf, section_id)
                        except Exception as e:
                            tqdm.write(f"  [ERROR] Re-bootstrap failed: {e}")
                            continue

                    if not debug_saved and html:
                        with open(os.path.join(OUTPUT_DIR, "debug_books.html"), "w", encoding="utf-8") as df:
                            df.write(html)
                        tqdm.write("    [DEBUG] First book HTML saved to debug_books.html")
                        debug_saved = True

                    rows = parse_books(html, section_id, dept_code, course_name, crn, instructor, term_norm)
                    for row in rows:
                        row["crawled_on"] = crawled_on
                        row["updated_on"] = crawled_on

                    append_csv(rows, CSV_PATH)
                    dept_rows  += len(rows)
                    total_rows += len(rows)

            if dept_rows:
                tqdm.write(f"    [{dept_code}] +{dept_rows} rows (total: {total_rows})")

    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE — {total_rows} rows written")
    print(f"CSV: {CSV_PATH}")
    if total_rows == 0:
        print("[!] No data written. Check debug_books.html for response inspection.")


if __name__ == "__main__":
    scrape(fresh="--fresh" in sys.argv)
