"""
Kutztown University of Pennsylvania Bookstore Textbook Scraper
Platform: Timber (by Herkimer Media) — Drupal-based, custom kubstore instance
URL: https://www.kubstore.com/find-courses

Flow:
  1. GET /find-courses → extract term options (tid values: 39=Spring, 40=Summer, 41=Fall)
  2. GET /find-courses/autocomplete?tid={tid}&q={char} (a-z, 0-9) → enumerate all sections
     Response: [{"value": 50018, "label": "<span ...>ACCT 121 | FINANCIAL ACCOUNTING | Section 010</span>"}]
  3. GET /my-courses/{section_id} → book data for that section
     HTML: div.adoption-list-content-group.adoption-type.{type}
             div.adoption-row
               h4 (title, may have "Billed To MyKU - " prefix)
               table.adoption-data tbody
                 tr.isbn → SKU: I{isbn13}
                 tr.author → Author: {author}
"""

import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None

SCHOOL_NAME = "kutztown_university_of_pennsylvania"
SCHOOL_ID = "3083584"
BASE_URL = "https://www.kubstore.com"
FIND_URL = BASE_URL + "/find-courses"
MY_COURSES_URL = BASE_URL + "/my-courses"
REQUEST_DELAY = 0.5

ADOPTION_MAP = {
    "prepaid": "Prepaid",
    "required": "Required",
    "optional": "Optional",
    "recommended": "Recommended",
    "not-required": "Not Required",
    "choice": "Choice",
}

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

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

BASE_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

def create_session():
    sess = requests.Session()
    sess.headers.update(BASE_HEADERS)
    return sess

def clean_term(label):
    """Strip '(Order Now)' / '(Pre-Order)' suffixes."""
    return re.sub(r"\s*\(.*?\)\s*$", "", label).strip()

def format_course_code(code):
    code = code.strip()
    if not code or code.startswith("|"):
        return code
    return f"|{code}"

def format_section_code(section):
    section = section.strip()
    if not section or section.startswith("|"):
        return section
    return f"|{section}"

def split_dept_course(raw):
    """'ACCT 121' → ('ACCT', '|121')."""
    raw = raw.strip()
    parts = raw.split(None, 1)
    if len(parts) == 2:
        return parts[0], format_course_code(parts[1])
    return raw, ""

def safe_get(sess, url, retries=3):
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.get(url, timeout=30)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return resp.text
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] GET failed (attempt {attempt + 1}): {e}")
                time.sleep(2 * (attempt + 1))
            else:
                raise
    return ""

def parse_find_courses_page(html):
    """Extract term options from /find-courses.

    Returns list of {value, label} dicts.
    """
    soup = BeautifulSoup(html, "html.parser")
    terms = []
    sel = (
        soup.find("select", {"name": "term_select"})
        or soup.find("select", {"id": "edit-term-select"})
    )
    if sel:
        for opt in sel.find_all("option"):
            val = opt.get("value", "").strip()
            text = clean_term(opt.get_text(strip=True))
            if val and text:
                terms.append({"value": val, "label": text})
    return terms

def parse_autocomplete_label(label_html):
    """Parse kubstore autocomplete label HTML into section metadata.

    Example:
        <span class='cdept-name'>Accounting</span> -
        <span class='cdept-code'>ACCT 121</span> |
        <span class='ccourse-desc'>FINANCIAL ACCOUNTING</span> |
        <span class='csection-name'>Section 010</span>

    Returns (dept_code, course_code, course_title, section_code).
    """
    soup = BeautifulSoup(label_html, "html.parser")

    dept_code = ""
    course_code = ""
    dept_code_el = soup.find("span", class_="cdept-code")
    if dept_code_el:
        raw = dept_code_el.get_text(strip=True)
        dept_code, course_code = split_dept_course(raw)

    course_title = ""
    desc_el = soup.find("span", class_="ccourse-desc")
    if desc_el:
        course_title = desc_el.get_text(strip=True)

    section = ""
    sec_el = soup.find("span", class_="csection-name")
    if sec_el:
        sec_text = sec_el.get_text(strip=True)
        section = re.sub(r"^Section\s+", "", sec_text, flags=re.I).strip()

    return dept_code, course_code, course_title, section

def fetch_autocomplete(sess, tid, query):
    """GET /find-courses/autocomplete?tid={tid}&q={query}.

    Returns list of section dicts: {value, dept_code, course_code, course_title, section}.
    """
    url = f"{FIND_URL}/autocomplete?tid={tid}&q={query}"
    try:
        time.sleep(REQUEST_DELAY)
        resp = sess.get(url, timeout=20)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        data = resp.json()
    except Exception as e:
        print(f"    [WARN] autocomplete q={query!r}: {e}")
        return []

    if not isinstance(data, list):
        return []

    results = []
    for item in data:
        sid = item.get("value")
        label_html = item.get("label", "")
        if not sid:
            continue
        dept_code, course_code, course_title, section = parse_autocomplete_label(label_html)
        results.append({
            "value": sid,
            "dept_code": dept_code,
            "course_code": course_code,
            "course_title": course_title,
            "section": section,
        })
    return results

def enumerate_sections(sess, tid, term_label):
    """Query autocomplete with a–z + 0–9, deduplicate, return all sections."""
    seen = {}
    queries = [chr(c) for c in range(ord("a"), ord("z") + 1)] + list("0123456789")
    print(f"    Enumerating sections ({len(queries)} queries)...")
    for q in queries:
        for item in fetch_autocomplete(sess, tid, q):
            sid = item["value"]
            if sid not in seen:
                seen[sid] = item
    print(f"    Found {len(seen)} unique sections for {term_label}")
    return list(seen.values())

def _clean_title(raw_title):
    """Strip 'Billed To MyKU - ', 'Billed to Account - ', etc. prefixes from titles."""
    raw_title = raw_title.strip()
    raw_title = re.sub(r"^Billed\s+[Tt]o\s+\S+\s+-\s+", "", raw_title).strip()
    return raw_title

def _clean_isbn(raw_sku):
    """'I9780137858644' → '9780137858644'. Strip leading alpha prefix."""
    raw = raw_sku.strip()
    raw = re.sub(r"^[A-Za-z]+", "", raw)
    raw = raw.replace("-", "").strip()
    return raw if re.match(r"^\d{10}$|^\d{13}$", raw) else ""

def fetch_section_books(sess, section_id, sec_meta, term_label, crawled_on):
    """GET /my-courses/{section_id} and parse book adoptions.

    Returns list of CSV row dicts (at least one row even if no materials).
    """
    url = f"{MY_COURSES_URL}/{section_id}"
    dept_code = sec_meta.get("dept_code", "")
    course_code = sec_meta.get("course_code", "")
    course_title = sec_meta.get("course_title", "")
    section = format_section_code(sec_meta.get("section", ""))

    try:
        html = safe_get(sess, url)
    except Exception as e:
        print(f"    [WARN] /my-courses/{section_id}: {e}")
        return [_make_row(dept_code, course_code, course_title, section,
                          term_label, "", "", "", "Fetch error", crawled_on)]

    soup = BeautifulSoup(html, "html.parser")
    rows = []

    page_text = soup.get_text(" ", strip=True)
    if "not been finalized" in page_text:
        return [_make_row(dept_code, course_code, course_title, section,
                          term_label, "", "", "", "Not Finalized", crawled_on)]

    for group in soup.find_all("div", class_=re.compile(r"\badoption-list-content-group\b")):
        adoption_type = ""
        for cls in group.get("class", []):
            if cls in ADOPTION_MAP:
                adoption_type = ADOPTION_MAP[cls]
                break
        if not adoption_type:
            title_h4 = group.find("h4", class_="adoption-type-title")
            if title_h4:
                adoption_type = title_h4.get_text(strip=True)

        for adoption_row in group.find_all("div", class_=re.compile(r"\badoption-row\b")):
            adoption_left = adoption_row.find("div", class_=re.compile(r"\badoption-left\b"))
            if not adoption_left:
                continue

            title_el = adoption_left.find("h4")
            title = _clean_title(title_el.get_text(strip=True)) if title_el else ""

            isbn = ""
            author = ""
            table = adoption_left.find("table", class_="adoption-data")
            if table:
                for tr in table.find_all("tr"):
                    cls_list = tr.get("class", [])
                    tds = tr.find_all("td")
                    if len(tds) < 2:
                        continue
                    val = tds[1].get_text(strip=True)
                    if "isbn" in cls_list or "isbn" in " ".join(cls_list):
                        isbn = _clean_isbn(val)
                    elif "author" in cls_list or "author" in " ".join(cls_list):
                        author = val

            if isbn or title:
                rows.append(_make_row(dept_code, course_code, course_title, section,
                                      term_label, isbn, title, author, adoption_type, crawled_on))

    if not rows:
        if re.search(r"no\s+(textbook|material|book|course material)s?\s+(required|found|needed)", page_text, re.I):
            adoption_note = "No materials required"
        elif re.search(r"no\s+required\s+material", page_text, re.I):
            adoption_note = "No materials required"
        else:
            adoption_note = "No materials found"
        rows.append(_make_row(dept_code, course_code, course_title, section,
                              term_label, "", "", "", adoption_note, crawled_on))

    return rows

def _make_row(dept_code, course_code, course_title, section, term, isbn, title, author, adoption, crawled_on):
    return {
        "source_url": FIND_URL,
        "school_id": SCHOOL_ID,
        "department_code": dept_code,
        "course_code": course_code,
        "course_title": course_title,
        "section": section,
        "section_instructor": "",
        "term": term,
        "isbn": isbn,
        "title": title,
        "author": author,
        "material_adoption_code": adoption,
        "crawled_on": crawled_on,
        "updated_on": crawled_on,
    }

def append_csv(rows, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    file_exists = os.path.exists(filepath) and os.path.getsize(filepath) > 0
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)

def get_scraped_section_ids(filepath):
    """Return set of (term, dept_code, course_code, section) tuples already in CSV."""
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return set()
    seen = set()
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (
                row.get("term", "").strip(),
                row.get("department_code", "").strip(),
                row.get("course_code", "").strip(),
                row.get("section", "").strip(),
            )
            seen.add(key)
    return seen

def dump_debug(html, label):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"debug_{label}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"    [DEBUG] Saved {len(html)} chars → {path}")

def scrape(fresh=False, discover_only=False):
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d 00:00:00")

    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run — deleted existing CSV.")

    scraped_keys = get_scraped_section_ids(CSV_PATH)
    if scraped_keys:
        print(f"[*] {len(scraped_keys)} entries already scraped.")

    sess = create_session()

    print("[*] Fetching /find-courses ...")
    html = safe_get(sess, FIND_URL)
    terms = parse_find_courses_page(html)

    print(f"[*] Terms: {[(t['value'], t['label']) for t in terms]}")

    if not terms:
        print("[!] No terms found — saving debug page and exiting.")
        dump_debug(html, "initial_page")
        return

    if discover_only:
        dump_debug(html, "initial_page")
        print("[*] Discovery mode — stopping after term list.")
        return

    total_rows = 0

    for term in terms:
        tid = term["value"]
        term_label = term["label"]
        print(f"\n[*] Term: {term_label} (tid={tid})")

        sections = enumerate_sections(sess, tid, term_label)
        if not sections:
            print(f"    [!] No sections found for {term_label}")
            continue

        remaining = [
            sec for sec in sections
            if (
                term_label,
                sec.get("dept_code", ""),
                sec.get("course_code", ""),
                format_section_code(sec.get("section", "")),
            ) not in scraped_keys
        ]
        skipped = len(sections) - len(remaining)
        if skipped:
            print(f"    Skipping {skipped} already-scraped sections.")
        if not remaining:
            print(f"    All sections already scraped for {term_label}.")
            continue

        print(f"    Processing {len(remaining)} sections...")
        term_rows = 0

        for sec in tqdm(remaining, desc=f"  {term_label}"):
            rows = fetch_section_books(sess, sec["value"], sec, term_label, crawled_on)
            if rows:
                append_csv(rows, CSV_PATH)
                term_rows += len(rows)
                total_rows += len(rows)

        tqdm.write(f"  [{term_label}] +{term_rows} rows  (running total: {total_rows})")

    print(f"\n{'=' * 60}")
    print("SCRAPE COMPLETE")
    print(f"{'=' * 60}")
    print(f"Total rows written : {total_rows}")
    print(f"CSV                : {CSV_PATH}")

if __name__ == "__main__":
    fresh = "--fresh" in sys.argv
    discover = "--discover" in sys.argv
    scrape(fresh=fresh, discover_only=discover)
