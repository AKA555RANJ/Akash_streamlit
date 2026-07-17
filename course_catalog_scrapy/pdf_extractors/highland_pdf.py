import csv
import re
import sys
from datetime import datetime
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from course_catalog_scrapy.pipelines import format_dept_code
from course_catalog_scrapy.text_utils import clean_course_title

PDF_URL = ("https://highlandcc.edu/documents/catalog-documents/"
           "2025-2027-course-catalog-revised3-27-2026.pdf")
PDF_PATH = "/tmp/highland.pdf"
SCHOOL_ID = "3031374"
SLUG = "highland_community_college__3031374__cc"
ACADEMIC_YEAR = "2025-2027"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
FIELDNAMES = ["school_id", "department_code", "course_code", "course_title",
              "graduate_type", "term", "academic_year", "source_url",
              "backup_filename", "crawled_on", "updated_on"]

# Highland lists its own (3-digit) courses in several formats; pages 30-37 also
# hold a garbled multi-column TRANSFER-ARTICULATION matrix whose university
# codes (4-digit, "(3" / "Hours)" fragments, doubled words) must be excluded.
TC = r"[A-Za-z0-9 ,&/:'.()+*\-]"
CR = r"\.?\d+(?:[-–+.]\d+)*"
COMPACT = re.compile(
    rf"([A-Z]{{1,5}})\s?(\d{{2,4}}[A-Z]?)\s+([A-Z][A-Za-z]{TC}{{2,48}}?)"
    rf"\s*\(?({CR})\)?\*{{0,2}}(?=\s+[A-Z]{{1,5}}\s?\d|\s*$)")
DESC = re.compile(
    rf"^([A-Z]{{1,5}})\s?(\d{{2,4}}[A-Z]?)\s+([A-Z][A-Za-z]{TC}{{3,50}}?)"
    rf"\s*\(?({CR})\)?\*{{0,2}}(\s|$)")
# course-list section: "HIS202 Introduction to Ancient History*" — no credit
NOCRED = re.compile(r"^([A-Z]{1,4})\s?(\d{3}[A-Z]?)\s+"
                    r"([A-Z][A-Za-z][A-Za-z0-9 ,&':.’\-]{2,52})\*?$")
# work-experience style: "ACR295 Occupational Work Experience ^ (0)"
WEXP = re.compile(r"^([A-Z]{1,4})\s?(\d{2,4}[A-Z]?)\s+"
                  r"([A-Z][A-Za-z][A-Za-z0-9 ,&'/:.’\-–^]{3,72}?)\s*\^?\s*\(\d+\)\s*$")
# bare trailing credit: "VIN135 OR Winter - Spring Viticulture 3"
TRAIL = re.compile(r"^([A-Z]{1,4})\s?(\d{3}[A-Z]?)\s+"
                   r"([A-Z][A-Za-z][A-Za-z0-9 ,&'/:.’\-–]{3,70}?)\s+(\d{1,2})$")
# certification shorthand titles: "TCH100 OSHA 10 1", "HVA112 EPA 608 1" —
# these legitimately contain digits, so they bypass the code-in-title reject
CERT = re.compile(r"^([A-Z]{1,4})\s?(\d{3}[A-Z]?)\s+"
                  r"((?:OSHA|EPA|CPR|KSPN)\s?[A-Z0-9]{1,4})\s+\d{1,2}$")
CODEIN = re.compile(r"\b[A-Z]{2,5}\s?\d{2,4}\b")
XL = re.compile(r"\s+(?:AND|OR|and|or)\s+[A-Z]{2,5}\s?\d.*$")
MARK = re.compile(r"\s*\(\s*\d[\d\s]*\)\s*(?:GE|SWT|GR)?\s*$"
                  r"|\s+with lab.*$|\s+\d+\s*$", re.I)
BADFRAG = re.compile(r"\bHours\b|\(\s*[3-9]\b|([A-Z]{3,})\s+\1")


def cl(t):
    t = XL.sub("", t)
    t = MARK.sub("", t)
    t = re.sub(r"[\^*]+", "", t)
    m = CODEIN.search(t)
    if m and m.start() > 3:
        t = t[:m.start()]
    return clean_course_title(t.strip(" +*,-^"))


def main():
    out_dir = DATA_DIR / SLUG
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with pdfplumber.open(PDF_PATH) as pdf:
        lines = []
        for pg in pdf.pages:
            lines += (pg.extract_text() or "").split("\n")

    seen = {}

    def add(dept, num, title):
        code = f"{dept} {num}"
        if (code not in seen and len(title) >= 4
                and re.search(r"[a-z]", title) and not CODEIN.search(title)):
            seen[code] = title

    for ln in lines:
        s = ln.strip()
        for m in COMPACT.finditer(s):
            add(m.group(1), m.group(2), cl(m.group(3)))
        if (m := DESC.match(s)):
            add(m.group(1), m.group(2), cl(m.group(3)))
        if BADFRAG.search(s):
            continue
        if (m := NOCRED.match(s)) and "(" not in s:
            add(m.group(1), m.group(2), clean_course_title(m.group(3).strip(" *")))
        if (m := WEXP.match(s)):
            add(m.group(1), m.group(2), cl(m.group(3)))
        if (m := TRAIL.match(s)):
            add(m.group(1), m.group(2), cl(m.group(3)))
        if (m := CERT.match(s)):
            code = f"{m.group(1)} {m.group(2)}"
            if code not in seen:
                seen[code] = m.group(3).strip()

    path = out_dir / f"{SLUG}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=FIELDNAMES)
        wr.writeheader()
        for code in sorted(seen):
            dept, num = code.split(" ", 1)
            fdept, fcode = format_dept_code(dept, code)
            wr.writerow({
                "school_id": SCHOOL_ID, "department_code": fdept,
                "course_code": fcode, "course_title": seen[code],
                "graduate_type": "", "term": "",
                "academic_year": ACADEMIC_YEAR, "source_url": PDF_URL,
                "backup_filename": "", "crawled_on": now, "updated_on": now,
            })
    print(f"wrote {len(seen)} rows to {path}")


if __name__ == "__main__":
    main()
