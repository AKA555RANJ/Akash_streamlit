import csv
import os

from itemadapter import ItemAdapter

OUTPUT_DIR = "../Data/bergen_community_college__3061268__syllabus"
CSV_FILENAME = "bergen_community_college__3061268__syllabus.csv"

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
