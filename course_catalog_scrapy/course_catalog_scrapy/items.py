import re

import scrapy

_URL_YEAR_RE = re.compile(r"(20\d\d)\s*-\s*(20?\d\d)")


def year_from_url(url):
    m = _URL_YEAR_RE.search(url or "")
    if not m:
        return ""
    a, b = m.group(1), m.group(2)
    if len(b) == 2:
        b = "20" + b
    return f"{a}-{b}"


class CourseItem(scrapy.Item):
    school_id = scrapy.Field()
    department_code = scrapy.Field()
    course_code = scrapy.Field()
    course_title = scrapy.Field()
    credits = scrapy.Field()
    graduate_type = scrapy.Field()
    term = scrapy.Field()
    academic_year = scrapy.Field()
    source_url = scrapy.Field()

    raw_html = scrapy.Field()
    backup_filename = scrapy.Field()
