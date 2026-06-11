import csv
from pathlib import Path

from course_catalog_scrapy.items import CourseItem

FIELDNAMES = [
    "school_id", "department_code", "course_code", "course_title", "credits",
    "graduate_type", "term", "academic_year", "source_url",
]
DATA_DIR = Path(__file__).resolve().parents[2] / "data"

def format_dept_code(dept, code):
    dept = (dept or "").strip()
    code = (code or "").strip()
    number = code
    if dept and code.upper().startswith(dept.upper()):
        number = code[len(dept):]
    number = number.lstrip(" -")
    return (f"|{dept}" if dept else ""), (f"|{number}" if number else "")

class CsvExportPipeline:
    def open_spider(self, spider):
        slug = getattr(spider, "slug", spider.name)
        out_dir = DATA_DIR / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        self.path = out_dir / f"{slug}.csv"
        self.file = self.path.open("w", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.file, fieldnames=FIELDNAMES)
        self.writer.writeheader()
        self.count = 0

    def process_item(self, item, spider):
        if isinstance(item, CourseItem):
            row = {k: item.get(k, "") for k in FIELDNAMES}
            row["department_code"], row["course_code"] = format_dept_code(
                row["department_code"], row["course_code"]
            )
            self.writer.writerow(row)
            self.count += 1
        return item

    def close_spider(self, spider):
        self.file.close()
        spider.logger.info(f"Wrote {self.count} rows to {self.path}")
