import re

import scrapy

from course_catalog_scrapy.items import CourseItem, year_from_url

CODE_RE = re.compile(r"^([A-Z]{2,5})\s*\d")

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
        term_txt = " ".join(response.css("div.course__term ::text").getall())
        term = re.sub(r"\s+", " ", term_txt).replace("Term:", "").strip(" ,")
        cm = CODE_RE.match(code)
        yield CourseItem(
            school_id=self.school_id,
            department_code=cm.group(1) if cm else code.split()[0],
            course_code=code,
            course_title=title,
            credits=credits,
            graduate_type="Undergraduate",
            term=term,
            academic_year=year_from_url(response.url),
            source_url=response.url,
        )
