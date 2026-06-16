import re

import scrapy

from course_catalog_scrapy.items import CourseItem, year_from_url

COURSE_CODE_RE = re.compile(r"^([A-Z]{2,5})\s?(\d{3}[A-Z]?)\b")
CREDITS_RE = re.compile(r"(\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?)\s*credit", re.I)
YEAR_RE = re.compile(r"\d{4}-\d{4}")
_SEASON_RE = re.compile(r"(Fall|Spring|Summer|Winter)\s+(\d{4})(?:\s*-\s*(\d{2,4}))?", re.I)
_AY_RE = re.compile(r"(\d{4})\s*-\s*(\d{4})")

def _term_in_academic_year(term, academic_year):
    ay = _AY_RE.search(academic_year or "")
    m = _SEASON_RE.search(term or "")
    if not ay or not m:
        return ""
    start, end = int(ay.group(1)), int(ay.group(2))
    season, year, is_range = m.group(1).lower(), int(m.group(2)), m.group(3) is not None
    if season == "fall":
        return term if year == start else ""
    if season == "winter" and is_range:
        return term if year == start else ""
    return term if year == end else ""

def _term_decision(last_term, academic_year):
    if not last_term or not _SEASON_RE.search(last_term):
        return True, ""
    in_ay = _term_in_academic_year(last_term, academic_year)
    return (True, in_ay) if in_ay else (False, "")

class SouthernCtSpider(scrapy.Spider):
    name = "southern_ct"
    school_id = "3009619"
    slug = "southern_connecticut_state_university__3009619__cc"
    allowed_domains = ["catalog.southernct.edu"]
    start_urls_by_type = {
        "Undergraduate": "https://catalog.southernct.edu/undergraduate/courses.html",
        "Graduate": "https://catalog.southernct.edu/graduate/courses.html",
    }

    def start_requests(self):
        for graduate_type, url in self.start_urls_by_type.items():
            yield scrapy.Request(url, callback=self.parse, cb_kwargs={"graduate_type": graduate_type})

    def _academic_year(self, response):
        for text in response.css("nav#breadcrumbs a::text, ul.prevnav li.selected a::text").getall():
            m = YEAR_RE.search(text)
            if m:
                return m.group(0)
        m = YEAR_RE.search(response.text)
        return m.group(0) if m else ""

    def parse(self, response, graduate_type):
        filter_year = self._academic_year(response)
        for box in response.css("div.course-box"):
            heading = " ".join(t.strip() for t in box.css("h2 ::text").getall() if t.strip())
            code_match = COURSE_CODE_RE.match(heading)
            if not code_match:
                continue
            credits_text = " ".join(t.strip() for t in box.css("p.course-credits ::text").getall() if t.strip())
            credits_match = CREDITS_RE.search(credits_text)
            term_text = " ".join(t.strip() for t in box.css("p.last-term-offered ::text").getall() if t.strip())
            last_term = term_text.split(":", 1)[1].strip() if ":" in term_text else term_text
            keep, term = _term_decision(last_term, filter_year)
            if not keep:
                continue
            box_id = box.attrib.get("id", "")
            yield CourseItem(
                school_id=self.school_id,
                department_code=code_match.group(1),
                course_code=f"{code_match.group(1)} {code_match.group(2)}",
                course_title=heading.split(" - ", 1)[1].strip() if " - " in heading else "",
                credits=credits_match.group(1).replace(" ", "") if credits_match else "",
                graduate_type=graduate_type,
                term=term,
                academic_year=year_from_url(response.url),
                source_url=f"{response.url}#{box_id}" if box_id else response.url,
            )
