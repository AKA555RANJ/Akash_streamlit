"""
Guilford Technical Community College Textbook Scraper
Platform: Timber (bookstorewebsoftware.com) — Drupal-based college bookstore CMS
Stores:   Greensboro + Jamestown campus terms both available at greensborobookstore.gtcc.edu

API: Pure GET requests — no FlareSolverr, no form tokens, no antibot needed.
  /timber/college/ajax?l=/college_term/{id}    → department chooser HTML
  /timber/college/ajax?l=/college_dept/{id}    → course chooser HTML
  /timber/college/ajax?l=/college_course/{id}  → section chooser HTML
  /timber/college/ajax?l=/college_section/{id} → materials HTML

Session note: A requests.Session must carry the Drupal session cookie so the
server knows which term is active when fetching dept/course/section levels.
A new session is started per term to avoid context bleed.

Materials HTML structure (inside /college_section/{id} response):
  <div class='req-group req-group-R ...'>        ← adoption type (R/O/C/P)
    <div class='timber-item-group ...'>
      <span class='tcc-product-title'>Title</span>
      <em class='author-data'>AUTHOR</em>
      <span class='tcc-sku-number'>(ISBN)</span>
    </div>
  </div>
"""

import csv
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None

SCHOOL_NAME = "guilford_technical_community_college"
SCHOOL_ID   = "3055621"
BASE_URL    = "https://greensborobookstore.gtcc.edu"
COLLEGE_URL = f"{BASE_URL}/college"
AJAX_URL    = f"{BASE_URL}/timber/college/ajax"

REQUEST_DELAY = 0.8

ADOPTION_MAP = {
    "R": "Required",
    "O": "Optional",
    "C": "Choice / Recommended",
    "P": "Recommended",
    "S": "Supplementary",
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

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def make_session():
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": UA,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "text/html, */*; q=0.01",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": COLLEGE_URL,
    })
    return sess


def ajax_get(sess, path, retries=3):
    """GET /timber/college/ajax?l={path} and return response text."""
    url = AJAX_URL
    params = {"l": path}
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] ajax_get {path} attempt {attempt+1}: {e}")
                time.sleep(3 * (attempt + 1))
            else:
                raise
    return ""


# ---------------------------------------------------------------------------
# HTML parsers for each chooser level
# ---------------------------------------------------------------------------

def parse_chooser_items(html, item_type):
    """
    Parse tcc-item-link anchors of a given type from chooser HTML.
    Returns list of (url_path, label_text).
    """
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for div in soup.find_all("div", class_=re.compile(rf"type-{item_type}")):
        a = div.find("a", class_="tcc-item-link")
        if a:
            url_path = a.get("url", "").strip()
            label    = a.get_text(" ", strip=True)
            if url_path:
                items.append((url_path, label))
    return items


def parse_term_items(html):
    """Parse term chooser — returns list of (url_path, label)."""
    return parse_chooser_items(html, "college_term")


def parse_dept_items(html):
    """Parse department chooser — returns list of (url_path, abbrev, name)."""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for div in soup.find_all("div", class_=re.compile(r"type-college_dept")):
        a = div.find("a", class_="tcc-item-link")
        if a:
            url_path = a.get("url", "").strip()
            abbrev   = _text(a.find("span", class_="abbreviation"))
            name     = _text(a.find("span", class_="name"))
            if url_path:
                items.append((url_path, abbrev, name))
    return items


def parse_course_items(html):
    """Parse course chooser — returns list of (url_path, course_code, course_title)."""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for div in soup.find_all("div", class_=re.compile(r"type-college_course")):
        a = div.find("a", class_="tcc-item-link")
        if a:
            url_path = a.get("url", "").strip()
            label    = a.get_text(" ", strip=True)
            # label format: "120 - Prin of Financial Accounting"
            if " - " in label:
                code, title = label.split(" - ", 1)
                code  = code.strip()
                title = title.strip()
            else:
                code  = label.strip()
                title = ""
            if url_path:
                items.append((url_path, code, title))
    return items


def parse_section_items(html):
    """Parse section chooser — returns list of (url_path, section_code, instructor)."""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for div in soup.find_all("div", class_=re.compile(r"type-college_section")):
        a = div.find("a", class_="tcc-item-link")
        if a:
            url_path = a.get("url", "").strip()
            label    = a.get_text(" ", strip=True)
            # label format: "ALL - Brown, Sharon"
            if " - " in label:
                sec, instructor = label.split(" - ", 1)
                sec        = sec.strip()
                instructor = instructor.strip()
            else:
                sec        = label.strip()
                instructor = ""
            if url_path:
                items.append((url_path, sec, instructor))
    return items


def clean_title(title):
    """Strip fee/access boilerplate from DayOne and similar titles.

    Removes patterns like:
      "(Access in canvas on 1st day of class (fee of $X ...))"
      "Access available in Canvas on 1st day..."
      "(eBook avail. 1st day of class in Canvas...)"
      "no item ships"
    Leaves the actual material name intact.
    """
    if not title:
        return title
    t = title.strip()
    # Remove from "(Access..." onwards
    t = re.sub(r'\s*\(Access\b.*', '', t, flags=re.IGNORECASE)
    # Remove from "(eBook avail..." or "(eBook available..." onwards
    t = re.sub(r'\s*\(eBook\s+avail\w*\b.*', '', t, flags=re.IGNORECASE)
    # Remove "Access in / Access available" boilerplate (standalone)
    t = re.sub(r'\s*Access\s+(in|available)\b.*', '', t, flags=re.IGNORECASE)
    # Remove "available in canvas" boilerplate (e.g. "Physics available in canvas on 1st day...")
    t = re.sub(r'\s*available in canvas\b.*', '', t, flags=re.IGNORECASE)
    # Remove "(fee of $X...)" parenthetical
    t = re.sub(r'\s*\(fee\b.*', '', t, flags=re.IGNORECASE)
    # Remove trailing "no item ships" note
    t = re.sub(r'\s*no item ships.*', '', t, flags=re.IGNORECASE)
    # Strip trailing stray punctuation/spaces
    t = re.sub(r'[\s,\-]+$', '', t)
    # Balance parentheses: strip back to last unmatched open paren
    while t.count('(') > t.count(')'):
        idx = t.rfind('(')
        t = t[:idx].rstrip(' ,\t')
    return t.strip()


def clean_course_title(title):
    """Return empty string if course_title is only punctuation/whitespace."""
    if not title:
        return title
    return "" if re.match(r'^[,.\s\-]+$', title) else title


def parse_materials(html, source_url, dept_code, course_code, course_title,
                    section_code, instructor, term_name):
    """
    Parse the tcc-product chooser HTML for textbook data.

    Structure:
      <div class='req-group req-group-R ...'>   ← adoption type letter after req-group-
        <div class='timber-item-group ...'>
          <span class='tcc-product-title'>Title text</span>
          EDITION [<em class='author-data'>AUTHOR</em>]
          <span class='tcc-sku-number'>(ISBN13)</span>
        </div>
      </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    base = {
        "department_code":   dept_code,
        "course_code":       fmt(course_code),
        "course_title":      clean_course_title(course_title),
        "section":           fmt(section_code),
        "section_instructor": instructor,
        "term":              normalize_term(term_name),
        "source_url":        source_url,
    }

    req_groups = soup.find_all("div", class_=re.compile(r"\breq-group\b"))
    for grp in req_groups:
        # Determine adoption type from class like 'req-group-R', 'req-group-O', etc.
        adoption_letter = ""
        for cls in grp.get("class", []):
            m = re.match(r"req-group-([A-Z])", cls)
            if m:
                adoption_letter = m.group(1)
                break
        adoption = ADOPTION_MAP.get(adoption_letter, adoption_letter or "Required")

        for item_div in grp.find_all("div", class_=re.compile(r"\btimber-item-group\b")):
            title_el  = item_div.find("span", class_="tcc-product-title")
            isbn_el   = item_div.find("span", class_="tcc-sku-number")
            author_el = item_div.find("em",   class_="author-data")

            title  = clean_title(_text(title_el))
            isbn   = _extract_isbn(_text(isbn_el))
            author = _text(author_el)

            if not (isbn or title):
                continue

            rows.append({
                **base,
                "isbn":                 isbn,
                "title":                title,
                "author":               author,
                "material_adoption_code": adoption,
            })

    if not rows:
        rows.append({
            **base,
            "isbn": "", "title": "", "author": "",
            "material_adoption_code": "This course does not require any course materials",
        })
    return rows


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _extract_isbn(raw):
    """
    Extract a clean ISBN/SKU from raw tcc-sku-number text like '(9780123456789R180)'.

    Timber appends rental/period codes after the identifier (e.g. 'R180', 'P90', 'R90').
    Strategy:
      1. Strip outer parens and whitespace.
      2. Remove rental suffix: trailing letter+digits pattern (e.g. R180, P90).
      3. Try to match a valid ISBN-13 (13 digits starting with 978/979).
      4. Fall back to raw digits (store SKUs, UPCs are legitimate non-ISBN identifiers).
      5. Return empty string for obvious placeholders (all zeros).
    """
    if not raw:
        return ""
    clean = raw.strip("() ")
    # Strip rental/period suffix: e.g. "9781234567890R180" -> "9781234567890"
    clean = re.sub(r"[A-Za-z]\d+$", "", clean).strip()
    digits = re.sub(r"[^\d]", "", clean)
    # Blank out obvious placeholders
    if not digits or set(digits) == {"0"}:
        return ""
    # Try ISBN-13 (13 digits starting with 978 or 979)
    m = re.search(r"(97[89]\d{10})", digits)
    if m:
        return m.group(1)
    # Return raw digits as-is (store SKU / UPC — valid non-ISBN identifiers)
    return digits


def _text(el, default=""):
    return el.get_text(strip=True) if el else default


def normalize_term(s):
    """Remove parenthetical suffixes and uppercase."""
    return re.sub(r"\s*\(.*?\)\s*", " ", s or "").strip().upper()


def fmt(code):
    """Prefix course/section code with | to preserve leading zeros."""
    code = (code or "").strip()
    return f"|{code}" if code and not code.startswith("|") else code


# ---------------------------------------------------------------------------
# CSV helpers
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
# Bootstrap: get term list from /college
# ---------------------------------------------------------------------------

def discover_terms():
    """Fetch /college and parse the term chooser. No FlareSolverr needed."""
    sess = make_session()
    print(f"[*] Fetching term list from {COLLEGE_URL}...")
    resp = sess.get(COLLEGE_URL, timeout=30)
    resp.raise_for_status()
    html = resp.text

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, "debug_bootstrap.html"), "w", encoding="utf-8") as f:
        f.write(html)

    terms = parse_term_items(html)
    print(f"    Found {len(terms)} terms")
    for path, label in terms:
        print(f"      {label!r:40s} → {path}")
    return terms


# ---------------------------------------------------------------------------
# Main scrape loop
# ---------------------------------------------------------------------------

def scrape_term(term_path, term_label, done_keys, crawled_on):
    """Scrape one term. Returns number of rows written."""
    print(f"\n[*] Term: {term_label!r}")

    # Fresh session per term — each starts by selecting the term
    sess = make_session()

    # Step 1: Select term → get departments
    dept_html = ajax_get(sess, term_path)
    dept_items = parse_dept_items(dept_html)
    if not dept_items:
        print(f"  [WARN] No departments for {term_label!r}")
        return 0
    print(f"  {len(dept_items)} departments")

    total_rows = 0
    debug_materials_saved = False

    for dept_path, dept_abbrev, dept_name in tqdm(dept_items, desc=f"  {term_label}"):
        dept_code = dept_abbrev.strip()

        # Step 2: Select dept → get courses
        course_html  = ajax_get(sess, dept_path)
        course_items = parse_course_items(course_html)
        if not course_items:
            continue

        for course_path, course_code, course_title in course_items:

            # Step 3: Select course → get sections
            section_html  = ajax_get(sess, course_path)
            section_items = parse_section_items(section_html)
            if not section_items:
                # No sections — record as no materials
                check_key = (normalize_term(term_label), dept_code, fmt(course_code), fmt(""))
                if check_key in done_keys:
                    continue
                rows = [{
                    "source_url":          COLLEGE_URL,
                    "school_id":           SCHOOL_ID,
                    "department_code":     dept_code,
                    "course_code":         fmt(course_code),
                    "course_title":        course_title,
                    "section":             "",
                    "section_instructor":  "",
                    "term":                normalize_term(term_label),
                    "isbn": "", "title": "", "author": "",
                    "material_adoption_code": "This course does not require any course materials",
                    "crawled_on":  crawled_on,
                    "updated_on":  crawled_on,
                }]
                append_csv(rows, CSV_PATH)
                total_rows += 1
                continue

            for sec_path, sec_code, instructor in section_items:
                check_key = (normalize_term(term_label), dept_code, fmt(course_code), fmt(sec_code))
                if check_key in done_keys:
                    continue

                source_url = f"{BASE_URL}{sec_path}"

                # Step 4: Select section → get materials
                try:
                    mat_html = ajax_get(sess, sec_path)
                except Exception as e:
                    tqdm.write(f"\n  [ERROR] {dept_code}/{course_code}/{sec_code}: {e}")
                    mat_html = ""

                if mat_html and not debug_materials_saved:
                    path = os.path.join(OUTPUT_DIR, "debug_materials.html")
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(mat_html)
                    tqdm.write(f"\n    [DEBUG] Saved debug_materials.html")
                    debug_materials_saved = True

                rows = parse_materials(
                    mat_html or "", source_url,
                    dept_code, course_code, course_title,
                    sec_code, instructor, term_label,
                )
                for row in rows:
                    row["school_id"]  = SCHOOL_ID
                    row["crawled_on"] = crawled_on
                    row["updated_on"] = crawled_on

                append_csv(rows, CSV_PATH)
                total_rows += len(rows)

    return total_rows


def scrape(fresh=False):
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run — deleted existing CSV.")

    done_keys = get_scraped_keys(CSV_PATH)
    if done_keys:
        print(f"[*] {len(done_keys)} combos already scraped, resuming.")

    terms = discover_terms()
    if not terms:
        print("[!] No terms found. Check debug_bootstrap.html.")
        return

    total_rows = 0
    for term_path, term_label in terms:
        n = scrape_term(term_path, term_label, done_keys, crawled_on)
        total_rows += n
        print(f"  → {n} rows written for {term_label!r}")

    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE — {total_rows} rows written")
    print(f"CSV: {CSV_PATH}")


if __name__ == "__main__":
    scrape(fresh="--fresh" in sys.argv)
