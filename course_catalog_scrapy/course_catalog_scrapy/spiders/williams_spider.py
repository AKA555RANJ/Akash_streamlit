import json
import re

import scrapy
from scrapy.selector import Selector

from course_catalog_scrapy.items import CourseItem, year_from_url

FLARESOLVERR = "http://localhost:8191/v1"
LIST_URL = "https://catalog.williams.edu/list/"
CODE_RE = re.compile(r"^([A-Z]{2,5})\s?\d")
TITLE_RE = re.compile(r"^\S+\s*(?:\([^)]*\)\s*)?(?:[A-Z]{2,4}\s+)?(.*)$")
YEAR_RE = re.compile(r"20\d\d-?\d{2,4}")

class WilliamsSpider(scrapy.Spider):
    name = "williams"
    school_id = "3037159"
    slug = "williams_college__3037159__cc"
    allowed_domains = ["localhost"]

    def start_requests(self):
        body = json.dumps({"cmd": "request.get", "url": LIST_URL, "maxTimeout": 80000})
        yield scrapy.Request(
            FLARESOLVERR, method="POST", body=body,
            headers={"Content-Type": "application/json"}, callback=self.parse,
        )

    def parse(self, response):
        html = json.loads(response.text)["solution"]["response"]
        sel = Selector(text=html)
        academic_year = year_from_url(response.url)

        seen = set()
        for a in sel.css("a.Accordion"):
            text = " ".join(t.strip() for t in a.css("::text").getall() if t.strip())
            code, sep, rest = text.partition(" - ")
            code = code.strip()
            if not sep or not CODE_RE.match(code) or code in seen:
                continue
            seen.add(code)
            tm = TITLE_RE.match(rest.strip())
            title = tm.group(1).strip() if tm else rest.strip()
            href = a.xpath(
                "ancestor::li[1]//a[contains(@class,'classinfo')]/@href"
            ).get() or ""
            yield CourseItem(
                school_id=self.school_id,
                department_code=CODE_RE.match(code).group(1),
                course_code=code,
                course_title=title,
                credits="",
                graduate_type="Undergraduate",
                term="",
                academic_year=academic_year,
                source_url=("https://catalog.williams.edu" + href) if href else LIST_URL,
            )

    @staticmethod
    def _norm_year(y):
        m = re.match(r"(20\d\d)-?(\d{2,4})", y)
        if not m:
            return y
        start, end = m.group(1), m.group(2)
        if len(end) == 2:
            end = start[:2] + end
        return f"{start}-{end}"
