#!/usr/bin/env python3

import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, quote

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

SCHOOL_NAME = "everett_community_college"
SCHOOL_ID = "3108881"
STORE_SLUG = "everettstore"
BASE_URL = "https://www.bkstr.com"
STORE_HOME = f"{BASE_URL}/{STORE_SLUG}/home"
SERVLET_BASE = f"{BASE_URL}/webapp/wcs/stores/servlet"
FLARESOLVERR_URL = "http://localhost:8191/v1"

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
]

REQUEST_DELAY = 0.5

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    f"{SCHOOL_NAME}__{SCHOOL_ID}__bks",
)
CSV_PATH = os.path.join(OUTPUT_DIR, f"{SCHOOL_NAME}__{SCHOOL_ID}__bks.csv")

FLARESOLVERR_SESSION = "everett_bkstr_scraper"

def flaresolverr_create_session():
    try:
        requests.post(FLARESOLVERR_URL, json={
            "cmd": "sessions.destroy",
            "session": FLARESOLVERR_SESSION,
        }, timeout=10)
    except Exception:
        pass
    resp = requests.post(FLARESOLVERR_URL, json={
        "cmd": "sessions.create",
        "session": FLARESOLVERR_SESSION,
    }, timeout=120)
    resp.raise_for_status()

def flaresolverr_destroy_session():
    try:
        requests.post(FLARESOLVERR_URL, json={
            "cmd": "sessions.destroy",
            "session": FLARESOLVERR_SESSION,
        }, timeout=10)
    except Exception:
        pass

def flaresolverr_get(url, max_timeout=60000):
    resp = requests.post(FLARESOLVERR_URL, json={
        "cmd": "request.get",
        "url": url,
        "session": FLARESOLVERR_SESSION,
        "maxTimeout": max_timeout,
    }, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"FlareSolverr error: {data}")

    sol = data["solution"]
    html = sol.get("response", "")
    ua = sol.get("userAgent", "")

    cookies = {}
    for c in sol.get("cookies", []):
        if c.get("name"):
            cookies[c["name"]] = c["value"]

    return html, cookies, ua

def create_session():
    print("[*] Bootstrapping session via FlareSolverr...")
    flaresolverr_create_session()
    html, cookies, ua = flaresolverr_get(STORE_HOME)

    sess = requests.Session()
    sess.cookies.update(cookies)
    sess.headers.update({
        "User-Agent": ua,
        "Referer": STORE_HOME,
        "Accept": "application/json, text/html, */*",
        "X-Requested-With": "XMLHttpRequest",
    })

    print(f"[*] Session ready. Cookies: {list(cookies.keys())}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    debug_path = os.path.join(OUTPUT_DIR, "debug_bootstrap.html")
    with open(debug_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"    Bootstrap HTML saved to {debug_path}")

    return sess, html

def refresh_session(sess):
    print("[*] Refreshing session via FlareSolverr...", flush=True)
    for attempt in range(5):
        try:
            flaresolverr_destroy_session()
            time.sleep(5 * (attempt + 1))
            return create_session()
        except Exception as e:
            print(f"  [WARN] Session refresh attempt {attempt + 1} failed: {e}", flush=True)
            if attempt == 4:
                raise

def is_cloudflare_block(text):
    if not text:
        return False
    lower = text[:1000].lower()
    return ("just a moment" in lower or "challenge-platform" in lower or
            "<title>attention" in lower)

def is_server_error(text):
    if not text:
        return False
    lower = text[:500].lower()
    return "server error" in lower or "502" in lower or "503" in lower

def discover_store_id(sess, bootstrap_html):
    print("[*] Discovering store ID...")

    patterns = [
        r'"storeId"\s*:\s*"?(\d+)"?',
        r"storeId[=:]\s*['\"]?(\d+)",
        r'data-store-id[="\s]+(\d+)',
        r'storeNumber["\s:=]+["\']?(\d+)',
    ]

    for pattern in patterns:
        m = re.search(pattern, bootstrap_html)
        if m:
            store_id = m.group(1)
            print(f"    Found store ID in HTML: {store_id}")
            cat_m = re.search(r'"catalogId"\s*:\s*"?(\d+)"?', bootstrap_html)
            catalog_id = cat_m.group(1) if cat_m else "10001"
            return store_id, catalog_id

    script_urls = re.findall(r'src=["\']([^"\']*(?:main|app|config)[^"\']*\.js[^"\']*)["\']',
                              bootstrap_html)
    for script_url in script_urls[:5]:
        if not script_url.startswith("http"):
            script_url = BASE_URL + "/" + script_url.lstrip("/")
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.get(script_url, timeout=30)
            if resp.status_code == 200:
                js_text = resp.text
                for pattern in patterns:
                    m = re.search(pattern, js_text)
                    if m:
                        store_id = m.group(1)
                        print(f"    Found store ID in JS bundle: {store_id}")
                        return store_id, "10001"
        except Exception:
            continue

    try:
        url = f"{SERVLET_BASE}/StoreCatalogDisplay?langId=-1&catalogId=10001&storeId=10001"
        time.sleep(REQUEST_DELAY)
        resp = sess.get(url, timeout=30)
        if resp.status_code == 200:
            for pattern in patterns:
                m = re.search(pattern, resp.text)
                if m:
                    store_id = m.group(1)
                    print(f"    Found store ID via StoreCatalogDisplay: {store_id}")
                    return store_id, "10001"
    except Exception as e:
        print(f"    StoreCatalogDisplay failed: {e}")

    raise RuntimeError(
        "Could not discover store ID. Check debug_bootstrap.html in output dir."
    )

def servlet_get(sess, params, retries=3):
    url = f"{SERVLET_BASE}/LocateCourseMaterialsServlet"
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.get(url, params=params, timeout=30)
            resp.raise_for_status()
            text = resp.text.strip()

            if is_cloudflare_block(text):
                raise RuntimeError("Cloudflare challenge detected")
            if is_server_error(text):
                raise RuntimeError("Server error (502/503)")

            if not text:
                return {}

            data = json.loads(text)
            return data
        except json.JSONDecodeError:
            if attempt < retries - 1:
                print(f"  [WARN] Non-JSON response (attempt {attempt + 1})")
                time.sleep(2 * (attempt + 1))
            else:
                print(f"  [ERROR] Non-JSON response: {text[:200]}")
                return {}
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] Servlet call failed (attempt {attempt + 1}): {e}")
                time.sleep(2 * (attempt + 1))
            else:
                raise
    return {}

def fetch_terms(sess, store_id, catalog_id):
    data = servlet_get(sess, {
        "requestType": "TERMS",
        "storeId": store_id,
        "catalogId": catalog_id,
        "langId": "-1",
        "demoKey": "d",
        "programId": "",
    })
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("data", data.get("terms", []))
    return []

def fetch_departments(sess, store_id, catalog_id, term_id):
    data = servlet_get(sess, {
        "requestType": "DEPARTMENTS",
        "storeId": store_id,
        "catalogId": catalog_id,
        "langId": "-1",
        "demoKey": "d",
        "programId": "",
        "termId": term_id,
    })
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("data", data.get("departments", []))
    return []

def fetch_courses(sess, store_id, catalog_id, term_id, dept_name):
    data = servlet_get(sess, {
        "requestType": "COURSES",
        "storeId": store_id,
        "catalogId": catalog_id,
        "langId": "-1",
        "demoKey": "d",
        "programId": "",
        "termId": term_id,
        "departmentName": dept_name,
    })
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("data", data.get("courses", []))
    return []

def fetch_sections(sess, store_id, catalog_id, term_id, dept_name, course_name):
    data = servlet_get(sess, {
        "requestType": "SECTIONS",
        "storeId": store_id,
        "catalogId": catalog_id,
        "langId": "-1",
        "demoKey": "d",
        "programId": "",
        "termId": term_id,
        "departmentName": dept_name,
        "courseName": course_name,
    })
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("data", data.get("sections", []))
    return []

def fetch_booklist(sess, store_id, term_id, dept_name, course_name, section_name):
    url = f"{SERVLET_BASE}/booklookServlet"
    params = {
        "bookstore_id-1": store_id,
        "term_id-1": term_id,
        "div-1": "",
        "dept-1": dept_name,
        "course-1": course_name,
        "section-1": section_name,
    }
    for attempt in range(3):
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.get(url, params=params, timeout=30)
            resp.raise_for_status()
            text = resp.text

            if is_cloudflare_block(text):
                raise RuntimeError("Cloudflare challenge detected")
            if is_server_error(text):
                raise RuntimeError("Server error (502/503)")

            return text
        except Exception as e:
            if attempt < 2:
                print(f"  [WARN] booklookServlet failed (attempt {attempt + 1}): {e}")
                time.sleep(2 * (attempt + 1))
            else:
                raise
    return ""

def parse_booklist_html(html_text, source_url, dept_code, course_code,
                         section_code, term_name):
    rows = []

    if not html_text or not html_text.strip():
        rows.append({
            "source_url": source_url,
            "department_code": dept_code,
            "course_code": course_code,
            "course_title": "",
            "section": section_code,
            "section_instructor": "",
            "term": normalize_term(term_name),
            "isbn": "",
            "title": "",
            "author": "",
            "material_adoption_code": "This course does not require any course materials",
        })
        return rows

    soup = BeautifulSoup(html_text, "html.parser")

    course_title = ""
    title_el = soup.select_one(".book-list-course-title, .course-info h3, .courseTitle")
    if title_el:
        course_title = title_el.get_text(strip=True)

    instructor = ""
    instr_el = soup.select_one(".instructor, .professorName, .book-list-instructor")
    if instr_el:
        instructor = instr_el.get_text(strip=True)

    book_items = soup.select(
        ".book-list-item, .cf-book, .material-group .material-item, "
        ".book_info, tr.book-row, .adoption-item"
    )

    if not book_items:
        script_tags = soup.select('script[type="application/json"], script[type="application/ld+json"]')
        for script in script_tags:
            try:
                jdata = json.loads(script.string)
                if isinstance(jdata, list):
                    for item in jdata:
                        if isinstance(item, dict) and ("isbn" in item or "ISBN" in item):
                            book_items.append(item)
            except (json.JSONDecodeError, TypeError):
                pass

    no_materials_patterns = [
        "no course materials",
        "no books required",
        "no textbooks",
        "materials have not been",
        "not yet posted",
    ]
    page_text = soup.get_text().lower()
    has_no_materials = any(p in page_text for p in no_materials_patterns)

    if not book_items and has_no_materials:
        rows.append({
            "source_url": source_url,
            "department_code": dept_code,
            "course_code": course_code,
            "course_title": course_title,
            "section": section_code,
            "section_instructor": instructor,
            "term": normalize_term(term_name),
            "isbn": "",
            "title": "",
            "author": "",
            "material_adoption_code": "This course does not require any course materials",
        })
        return rows

    if not book_items:
        book_items = soup.select("table tr")
        book_items = [tr for tr in book_items if tr.find("td")]

    for item in book_items:
        if isinstance(item, dict):
            isbn = str(item.get("isbn", item.get("ISBN", item.get("isbn13", "")))).replace("-", "").strip()
            title = str(item.get("title", item.get("bookTitle", "")))
            author = str(item.get("author", item.get("bookAuthor", "")))
            adoption = str(item.get("required", item.get("status", item.get("adoptionCode", ""))))
        else:
            isbn = ""
            title = ""
            author = ""
            adoption = ""

            isbn_el = item.select_one(".isbn, [data-isbn], .book-isbn")
            if isbn_el:
                isbn_text = isbn_el.get_text(strip=True)
                isbn_match = re.search(r'(\d[\d-]{9,})', isbn_text)
                if isbn_match:
                    isbn = isbn_match.group(1).replace("-", "")
            if not isbn:
                all_text = item.get_text()
                isbn_match = re.search(r'ISBN[:\s]*(\d[\d-]{9,})', all_text, re.I)
                if isbn_match:
                    isbn = isbn_match.group(1).replace("-", "")

            title_el = item.select_one(".book-title, .title, h4, .material-title, a.title")
            if title_el:
                title = title_el.get_text(strip=True)

            author_el = item.select_one(".book-author, .author, .material-author")
            if author_el:
                author_text = author_el.get_text(strip=True)
                author = re.sub(r'^(?:by|author:?)\s*', '', author_text, flags=re.I)

            adopt_el = item.select_one(".adoption-status, .required, .requirement, .adoption-code")
            if adopt_el:
                adoption = adopt_el.get_text(strip=True)
            if not adoption:
                item_text = item.get_text().lower()
                if "required" in item_text:
                    adoption = "Required"
                elif "recommended" in item_text:
                    adoption = "Recommended"
                elif "optional" in item_text:
                    adoption = "Optional"

        if adoption.lower() in ("true", "yes", "required"):
            adoption = "Required"
        elif adoption.lower() in ("false", "no", "recommended"):
            adoption = "Recommended"
        elif adoption.lower() in ("optional",):
            adoption = "Optional"

        if isbn or title:
            rows.append({
                "source_url": source_url,
                "department_code": dept_code,
                "course_code": course_code,
                "course_title": course_title,
                "section": section_code,
                "section_instructor": instructor,
                "term": normalize_term(term_name),
                "isbn": isbn,
                "title": title,
                "author": author,
                "material_adoption_code": adoption or "Required",
            })

    if not rows:
        rows.append({
            "source_url": source_url,
            "department_code": dept_code,
            "course_code": course_code,
            "course_title": course_title,
            "section": section_code,
            "section_instructor": instructor,
            "term": normalize_term(term_name),
            "isbn": "",
            "title": "",
            "author": "",
            "material_adoption_code": "This course does not require any course materials",
        })

    return rows

def get_field(obj, *keys, default=""):
    for key in keys:
        if key in obj:
            val = obj[key]
            if val is not None:
                return str(val)
    return default

def normalize_term(term_str):
    if not term_str:
        return ""
    return term_str.strip().upper()

def append_csv(rows, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    file_exists = os.path.exists(filepath) and os.path.getsize(filepath) > 0
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)

def get_scraped_departments(filepath):
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return set()
    scraped = set()
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dept = row.get("department_code", "").strip()
            term = row.get("term", "").strip()
            if dept:
                scraped.add((term, dept))
    return scraped

def scrape(fresh=False):
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run — deleted existing CSV.")

    done_depts = get_scraped_departments(CSV_PATH)
    if done_depts:
        print(f"[*] {len(done_depts)} (term, dept) combos already scraped.")
        print("[*] Will only scrape missing departments.")

    sess, bootstrap_html = create_session()

    store_id, catalog_id = discover_store_id(sess, bootstrap_html)
    print(f"[*] Store ID: {store_id}, Catalog ID: {catalog_id}")

    print("[*] Fetching terms...")
    terms = fetch_terms(sess, store_id, catalog_id)
    if not terms:
        print("[!] No terms found. Exiting.")
        flaresolverr_destroy_session()
        return

    print(f"    Found {len(terms)} terms:")
    for t in terms:
        term_id = get_field(t, "id", "termId", "term_id", "value")
        term_name = get_field(t, "name", "termName", "term_name", "label", "text")
        print(f"      {term_id}: {term_name}")

    total_rows = 0
    debug_dumped = False

    for term_obj in terms:
        term_id = get_field(term_obj, "id", "termId", "term_id", "value")
        term_name = get_field(term_obj, "name", "termName", "term_name", "label", "text")
        if not term_id:
            continue

        print(f"\n[*] Processing term: {term_name} ({term_id})")

        print("[*] Fetching departments...")
        departments = fetch_departments(sess, store_id, catalog_id, term_id)
        if not departments:
            print("    No departments found for this term.")
            continue

        print(f"    Found {len(departments)} departments")

        for dept_obj in tqdm(departments, desc=f"  {term_name}"):
            dept_name = get_field(dept_obj, "categoryName", "name", "departmentName",
                                  "label", "text", "value")
            dept_code = get_field(dept_obj, "code", "departmentCode", "abrev",
                                  default=dept_name)

            if not dept_name:
                continue

            if (normalize_term(term_name), dept_code) in done_depts:
                continue

            try:
                courses = fetch_courses(sess, store_id, catalog_id, term_id, dept_name)
            except Exception as e:
                print(f"\n  [ERROR] fetch_courses dept={dept_code}: {e}", flush=True)
                try:
                    sess, _ = refresh_session(sess)
                    courses = fetch_courses(sess, store_id, catalog_id, term_id, dept_name)
                except Exception as e2:
                    print(f"  [ERROR] Retry failed for dept={dept_code}: {e2}", flush=True)
                    continue

            if not courses:
                append_csv([{
                    "source_url": STORE_HOME,
                    "school_id": SCHOOL_ID,
                    "department_code": dept_code,
                    "course_code": "",
                    "course_title": "",
                    "section": "",
                    "section_instructor": "",
                    "term": normalize_term(term_name),
                    "isbn": "",
                    "title": "",
                    "author": "",
                    "material_adoption_code": "This course does not require any course materials",
                    "crawled_on": crawled_on,
                }], CSV_PATH)
                total_rows += 1
                continue

            dept_rows = 0

            for course_obj in courses:
                course_name = get_field(course_obj, "categoryName", "name", "courseName",
                                        "label", "text", "value")
                course_code = get_field(course_obj, "code", "courseCode",
                                        default=course_name)

                if not course_name:
                    continue

                try:
                    sections = fetch_sections(sess, store_id, catalog_id, term_id,
                                              dept_name, course_name)
                except Exception as e:
                    print(f"\n  [WARN] fetch_sections {dept_code}/{course_code}: {e}")
                    sections = []

                if not sections:
                    source_url = (f"{SERVLET_BASE}/booklookServlet?"
                                  f"bookstore_id-1={store_id}&term_id-1={term_id}"
                                  f"&dept-1={quote(dept_name)}&course-1={quote(course_name)}"
                                  f"&section-1=")
                    try:
                        bl_html = fetch_booklist(sess, store_id, term_id,
                                                 dept_name, course_name, "")
                    except Exception as e:
                        print(f"\n  [WARN] booklookServlet {dept_code}/{course_code}: {e}")
                        bl_html = ""

                    if not debug_dumped and bl_html:
                        debug_path = os.path.join(OUTPUT_DIR, "debug_booklist.html")
                        with open(debug_path, "w", encoding="utf-8") as df:
                            df.write(bl_html)
                        print(f"\n    [DEBUG] First booklist response saved to {debug_path}")
                        debug_dumped = True

                    rows = parse_booklist_html(bl_html, source_url, dept_code,
                                               course_code, "", term_name)
                    for row in rows:
                        row["school_id"] = SCHOOL_ID
                        row["crawled_on"] = crawled_on
                    if rows:
                        append_csv(rows, CSV_PATH)
                        dept_rows += len(rows)
                        total_rows += len(rows)
                else:
                    for sec_obj in sections:
                        sec_name = get_field(sec_obj, "categoryName", "name", "sectionName",
                                             "label", "text", "value")
                        if not sec_name:
                            continue

                        source_url = (f"{SERVLET_BASE}/booklookServlet?"
                                      f"bookstore_id-1={store_id}&term_id-1={term_id}"
                                      f"&dept-1={quote(dept_name)}&course-1={quote(course_name)}"
                                      f"&section-1={quote(sec_name)}")
                        try:
                            bl_html = fetch_booklist(sess, store_id, term_id,
                                                     dept_name, course_name, sec_name)
                        except Exception as e:
                            print(f"\n  [WARN] booklookServlet {dept_code}/{course_code}/{sec_name}: {e}")
                            bl_html = ""

                        if not debug_dumped and bl_html:
                            debug_path = os.path.join(OUTPUT_DIR, "debug_booklist.html")
                            with open(debug_path, "w", encoding="utf-8") as df:
                                df.write(bl_html)
                            print(f"\n    [DEBUG] First booklist response saved to {debug_path}")
                            debug_dumped = True

                        rows = parse_booklist_html(bl_html, source_url, dept_code,
                                                   course_code, sec_name, term_name)
                        for row in rows:
                            row["school_id"] = SCHOOL_ID
                            row["crawled_on"] = crawled_on
                        if rows:
                            append_csv(rows, CSV_PATH)
                            dept_rows += len(rows)
                            total_rows += len(rows)

            if dept_rows:
                tqdm.write(f"    [{dept_code}] +{dept_rows} rows (total: {total_rows})")

    flaresolverr_destroy_session()

    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE")
    print(f"{'='*60}")
    print(f"Total rows written: {total_rows}")
    print(f"CSV: {CSV_PATH}")

    if total_rows == 0:
        print("\n[!] No data collected. Check debug files in output directory.")
        print(f"    - {os.path.join(OUTPUT_DIR, 'debug_bootstrap.html')}")
        print(f"    - {os.path.join(OUTPUT_DIR, 'debug_booklist.html')}")

if __name__ == "__main__":
    fresh = "--fresh" in sys.argv
    scrape(fresh=fresh)
