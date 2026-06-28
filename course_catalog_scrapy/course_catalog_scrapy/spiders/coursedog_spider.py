import json
import re
from urllib.parse import urlencode

import scrapy

from course_catalog_scrapy.items import CourseItem, year_from_url

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
    body = None
    effective = ""

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
        self.academic_year = year_from_url(self.origin)
        # When a subclass leaves body unset, derive the catalog's own course
        # filter (coursesFilters), effective date, and year from the catalog object.
        if self.body is None:
            data = response.json()
            cf = data.get("coursesFilters") or {"condition": "and", "filters": []}
            self.body = json.dumps({"condition": "AND", "filters": [cf]})
            if not self.effective:
                eff = (data.get("effectiveStartDate") or "")[:10]
                if eff:
                    self.effective = f"{eff},{eff}"
            year = _year(data.get("displayName") or "")
            if year:
                self.academic_year = year
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
        # use min/max only when they carry a non-zero value (some tenants, e.g.
        # Anthology, leave min/max=0 and put the real credit in value/numberOfCredits)
        if (mn not in (None, "0")) or (mx not in (None, "0")):
            if mn is None:
                return mx
            if mx is None or mn == mx:
                return mn
            return f"{mn}-{mx}"
        v = _fmt_num(ch.get("value"))
        if v not in (None, "0"):
            return v
        noc = _fmt_num(credits.get("numberOfCredits"))
        if noc not in (None, "0"):
            return noc
        return mn or v or noc or ""


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


class FSUSpider(CoursedogSpider):
    name = "fsu"
    school_id = "3012765"
    slug = "florida_state_university__3012765__cc"
    origin = "https://bulletin.fsu.edu"
    tenant = "fsu_peoplesoft"
    catalog_id = "f8cXWDJD0Lphf2KTcUZh"
    effective = "2026-08-24,2026-08-24"
    body = '{"condition":"AND","filters":[{"filters":[{"id":"offerNumber-course","condition":"field","name":"offerNumber","inputType":"number","group":"course","type":"isNot","value":99},{"id":"status-course","condition":"field","name":"status","inputType":"select","group":"course","type":"is","value":"Active","customField":false}],"id":"JfBrN8M5","condition":"and"}]}'


class WCULASpider(CoursedogSpider):
    name = "wcu_la"
    school_id = "2996273"
    slug = "west_coast_university-los_angeles__2996273__cc"
    origin = 'https://wcucurrent.catalog.prod.coursedog.com'
    tenant = 'wcu_campusnexus'
    catalog_id = 'CH4gxLXlt5m9ocXA5QeJ'
    effective = '2026-01-01,2026-01-01'
    body = '{"condition":"AND","filters":[{"filters":[{"id":"status-course","condition":"field","name":"status","inputType":"select","group":"course","type":"is","value":"Active","customField":false}],"id":"w0cZZITs","condition":"or"}]}'


class RowanBurlingtonSpider(CoursedogSpider):
    name = "rowan_burlington"
    school_id = "3061272"
    slug = "rowan_college_at_burlington_county__3061272__cc"
    origin = 'https://rcbc.catalog.prod.coursedog.com'
    tenant = 'rcbc_colleague'
    catalog_id = 'YMcEJQ2ylMoKDthe71o7'
    # body/effective/academic_year derived from the 2026-2027 catalog (coursesFilters)


class MidlandSpider(CoursedogSpider):
    # Two catalogs (undergrad + grad) -> one CSV; filter derived from each catalog.
    name = "midland"
    school_id = "3058587"
    slug = "midland_university__3058587__cc"
    origin = "https://undergrad.catalog.midlandu.edu"
    tenant = "midland_campusnexus"
    catalog_id = "BCpm4QkCCrhY8bxob1fk"  # placeholder (real flow uses `catalogs`)
    catalogs = [("BCpm4QkCCrhY8bxob1fk", "Undergraduate"),
                ("yDxuvyM80rI961SCGzqU", "Graduate")]

    def start_requests(self):
        for cat, gt in self.catalogs:
            yield scrapy.Request(f"{API}/ca/{self.tenant}/catalogs/{cat}",
                                 headers=self._headers(), callback=self.parse_cat,
                                 cb_kwargs={"cat": cat, "gt": gt}, dont_filter=True)

    def parse_cat(self, response, cat, gt):
        data = response.json()
        cf = data.get("coursesFilters") or {"condition": "and", "filters": []}
        body = json.dumps({"condition": "AND", "filters": [cf]})
        eff = (data.get("effectiveStartDate") or "2026-08-24")[:10]
        year = _year(data.get("displayName") or "")
        if year:
            self.academic_year = year
        yield self._mid_request(cat, gt, body, f"{eff},{eff}", 0)

    def _mid_request(self, cat, gt, body, eff, skip):
        params = {"catalogId": cat, "skip": skip, "limit": PAGE, "orderBy": "code",
                  "effectiveDatesRange": eff, "ignoreEffectiveDating": "false",
                  "ignoreTotalCount": "false", "columns": COLUMNS}
        url = f"{API}/cm/{self.tenant}/courses/search/$filters?" + urlencode(params)
        return scrapy.Request(url, method="POST", body=body,
                              headers=self._headers(json_body=True),
                              callback=self.parse_mid,
                              cb_kwargs={"cat": cat, "gt": gt, "body": body,
                                         "eff": eff, "skip": skip}, dont_filter=True)

    def parse_mid(self, response, cat, gt, body, eff, skip):
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
                school_id=self.school_id, department_code=subj, course_code=code,
                course_title=(c.get("longName") or c.get("name") or "").strip(),
                credits=self._credits(c.get("credits") or {}), graduate_type=gt,
                term="", academic_year=self.academic_year,
                source_url=self.origin + "/courses",
            )
        if skip + PAGE < total:
            yield self._mid_request(cat, gt, body, eff, skip + PAGE)


class WhitmanSpider(CoursedogSpider):
    name = "whitman"
    school_id = "3108844"
    slug = "whitman_college__3108844__cc"
    origin = "https://catalog.whitman.edu"
    tenant = "whitman_colleague_ethos"
    catalog_id = "XzIdyKNNwIUTTcA4c6Pe"
    # body/effective/academic_year derived from the catalog object (coursesFilters)


class EasternArizonaSpider(CoursedogSpider):
    name = "eastern_arizona"
    school_id = "2990705"
    slug = "eastern_arizona_college__2990705__cc"
    origin = "https://catalog.eac.edu"
    tenant = "eac_anthology"
    catalog_id = "dpmgj58Ivvz8zQEyQOjN"
    # body/effective/academic_year derived from the catalog object (coursesFilters)


class GreenfieldSpider(CoursedogSpider):
    name = "greenfield"
    school_id = "3037197"
    slug = "greenfield_community_college__3037197__cc"
    origin = "https://catalog.gcc.mass.edu"
    tenant = "gcc_banner_sql"
    catalog_id = "Tq3vInBCVkfzBa5krhiu"
    # body/effective/academic_year derived from the catalog object (coursesFilters)


class NeomedSpider(CoursedogSpider):
    name = "neomed"
    school_id = "3073781"
    slug = "northeast_ohio_medical_university__3073781__cc"
    origin = "https://catalog.neomed.edu"
    tenant = "neomed_banner_sql"
    catalog_id = "AAiqrvKholCprlJDolzR"
    # body/effective/academic_year derived from the catalog object (coursesFilters)


class JamestownSpider(CoursedogSpider):
    name = "jamestown"
    school_id = "3067468"
    slug = "jamestown_community_college__3067468__cc"
    origin = "https://catalog.sunyjcc.edu"
    tenant = "suny_jcc_banner"
    catalog_id = "h1vfdEhiUE1gsEtGuQyJ"
    # body/effective/academic_year derived from the catalog object (coursesFilters)


class UNTDallasSpider(CoursedogSpider):
    # Two catalogs (undergrad + graduate) -> one CSV; per-catalog filter, origin,
    # and graduate_type. body/effective/year derived from each catalog object.
    name = "unt_dallas"
    school_id = "3094311"
    slug = "university_of_north_texas_at_dallas__3094311__cc"
    tenant = "untdallas_peoplesoft"
    origin = "https://undergrad.catalog.untdallas.edu"
    catalog_id = "iy0jnKLU4sRy9tAZl2Xg"  # placeholder (real flow uses `catalogs`)
    catalogs = [("iy0jnKLU4sRy9tAZl2Xg", "Undergraduate",
                 "https://undergrad.catalog.untdallas.edu"),
                ("fXSWetEuBzJ3jRXSr0Tv", "Graduate",
                 "https://graduate.catalog.untdallas.edu")]

    def _hdr(self, origin, json_body=False):
        h = {"Accept": "application/json", "Origin": origin, "Referer": origin + "/"}
        if json_body:
            h["Content-Type"] = "application/json"
        return h

    def start_requests(self):
        for cat, gt, origin in self.catalogs:
            yield scrapy.Request(f"{API}/ca/{self.tenant}/catalogs/{cat}",
                                 headers=self._hdr(origin), callback=self.parse_cat,
                                 cb_kwargs={"cat": cat, "gt": gt, "origin": origin},
                                 dont_filter=True)

    def parse_cat(self, response, cat, gt, origin):
        data = response.json()
        cf = data.get("coursesFilters") or {"condition": "and", "filters": []}
        body = json.dumps({"condition": "AND", "filters": [cf]})
        eff = (data.get("effectiveStartDate") or "2026-08-24")[:10]
        year = _year(data.get("displayName") or "")
        if year:
            self.academic_year = year
        yield self._req(cat, gt, origin, body, f"{eff},{eff}", 0)

    def _req(self, cat, gt, origin, body, eff, skip):
        params = {"catalogId": cat, "skip": skip, "limit": PAGE, "orderBy": "code",
                  "effectiveDatesRange": eff, "ignoreEffectiveDating": "false",
                  "ignoreTotalCount": "false", "columns": COLUMNS}
        url = f"{API}/cm/{self.tenant}/courses/search/$filters?" + urlencode(params)
        return scrapy.Request(url, method="POST", body=body,
                              headers=self._hdr(origin, json_body=True),
                              callback=self.parse_cat_courses,
                              cb_kwargs={"cat": cat, "gt": gt, "origin": origin,
                                         "body": body, "eff": eff, "skip": skip},
                              dont_filter=True)

    def parse_cat_courses(self, response, cat, gt, origin, body, eff, skip):
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
                school_id=self.school_id, department_code=subj, course_code=code,
                course_title=(c.get("longName") or c.get("name") or "").strip(),
                credits=self._credits(c.get("credits") or {}), graduate_type=gt,
                term="", academic_year=self.academic_year,
                source_url=origin + "/courses",
            )
        if skip + PAGE < total:
            yield self._req(cat, gt, origin, body, eff, skip + PAGE)


class PrattSpider(CoursedogSpider):
    name = 'pratt'
    school_id = '3072054'
    slug = 'pratt_institute-main__3072054__cc'
    origin = 'https://pratt-gr.catalog.prod.coursedog.com'
    tenant = 'pratt_colleague'
    catalog_id = 'qWXRahsruzCJek6PTAG0'
