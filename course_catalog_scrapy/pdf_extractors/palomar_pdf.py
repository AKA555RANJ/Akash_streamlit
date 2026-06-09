import csv
import re
from pathlib import Path

import pdfplumber

PDF_URL = "https://www.palomar.edu/catalog/wp-content/uploads/sites/8/2026/05/2026-2027-Catalog-Volume-LXXV-Reduced.pdf"
PDF_PATH = "/tmp/palomar.pdf"
SCHOOL_ID = "2995726"
SLUG = "palomar_college__2995726__cc"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
FIELDNAMES = ["school_id", "department_code", "course_code", "course_title",
              "credits", "graduate_type", "term", "academic_year", "source_url"]

HEADER_RE = re.compile(r'^([A-Z]{2,4})\s(\d{2,3}[A-Z]?)\s+(.+?)\s+\((\d+(?:\.\d+)?)\)\s*$', re.M)
YEAR_RE = re.compile(r'20\d\d\s*[-–]\s*20\d\d')


def main():
    out_dir = DATA_DIR / SLUG
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, seen, year = [], set(), ""
    with pdfplumber.open(PDF_PATH) as pdf:
        for pg in pdf.pages:
            w = pg.width
            for x0, x1 in ((0, w / 2), (w / 2, w)):
                text = pg.crop((x0, 0, x1, pg.height)).extract_text() or ""
                if not year:
                    ym = YEAR_RE.search(text)
                    if ym:
                        year = re.sub(r'\s', '', ym.group(0)).replace('–', '-')
                for dept, num, title, units in HEADER_RE.findall(text):
                    code = f"{dept} {num}"
                    if code in seen:
                        continue
                    seen.add(code)
                    rows.append({
                        "school_id": SCHOOL_ID, "department_code": dept,
                        "course_code": code, "course_title": title.strip(),
                        "credits": units, "graduate_type": "Undergraduate",
                        "term": "", "academic_year": year, "source_url": PDF_URL,
                    })
    path = out_dir / f"{SLUG}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=FIELDNAMES)
        wr.writeheader()
        wr.writerows(rows)
    print(f"wrote {len(rows)} rows to {path} | year={year}")


if __name__ == "__main__":
    main()
