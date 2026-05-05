import csv
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

BASE_URL    = "https://bookstore.lsue.edu"
LISTING_URL = BASE_URL + "/find-courses"
AUTO_URL    = BASE_URL + "/find-courses/autocomplete"

SCHOOL_ID   = "3035074"
SCHOOL_NAME = "louisiana_state_university_eunice"

CSV_FIELDS = [
    "source_url", "school_id", "department_code", "course_code", "course_title",
    "section", "section_instructor", "term", "isbn", "title", "author",
    "material_adoption_code", "crawled_on", "updated_on",
]

DEFAULT_DELAY  = 3.0
BATCH_SIZE     = 10
AUTOCOMPLETE_Q = list("abcdefghijklmnopqrstuvwxyz0123456789")

ADOPTION_MAP = {
    "required":     "Required Material(s)",
    "optional":     "Optional Material(s)",
    "choice":       "Choose One",
    "recommended":  "Recommended Material(s)",
}

def make_session():
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": LISTING_URL,
    })
    return sess

def get_form_token(sess):
    r = sess.get(LISTING_URL, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    return soup.find("input", {"name": "form_build_id"})["value"]

def select_term(sess, fbi, term_id):
    sess.headers.update({"X-Requested-With": "XMLHttpRequest", "Accept": "application/json, */*"})
    r = sess.post(LISTING_URL + "?ajax_form=1", data={
        "term_select": term_id, "op": "Select Term",
        "form_build_id": fbi, "form_id": "timber_college_courses",
        "_triggering_element_name": "op", "_triggering_element_value": "Select Term",
    }, timeout=20)
    r.raise_for_status()
    cmds = r.json()
    del sess.headers["X-Requested-With"]
    sess.headers["Accept"] = "text/html,*/*"
    return next(c["new"] for c in cmds if c["command"] == "update_build_id")

def fetch_all_sections(sess, term_id):
    sections = {}
    for q in AUTOCOMPLETE_Q:
        for attempt in range(5):
            try:
                time.sleep(DEFAULT_DELAY * (attempt + 1))
                r = sess.get(AUTO_URL, params={"tid": term_id, "q": q}, timeout=30)
                r.raise_for_status()
                break
            except Exception as e:
                if attempt == 4:
                    tqdm.write(f"  [WARN] autocomplete q={q!r}: {e}")
                    r = None
        if r is None:
            continue
        try:
            items = r.json()
        except Exception:
            continue
        for item in items:
            if item["value"] not in sections:
                soup = BeautifulSoup(item["label"], "html.parser")
                dept_name  = (soup.find(class_="cdept-name") or BeautifulSoup("", "html.parser")).get_text(strip=True)
                code_el    = soup.find(class_="cdept-code")
                desc_el    = soup.find(class_="ccourse-desc")
                section_el = soup.find(class_="csection-name")
                code_text  = code_el.get_text(strip=True) if code_el else ""
                parts      = code_text.split() if code_text else []
                dept_code  = parts[0] if parts else ""
                course_num = parts[1] if len(parts) > 1 else ""
                sections[item["value"]] = {
                    "section_id":   item["value"],
                    "dept_code":    dept_code,
                    "dept_name":    dept_name,
                    "course_num":   course_num,
                    "course_title": desc_el.get_text(strip=True) if desc_el else "",
                    "section_name": section_el.get_text(strip=True).replace("Section ", "") if section_el else "",
                    "label":        BeautifulSoup(item["label"], "html.parser").get_text(" ", strip=True),
                }
    return list(sections.values())

def parse_section_html(section_div, section_meta, term_name, crawled_on):
    rows = []
    base = {
        "source_url":         LISTING_URL,
        "school_id":          SCHOOL_ID,
        "department_code":    section_meta["dept_code"],
        "course_code":        "|" + section_meta["course_num"],
        "course_title":       section_meta["course_title"],
        "section":            "|" + section_meta["section_name"],
        "section_instructor": "",
        "term":               term_name.upper(),
        "crawled_on":         crawled_on,
        "updated_on":         crawled_on,
    }

    adoption_groups = section_div.select("div.adoption-list-content-group")
    if not adoption_groups:
        content = section_div.select_one(".section-content")
        no_text = content and "no text required" in content.get_text(strip=True).lower() if content else False
        rows.append({**base, "isbn": "", "title": "", "author": "",
                     "material_adoption_code": "No text required" if no_text else ""})
        return rows

    for group in adoption_groups:
        classes = group.get("class", [])
        adoption_raw = ""
        if "adoption-type" in classes:
            idx = classes.index("adoption-type")
            if idx + 1 < len(classes) and not classes[idx + 1].startswith(("js-", "form-")):
                adoption_raw = classes[idx + 1]
        if not adoption_raw:
            for cls in classes:
                if cls.startswith("adoption-type") and cls != "adoption-type":
                    adoption_raw = cls.replace("adoption-type", "").strip("-").strip()
        adoption = ADOPTION_MAP.get(adoption_raw.lower(), adoption_raw.capitalize() if adoption_raw else "")

        for adoption_row in group.select("div[class*=adoption-row]"):
            h4 = adoption_row.select_one(".adoption-left h4")
            title = h4.get_text(strip=True) if h4 else ""
            tbl   = adoption_row.select_one("table.adoption-data")
            isbn, author = "", ""
            if tbl:
                for tr in tbl.select("tr"):
                    cells = tr.find_all("td")
                    if len(cells) == 2:
                        label = cells[0].get_text(strip=True).lower()
                        val   = cells[1].get_text(strip=True)
                        if "isbn" in label:
                            isbn = re.sub(r"[^0-9X]", "", val.upper())
                        elif "author" in label:
                            author = val
            if title:
                rows.append({**base, "isbn": isbn, "title": title, "author": author,
                             "material_adoption_code": adoption})

    if not rows:
        rows.append({**base, "isbn": "", "title": "", "author": "", "material_adoption_code": ""})
    return rows

def fetch_books_batch(sess, term_id, batch, term_name, crawled_on):
    fbi     = get_form_token(sess)
    new_fbi = select_term(sess, fbi, term_id)

    post_data = {
        "term_select": term_id, "form_build_id": new_fbi,
        "form_id": "timber_college_courses",
        "_triggering_element_name": "op",
        "_triggering_element_value": "Add all selected to 'My Courses'",
        "op": "Add all selected to 'My Courses'",
    }
    for i, item in enumerate(batch, 1):
        post_data[f"course_autocomplete{i}"]       = item["label"]
        post_data[f"course_autocomplete{i}_value"] = str(item["section_id"])
    for i in range(len(batch) + 1, 11):
        post_data[f"course_autocomplete{i}"]       = ""
        post_data[f"course_autocomplete{i}_value"] = ""

    time.sleep(DEFAULT_DELAY)
    r = sess.post(LISTING_URL, data=post_data, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    all_rows = []
    section_map = {str(item["section_id"]): item for item in batch}
    for row_div in soup.select("div.section-row"):
        m = re.search(r"section-row-(\d+)", " ".join(row_div.get("class", [])))
        if not m:
            continue
        sid = m.group(1)
        meta = section_map.get(sid)
        if not meta:
            continue
        rows = parse_section_html(row_div, meta, term_name, crawled_on)
        all_rows.extend(rows)
    return all_rows

def get_scraped_keys(filepath):
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return set()
    with open(filepath, "r", encoding="utf-8") as f:
        return {(r.get("term",""), r.get("department_code",""), r.get("course_code",""), r.get("section",""))
                for r in csv.DictReader(f)}

def append_csv(rows, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    new_file = not os.path.exists(filepath) or os.path.getsize(filepath) == 0
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)

def scrape(csv_path, fresh=False, term_filter=None):
    if fresh and os.path.exists(csv_path):
        os.remove(csv_path)
        print("[*] Fresh run — deleted existing CSV.")

    done_keys  = get_scraped_keys(csv_path)
    crawled_on = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    sess       = make_session()

    fbi = get_form_token(sess)
    print("[*] Fetching available terms...")
    r = sess.get(LISTING_URL, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    term_opts = [(o["value"], o.get_text(strip=True))
                 for o in soup.select("select[name=term_select] option") if o.get("value")]
    print(f"    Terms: {[(t[1]) for t in term_opts]}")

    total = 0
    for term_id, term_name in term_opts:
        if term_filter and term_filter.lower() not in term_name.lower():
            print(f"[*] Skipping: {term_name}")
            continue

        print(f"\n[*] Term: {term_name} ({term_id})")

        print("[*] Collecting sections via autocomplete...")
        sections = fetch_all_sections(sess, term_id)
        print(f"    {len(sections)} unique sections")

        pending = [s for s in sections
                   if (term_name.upper(), s["dept_code"], "|"+s["course_num"], "|"+s["section_name"]) not in done_keys]
        print(f"    {len(pending)} sections to scrape")

        batches = [pending[i:i+BATCH_SIZE] for i in range(0, len(pending), BATCH_SIZE)]
        for batch in tqdm(batches, desc=f"  {term_name}"):
            try:
                rows = fetch_books_batch(sess, term_id, batch, term_name, crawled_on)
            except Exception as e:
                tqdm.write(f"  [WARN] batch failed: {e} — retrying")
                try:
                    fbi     = get_form_token(sess)
                    new_fbi = select_term(sess, fbi, term_id)
                    rows    = fetch_books_batch(sess, term_id, batch, term_name, crawled_on)
                except Exception as e2:
                    tqdm.write(f"  [ERROR] retry failed: {e2}")
                    rows = []
            append_csv(rows, csv_path)
            total += len(rows)

    return total

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Scrape textbooks from LSU Eunice bookstore.")
    parser.add_argument("--fresh",       action="store_true")
    parser.add_argument("--term-filter", default=None)
    args = parser.parse_args()

    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", f"{SCHOOL_NAME}__{SCHOOL_ID}__bks")
    csv_path   = os.path.join(output_dir, f"{SCHOOL_NAME}__{SCHOOL_ID}__bks.csv")
    print(f"[*] Output: {csv_path}")

    total = scrape(csv_path, fresh=args.fresh, term_filter=args.term_filter)
    print(f"\n[+] Done — {total} rows written")

if __name__ == "__main__":
    main()
