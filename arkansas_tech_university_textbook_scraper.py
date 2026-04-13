import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlencode

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None

SCHOOL_NAME = "arkansas_tech_university"
SCHOOL_ID   = "2989257"
BASE_URL    = "https://theatubookstore.com"
STUDENT_URL = f"{BASE_URL}/student"

REQUEST_DELAY = 0.8

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

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

_OPT_VAL_RE = re.compile(r'value=\\"([^\\"]+)\\"')

_ISBN_RE = re.compile(r"97[89]\d{10}")

def encode_path(s):
    return quote(str(s), safe="")

def normalize_term(s):
    return re.sub(r"\s*\(.*?\)\s*", "", s or "").strip()

def fmt_code(code):
    code = (code or "").strip()
    return f"|{code}" if code and not code.startswith("|") else code

def bootstrap_session():
    print("[*] Bootstrapping session from /student …")
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
    })

    resp = sess.get(STUDENT_URL, timeout=30)
    resp.raise_for_status()
    html = resp.text

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, "debug_student.html"), "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"    Saved debug_student.html ({len(html):,} bytes)")

    soup = BeautifulSoup(html, "lxml")

    school_sel = soup.find("select", {"id": "lookup_school_id"})
    schools = []
    if school_sel:
        for opt in school_sel.find_all("option"):
            v = opt.get("value", "").strip()
            if v:
                schools.append({"value": v, "text": opt.get_text(strip=True)})
    if not schools:
        schools = [
            {"value": "ATU-Main Campus",  "text": "ATU-Main Campus"},
            {"value": "ATU-Ozark Campus", "text": "ATU-Ozark Campus"},
        ]
        print("    [WARN] School select not found — using hard-coded fallback.")
    else:
        print(f"    Schools: {[s['value'] for s in schools]}")

    term_sel = soup.find("select", {"id": "lookup_term_0"})
    terms = []
    if term_sel:
        for opt in term_sel.find_all("option"):
            v = opt.get("value", "").strip()
            t = opt.get_text(strip=True)
            if v and t:
                terms.append({"value": v, "text": normalize_term(t)})
    if not terms:
        terms = [{"value": "SPRING 2026", "text": "SPRING 2026"}]
        print("    [WARN] Term select not found — using hard-coded 'SPRING 2026'.")
    else:
        print(f"    Terms: {[t['text'] for t in terms]}")

    dept_sel = soup.find("select", {"id": "lookup_department_0"})
    departments = []
    if dept_sel:
        for opt in dept_sel.find_all("option"):
            v = opt.get("value", "").strip()
            if v:
                departments.append(v)
    print(f"    Departments: {len(departments)} found"
          + (f", first 5: {departments[:5]}" if departments else ""))

    return sess, schools, terms, departments

def refresh_session(old_sess):
    print("[*] Refreshing session …")
    for attempt in range(3):
        try:
            time.sleep(5 * (attempt + 1))
            return bootstrap_session()
        except Exception as exc:
            print(f"  [WARN] Refresh attempt {attempt + 1} failed: {exc}")
            if attempt == 2:
                raise

def _ajax_get(sess, url, retries=3):
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.get(url, headers={
                "Accept": "text/html, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": STUDENT_URL,
            }, timeout=30)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (204, 422):
                return ""
            if resp.status_code >= 500 and attempt < retries - 1:
                print(f"  [WARN] {resp.status_code} for {url} (attempt {attempt + 1})")
                time.sleep(3 * (attempt + 1))
                continue
            return ""
        except Exception as exc:
            if attempt < retries - 1:
                print(f"  [WARN] _ajax_get attempt {attempt + 1} {url}: {exc}")
                time.sleep(2 * (attempt + 1))
            else:
                print(f"  [ERROR] _ajax_get {url}: {exc}")
                return ""
    return ""

def parse_js_options(js_text):
    return _OPT_VAL_RE.findall(js_text)

def fetch_courses(sess, school_val, term_val, dept):
    url = (f"{BASE_URL}/course_lookup/{encode_path(school_val)}"
           f"/courses/{encode_path(term_val)}/{dept}/0")
    return parse_js_options(_ajax_get(sess, url))

def fetch_sections(sess, school_val, term_val, dept, course):
    url = (f"{BASE_URL}/course_lookup/{encode_path(school_val)}"
           f"/sections/{encode_path(term_val)}/{dept}/{course}/0")
    return parse_js_options(_ajax_get(sess, url))

def fetch_materials(sess, school_val, term_val, dept, course, section,
                    debug_saved, retries=3):
    url = f"{BASE_URL}/courselisting/index/loadMaterials"
    courses_json = json.dumps([{
        "school":   school_val,
        "term":     term_val,
        "dept":     dept,
        "course":   course,
        "section":  section,
    }])
    params = [
        ("school[id]",    school_val),
        ("school[0]",     school_val),
        ("term[0]",       term_val),
        ("department[0]", dept),
        ("course[0]",     course),
        ("section[0]",    section),
        ("courses",       courses_json),
        ("commit",        "Lookup Courses"),
    ]

    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.get(url, params=params, headers={
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Referer": STUDENT_URL,
            }, timeout=45)

            if resp.status_code == 200:
                if not debug_saved:
                    with open(os.path.join(OUTPUT_DIR, "debug_materials.html"),
                              "w", encoding="utf-8") as fh:
                        fh.write(resp.text)
                    print("    [DEBUG] First materials response saved → debug_materials.html")
                    debug_saved = True
                return resp.text, debug_saved

            if resp.status_code >= 500 and attempt < retries - 1:
                print(f"  [WARN] materials HTTP {resp.status_code} "
                      f"{dept}/{course}/{section} (attempt {attempt + 1})")
                time.sleep(3 * (attempt + 1))
                continue

            print(f"  [WARN] materials HTTP {resp.status_code} {dept}/{course}/{section}")
            return "", debug_saved

        except Exception as exc:
            if attempt < retries - 1:
                print(f"  [WARN] fetch_materials attempt {attempt + 1}: {exc}")
                time.sleep(2 * (attempt + 1))
            else:
                print(f"  [ERROR] fetch_materials {dept}/{course}/{section}: {exc}")
                return "", debug_saved
    return "", debug_saved

_ADOPTION_NORM = {
    "required":               "Required",
    "optional":               "Optional",
    "recommended":            "Recommended",
    "choice":                 "Choice",
    "instructor recommended": "Recommended",
}

def _normalize_adoption(raw_text):
    key = raw_text.strip().lower()
    return _ADOPTION_NORM.get(key, raw_text.strip().capitalize())

def parse_materials(html, source_url, term_val, dept, course, section):
    base = {
        "source_url":      source_url,
        "department_code": dept,
        "course_code":     fmt_code(course),
        "section":         fmt_code(section),
        "term":            normalize_term(term_val),
    }
    if not html:
        return [{
            **base,
            "course_title": "", "section_instructor": "",
            "isbn": "", "title": "", "author": "",
            "material_adoption_code": "This course does not require any course materials",
        }]

    soup = BeautifulSoup(html, "lxml")

    flash = soup.find(class_="flash")
    if flash and "not found" in flash.get_text().lower():
        tqdm.write(f"    [WARN] Flash error for {dept}/{course}/{section}: "
                   f"{flash.get_text(strip=True)[:80]}")

    cw = soup.find(class_="course-wrapper")
    section_el = cw.find("section", class_="course") if cw else None

    course_title = ""
    section_instructor = ""

    if section_el:
        h2 = section_el.find("h2", class_="course-name")
        course_title = h2.get_text(strip=True) if h2 else ""

        info_div = section_el.find(class_="course-info")
        if info_div:
            info_text = info_div.get_text(" ", strip=True)
            last_seg = info_text.split(" - ")[-1].strip()
            sec_clean = section.lstrip("|").strip()
            if sec_clean and last_seg.startswith(sec_clean):
                section_instructor = last_seg[len(sec_clean):].strip()
            else:
                section_instructor = last_seg

    def _no_material():
        return {
            **base,
            "course_title":          course_title,
            "section_instructor":    section_instructor,
            "isbn":                  "",
            "title":                 "",
            "author":                "",
            "material_adoption_code": "This course does not require any course materials",
        }

    if not section_el:
        return [_no_material()]

    rows = []
    current_adoption = "Required"

    for child in section_el.children:
        if not hasattr(child, "name") or child.name is None:
            continue

        if child.name == "h5" and "course-requriement-text" in child.get("class", []):
            b = child.find("b")
            if b:
                current_adoption = _normalize_adoption(b.get_text(strip=True))
            continue

        if child.name == "div":
            classes = child.get("class", [])

            h5 = child.find("h5", class_="course-requriement-text")
            if h5:
                b = h5.find("b")
                if b:
                    current_adoption = _normalize_adoption(b.get_text(strip=True))

            if "item-row" in classes:
                row = _parse_item_row(child, base, course_title,
                                      section_instructor, current_adoption)
                if row:
                    rows.append(row)
            else:

                for item in child.find_all("div", class_="item-row", recursive=False):
                    row = _parse_item_row(item, base, course_title,
                                          section_instructor, current_adoption)
                    if row:
                        rows.append(row)

    if not rows:

        return [_no_material()]

    return rows

def _parse_item_row(item, base, course_title, section_instructor, adoption):

    h3 = item.find("h3")
    title = h3.get_text(strip=True) if h3 else ""

    isbn = ""
    for attr_div in item.find_all(class_="standard-attribute"):
        strong = attr_div.find("strong")
        if strong and "isbn" in strong.get_text().lower():
            raw = attr_div.get_text(" ", strip=True)
            m = _ISBN_RE.search(re.sub(r"[-\s]", "", raw))
            if m:
                isbn = m.group(0)
                break

    if not isbn and not title:
        return None

    author = ""
    for attr_div in item.find_all(class_="standard-attribute"):
        strong = attr_div.find("strong")
        if strong and "author" in strong.get_text().lower():
            author = attr_div.get_text(" ", strip=True)
            author = re.sub(r"(?i)\bauthor\s*:?\s*", "", author).strip()
            break

    return {
        **base,
        "course_title":          course_title,
        "section_instructor":    section_instructor,
        "isbn":                  isbn,
        "title":                 title,
        "author":                author,
        "material_adoption_code": adoption,
    }

def append_csv(rows, filepath, crawled_on):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    new_file = not os.path.exists(filepath) or os.path.getsize(filepath) == 0
    with open(filepath, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        if new_file:
            writer.writeheader()
        for row in rows:
            row.setdefault("school_id",  SCHOOL_ID)
            row.setdefault("crawled_on", crawled_on)
            row.setdefault("updated_on", crawled_on)
            writer.writerow(row)

def get_scraped_keys(filepath):
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return set()
    with open(filepath, "r", encoding="utf-8") as fh:
        return {
            (r.get("term", ""), r.get("department_code", ""),
             r.get("course_code", ""), r.get("section", ""))
            for r in csv.DictReader(fh)
        }

def scrape(fresh=False):
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run — deleted existing CSV.")

    done_keys = get_scraped_keys(CSV_PATH)
    if done_keys:
        print(f"[*] {len(done_keys)} combos already scraped, resuming.")

    sess, schools, terms, departments = bootstrap_session()

    if not schools or not terms or not departments:
        print("[!] Missing schools/terms/departments — check debug_student.html. Exiting.")
        return

    total_rows  = 0
    debug_saved = False

    for school in schools:
        school_val = school["value"]
        print(f"\n{'='*60}")
        print(f"[*] School: {school_val}")

        for term in terms:
            term_val  = term["value"]
            term_text = normalize_term(term["text"])
            print(f"\n[*]   Term: {term_text}")

            for dept in tqdm(departments, desc=f"  {school_val[:18]}/{term_text[:10]}"):
                courses = fetch_courses(sess, school_val, term_val, dept)
                if not courses:
                    continue

                for course in courses:
                    sections = fetch_sections(sess, school_val, term_val, dept, course)
                    if not sections:
                        sections = [""]

                    for section in sections:
                        check_key = (term_text, dept,
                                     fmt_code(course), fmt_code(section))
                        if check_key in done_keys:
                            continue

                        source_url = (
                            f"{BASE_URL}/courselisting/index/loadMaterials?"
                            + urlencode([
                                ("school[id]",    school_val),
                                ("school[0]",     school_val),
                                ("term[0]",       term_val),
                                ("department[0]", dept),
                                ("course[0]",     course),
                                ("section[0]",    section),
                                ("courses",       json.dumps([{
                                    "school":  school_val,
                                    "term":    term_val,
                                    "dept":    dept,
                                    "course":  course,
                                    "section": section,
                                }])),
                                ("commit",        "Lookup Courses"),
                            ])
                        )

                        html, debug_saved = fetch_materials(
                            sess, school_val, term_val, dept, course, section,
                            debug_saved,
                        )

                        if not html:
                            tqdm.write(f"  [WARN] Empty response — "
                                       f"refreshing session for {dept}/{course}/{section} …")
                            try:
                                sess, schools, terms, departments = refresh_session(sess)
                                html, debug_saved = fetch_materials(
                                    sess, school_val, term_val, dept, course, section,
                                    debug_saved,
                                )
                            except Exception as exc:
                                tqdm.write(f"  [ERROR] Session refresh failed: {exc}")

                        rows = parse_materials(
                            html, source_url, term_val, dept, course, section
                        )
                        for row in rows:
                            row["school_id"]  = SCHOOL_ID
                            row["crawled_on"] = crawled_on
                            row["updated_on"] = crawled_on

                        append_csv(rows, CSV_PATH, crawled_on)
                        total_rows += len(rows)
                        done_keys.add(check_key)

    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE — {total_rows} rows written")
    print(f"CSV: {CSV_PATH}")
    if total_rows == 0:
        print("[!] Zero rows. Inspect debug_student.html and debug_materials.html.")

if __name__ == "__main__":
    scrape(fresh="--fresh" in sys.argv)
