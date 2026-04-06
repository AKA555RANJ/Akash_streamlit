
import csv
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from tqdm import tqdm

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

SCHOOL_NAME = "maryville_university_of_saint_louis"
SCHOOL_ID = "3050199"
BASE_URL = "https://activation.maryville.edu/course-materials"
PROXY = "http://mtiqarye-rotate:8mqrpvby67qp@p.webshare.io:80/"
REQUEST_DELAY = 0.5

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

SOURCE_URL = BASE_URL + "/"

PROXIES = {
    "http": PROXY,
    "https": PROXY,
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BASE_URL + "/",
}

def create_session():
    sess = requests.Session()
    sess.headers.update(HEADERS)
    sess.proxies.update(PROXIES)
    return sess

def normalize_term(raw):
    """Convert "26/SP", "26/SP1", "26/FA", "26/SU" to readable strings."""
    m = re.match(r'(\d{2})/([A-Z]+)(\d*)', raw.strip())
    if not m:
        return raw.strip()
    yr, sem, session = m.groups()
    name_map = {"SP": "SPRING", "FA": "FALL", "SU": "SUMMER", "WIN": "WINTER"}
    name = name_map.get(sem, sem)
    result = f"{name} {yr}"
    if session:
        result += f" SESSION {session}"
    return result

def fetch_prefixes(sess, retries=3):
    """GET home page and extract all department prefixes."""
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.get(BASE_URL + "/", timeout=30, verify=False)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            soup = BeautifulSoup(resp.text, "html.parser")
            opts = soup.find_all("option", class_="pick-px")
            return [o.get("value", "").strip() for o in opts if o.get("value", "").strip()]
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] fetch_prefixes attempt {attempt + 1} failed: {e}", flush=True)
                time.sleep(2 * (attempt + 1))
            else:
                raise
    return []

def fetch_course_numbers(sess, prefix, retries=3):
    """POST pick_course-number.php → list of course number strings."""
    url = BASE_URL + "/asynch/pick_course-number.php"
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.post(url, data={"prefix": prefix}, timeout=30, verify=False)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            soup = BeautifulSoup(resp.text, "html.parser")
            opts = soup.find_all("option", class_="pick-cn")
            return [o.get("value", "").strip() for o in opts if o.get("value", "").strip()]
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] fetch_course_numbers prefix={prefix} attempt {attempt + 1}: {e}", flush=True)
                time.sleep(2 * (attempt + 1))
            else:
                print(f"  [ERROR] fetch_course_numbers prefix={prefix}: {e}", flush=True)
    return []

def fetch_sections(sess, prefix, cn, retries=3):
    """POST pick_course-section.php → list of section dicts."""
    url = BASE_URL + "/asynch/pick_course-section.php"
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.post(url, data={"cn": cn, "prefix": prefix}, timeout=30, verify=False)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return parse_section_options(resp.text, prefix, cn)
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] fetch_sections {prefix} {cn} attempt {attempt + 1}: {e}", flush=True)
                time.sleep(2 * (attempt + 1))
            else:
                print(f"  [ERROR] fetch_sections {prefix} {cn}: {e}", flush=True)
    return []

def parse_section_options(html, prefix, cn):
    """
    Parse section <option> elements.
    Option text format: "{COURSE_TITLE} {SECTION_CODE} {TERM_CODE}"
    Returns list of dicts: {sct_val, course_title, term_raw, term}
    """
    soup = BeautifulSoup(html, "html.parser")
    opts = soup.find_all("option", class_="pick-sct")
    results = []
    for opt in opts:
        sct_val = opt.get("value", "").strip()
        if not sct_val:
            continue
        full_text = opt.get_text(strip=True)
        tokens = full_text.split()
        if len(tokens) < 2:
            results.append({
                "sct_val": sct_val,
                "course_title": full_text,
                "term_raw": "",
                "term": "",
            })
            continue

        term_raw = tokens[-1]
        suffix = f" {sct_val} {term_raw}"
        if full_text.endswith(suffix):
            course_title = full_text[: -len(suffix)].strip()
        else:
            course_title = " ".join(tokens[:-2]).strip()

        results.append({
            "sct_val": sct_val,
            "course_title": course_title,
            "term_raw": term_raw,
            "term": normalize_term(term_raw),
        })
    return results

def fetch_books(sess, prefix, cn, sct, retries=3):
    """POST show-books.php → raw HTML fragment."""
    url = BASE_URL + "/asynch/show-books.php"
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = sess.post(url, data={"cn": cn, "prefix": prefix, "sct": sct}, timeout=30, verify=False)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return resp.text
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [WARN] fetch_books {prefix} {cn} {sct} attempt {attempt + 1}: {e}", flush=True)
                time.sleep(2 * (attempt + 1))
            else:
                print(f"  [ERROR] fetch_books {prefix} {cn} {sct}: {e}", flush=True)
    return ""

def clean_text(text):
    """Replace Unicode replacement character (U+FFFD) with registered trademark ® where applicable."""
    return text.replace("\ufffd", "\u00ae")

def parse_books(html, prefix, cn, section_info, crawled_on):
    """
    Parse show-books.php HTML fragment.

    Li structure:
        Title, <em>edition</em><br>
        <em>Publisher</em><br>
        <em>Author</em><br>
        ISBN: 9780000000000<br>
        MATERIAL TYPE<br>
        <a ...>Library Material</a>
    """
    html = clean_text(html)
    soup = BeautifulSoup(html, "html.parser")
    ul = soup.find("ul")

    dept_code = prefix
    course_code = f"|{cn}"
    section_val = f"|{section_info['sct_val']}"
    course_title = section_info["course_title"]
    term = section_info["term"]

    base_row = {
        "source_url": SOURCE_URL,
        "school_id": SCHOOL_ID,
        "department_code": dept_code,
        "course_code": course_code,
        "course_title": course_title,
        "section": section_val,
        "section_instructor": "",
        "term": term,
        "crawled_on": crawled_on,
        "updated_on": crawled_on,
    }

    if not ul or not ul.find("li"):
        row = dict(base_row)
        row.update({"isbn": "", "title": "", "author": "", "material_adoption_code": ""})
        return [row]

    results = []
    seen_isbns = set()

    for li in ul.find_all("li"):
        ems = li.find_all("em")
        edition = ems[0].get_text(strip=True) if len(ems) > 0 else ""
        author = ems[2].get_text(strip=True) if len(ems) > 2 else (
            ems[1].get_text(strip=True) if len(ems) > 1 else ""
        )

        raw_title = ""
        for child in li.children:
            if isinstance(child, Tag):
                break
            if isinstance(child, NavigableString):
                text = str(child).strip().rstrip(",").strip()
                if text:
                    raw_title = text
                    break

        if edition:
            full_title = f"{raw_title}, {edition}" if raw_title else edition
        else:
            full_title = raw_title

        li_text = li.get_text(" ", strip=True)
        isbn_match = re.search(r'ISBN:\s*(\d[\d\-]{9,})', li_text)
        isbn = isbn_match.group(1).replace("-", "").strip() if isbn_match else ""

        li_lines = [s.strip() for s in li.get_text(separator="\n").splitlines() if s.strip()]
        material_type = ""
        for i, line in enumerate(li_lines):
            if line.startswith("ISBN:"):
                for j in range(i + 1, len(li_lines)):
                    candidate = li_lines[j].strip()
                    if candidate and "library material" not in candidate.lower() and not candidate.startswith("http"):
                        material_type = candidate
                        break
                break

        dedup_key = isbn if isbn else full_title
        if dedup_key and dedup_key in seen_isbns:
            continue
        seen_isbns.add(dedup_key)

        row = dict(base_row)
        row.update({
            "isbn": isbn,
            "title": full_title,
            "author": author,
            "material_adoption_code": material_type,
        })
        results.append(row)

    return results if results else [{
        **base_row,
        "isbn": "", "title": "", "author": "", "material_adoption_code": "",
    }]

def append_csv(rows, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    file_exists = os.path.exists(filepath) and os.path.getsize(filepath) > 0
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)

def get_scraped_keys(filepath):
    """Return set of (dept, course_code, section) tuples already in the CSV."""
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return set()
    scraped = set()
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dept = row.get("department_code", "").strip()
            cc = row.get("course_code", "").strip()
            sec = row.get("section", "").strip()
            if dept:
                scraped.add((dept, cc, sec))
    return scraped

def scrape(fresh=False):
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d 00:00:00")

    if fresh and os.path.exists(CSV_PATH):
        os.remove(CSV_PATH)
        print("[*] Fresh run — deleted existing CSV.")

    done_keys = get_scraped_keys(CSV_PATH)
    if done_keys:
        print(f"[*] {len(done_keys)} section keys already scraped (resume mode).")

    sess = create_session()

    print("[*] Fetching department prefixes...")
    prefixes = fetch_prefixes(sess)
    print(f"    Found {len(prefixes)} prefixes: {prefixes[:10]}{'...' if len(prefixes) > 10 else ''}")

    if not prefixes:
        print("[!] No prefixes found. Exiting.")
        return

    total_rows = 0
    debug_dumped = False

    for prefix in tqdm(prefixes, desc="Prefixes"):
        try:
            course_numbers = fetch_course_numbers(sess, prefix)
        except Exception as e:
            print(f"\n  [ERROR] fetch_course_numbers prefix={prefix}: {e}", flush=True)
            continue

        if not course_numbers:
            tqdm.write(f"    [{prefix}] no courses found — skipping")
            continue

        prefix_rows = 0

        for cn in course_numbers:
            try:
                section_opts = fetch_sections(sess, prefix, cn)
            except Exception as e:
                print(f"\n  [ERROR] fetch_sections {prefix} {cn}: {e}", flush=True)
                continue

            if not section_opts:
                continue

            for sec_info in section_opts:
                sct_val = sec_info["sct_val"]
                key = (prefix, f"|{cn}", f"|{sct_val}")

                if key in done_keys:
                    continue

                try:
                    html = fetch_books(sess, prefix, cn, sct_val)
                except Exception as e:
                    print(f"\n  [ERROR] fetch_books {prefix} {cn} {sct_val}: {e}", flush=True)
                    continue

                if not debug_dumped and html.strip():
                    debug_path = os.path.join(OUTPUT_DIR, "debug_books.html")
                    os.makedirs(OUTPUT_DIR, exist_ok=True)
                    with open(debug_path, "w", encoding="utf-8") as df:
                        df.write(html)
                    print(f"\n    [DEBUG] First books HTML dumped to {debug_path}", flush=True)
                    debug_dumped = True

                rows = parse_books(html, prefix, cn, sec_info, crawled_on)
                append_csv(rows, CSV_PATH)
                done_keys.add(key)
                prefix_rows += len(rows)
                total_rows += len(rows)

        if prefix_rows:
            tqdm.write(f"    [{prefix}] +{prefix_rows} rows (total: {total_rows})")

    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE")
    print(f"{'='*60}")
    print(f"Total rows written: {total_rows}")
    print(f"CSV: {CSV_PATH}")

if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    fresh = "--fresh" in sys.argv
    scrape(fresh=fresh)
