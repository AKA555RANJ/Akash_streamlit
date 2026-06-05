import csv
from pathlib import Path

from course_catalog_scrapy.items import CourseItem

# Column order for the exported CSV (matches CourseItem).
FIELDNAMES = [
    "school_id",
    "department_code",
    "course_code",
    "course_title",
    "credits",
    "graduate_type",
    "term",
    "academic_year",
    "source_url",
]

# Repo root: .../Akash_streamlit/course_catalog_scrapy/course_catalog_scrapy/pipelines.py
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"


class CsvExportPipeline:
    """Write each spider's items to data/<spider.slug>/<spider.slug>.csv."""

    def open_spider(self, spider):
        slug = getattr(spider, "slug", spider.name)
        out_dir = DATA_DIR / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        self._path = out_dir / f"{slug}.csv"
        self._file = self._path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=FIELDNAMES)
        self._writer.writeheader()
        self._count = 0
        spider.logger.info(f"Writing CSV to {self._path}")

    def process_item(self, item, spider):
        if isinstance(item, CourseItem):
            self._writer.writerow({k: item.get(k, "") for k in FIELDNAMES})
            self._count += 1
        return item

    def close_spider(self, spider):
        self._file.close()
        spider.logger.info(f"Wrote {self._count} rows to {self._path}")
