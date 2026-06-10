import json
import re
from urllib.parse import urlencode

import scrapy

from course_catalog_scrapy.items import CourseItem

API = "https://app.coursedog.com/api/v1"
TENANT = "maricopa_peoplesoft_direct"
# Fall 2026 effective date = AY2026-2027 (the col K catalog).
EFFECTIVE = "2026-08-22,2026-08-22"
COLUMNS = ("name,courseNumber,subjectCode,code,career,college,longName,"
           "status,institution,institutionId,credits")
PAGE = 500
YEAR_RE = re.compile(r"(\d{2})\s*-\s*(\d{2})")   # "26-27" in the catalog displayName


def _fmt_num(v):
    if v is None:
        return None
    try:
        f = float(v)
        return str(int(f)) if f == int(f) else str(f)
    except (TypeError, ValueError):
        return str(v)


class MaricopaCoursedogSpider(scrapy.Spider):
    """Base spider for Maricopa County CCD colleges on Coursedog.

    The district runs one Coursedog tenant (maricopa_peoplesoft_direct); each college is a
    separate catalog (distinct catalogId) selected by an offerNumber filter, served via a
    public JSON API (no auth; gated on Origin/Referer). Reverse-engineered with Playwright
    (HANDOFF s7.3). Subclasses set name/school_id/slug/subdomain/catalog_id/offer_number.
    """

    custom_settings = {"ROBOTSTXT_OBEY": False, "DOWNLOAD_DELAY": 0.3,
                       "CONCURRENT_REQUESTS": 4}
    academic_year = ""

    @property
    def origin(self):
        return f"https://{self.subdomain}.catalog.maricopa.edu"

    def _headers(self, json_body=False):
        h = {"Accept": "application/json", "Origin": self.origin,
             "Referer": self.origin + "/"}
        if json_body:
            h["Content-Type"] = "application/json"
        return h

    def start_requests(self):
        # 1) catalog metadata -> academic_year from its displayName ("26-27 ... Catalog")
        yield scrapy.Request(
            f"{API}/ca/{TENANT}/catalogs/{self.catalog_id}",
            headers=self._headers(), callback=self.parse_catalog, dont_filter=True)

    def parse_catalog(self, response):
        dn = (response.json() or {}).get("displayName") or ""
        m = YEAR_RE.search(dn)
        self.academic_year = f"20{m.group(1)}-20{m.group(2)}" if m else ""
        yield self._courses_request(0)

    def _courses_request(self, skip):
        params = {"catalogId": self.catalog_id, "skip": skip, "limit": PAGE,
                  "orderBy": "code", "formatDependents": "false",
                  "effectiveDatesRange": EFFECTIVE, "ignoreEffectiveDating": "false",
                  "ignoreTotalCount": "false", "columns": COLUMNS}
        url = f"{API}/cm/{TENANT}/courses/search/$filters?" + urlencode(params)
        body = {"condition": "AND", "filters": [{"filters": [
            {"id": "status-course", "condition": "field", "name": "status",
             "inputType": "select", "group": "course", "type": "is",
             "value": "Active", "customField": False},
            {"id": "career-course", "condition": "field", "name": "career",
             "inputType": "careerSelect", "group": "course", "type": "contains",
             "value": "CRED", "customField": False},
            {"id": "offerNumber-course", "condition": "field", "name": "offerNumber",
             "inputType": "number", "group": "course", "type": "is",
             "value": self.offer_number},
        ], "id": "kvPfMSbf", "condition": "and"}]}
        return scrapy.Request(url, method="POST", body=json.dumps(body),
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
            if code in self.seen:
                continue
            self.seen.add(code)
            yield CourseItem(
                school_id=self.school_id,
                department_code=subj,
                course_code=code,
                course_title=(c.get("longName") or c.get("name") or "").strip(),
                credits=self._credits(c.get("credits") or {}),
                graduate_type="Undergraduate",
                term="",
                academic_year=self.academic_year,
                source_url=self.origin + "/courses",
            )
        if skip + PAGE < total:
            yield self._courses_request(skip + PAGE)

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.seen = set()

    @staticmethod
    def _credits(credits):
        ch = credits.get("creditHours") or {}
        mn, mx = _fmt_num(ch.get("min")), _fmt_num(ch.get("max"))
        if mn is None and mx is None:
            return _fmt_num(credits.get("numberOfCredits")) or ""
        if mn == mx or mx is None:
            return mn or mx or ""
        if mn is None:
            return mx
        return f"{mn}-{mx}"


class MesaSpider(MaricopaCoursedogSpider):
    name = "mesa"
    school_id = "2990776"
    slug = "mesa_community_college__2990776__cc"
    subdomain = "mesacc"
    catalog_id = "RQzc6b76uitYyaXJt27C"
    offer_number = 4


class ParadiseValleySpider(MaricopaCoursedogSpider):
    name = "paradise_valley"
    school_id = "2990782"
    slug = "paradise_valley_community_college__2990782__cc"
    subdomain = "paradisevalley"
    catalog_id = "HirEuyo6daAN3xmWWf45"
    offer_number = 9


class ScottsdaleSpider(MaricopaCoursedogSpider):
    name = "scottsdale"
    school_id = "2990779"
    slug = "scottsdale_community_college__2990779__cc"
    subdomain = "scottsdalecc"
    catalog_id = "n1NpLQ9WGeg5jvC66ZRP"
    offer_number = 5
