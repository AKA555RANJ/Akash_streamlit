import csv
import gzip
import hashlib
import os
from datetime import datetime
from pathlib import Path

from course_catalog_scrapy.items import CourseItem
from course_catalog_scrapy.text_utils import clean_course_title

FIELDNAMES = [
    "school_id", "department_code", "course_code", "course_title", "credits",
    "graduate_type", "term", "academic_year", "source_url",
    "crawled_on", "updated_on", "html_backup_path",
]
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
HTML_BACKUP_REL = "dist/html_backup"
HTML_BACKUP_DIR = Path(__file__).resolve().parents[2] / HTML_BACKUP_REL


def format_dept_code(dept, code):
    dept = (dept or "").strip()
    code = (code or "").strip()
    number = code
    if dept and code.upper().startswith(dept.upper()):
        number = code[len(dept):]
    number = number.lstrip(" -")
    return (f"|{dept}" if dept else ""), (f"|{number}" if number else "")


class HTMLCompactStoragePipeline:
    def __init__(self):
        self.base_dir = str(HTML_BACKUP_DIR)
        self.seen_hashes = set()

    def process_item(self, item, spider):
        raw_html = item.get("raw_html")
        if not raw_html:
            return item

        if not item.get("course_code") and not item.get("course_title"):
            self._cleanup_html(item)
            return item

        school_id = item.get("school_id") or getattr(spider, "name", "unknown_school")
        try:
            if isinstance(raw_html, str):
                raw_html = raw_html.encode("utf-8")
            content_hash = hashlib.sha256(raw_html).hexdigest()[:8]
            filename = f"{content_hash}.html.gz"
            # Stored path is repo-relative (portable); file is written to the absolute dir.
            item["html_backup_path"] = os.path.join(HTML_BACKUP_REL, str(school_id), filename)
            target_dir = os.path.join(self.base_dir, str(school_id))
            file_path = os.path.join(target_dir, filename)

            if content_hash in self.seen_hashes:
                return item

            os.makedirs(target_dir, exist_ok=True)
            if not os.path.exists(file_path):
                with gzip.open(file_path, "wb") as f:
                    f.write(raw_html)
            self.seen_hashes.add(content_hash)
        except Exception as e:
            spider.logger.error(
                f"Storage Pipeline Failure | School: {school_id} | "
                f"URL: {item.get('source_url', 'Unknown')} | Error: {str(e)}"
            )
        finally:
            self._cleanup_html(item)

        return item

    def _cleanup_html(self, item):
        if "raw_html" in item:
            del item["raw_html"]


class CleanCourseTitlePipeline:
    def process_item(self, item, spider):
        if isinstance(item, CourseItem) and item.get("course_title"):
            item["course_title"] = clean_course_title(item["course_title"])
        return item


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
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            row = {k: item.get(k, "") for k in FIELDNAMES}
            row["department_code"], row["course_code"] = format_dept_code(
                row["department_code"], row["course_code"]
            )
            row["crawled_on"] = now
            row["updated_on"] = now
            self.writer.writerow(row)
            self.count += 1
        return item

    def close_spider(self, spider):
        self.file.close()
        spider.logger.info(f"Wrote {self.count} rows to {self.path}")
