import json
import re
from urllib.parse import urlencode

import scrapy

from course_catalog_scrapy.items import CourseItem

API = "https://app.coursedog.com/api/v1"
COLUMNS = "code,subjectCode,courseNumber,name,longName,credits,career,college,status"
PAGE = 500


def _fmt_num(v):
    if v is None:
        return None
    try:
        f = float(v)
        return str(int(f)) if f == int(f) else str(f)
    except (TypeError, ValueError):
        return str(v)


def _year(name):
    m = re.search(r"(20\d\d)\s*[-_/]\s*(20\d\d)", name)
    if m:
        return m.group(1) + "-" + m.group(2)
    m = re.search(r"\b(\d{2})\s*[-_/]\s*(\d{2})\b", name)
    if m:
        return "20" + m.group(1) + "-20" + m.group(2)
    return ""


class CoursedogSpider(scrapy.Spider):
    custom_settings = {"ROBOTSTXT_OBEY": False, "DOWNLOAD_DELAY": 0.3,
                       "CONCURRENT_REQUESTS": 4}
    academic_year = ""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.seen = set()

    def _headers(self, json_body=False):
        h = {"Accept": "application/json", "Origin": self.origin,
             "Referer": self.origin + "/"}
        if json_body:
            h["Content-Type"] = "application/json"
        return h

    def start_requests(self):
        yield scrapy.Request(f"{API}/ca/{self.tenant}/catalogs/{self.catalog_id}",
                             headers=self._headers(), callback=self.parse_catalog,
                             dont_filter=True)

    def parse_catalog(self, response):
        dn = (response.json() or {}).get("displayName") or ""
        self.academic_year = _year(dn)
        yield self._courses_request(0)

    def _courses_request(self, skip):
        params = {"catalogId": self.catalog_id, "skip": skip, "limit": PAGE,
                  "orderBy": "code", "effectiveDatesRange": self.effective,
                  "ignoreEffectiveDating": "false", "ignoreTotalCount": "false",
                  "columns": COLUMNS}
        url = f"{API}/cm/{self.tenant}/courses/search/$filters?" + urlencode(params)
        return scrapy.Request(url, method="POST", body=self.body,
                              headers=self._headers(json_body=True),
                              callback=self.parse_courses, cb_kwargs={"skip": skip},
                              dont_filter=True)

    def parse_courses(self, response, skip):
        data = response.json()
        total = data.get("listLength") or 0
        for c in data.get("data") or []:
            subj = (c.get("subjectCode") or "").strip()
            num = (c.get("courseNumber") or "").strip()
            code = f"{subj} {num}".strip() if subj and num else (c.get("code") or "").strip()
            if not code or code in self.seen:
                continue
            self.seen.add(code)
            yield CourseItem(
                school_id=self.school_id,
                department_code=subj,
                course_code=code,
                course_title=(c.get("longName") or c.get("name") or "").strip(),
                credits=self._credits(c.get("credits") or {}),
                graduate_type="",
                term="",
                academic_year=self.academic_year,
                source_url=self.origin + "/courses",
            )
        if skip + PAGE < total:
            yield self._courses_request(skip + PAGE)

    @staticmethod
    def _credits(credits):
        ch = credits.get("creditHours") or {}
        mn, mx = _fmt_num(ch.get("min")), _fmt_num(ch.get("max"))
        if mn is None and mx is None:
            v = _fmt_num(ch.get("value"))
            return v if v is not None else (_fmt_num(credits.get("numberOfCredits")) or "")
        if mn == mx or mx is None:
            return mn or mx or ""
        if mn is None:
            return mx
        return f"{mn}-{mx}"


class UMNTwinCitiesSpider(CoursedogSpider):
    name = 'umn_twin_cities'
    school_id = '3047037'
    slug = 'university_of_minnesota-twin_cities__3047037__cc'
    origin = 'https://umtc.catalog.prod.coursedog.com'
    tenant = 'umn_umntc_peoplesoft'
    catalog_id = 'QEPaNgPjyzEkVlRYv42S'
    effective = '2026-09-08,2032-12-15'
    body = '{"condition":"AND","filters":[{"condition":"and","filters":[{"id":"status-course","name":"status","inputType":"select","group":"course","type":"is","value":"Active"},{"id":"catalogPrint-course","name":"catalogPrint","inputType":"boolean","group":"course","type":"isNot","value":false}]}]}'

class UMNDuluthSpider(CoursedogSpider):
    name = 'umn_duluth'
    school_id = '3047039'
    slug = 'university_of_minnesota-duluth__3047039__cc'
    origin = 'https://umd.catalog.prod.coursedog.com'
    tenant = 'umn_umndl_peoplesoft'
    catalog_id = 'iIMp6RhVqhlPF9jrsxn3'
    effective = '2026-08-31,2032-12-17'
    body = '{"condition":"AND","filters":[{"condition":"and","filters":[{"id":"status-course","name":"status","inputType":"select","group":"course","type":"is","value":"Active"},{"id":"catalogPrint-course","name":"catalogPrint","inputType":"boolean","group":"course","type":"isNot","value":false}]}]}'

class USDSpider(CoursedogSpider):
    name = 'usd'
    school_id = '2995739'
    slug = 'university_of_san_diego__2995739__cc'
    origin = 'https://undergraduate.catalog.sandiego.edu'
    tenant = 'san_diego_banner'
    catalog_id = 'a2SnCpZwoxm0QEwfgQst'
    effective = '2026-09-03,2026-09-03'
    body = '{"condition":"AND","filters":[{"filters":[{"id":"courseLevel-course","condition":"field","name":"courseLevel","inputType":"select","group":"course","type":"is","value":["Undergraduate"],"customField":true},{"id":"college-course","condition":"field","name":"college","inputType":"collegeSelect","group":"course","type":"isNot","value":"School of Law","customField":false},{"id":"college-course","condition":"field","name":"college","inputType":"collegeSelect","group":"course","type":"isNot","value":"Paralegal Studies","customField":false},{"id":"departments-course","condition":"field","name":"departments","inputType":"select","group":"course","type":"isNot","value":["FST"],"customField":false},{"id":"status-course","condition":"field","name":"status","inputType":"select","group":"course","type":"isNot","value":"Inactive","customField":false},{"id":"status-course","condition":"field","name":"status","inputType":"select","group":"course","type":"isNot","value":"Non-Catalog Course","customField":false},{"id":"courseNumber-course","condition":"field","name":"courseNumber","inputType":"text","group":"course","type":"lessThan","value":"500","customField":false},{"id":"courseNumber-course","condition":"field","name":"courseNumber","inputType":"text","group":"course","type":"lessThan","value":"D500","customField":false}],"id":"UA7ZNlzU","condition":"and"}]}'

class CarsonNewmanSpider(CoursedogSpider):
    name = 'carson_newman'
    school_id = '3091073'
    slug = 'carson-newman_university__3091073__cc'
    origin = 'https://carsonnewman.catalog.prod.coursedog.com'
    tenant = 'carsonnewman_colleague_ethos'
    catalog_id = 'eaYrB8CAwF58LHI7hqkq'
    effective = '2026-08-01,2026-08-01'
    body = '{"condition":"AND","filters":[{"filters":[{"id":"startTerm-course","condition":"field","name":"startTerm","inputType":"text","group":"course","type":"doesNotContain","value":"2027 Spring Transfer","customField":false},{"id":"courseNumber-course","condition":"field","name":"courseNumber","inputType":"text","group":"course","type":"doesNotContain","value":"ELEC"},{"id":"courseNumber-course","condition":"field","name":"courseNumber","inputType":"text","group":"course","type":"doesNotContain","value":"GER"},{"id":"courseNumber-course","condition":"field","name":"courseNumber","inputType":"text","group":"course","type":"doesNotContain","value":"VRS"},{"id":"courseNumber-course","condition":"field","name":"courseNumber","inputType":"text","group":"course","type":"doesNotContain","value":"REQU"}],"id":"r6xkd4Xa","condition":"and"}]}'
