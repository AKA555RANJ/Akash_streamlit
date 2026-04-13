import csv
import os
import re
import sys
import time
import warnings
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from tqdm import tqdm

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None

SCHOOL_NAME = "colgate_university"
SCHOOL_ID   = "3067194"
BASE_URL    = "https://www.colgatebookstore.com"

BATCH_SIZE    = 15
REQUEST_DELAY = 1.0

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

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

def normalize_term(s):
    s = (s or "").strip()
    s = re.sub(r"(?i)^colgate\s+university\s*[-\u2013]\s*", "", s).strip()
    s = re.sub(r"\s*\(.*?\)\s*", " ", s).strip()
    s = re.sub(r"(?i)\s+of\s+", " ", s).strip()
    return s.upper()

def bootstrap():
    print("[*] Bootstrapping session...")
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": BASE_URL + "/buy_textbooks.asp",
    })

    resp = sess.get(BASE_URL + "/buy_textbooks.asp", timeout=30)
    resp.raise_for_status()
    html = resp.text

    csrf_token = ""
    m = re.search(r'name="__CSRFToken"\s+id="__CSRFToken"\s+value="([^"]+)"', html)
    if m:
        csrf_token = m.group(1)
        print(f"[*] CSRF token: {csrf_token[:20]}...")
    else:
        print("[WARN] __CSRFToken not found — POST may fail")

    soup = BeautifulSoup(html, "html.parser")
    term_select = soup.find("select", {"id": "fTerm"})
    if not term_select:
        raise RuntimeError("Term select not found in buy_textbooks.asp")

    campus_id = term_id = term_name = ""
    for opt in term_select.find_all("option"):
        val = opt.get("value", "")
        if "|" not in val:
            continue
        parts = val.split("|", 1)
        if parts[0] == "0":
            continue
        campus_id = parts[0]
        term_id   = parts[1]
        term_name = normalize_term(opt.get_text(strip=True))
        print(f"[*] Term: '{term_name}' (campus={campus_id}, term={term_id})")
        break

    if not term_id:
        raise RuntimeError("No active term found in buy_textbooks.asp")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, "debug_bootstrap.html"), "w", encoding="utf-8") as f:
        f.write(html)

    print("[*] Session ready.")
    return sess, csrf_token, campus_id, term_id, term_name

def re_bootstrap(old_sess):
    print("[*] Re-bootstrapping to refresh CSRF token...", flush=True)
    for attempt in range(3):
        try:
            time.sleep(3 * (attempt + 1))
            return bootstrap()
        except Exception as e:
            print(f"  [WARN] Re-bootstrap attempt {attempt + 1} failed: {e}", flush=True)
            if attempt == 2:
                raise

def is_xml_error(text):
    if not text:
        return True
    lower = text[:500].lower()
    return (
        "error.asp" in lower
        or "object moved" in lower
        or "just a moment" in lower
        or ("<!doctype" in lower[:100] and
            "<departments" not in text[:500] and
            "<courses"     not in text[:500] and
            "<sections"    not in text[:500])
    )

def is_post_error(text):
    if not text or len(text) < 200:
        return True
    lower = text[:1000].lower()
    return (
        "object moved" in lower
        or "just a moment" in lower
        or "challenge-platform" in lower
        or ("<title>error" in lower)
        or ("error.asp" in lower and "course-bookdisplay" not in lower)
    )

def xml_get(sess, params, retries=3):
    url = BASE_URL + "/textbooks_xml.asp"
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.get(url, params=params, timeout=30)
            resp.raise_for_status()
            text = resp.text.strip()

            if is_xml_error(text):
                raise RuntimeError(f"Error/redirect response from textbooks_xml.asp: {text[:200]}")

            return BeautifulSoup(text, "html.parser")
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] xml_get attempt {attempt + 1}: {e}")
                time.sleep(2 * (attempt + 1))
            else:
                raise
    return BeautifulSoup("", "html.parser")

def fetch_departments(sess, campus_id, term_id):
    params = {"control": "campus", "campus": campus_id, "term": term_id}
    soup = xml_get(sess, params)
    return [
        {
            "dept_id":   dept.get("id", ""),
            "dept_code": dept.get("abrev", ""),
            "dept_name": dept.get("name", ""),
        }
        for dept in soup.find_all("department")
    ]

def fetch_courses(sess, dept_id, term_id):
    params = {"control": "department", "dept": dept_id, "term": term_id}
    soup = xml_get(sess, params)
    return [
        {
            "course_id":   course.get("id", ""),
            "course_name": course.get("name", ""),
        }
        for course in soup.find_all("course")
    ]

def fetch_sections(sess, course_id, term_id):
    params = {"control": "course", "course": course_id, "term": term_id}
    soup = xml_get(sess, params)
    return [
        {
            "section_id":   sec.get("id", ""),
            "section_name": sec.get("name", ""),
            "instructor":   sec.get("instructor", ""),
        }
        for sec in soup.find_all("section")
    ]

def fetch_textbooks(sess, section_ids, csrf_token, campus_id, term_id):
    url = BASE_URL + "/textbook_express.asp?mode=2&step=2"
    data = {
        "sectionIds":     ",".join(str(sid) for sid in section_ids),
        "selTerm":        f"{campus_id}|{term_id}",
        "__CSRFToken":    csrf_token,
        "tbe-block-mode": "0",
    }
    time.sleep(REQUEST_DELAY)
    resp = sess.post(url, data=data, timeout=60)
    resp.raise_for_status()
    text = resp.text
    if is_post_error(text):
        raise RuntimeError(f"Error/redirect response from textbook_express.asp: {text[:300]}")
    return text

def _is_ebook_note(title_text):
    return bool(re.search(
        r"\bebook\b|\bwill be charged\b|\bcharged to\b|\bdigital\b",
        title_text, re.I,
    ))

def fmt_code(code):
    code = (code or "").strip()
    return f"|{code}" if code and not code.startswith("|") else code

def parse_textbook_html(html, section_meta, term_name):
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen_keys = set()

    section_headers = [
        h3 for h3 in soup.find_all("h3")
        if h3.find("span", id="course-bookdisplay-coursename")
    ]

    for h3 in section_headers:
        dept_code = course_code = section_name = instructor = ""

        header_span = h3.find("span", id="course-bookdisplay-coursename")
        if header_span:
            header_text = header_span.get_text(strip=True)
            m = re.match(
                r"(.+?)\s*-\s*(\S+),\s*section\s+(\S+)\s*(?:\((.+?)\))?",
                header_text,
            )
            if m:
                dept_code    = m.group(1).strip()
                course_code  = fmt_code(m.group(2).strip())
                section_name = fmt_code(m.group(3).strip())
                instructor   = m.group(4).strip() if m.group(4) else ""

        if not dept_code:
            di = h3.find_previous("input", {"name": "dept_name"})
            ci = h3.find_previous("input", {"name": "course_name"})
            si = h3.find_previous("input", {"name": "section_name"})
            if di:
                dept_code    = di.get("value", "")
            if ci:
                course_code  = fmt_code(ci.get("value", ""))
            if si:
                section_name = fmt_code(si.get("value", ""))

        dedup_key = (dept_code, course_code, section_name)
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        if not instructor:
            for sm in section_meta.values():
                if sm["dept_code"] == dept_code and sm["section"] == section_name:
                    instructor = sm.get("instructor", "")
                    break

        base = {
            "department_code":  dept_code,
            "course_code":      course_code,
            "course_title":     "",
            "section":          section_name,
            "section_instructor": instructor,
            "term":             term_name,
        }

        table = h3.find_next_sibling("table", id=re.compile(r"^section-\d+"))
        if not table:
            table = h3.find_next("table", id=re.compile(r"^section-\d+"))

        book_rows = table.find_all("tr", class_=re.compile(r"\bbook\b")) if table else []

        if not book_rows:
            results.append({
                **base,
                "isbn": "", "title": "", "author": "",
                "material_adoption_code": "This course does not require any course materials",
            })
            continue

        section_books = []
        for row in book_rows:
            title_el  = row.find("span", class_="book-title")
            author_el = row.find("span", class_="book-author")
            isbn_el   = row.find("span", class_="isbn")
            req_el    = row.find("p", class_="book-req")

            raw_title  = title_el.get_text(strip=True)  if title_el  else ""
            raw_author = author_el.get_text(strip=True) if author_el else ""
            isbn       = isbn_el.get_text(strip=True).replace("-", "") if isbn_el else ""
            adoption   = req_el.get_text(strip=True).capitalize()      if req_el  else ""

            if _is_ebook_note(raw_title):
                title  = ""
                author = raw_author
            else:
                title  = raw_title
                author = raw_author

            if re.search(r"see instructor|not a book|no text required", title, re.I):
                continue

            if title or isbn:
                section_books.append({
                    **base,
                    "isbn": isbn, "title": title, "author": author,
                    "material_adoption_code": adoption,
                })

        if section_books:
            results.extend(section_books)
        else:
            results.append({
                **base,
                "isbn": "", "title": "", "author": "",
                "material_adoption_code": "This course does not require any course materials",
            })

    if not results:
        page_text = soup.get_text(" ", strip=True).lower()
        no_mat = ("no course materials" in page_text or
                  "not require" in page_text or
                  "no textbook" in page_text or
                  "no books" in page_text)
        for sid, meta in section_meta.items():
            results.append({
                "department_code":    meta["dept_code"],
                "course_code":        meta["course_code"],
                "course_title":       "",
                "section":            meta["section"],
                "section_instructor": meta["instructor"],
                "term":               term_name,
                "isbn": "", "title": "", "author": "",
                "material_adoption_code": (
                    "This course does not require any course materials"
                    if no_mat else ""
                ),
            })

    return results

def append_csv(rows, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    file_exists = os.path.exists(filepath) and os.path.getsize(filepath) > 0
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
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

def scrape(fresh=False):
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run — deleted existing CSV.")

    done_keys = get_scraped_keys(CSV_PATH)
    if done_keys:
        print(f"[*] {len(done_keys)} combos already scraped, resuming.")

    sess, csrf_token, campus_id, term_id, term_name = bootstrap()
    source_url = BASE_URL + "/buy_textbooks.asp"

    print("[*] Fetching departments...")
    depts = fetch_departments(sess, campus_id, term_id)
    print(f"    Found {len(depts)} departments")
    if not depts:
        print("[!] No departments found. Exiting.")
        return

    total_rows    = 0
    debug_dumped  = False
    all_dept_codes = {d["dept_code"] for d in depts}

    for dept in tqdm(depts, desc="Departments"):
        dept_id   = dept["dept_id"]
        dept_code = dept["dept_code"]

        try:
            courses = fetch_courses(sess, dept_id, term_id)
        except Exception as e:
            tqdm.write(f"\n  [ERROR] fetch_courses dept={dept_code}: {e}")
            try:
                sess, csrf_token, campus_id, term_id, term_name = re_bootstrap(sess)
                courses = fetch_courses(sess, dept_id, term_id)
            except Exception as e2:
                tqdm.write(f"  [ERROR] Retry failed for dept={dept_code}: {e2}")
                continue

        if not courses:
            append_csv([{
                "source_url": source_url, "school_id": SCHOOL_ID,
                "department_code": dept_code, "course_code": "",
                "course_title": "", "section": "", "section_instructor": "",
                "term": term_name, "isbn": "", "title": "", "author": "",
                "material_adoption_code": "No courses found for this department",
                "crawled_on": crawled_on, "updated_on": crawled_on,
            }], CSV_PATH)
            total_rows += 1
            continue

        all_section_ids = []
        section_meta    = {}

        for course in courses:
            course_name = course["course_name"]
            course_code = fmt_code(course_name)

            try:
                sections = fetch_sections(sess, course["course_id"], term_id)
            except Exception as e:
                tqdm.write(f"\n  [ERROR] fetch_sections {dept_code} {course_name}: {e}")
                continue

            for sec in sections:
                section_name = fmt_code(sec["section_name"])
                check_key    = (term_name, dept_code, course_code, section_name)
                if check_key in done_keys:
                    continue
                sid = sec["section_id"]
                all_section_ids.append(sid)
                section_meta[sid] = {
                    "dept_code":  dept_code,
                    "course_code": course_code,
                    "section":    section_name,
                    "instructor": sec["instructor"],
                }

        if not all_section_ids:
            continue

        batches = [
            all_section_ids[i:i + BATCH_SIZE]
            for i in range(0, len(all_section_ids), BATCH_SIZE)
        ]

        dept_rows = 0
        for batch_idx, batch in enumerate(batches):
            for attempt in range(3):
                try:
                    html = fetch_textbooks(sess, batch, csrf_token, campus_id, term_id)

                    if not debug_dumped:
                        debug_path = os.path.join(OUTPUT_DIR, "debug_textbook_express.html")
                        os.makedirs(OUTPUT_DIR, exist_ok=True)
                        with open(debug_path, "w", encoding="utf-8") as df:
                            df.write(html)
                        tqdm.write(f"\n    [DEBUG] First POST HTML dumped to {debug_path}")
                        debug_dumped = True

                    batch_meta = {sid: section_meta[sid] for sid in batch if sid in section_meta}
                    materials  = parse_textbook_html(html, batch_meta, term_name)

                    rows = []
                    for row in materials:
                        row["source_url"]  = source_url
                        row["school_id"]   = SCHOOL_ID
                        row["crawled_on"]  = crawled_on
                        row["updated_on"]  = crawled_on
                        rows.append(row)

                    if rows:
                        append_csv(rows, CSV_PATH)
                        dept_rows  += len(rows)
                        total_rows += len(rows)

                    break

                except Exception as e:
                    tqdm.write(f"\n  [!] Batch {batch_idx} attempt {attempt + 1} failed: {e}")
                    if attempt < 2:
                        sess, csrf_token, campus_id, term_id, term_name = re_bootstrap(sess)
                    else:
                        tqdm.write(f"  [!] SKIPPING batch {batch_idx} for dept={dept_code}")

        tqdm.write(f"    [{dept_code}] +{dept_rows} rows (total: {total_rows})")

    print(f"\n{'='*60}")
    print("SCRAPE COMPLETE")
    print(f"{'='*60}")
    print(f"Total rows written : {total_rows}")
    print(f"CSV                : {CSV_PATH}")

    final_depts = {
        row.get("department_code", "")
        for row in (
            csv.DictReader(open(CSV_PATH, encoding="utf-8"))
            if os.path.exists(CSV_PATH) else []
        )
    }
    missing = all_dept_codes - final_depts
    if missing:
        print(f"\n[!] MISSING {len(missing)} departments: {sorted(missing)}")
        print("  Re-run without --fresh to scrape only these.")
    else:
        print(f"\n[OK] All {len(all_dept_codes)} departments scraped successfully!")

if __name__ == "__main__":

    scrape(fresh="--fresh" in sys.argv)
