import csv
import os
from datetime import datetime, timezone

from itemadapter import ItemAdapter

OUTPUT_DIR = "../Data/delaware_technical_community_college_terry__2984303__syllabus"
CSV_FILENAME = "delaware_technical_community_college_terry__2984303__syllabus.csv"

SCHEMA_FIELDS = [
    "school_id",
    "term_code",
    "term",
    "department_code",
    "department_name",
    "course_code",
    "course_titel",
    "section_code",
    "instructor",
    "syllabus_filename",
    "syllabus_file_format",
    "syllabus_filepath_local",
    "syllabus_filesize",
    "syllabus_file_source_url",
    "source_url",
    "crawled_on",
    "downloaded_on",
]


class HtmlDownloadPipeline:

    def open_spider(self, spider):
        os.makedirs(OUTPUT_DIR, exist_ok=True)

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        html_body = adapter.get("_syllabus_html")
        if not html_body:
            return item

        del item["_syllabus_html"]

        course_code = adapter.get("course_code", "UNKNOWN")
        filename = f"{course_code}.html"
        filepath = os.path.join(OUTPUT_DIR, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html_body)

        filesize = os.path.getsize(filepath)
        now = datetime.now(timezone.utc).isoformat()

        adapter["syllabus_filename"] = filename
        adapter["syllabus_file_format"] = "html"
        adapter["syllabus_filepath_local"] = filepath
        adapter["syllabus_filesize"] = str(filesize)
        adapter["downloaded_on"] = now

        return item


class CsvExportPipeline:

    def open_spider(self, spider):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        csv_path = os.path.join(OUTPUT_DIR, CSV_FILENAME)
        self._file = open(csv_path, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(
            self._file, fieldnames=SCHEMA_FIELDS, extrasaction="ignore"
        )
        self._writer.writeheader()

    def close_spider(self, spider):
        self._file.close()

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        row = {f: adapter.get(f, "") for f in SCHEMA_FIELDS}
        self._writer.writerow(row)
        return item
