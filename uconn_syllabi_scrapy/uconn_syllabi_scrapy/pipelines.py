import csv
import hashlib
import json
import os
import re
from urllib.parse import urlparse, parse_qs

import scrapy
from itemadapter import ItemAdapter
from scrapy.pipelines.files import FilesPipeline

# Fields written to CSV and JSON output
OUTPUT_FIELDS = [
    "term_name",
    "class_name",
    "section",
    "instructor",
    "syllabus_web_url",
    "syllabus_local_filepath",
    "syllabus_local_filename",
]

OUTPUT_DIR = "output"


class UConnFilesPipeline(FilesPipeline):
    """Custom FilesPipeline that generates structured filenames and sets local path fields."""

    def get_media_requests(self, item, info):
        adapter = ItemAdapter(item)
        for url in adapter.get("file_urls") or []:
            yield scrapy.Request(url, headers={"Referer": "https://syllabus.uconn.edu/public/search_term.php"})

    def file_path(self, request, response=None, info=None, *, item=None):
        """Generate: {term_code}_{dept}_{number}_{file_id}.{ext}"""
        adapter = ItemAdapter(item) if item else {}
        term_code = (adapter.get("term_code") or "0000").strip()
        class_name = (adapter.get("class_name") or "").strip()

        # Split "CSE 3666" → dept="CSE", number="3666"
        parts = class_name.split(None, 1)
        dept = re.sub(r"[^\w]", "", parts[0]) if parts else "UNKNOWN"
        number = re.sub(r"[^\w]", "", parts[1]) if len(parts) > 1 else "0"

        # Extract file_id from download.php?file=ID|HASH
        url = request.url
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        file_param = qs.get("file", [""])[0]
        # file_param may be URL-decoded (pipe) or encoded (%7C)
        file_param_decoded = file_param.replace("%7C", "|")
        if "|" in file_param_decoded:
            file_id = file_param_decoded.split("|")[0].strip()
        else:
            # Fallback: 12-char SHA-1 of the URL
            file_id = hashlib.sha1(url.encode()).hexdigest()[:12]

        # Determine extension from URL or default to .pdf
        path = parsed.path.lower()
        if path.endswith(".docx"):
            ext = "docx"
        elif path.endswith(".doc"):
            ext = "doc"
        else:
            ext = "pdf"

        filename = f"{term_code}_{dept}_{number}_{file_id}.{ext}"
        return filename

    def item_completed(self, results, item, info):
        adapter = ItemAdapter(item)
        store = info.spider.settings.get("FILES_STORE", "syllabi_downloads")

        downloaded = [r for ok, r in results if ok]
        if downloaded:
            rel_path = downloaded[0]["path"]
            filename = os.path.basename(rel_path)
            local_filepath = os.path.join(store, filename)
            adapter["syllabus_local_filepath"] = local_filepath
            adapter["syllabus_local_filename"] = filename
        else:
            # no_download mode or failed download
            if not adapter.get("syllabus_local_filepath"):
                adapter["syllabus_local_filepath"] = ""
            if not adapter.get("syllabus_local_filename"):
                adapter["syllabus_local_filename"] = ""

        return item


class CsvExportPipeline:
    """Streams rows to output/syllabi_metadata.csv as items are scraped."""

    def open_spider(self, spider):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        self._file = open(os.path.join(OUTPUT_DIR, "syllabi_metadata.csv"), "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        self._writer.writeheader()

    def close_spider(self, spider):
        self._file.close()

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        row = {f: adapter.get(f, "") for f in OUTPUT_FIELDS}
        self._writer.writerow(row)
        return item


class JsonExportPipeline:
    """Collects all items in memory and writes output/syllabi_metadata.json on close."""

    def open_spider(self, spider):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        self._records = []

    def close_spider(self, spider):
        out_path = os.path.join(OUTPUT_DIR, "syllabi_metadata.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(self._records, f, ensure_ascii=False, indent=2)
        spider.logger.info(f"JSON output written: {out_path} ({len(self._records)} records)")

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        record = {f: adapter.get(f, "") for f in OUTPUT_FIELDS}
        self._records.append(record)
        return item
