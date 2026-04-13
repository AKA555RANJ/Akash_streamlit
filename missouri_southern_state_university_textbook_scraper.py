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

SCHOOL_NAME  = "missouri_southern_state_university"
SCHOOL_ID    = "3050205"
BASE_URL     = "https://www.mssubookstore.com"
COLLEGE_URL  = f"{BASE_URL}/college"
AJAX_URL     = f"{BASE_URL}/timber/college/ajax"

REQUEST_DELAY = 0.6
ISBN_DELAY    = 0.3

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

CHROME_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
    "Referer": COLLEGE_URL,
    "X-Requested-With": "XMLHttpRequest",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

def create_session():
    sess = requests.Session()
    sess.headers.update(CHROME_HEADERS)

    print("[*] Initialising session via /college ...")
    resp = sess.get(COLLEGE_URL, timeout=20)
    resp.raise_for_status()
    print(f"    OK (status={resp.status_code}, cookies={list(sess.cookies.keys())})")
    return sess

def refresh_session(sess):
    print("[*] Refreshing session...", flush=True)
    for attempt in range(4):
        try:
            time.sleep(8 * (attempt + 1))
            return create_session()
        except Exception as e:
            print(f"  [WARN] Refresh attempt {attempt+1} failed: {e}", flush=True)
            if attempt == 3:
                raise

def _get(sess, url, retries=3, timeout=20):
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.get(url, timeout=timeout)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (403, 503):
                print(f"  [WARN] HTTP {resp.status_code} on {url} (attempt {attempt+1})")
                time.sleep(5 * (attempt + 1))
                continue
            resp.raise_for_status()
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] GET {url} attempt {attempt+1}: {e}")
                time.sleep(3 * (attempt + 1))
            else:
                raise
    return ""

def ajax_get(sess, l_path, retries=3):
    from urllib.parse import quote
    encoded = quote(l_path, safe="")
    url = f"{AJAX_URL}?l={encoded}"
    return _get(sess, url, retries=retries)

def get_terms(sess):
    print("[*] Fetching terms from /college ...")
    html = _get(sess, COLLEGE_URL)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    terms = []
    for a in soup.select("a.tcc-item-link"):
        url_attr = a.get("url", "")
        if "/college_term/" in url_attr:
            term_id = url_attr.split("/college_term/")[-1].strip("/")
            term_name = a.get_text(" ", strip=True)
            if term_id and term_name:
                terms.append({"term_id": term_id, "term_name": term_name})
    print(f"    Found {len(terms)} terms: {[t['term_name'] for t in terms]}")
    return terms

def get_depts(sess, term_id):
    html = ajax_get(sess, f"/college_term/{term_id}")
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    depts = []
    for item in soup.select("#tcc-college_dept a.tcc-item-link"):
        url_attr = item.get("url", "")
        dept_id = url_attr.split("/college_dept/")[-1].strip("/") if "/college_dept/" in url_attr else ""
        abbr = (item.select_one("span.abbreviation") or item).get_text(strip=True).split("-")[0].strip()

        abbr_tag = item.select_one("span.abbreviation")
        name_tag = item.select_one("span.name")
        dept_code = abbr_tag.get_text(strip=True) if abbr_tag else abbr
        dept_name = name_tag.get_text(strip=True) if name_tag else ""
        if dept_id and dept_code:
            depts.append({"dept_id": dept_id, "dept_code": dept_code, "dept_name": dept_name})
    return depts

def get_courses(sess, dept_id):
    html = ajax_get(sess, f"/college_dept/{dept_id}")
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    courses = []
    for item in soup.select("#tcc-college_course a.tcc-item-link"):
        url_attr = item.get("url", "")
        course_id = url_attr.split("/college_course/")[-1].strip("/") if "/college_course/" in url_attr else ""
        text = item.get_text(" ", strip=True)
        course_num, course_title = _parse_dash_split(text)
        if course_id:
            courses.append({"course_id": course_id, "course_num": course_num,
                            "course_title": course_title})
    return courses

def get_sections(sess, course_id):
    html = ajax_get(sess, f"/college_course/{course_id}")
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    sections = []
    for item in soup.select("#tcc-college_section a.tcc-item-link"):
        url_attr = item.get("url", "")
        section_id = url_attr.split("/college_section/")[-1].strip("/") if "/college_section/" in url_attr else ""
        text = item.get_text(" ", strip=True)
        section_num, instructor = _parse_dash_split(text)
        if section_id:
            sections.append({"section_id": section_id, "section_num": section_num,
                              "instructor": instructor})
    return sections

def get_materials_html(sess, section_id):
    return ajax_get(sess, f"/college_section/{section_id}")

ISBN_RE = re.compile(r'97[89]\d{10}')

def get_isbn(sess, nid, cache):
    if nid in cache:
        return cache[nid]

    isbn = ""
    try:
        time.sleep(ISBN_DELAY)
        html = _get(sess, f"{BASE_URL}/node/{nid}", timeout=15)
        if html:

            match = ISBN_RE.search(html)
            if match:
                isbn = match.group(0)
    except Exception as e:
        print(f"  [WARN] ISBN lookup failed for nid={nid}: {e}")

    cache[nid] = isbn
    return isbn

ADOPTION_MAP = {
    "req-group-R": "Required Material(s)",
    "req-group-O": "Recommended Material(s)",
}

def parse_materials(html, source_url, dept_code, course_num, course_title,
                    section_num, instructor, term_name, sess, isbn_cache):
    base = {
        "source_url":        source_url,
        "school_id":         SCHOOL_ID,
        "department_code":   dept_code,
        "course_code":       fmt(course_num),
        "course_title":      course_title,
        "section":           fmt(section_num),
        "section_instructor": instructor,
        "term":              normalize_term(term_name),
    }

    soup = BeautifulSoup(html, "html.parser")
    product_div = soup.select_one("#tcc-product")

    if not product_div:
        return [{**base, "isbn": "", "title": "", "author": "",
                 "material_adoption_code": "This course does not require any course materials"}]

    body = product_div.select_one(".tcc-section-body")
    req_groups = body.select("div.req-group") if body else []

    if not req_groups:
        return [{**base, "isbn": "", "title": "", "author": "",
                 "material_adoption_code": "This course does not require any course materials"}]

    rows = []
    for group in req_groups:

        adoption = "Required Material(s)"
        for cls, label in ADOPTION_MAP.items():
            if cls in group.get("class", []):
                adoption = label
                break

        for item_group in group.select(".item.group"):
            title_tag  = item_group.select_one("span.tcc-product-title")
            author_tag = item_group.select_one("em.author-data")
            sku_tag    = item_group.select_one("span.tcc-sku-number")
            product_div2 = item_group.select_one("div.chooser-product")

            title  = title_tag.get_text(strip=True) if title_tag else ""
            author = author_tag.get_text(strip=True) if author_tag else ""
            nid    = product_div2.get("nid", "") if product_div2 else ""

            isbn = ""
            if sku_tag:
                raw_sku = re.sub(r"[^0-9]", "", sku_tag.get_text(strip=True))
                if ISBN_RE.fullmatch(raw_sku):
                    isbn = raw_sku

            if not isbn and nid:
                isbn = get_isbn(sess, nid, isbn_cache)

            if title or isbn:
                rows.append({**base, "isbn": isbn, "title": title,
                             "author": author, "material_adoption_code": adoption})

    if not rows:
        rows.append({**base, "isbn": "", "title": "", "author": "",
                     "material_adoption_code": "This course does not require any course materials"})
    return rows

def _parse_dash_split(text):
    parts = text.split(" - ", 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return text.strip(), ""

def normalize_term(s):
    return re.sub(r"\s*\(.*?\)\s*", " ", s or "").strip().upper()

def fmt(code):
    code = (code or "").strip()
    return f"|{code}" if code and not code.startswith("|") else code

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
        return {(r.get("term", ""), r.get("department_code", ""),
                 r.get("course_code", ""), r.get("section", ""))
                for r in csv.DictReader(f)}

def scrape(fresh=False):
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run — deleted existing CSV.")

    done_keys = get_scraped_keys(CSV_PATH)
    if done_keys:
        print(f"[*] {len(done_keys)} combos already scraped, resuming.")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    sess = create_session()
    isbn_cache = {}
    total_rows = 0
    debug_saved = False

    terms = get_terms(sess)
    if not terms:
        print("[!] No terms found. Exiting.")
        return

    for term in terms:
        term_id   = term["term_id"]
        term_name = term["term_name"]
        norm_term = normalize_term(term_name)
        print(f"\n[*] Term: {term_name} (id={term_id})")

        depts = get_depts(sess, term_id)
        if not depts:
            print("    No departments found.")
            continue
        print(f"    {len(depts)} departments")

        for dept in tqdm(depts, desc=f"  {term_name}"):
            dept_id   = dept["dept_id"]
            dept_code = dept["dept_code"]

            courses = get_courses(sess, dept_id)
            if not courses:
                continue

            dept_rows = 0
            for course in courses:
                course_id    = course["course_id"]
                course_num   = course["course_num"]
                course_title = course["course_title"]

                sections = get_sections(sess, course_id)
                if not sections:
                    continue

                for sec in sections:
                    section_id  = sec["section_id"]
                    section_num = sec["section_num"]
                    instructor  = sec["instructor"]

                    check_key = (norm_term, dept_code, fmt(course_num), fmt(section_num))
                    if check_key in done_keys:
                        continue

                    from urllib.parse import quote
                    source_url = f"{AJAX_URL}?l={quote('/college_section/'+section_id, safe='')}"

                    try:
                        mat_html = get_materials_html(sess, section_id)
                    except Exception as e:
                        tqdm.write(f"\n  [ERROR] {dept_code}/{course_num}/{section_num}: {e}")
                        tqdm.write("  [INFO] Refreshing session...")
                        try:
                            sess = refresh_session(sess)
                            mat_html = get_materials_html(sess, section_id)
                        except Exception as e2:
                            tqdm.write(f"  [ERROR] Retry failed: {e2}")
                            mat_html = ""

                    if not debug_saved and mat_html:
                        debug_path = os.path.join(OUTPUT_DIR, "debug_results.html")
                        with open(debug_path, "w", encoding="utf-8") as df:
                            df.write(mat_html)
                        tqdm.write(f"\n    [DEBUG] First materials response → debug_results.html")
                        debug_saved = True

                    rows = parse_materials(
                        mat_html, source_url, dept_code, course_num, course_title,
                        section_num, instructor, term_name, sess, isbn_cache,
                    )
                    for row in rows:
                        row["crawled_on"] = crawled_on
                        row["updated_on"] = crawled_on

                    append_csv(rows, CSV_PATH)
                    done_keys.add(check_key)
                    dept_rows  += len(rows)
                    total_rows += len(rows)

            if dept_rows:
                tqdm.write(f"    [{dept_code}] +{dept_rows} rows (total: {total_rows})")

    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE — {total_rows} rows written")
    print(f"CSV: {CSV_PATH}")
    if total_rows == 0:
        print("[!] No data written. Check debug_results.html for response sample.")

if __name__ == "__main__":
    scrape(fresh="--fresh" in sys.argv)
