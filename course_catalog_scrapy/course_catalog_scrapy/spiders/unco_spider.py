import re

import scrapy

from course_catalog_scrapy.items import CourseItem

YEAR_RE = re.compile(r"20\d\d-20\d\d")
SUBJ_RE = re.compile(
    r"^/en/[^/]+/(?:undergraduate|graduate)-catalog/course-descriptions/[^/]+$"
)


class UncoSpider(scrapy.Spider):
    name = "unco"
    school_id = "3007266"
    slug = "university_of_northern_colorado__3007266__cc"
    allowed_domains = ["unco.smartcatalogiq.com"]
    start_urls_by_type = {
        "Undergraduate": "https://unco.smartcatalogiq.com/en/2026-2027/undergraduate-catalog/course-descriptions/",
        "Graduate": "https://unco.smartcatalogiq.com/en/2026-2027/graduate-catalog/course-descriptions/",
    }

    def start_requests(self):
        for graduate_type, url in self.start_urls_by_type.items():
            yield scrapy.Request(url, callback=self.parse_index, cb_kwargs={"graduate_type": graduate_type})

    def parse_index(self, response, graduate_type):
        seen = set()
        for href in response.css("a::attr(href)").getall():
            href = href.split("#")[0].split("?")[0]
            if SUBJ_RE.match(href) and href not in seen:
                seen.add(href)
                yield response.follow(href, callback=self.parse_subject, cb_kwargs={"graduate_type": graduate_type})

    def parse_subject(self, response, graduate_type):
        m = YEAR_RE.search(response.text)
        academic_year = m.group(0) if m else ""
        for h2 in response.css("div.courselist h2.course-name"):
            code = (h2.css("span::text").get() or "").strip()
            if not code:
                continue
            full = " ".join(t.strip() for t in h2.css("a ::text").getall() if t.strip())
            title = full[len(code):].strip() if full.startswith(code) else full
            credits = "".join((h2.xpath(
                "following-sibling::div[contains(@class,'sc-credithours')][1]"
                "//div[contains(@class,'credits')]/text()"
            ).get() or "").split())
            href = h2.css("a::attr(href)").get() or response.url
            yield CourseItem(
                school_id=self.school_id,
                department_code=code.split()[0],
                course_code=code,
                course_title=title,
                credits=credits,
                graduate_type=graduate_type,
                term="",
                academic_year=academic_year,
                source_url=response.urljoin(href),
            )
