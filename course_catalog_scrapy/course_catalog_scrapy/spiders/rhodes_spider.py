import re

import scrapy

from course_catalog_scrapy.items import CourseItem

CODE_RE = re.compile(r"^([A-Z]{2,5})\s*\d")
YEAR_RE = re.compile(r"20\d\d-20?\d\d")

class RhodesSpider(scrapy.Spider):
    name = "rhodes"
    school_id = "3091104"
    slug = "rhodes_college__3091104__cc"
    allowed_domains = ["catalog.rhodes.edu"]
    start_urls = ["https://catalog.rhodes.edu/courses"]

    def parse(self, response):
        for li in response.css("div.views-field-field-course-number"):
            href = li.css("a::attr(href)").get()
            texts = [t.strip() for t in li.css("a::text").getall() if t.strip()]
            code = texts[0].rstrip(":").strip() if texts else ""
            title = texts[1] if len(texts) > 1 else ""
            if not href or not code:
                continue
            yield response.follow(
                href, callback=self.parse_course, cb_kwargs={"code": code, "title": title}
            )

    def parse_course(self, response, code, title):
        credits = "".join((response.css("div.course__credits span::text").get() or "").split())
        m = YEAR_RE.search(response.text)
        cm = CODE_RE.match(code)
        yield CourseItem(
            school_id=self.school_id,
            department_code=cm.group(1) if cm else code.split()[0],
            course_code=code,
            course_title=title,
            credits=credits,
            graduate_type="Undergraduate",
            term="",
            academic_year=m.group(0) if m else "",
            source_url=response.url,
        )
