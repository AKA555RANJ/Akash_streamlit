# Course Catalog Scraper — Handoff / Session Guide

Single source of truth for resuming this work in a fresh session. Read this first,
then `SCRAPE_NOTES.md` (per-school status log).

---

## 1. Goal
Scrape 2026-2027 **course-catalog** data for colleges whose catalog is available as a
**web** version, one dedicated scraper per school, into a fixed CSV schema.

## 2. Source of truth
Workbook: `/Users/akashranjan/Downloads/Course Catalog - Rational Solver-10.xlsx`
Sheet: **`Catalog-Data`** (~1,768 rows). Relevant columns:

| Col | Field |
|---|---|
| A | school_id (7-digit) |
| B | university_name |
| E | File Name = folder **slug** (ends in `__cc`) |
| I | `2026-2027 Catalog Available?` (TRUE/FALSE) |
| J | Catalog Home Page |
| K | Catalog URL For AY2026-2027 |
| L | Type of Catalog (`Web` / `PDF` / `Web, PDF`) |
| M | Sub Type (platform: AZ Sitemap, Web View Rows, Coursedog, Catod_Navoid, Selfservice, Class Search, CurriQunet, eLumen, SmartCatalogIQ, …) |
| O | Spider Status |
| P | Last Crawled On |

Read it with openpyxl via **system** `python3` (has openpyxl); the venv may not.

## 3. Scope rules (manager-confirmed)
- In scope: **col I = TRUE** AND **col L == "Web"** exactly (skip `PDF` and `Web, PDF`).
- **EXCLUDE** these platforms (col M): `Class Search` (course-search), `Catod_Navoid`
  (acalog catoid/navoid), `AZ Sitemap` (= CourseLeaf), `Coursedog`.
  - **Exclusion DROPPED (manager-directed, see §8b):** the platform-exclusion list is no
    longer in force — previously-excluded platforms (Coursedog, CourseLeaf, acalog, …) are
    now in scope. Coursedog (Mesa/PV/Scottsdale) and CourseLeaf (7 schools) already scraped.
- **Targets**: `Web View Rows`, `CurriQunet`, `eLumen`, `SmartCatalogIQ`, plus genuine
  static blank-Sub-Type rows. `Selfservice` (Banner/Ellucian) = skip.
- Always verify the real platform: some "Web View Rows" rows are CourseLeaf hidden behind
  Cloudflare — render with FlareSolverr and check before building (CSU Chico, RIT were
  unmasked as CourseLeaf and excluded).

## SCHEMA CHANGE 2026-06-23 (manager-directed): CREDITS DROPPED -> 11 columns.
`credits` is no longer collected/emitted (CsvExportPipeline FIELDNAMES, Palomar, IU spider all
updated; spider credit logic left in place but unused). academic_year is now read FROM THE PAGE
when shown (see §4a). Output is now:
```
school_id, department_code, course_code, course_title, graduate_type, term,
academic_year, source_url, backup_filename, crawled_on, updated_on
```

## 4a. academic_year — now PAGE-derived when present (manager/client-directed 2026-06-23)
Client flagged blank academic_year where the page clearly shows it. New rule: capture the catalog
year from the PAGE when shown, else from the URL, else blank. `items.year_from_page(html)` reads it
from the <title> or a YYYY-YYYY next to Edition/Catalog/Bulletin. Wired: CourseLeaf (`2026-2027
Edition`), Clean Catalog/course-teaser (home <title> "College Catalog 2026-2027" — fetch the home
first), Maricopa (catalog displayName "26-27 ..."), IU (= AY of the scraped terms). Coursedog already
derived from displayName. PDF/static keep URL-or-blank.

## 4b. (historical) Output schema — CSV (12 columns) BEFORE the 2026-06-23 credits drop
## (matches manager sample `south_college__3091089__cc.csv`, used 2026-06-16 .. 2026-06-22)
```
school_id, department_code, course_code, course_title, credits, graduate_type, term,
academic_year, source_url, backup_filename, crawled_on, updated_on
```
The CourseItem also has transient fields `raw_html` + `backup_filename` (see §5b). The CSV
columns above are emitted by `CsvExportPipeline`; crawled_on/updated_on/backup_filename are
NOT carried by the spider — the pipelines fill them.

### CSV conventions (manager-confirmed)
- **Split** the scraped code: `department_code` = letters, `course_code` = number only.
  Done in the **shared pipeline** (`format_dept_code`), NOT in spiders.
- **Leading `|`**: store `|AAC` and `|200` (the `|` forces text so `010` is not coerced
  to `10`). PDF extractors import the same `format_dept_code` helper.
- `school_id` = 7-digit col A. `graduate_type` = Undergraduate/Graduate when known else blank.
- **course_title**: cleaned by `CleanCourseTitlePipeline` → `text_utils.clean_course_title`
  (strips trailing `*`, credit text like `(3)`/`3 credits`, trailing punctuation). KNOWN
  edge cases of that method: `C#`→`C`, and `(1868-2000)` year-ranges get dropped — accepted
  (manager's exact method).
- **academic_year**: ONLY from the **start URL** (`items.year_from_url(response.url)` finds
  `20\d\d-20\d\d` / `20\d\d-\d\d`). If the year is not in the URL → **blank**. NEVER scrape
  it from page content/titles/descriptions (Rhodes once wrongly pulled `2016-2017` from a
  course description). Schools that keep a year: UNC Greeley (`/en/2026-2027/`), Los Rios
  (`/2026-2027-unofficial-catalog-preview/`), MCC-KC (`2026-2027/` route), Palomar (PDF URL).
- **term**: keep EXACTLY as the page shows (`Spring`, `Fall`, `Spring, Fall`). NO year
  adjustment (never synthesize `Spring 2026`). Capture it if the page exposes it (Rhodes:
  `div.course__term`). Term logic lives inside the spider.
- **crawled_on / updated_on**: set by `CsvExportPipeline` to
  `datetime.now().strftime("%Y-%m-%d %H:%M:%S")` (both equal). Manual per-school timesheet
  dates are applied post-hoc only when the manager asks.
- **backup_filename**: just the gz filename (e.g. `41b28602.html.gz`), set by the HTML
  pipeline. NOT a path — the folder is `<school_id>/<filename[:2]>/`.
- CSV path: `data/<col-E-slug>/<col-E-slug>.csv` (gitignored; `git add -f`; Git LFS).

## 5. Architecture
ONE shared Scrapy project. Shared spiders are PARAMETERISED base classes (one base + thin
per-school subclasses), NOT one file per school. Files:
```
course_catalog_scrapy/
  scrapy.cfg
  course_catalog_scrapy/
    items.py        # CourseItem (+ raw_html, backup_filename) + year_from_url()
    settings.py     # SPIDER_MIDDLEWARES{AttachRawHtmlMiddleware:100}; ITEM_PIPELINES below
    middlewares.py  # AttachRawHtmlMiddleware: sets item['raw_html']=response.body on every CourseItem
    pipelines.py    # format_dept_code + 3 pipelines (see §5b)
    text_utils.py   # clean_course_title, html_to_text (lazy html2text), extract_course_title_from_long_line
    spiders/
      courseleaf_spider.py        # base CourseLeafSpider + ~25 subclasses (4 layouts, see §9)
      coursedog_spider.py         # base CoursedogSpider + subclasses (UMN-TC/Duluth, USD, Carson-Newman, FSU, WCU-LA)
      maricopa_coursedog_spider.py# Maricopa district Coursedog (Mesa/PV/Scottsdale)
      los_rios_spider.py          # base LosRiosSpider + ARC/FLC/SCC/Cosumnes (program tables)
      <one-off>_spider.py         # southern_ct, unco, nicholls, rhodes, mcckc, williams, umass_boston
  pdf_extractors/palomar_pdf.py   # standalone pdfplumber (imports format_dept_code + year_from_url)
  SCRAPE_NOTES.md / HANDOFF.md
dist/html_backup/   # gz HTML backups (GITIGNORED, local only)  -> see §5b
html_backups/       # per-school <school_id>.zip (pushed to main, LFS)
```

## 5b. Pipelines + HTML backup (added 2026-06-16, manager-required)
ITEM_PIPELINES run in this order:
1. `HTMLCompactStoragePipeline` (100) — gzips `response.body` to
   `dist/html_backup/<school_id>/<hash[:2]>/<hash>.html.gz` (sha256[:8]; deduped by content
   hash so multi-course pages store once). Sets `item['backup_filename']=<hash>.html.gz`,
   then deletes `raw_html`. API spiders store JSON (still the raw source); PDF (Palomar) has none.
2. `CleanCourseTitlePipeline` (200) — `clean_course_title(item['course_title'])`.
3. `CsvExportPipeline` (300) — writes the 12-col CSV; fills crawled_on/updated_on=now.
`AttachRawHtmlMiddleware` (spider middleware) attaches raw_html to every CourseItem in one
place, so spiders don't need to.
**HTML delivery to git:** after a school is crawled, zip its backup folder ->
`html_backups/<school_id>.zip` (contains `<school_id>/<hash[:2]>/<hash>.html.gz`); build with
`cd dist/html_backup && zip -rq ../../html_backups/<school_id>.zip <school_id>`. Push the zip
to main (LFS). `dist/` itself stays gitignored. Sample reference: manager's `3091089.zip`.

## 6. Environment
- venv: `/Users/akashranjan/Akash_streamlit/.venv_catalog` (python 3.9.6, Scrapy 2.13.4,
  pdfplumber, playwright). System `python3` has openpyxl but NOT scrapy.
- Run a spider: `cd course_catalog_scrapy && ../.venv_catalog/bin/scrapy crawl <name>`
  - Smoke test: add `-s CLOSESPIDER_ITEMCOUNT=20` (note: single-page spiders ignore it).
  - Gentle (rate-limited sites): `-s DOWNLOAD_DELAY=2 -s CONCURRENT_REQUESTS=1`.
- Run a PDF extractor: `.venv_catalog/bin/python course_catalog_scrapy/pdf_extractors/<x>.py`
- **FlareSolverr** (for Cloudflare/403 and to render/inspect): already runs at
  `http://localhost:8191`. Start (user's macOS setup):
  ```
  export PATH="/opt/homebrew/bin:$PATH"
  export CHROME_EXE_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  export HEADLESS=false
  python3.12 -m flaresolverr
  ```
  Call: `POST http://localhost:8191/v1 {"cmd":"request.get","url":..,"maxTimeout":80000}`.
  `solution.response` is the rendered HTML string (for JSON endpoints it is parsed
  dict/list). Use sequentially (one request at a time).
- **Playwright**: `.venv_catalog`, launch with `channel="chrome"` (system Chrome, no
  download). Headless works for normal SPAs; Cloudflare sites need FlareSolverr instead.

## 7. Techniques by catalog type (decision tree)
1. **Static HTML, all on one/few pages** → plain Scrapy (Southern CT, UNCO, Nicholls).
2. **Index → detail pages** for missing fields → follow links (Rhodes: credits on detail).
3. **SPA** → use Playwright to capture the JSON/XHR API, then hit the API directly with
   Scrapy/requests (eLumen: `api-prod.elumenapp.com`).
4. **Cloudflare / 403** → FlareSolverr renders it; the spider can POST to FlareSolverr in
   `start_requests` and parse `solution.response` (Williams).
5. **Web unreachable (network/TLS block)** → look for a reachable **2026-2027 PDF** on the
   school's own domain; parse with pdfplumber **column-aware** (crop left/right halves —
   `page.crop((0,0,w/2,h))` and `(w/2,0,w,h)`) to avoid 2-column text merging (Palomar).
6. If no reachable current source exists → mark UNDELIVERABLE in notes, hand to manager.

## 8. Status — ~88 schools scraped & pushed (as of 2026-06-22); see dated batch blocks below
NOTE: the per-platform counts in this paragraph are frozen at 2026-06-16; the BATCH blocks
below (06-16b, 06-17, 06-19→06-21) are the authoritative record of everything added since.
New spiders since: banner_ssb, asu, columbia, modern_campus (course-teaser), enmu,
pdf_catalog, mid_michigan, iu_igps, rice (+ acalog, coursedog/courseleaf subclasses).
Counts by platform: CourseLeaf 26 (UIUC, LMU, CSU San Bernardino/Bakersfield/Dominguez/Chico,
Columbus State, N. Iowa, St Louis CC, UC Davis, Pace, CU Denver, Texas Southern, USC Columbia,
Greenville Tech, TAMU-CC, Frederick CC, Cal Poly, Cuyahoga, DePaul, Stark State, +Moorpark),
Coursedog 9 (Mesa/PV/Scottsdale = Maricopa district; UMN-TC/Duluth, USD, Carson-Newman, FSU,
WCU-LA, +Rowan@Burlington), acalog 3 (Ivy Tech, Trident Tech, CSU Long Beach), Los Rios
program-table 4 (American River, Folsom Lake, Sacramento City, Cosumnes River), SmartCatalogIQ
1 (UNC Greeley), eLumen 1 (MCC-KC), FlareSolverr 1 (Williams), static 3 (Southern CT, Nicholls,
+UW-Seattle), Drupal course-teaser 1 (Emory & Henry), PDF 1 (Palomar).

BATCH 2026-06-16b (7, pushed as course_catalog_bundle.zip @ commit 60e2af4): Moorpark 1106,
UW-Seattle 15749, Emory & Henry 1074, Ivy Tech 2430, Trident 1070, CSU Long Beach 5346,
Rowan@Burlington 801. CAVEAT: in -14 these all turned out OWNED (Moorpark/Emory→Admin,
UW/Rowan→Akash, Ivy/Trident/CSULB→Admin "Completed") — i.e. that batch overlapped claimed work
(ownership not checked at pick time). New code from it stays valid: acalog_spider.py (AcalogSpider)
+ CoursedogSpider catalog-derived body/effective/year when body=None. Angelina (3094051) DROPPED
(Coursedog API returns 0 courses).

BATCH 2026-06-17 (7, CLEAN unassigned per the §11 ownership check, pushed as
course_catalog_bundle.zip — supersedes the 60e2af4 bundle): 6 Indiana University campuses via
IU iGPS sisjee JSON API (`iu_igps_spider.py`) — South Bend 1065, Northwest 801, Kokomo 695,
Southeast 831, East 638, Indianapolis 2737 — plus Rice University 6527 (Banner SWKSCAT static,
`rice_spider.py`). = 13,294 rows. All R=None/O=None in -14 (no Admin/Akash). New shared spiders:
iu_igps_spider.py, rice_spider.py.

BATCHES 2026-06-19 → 06-21 (clean, pushed; RS-15 source; all non-AZ-Sitemap, R not Admin/Akash).
KEY LESSON: trust **col K (the real platform URL)**, not col M (Sub Type) — labels mislead
(e.g. "Class Search"/"Selfservice"/"BLANK" rows are really Banner SSB / Coursedog / course-teaser).
Schools delivered (date / rows / platform / spider):
- UC-Riverside 6834, Yeshiva 4747, Kutztown 3198 — **Banner 9 SSB** course catalog API
  (`banner_ssb_spider.py`): termSelection->term/search->courseSearchResults JSON. Fixes:
  html.unescape titles ("DNA &amp;"->"&"); skip "----" subject-credit placeholders (no digit in num).
  Kutztown needs `mepCode` (PASSHE shared Banner). Term = Fall 2026 course catalog.
- IU-Bloomington 5027 — IU iGPS (`iu_igps_spider.py`, inst IUBLA).
- ASU-Downtown 14808 — **ASU course microservice** (`asu_spider.py`):
  eadvs-cscc-catalog-api.apps.asu.edu/.../search/courses (Authorization: "Bearer null", no real
  auth); per-subject; UNITSMINIMUM/MAXIMUM credits. University-wide catalog.
- Columbia 3515 — **Directory of Classes** (`columbia_spider.py`): 174 Fall-2026 subject pages,
  sections deduped to courses, Points=credits. GOTCHA: subject pages MIX subjects (ITAL page
  lists Hungarian) — take the real subject code from the section link, not the page filename.
- Course-teaser / "Clean Catalog" (Modern Campus Drupal, `modern_campus_spider.py` =
  CourseTeaserSpider): NHTI 620, Northwest Nazarene 909, Full Sail 699, Oakwood 1023 (all
  `/classes?page=N`), Craven 565 (`/courses` — set `classes_path`). a.course-teaser-badge +
  h2.course-teaser-title + div.course-teaser-credits.
- Coursedog (`coursedog_spider.py` subclasses): Whitman 2013, Eastern Arizona 1062, Midland 872
  (undergrad+grad in one spider via `catalogs` list). Rowan@Burlington 801. _credits FIX: use
  creditHours.value / numberOfCredits when min/max are 0 (Anthology tenant). Whitman/EAC/Midland
  body derived from catalog coursesFilters (body=None). EMPTY Coursedog catalogs (skip): Angelina,
  Trocaire (listLength 0).
- Mid Michigan 621 — accordion HTML (`mid_michigan_spider.py`): h3.accordion-header buttons
  "DEPT.NUM Title CREDITS (lec-lab)"; year from /2026-2027-catalog/ URL.
- PDFs (column-aware pdfplumber): ENMU 1583 (`enmu_spider.py`, UG+grad), La Sierra 1410, Regent
  2004, Pacific Union 344 (`pdf_catalog_spider.py` = PdfCatalogSpider base + subclasses). Technique:
  detect 2-column gutter via word x-gap (NOT page midpoint — splits codes); TIGHT parser = wordy
  letter-led title + paren credits "(N units/cr)". Only PDFs with a real per-course Course-
  Descriptions section work.

BATCH 2026-06-21b (bundle-6, 4 schools / 8,613 rows; RS-15 rows 535-594 scan; all R/O empty):
- Greenfield CC 336, UNT Dallas 1550 (UG+grad, two catalogs -> one CSV w/ graduate_type),
  South Mountain CC 6131 (Maricopa 6th college, catalog xl2hM3DML8ekjw7BStjW, offerNumber 7=SMC07,
  == Rio Salado common course bank) — Coursedog. New subclasses GreenfieldSpider/UNTDallasSpider
  (coursedog_spider.py; body/effective/year derived from each catalog's coursesFilters/displayName;
  UNT threads a per-catalog origin so UG/grad source_url differ), SouthMountainSpider
  (maricopa_coursedog_spider.py). Greenfield/UNT academic_year=2026-2027 (displayName); South
  Mountain blank (consistent with Maricopa siblings).
- Wilkes CC 596 — PDF (WilkesSpider in pdf_catalog_spider.py): NC-CC 2-column Course-Descriptions
  section via geometric left/right half-crop (the gutter+top/3 path merged the two columns);
  regex "DEPT NNN Title <3-4 ints>" with CREDIT = LAST int (per the catalog's own legend); section
  bounded dynamically from the "section contains descriptions of courses" intro page so the
  program-requirement tables (same line format) are skipped. 596 courses / 104 subjects, 0
  blanks/dups; academic_year blank (URL year is underscore-separated, like La Sierra/Regent).
  UPDATES the "only 4 PDFs scrapable" finding: NC community-college catalogs that carry a regular
  Course-Descriptions table ARE scrapable (credit = last of class/lab/clinical/credit), unlike the
  degree-plan/check-sheet PDFs. NOT scraped from 535-594: 544 Pima Medical-Las Vegas (Vol XI
  national PDF = known not-scrapable); every other row is I=FALSE (no 2026-2027 catalog).

BATCH 2026-06-22 (bundle-7, 4 schools / 2,634 rows; RS-15 rows 595-677 scan; all R/O empty):
- Alfred University 1725 — Clean Catalog "course-teaser-table" variant (NEW CourseTeaserTableSpider
  in modern_campus_spider.py): div.course-teaser-table-label a = code, h2.course-teaser-table-title
  = title, div.course-teaser-table-credits span.credits = credits; UG (undergraduatecatalog) + grad
  (graduatecatalog) merged into one CSV w/ graduate_type; academic_year blank (no year in URL).
- Northeast Ohio Medical (NEOMED) 457 — Coursedog (NeomedSpider; tenant neomed_banner_sql, catalog
  AAiqrvKholCprlJDolzR = "2026-2027 Catalog"); body/effective/year derived from catalog object;
  AY 2026-2027; fractional medical credits (0.5/1.5) preserved.
- Northeastern Oklahoma A&M 214 — PDF (NortheasternOklahomaSpider in pdf_catalog_spider.py):
  single-column descriptions, regex "DEPT NNNN Title  Class N[, Lab N], Cr. N" with CREDIT = the
  Cr value; section bounded by the "COURSE DESCRIPTIONS" header. AY blank (URL "2025__2027"
  double-underscore evades year_from_url).
- Highland CC 238 — PDF (HighlandSpider): "DEPT NNN Title [GE|SWT|^|@] (credits)" with 1-2 letter
  dept codes; trailing transfer/age markers stripped from title; section bounded by the "Indicates
  the number of credits" legend (skips the earlier program tables of identical format). AY
  2025-2027 (biennial, from URL). NOT scraped from 595-677: South Seattle (Web,PDF biennial),
  Fortis Pensacola/Columbus (known not-scrapable rolling national PDF); rest I=FALSE.
NEW shared layout: CourseTeaserTableSpider (Clean Catalog "table" variant). PDF lesson reinforced:
NC/OK/KS community-college catalogs with a regular Course-Descriptions section ARE scrapable
(bound to the section header to skip the program/requirement tables of the same line format).

BATCH 2026-06-22b (bundle-8, COMBINED 11 schools / 13,374 rows; course_catalog_bundle-8.zip):
OUR 6 (RS-15 rows 595-704, 12-col + backups): Alfred 1725, NEOMED 457, NEOAM 214, Highland 238,
Jamestown 719 (Coursedog suny_jcc_banner / catalog h1vfdEhiUE1gsEtGuQyJ "SUNY JCC 2026-2027";
NEW JamestownSpider), Plaza 300 (PDF; NEW PlazaSpider, "CODE NNN Title N credits", section-bounded).
PLUS 5 from the parallel `catalog_scrape_2627/` tool (3-4 col source -> NORMALIZED here to the 12-col
schema: dept/code |-split, credits parsed from "(N Credits)"/"Credits N", academic_year 2026-2027 from
the filename, source_url from col K, dedup by (dept,code)):
- UConn-Stamford 7445 (CourseLeaf; credits filled; its 7,137 descriptions were DROPPED to fit the
  12-col schema and remain in catalog_scrape_2627/),
- Lord Fairfax/Laurel Ridge 486 (Acalog, credits blank), SUNY Corning 590 (Clean Catalog, credits
  filled), SWAU 760 (Clean Catalog, credits blank), SW Michigan 440 (Acalog, credits blank).
Craven (3055614) + Alfred (3067170) also exist in that tool's output but were ALREADY in our data ->
excluded from the merge (we used our own Alfred 1725). bundle-8 = code/ + csv/ (11) + html/ (our 3
web schools) + pdf/ (our 3 PDF schools); the 5 external schools have no backups (not crawled by us).

BUNDLE-9 2026-06-23 (FULL RE-SCRAPE + QC of all 77 Akash-owned schools in RS-16; 238,659 rows):
Applied the 3 manager-directed changes to every school: (1) drop credits -> 11 col; (2) academic_year
from page (§4a); (3) IU term-coverage = union of all available AY terms (Summer 2026 + Fall 2026 now;
fixes the "less than live" miss — IU-Bloomington 5027 -> 5414). LIVE-COMPLETENESS QC (compare to the
source's own total, NOT the prior count): Coursedog/Maricopa vs API listLength, Banner vs totalCount,
CourseLeaf vs index subjects; for any gap, deep-diff live-unique-codes vs ours (dedup vs real miss).
REAL under-collections caught & fixed (would have passed a prior-count check): **UNI 1919->2812
(+893)** and **DePaul 8790->9186 (+396)** — root cause CODE_RE capped dept at [A-Z]{2,6}; widened to
handle long (THEATRE/TEACHING), two-word (MUS HIST), ampersand (A&S/T&L) and single-letter codes.
Also: Nicholls global dedup (-34 dup), Stark/CourseLeaf no-number-block guard. 3 schools REBUILT as
proper spiders instead of the external `catalog_scrape_2627` CSVs: UConn-Stamford (CourseLeaf UG+grad
7445), SUNY Corning (Clean Catalog 590), SWAU (Clean Catalog UG+grad 760) — all match the external
counts exactly and add academic_year+grad_type. STILL external (FlareSolverr can't beat acalog
anti-bot, 202/0): Lord Fairfax 3106117, SW Michigan 3042629 — normalized to 11-col. EXCLUDED (no data
anywhere): H Councill Trenholm 2988057, The School of Architecture 2990789. Pushed as
course_catalog_bundle-9.zip (code/ + csv/ 77 + html/ 74 backups + pdf/ 8).

PDF REALITY (probed all 34 in-scope PDFs — see SCRAPE_NOTES): only 4 are cleanly scrapable
(ENMU, La Sierra, Regent, Pacific Union — paren-credit descriptions). The other 30 are
degree-plan / check-sheet / prereq formatted: credits extract as page-numbers/contact-hours,
codes scattered in requirement lists -> NOT cleanly extractable (would ship garbage). Do not retry.

STILL NOT SCRAPABLE (confirmed, do not retry): Lord Fairfax (acalog behind bot-challenge
FlareSolverr can't solve), Trocaire/Angelina (empty Coursedog), Cedarville/Fayetteville/Coastal
Carolina (Colleague Self-Service 30-row cap), Duke (Shibboleth login), Madison/Lake Land/WPI/
Columbus State (JS SPAs), Chaffey/Riverside + 2 more (CurriQunet network-block).
CAVEATS: FSU = draft 2026-27 General Bulletin; WCU-LA = calendar-2026 catalog (both
academic_year blank). NOTE: only the last 7 (Cal Poly, Cuyahoga, DePaul, Stark, Cosumnes,
FSU, WCU-LA) have the new 12-col schema + HTML backups + html_backups/<id>.zip; earlier ones
predate that and would need a re-scrape to add backups.
SCOPE: manager said DO NOT scrape `catoid=` (acalog/Catod_Navoid) schools. CurriQunet
(Chaffey 2995976, Riverside 2996025) network-blocked here = UNDELIVERABLE.

--- (historical) original 18-target set: 14 scraped · 2 excluded (CourseLeaf) · 2 undeliverable ---
SCRAPED & DONE (14 from the original target set, pushed to main; CSVs in `data/<slug>/`):

| school_id | school | platform | rows |
|---|---|---|---|
| 3009619 | Southern Connecticut State | Web View Rows (static) | 2023 |
| 3007266 | UNC Greeley | SmartCatalogIQ (multi-level) | 3333 |
| 3035086 | Nicholls State | Web View Rows (subject pages) | 1561 |
| 3091104 | Rhodes College | Web View Rows (index+detail) | 1420 |
| 3050281 | Metropolitan CC-Kansas City | eLumen SPA (API) | 939 |
| 3037159 | Williams College | class-schedule SPA (FlareSolverr) | 1378 |
| 2995726 | Palomar College | PDF (web unreachable) | 932 |
| 3037211 | UMass Boston | Web View Rows (index+detail) | 1569 |
| 2990776 | Mesa CC | Coursedog SPA (JSON API) | 6149 |
| 2990782 | Paradise Valley CC | Coursedog SPA (JSON API) | 6149 |
| 2990779 | Scottsdale CC | Coursedog SPA (JSON API) | 6149 |
| 2995968 | American River | Web View Rows (program tables, derived) | 1579 |
| 2996053 | Folsom Lake | Web View Rows (program tables, derived) | 525 |
| 2996026 | Sacramento City | Web View Rows (program tables, derived) | 1049 |

Notes: Mesa/PV/Scottsdale are ONE Maricopa district Coursedog catalog (common course
numbering -> identical course bank across the three; CSVs differ only by school_id /
source_url). Los Rios three are DERIVED from per-program requirement tables (no standalone
listing exists; incomplete, no descriptions). UMass Boston needs a browser UA (default 403).
See SCRAPE_NOTES.md for per-platform details.

## 8b. Expansion: exclusion list DROPPED (manager direction)
Manager asked to scrape previously-excluded platforms too (work down the in-scope Web rows from
the top). 86 in-scope Web rows total; ~73 were unscraped. Biggest scrapable groups: CourseLeaf
(24, was "AZ Sitemap"), Coursedog (8, technique proven), acalog/Catod_Navoid (10). Built a shared
`courseleaf_spider.py` (handles all 3 CourseLeaf layouts — see SCRAPE_NOTES). 7 CourseLeaf done so
far then PAUSED at manager request (cap of 7): UIUC (3023894, 9452), LMU (3006182, 4665), CSU San
Bernardino (2996062, 4049), CSU Dominguez (2996065, 3035), CSU Bakersfield (2996060, 2461), Columbus
State (3017973, 2349), Northern Iowa (3020616, 1919). NEXT when resumed: more CourseLeaf, then the
Coursedog batch (generic spider; tenants like fsu_peoplesoft, umn_umntc_peoplesoft — capture
catalogId via Playwright like Maricopa), then acalog. Class Search / Self-Service / blank = dynamic
portals, case-by-case. (Note: CSU Chico 2996064 + RIT 3067286 below were excluded as CourseLeaf
when CourseLeaf was out of scope; they are now scrapable with courseleaf_spider if wanted.)

EXCLUDED earlier as CourseLeaf (now scrapable via courseleaf_spider if desired):
CSU Chico (2996064), RIT (3067286).

UNDELIVERABLE here (CurriQunet network block — need a different network/IP where
curriqunet.com resolves): Chaffey (2995976), Riverside (2996025). [Scottsdale was here but
was RECOVERED via the Maricopa Coursedog — only its old curriculum.maricopa.edu URL was
blocked.]

## 9. Per-school implementation notes (selectors / APIs / gotchas)
- **Southern CT**: `div.course-box[id]` → `h2` "CODE NNN - Title", `p.course-credits`,
  `p.last-term-offered` ("Last Term Offered: Spring 2027"). Year from `nav#breadcrumbs a`.
  Term filter (inline in spider): keep only terms within academic_year, keep "not yet
  offered", drop historical. UG + grad pages.
- **UNCO** (SmartCatalogIQ): index `…/course-descriptions/` → subject links = path with one
  segment after `course-descriptions/`. Subject page: `div.courselist h2.course-name` →
  `span` = code, anchor text = title; credits via
  `following-sibling::div[contains(@class,'sc-credithours')][1]//div[@class='credits']`.
  Normalize credits whitespace. UG + graduate catalogs.
- **Nicholls**: 91 subject pages under `…/courses_of_instruction/<subject>/`. Courses are
  `<p>` with `<strong>CODE. Title</strong>` (sometimes two `<strong>` tags) then `C-L-L`
  triple; credits = first number of the triple. Parse via paragraph text up to the triple,
  fallback to combined `<strong>` text. **Rate-limits (429)** → run gentle.
- **Rhodes**: index `div.views-field-field-course-number` has NESTED `<a>` (parser splits
  them) → code = 1st `a::text`, title = 2nd. Credits on detail page
  `div.course__credits span`. NO on-page year → academic_year blank + note. **Antibot
  rate-limits detail pages** (slow; 1,442 requests).
- **MCCKC** (eLumen API): `content_url(route) =
  api-prod.elumenapp.com/catalog/sites/publish/content/<route-with-/-as-,>?tenant=mcckc.elumenapp.com`.
  Crawl: `2026-2027/courses` → `2026-2027/department/<slug>` → `a.navitem`
  (`span.navitem-x-text` = "CODE - Title", href `2026-2027/course/<key>`) → course detail
  has "X.X Credits" + year. Reverse-engineered via Playwright network capture.
- **Williams**: SPA class schedule. Spider POSTs to FlareSolverr to render
  `catalog.williams.edu/list/`. Courses are `a.Accordion` text
  "DEPT NUM - SECTION (SEM) TYPE Title"; dedupe sections → courses; credits NOT in listing
  (blank); year "2026-27" normalized to "2026-2027". Cloudflare-gated (needs FlareSolverr).
- **Palomar** (PDF): `pdf_extractors/palomar_pdf.py`. COURSES section ~pp.203-358, 2-column.
  Column-crop each page; header regex `^(DEPT)\s(NUM)\s+(title)\s+\((units)\)$`. Year from
  PDF URL (`year_from_url(PDF_URL)` → 2026-2027). Web catalog (CurriQunet) unreachable.
- **CourseLeaf** (`courseleaf_spider.py`, ~25 schools): base spider crawls a subject index
  (`base_path` + one path segment) → per-subject pages; single-page catalogs handled too.
  `parse_courseblock` handles 4 layouts in order: (1) `span.detail-code`/`detail-title`/
  `detail-*hours*`; (2) `span.courseblockcode`/`courseblock__title`/`courseblock__hours`
  (Cal Poly); (3) `span.coursetitle`/`coursehours` (CSUSB); (4) free text in
  `p.courseblocktitle` — supports pipe-delimited `CODE | Title | N hours` (DePaul),
  hyphen codes `ACCT-1011` (Cuyahoga), and a sibling `<p class="courseblock">N Credits`
  fallback (Cuyahoga). Hours via `span[class*="detail-"][class*="hours"]`; lecture-lab-credit
  triple `(3-0-3)`→last number; ranges `(1-3)` kept. UG+grad = two start_pages. NEEDS browser
  UA (default Scrapy UA = 403 on many). academic_year = year_from_url (blank for most).
- **Coursedog** (`coursedog_spider.py` + `maricopa_coursedog_spider.py`): POST
  `app.coursedog.com/api/v1/cm/<tenant>/courses/search/$filters?catalogId=&skip=&limit=500&
  effectiveDatesRange=YYYY-08-..&columns=code,subjectCode,courseNumber,longName,credits,...`
  with a JSON filter body, headers `Origin/Referer = <school>.catalog.*`. Public (no auth).
  Capture tenant (URL `/cm/<tenant>/`), catalogId + effectiveDatesRange (query) and the body
  via Playwright network capture of the live `/courses` page; paginate skip/limit until
  listLength. credits = `credits.creditHours.{min,max}` else `.value` else `numberOfCredits`.
  Maricopa = ONE district catalog per college (offerNumber filter); pick the 2026-2027
  catalogId (check displayName — avoid 2025/calendar-year/draft unless intended).
- **Los Rios** (`los_rios_spider.py`): no standalone course list; crawl every
  `…/list-of-programs/<program>` page, parse `<td data-th="Course Code/Course Title/Units">`,
  dedupe by code. Units from cell or trailing `(N)`/`(1 - 4)` in the title. academic_year
  2026-2027 (in the URL). DERIVED/incomplete (no descriptions) — note in SCRAPE_NOTES.

## 10. Gotchas learned
- `curriqunet.com` → connection refused to ALL tools (curl=000, FlareSolverr, headless &
  headful Playwright). `curriculum.maricopa.edu` → times out. These are network/IP blocks.
- `mccd.edu` = **Merced** College, NOT Maricopa — wrong PDF for Scottsdale.
- Python 3.9 f-strings cannot contain backslashes (build regex strings outside the f-string).
- FlareSolverr returns JSON endpoints as parsed objects, HTML as a string — handle both.
- `data/` is gitignored; CSVs are force-added (`git add -f`) and tracked via Git LFS.
- ROBOTSTXT_OBEY robots.txt 500 errors are harmless; the crawl proceeds.

## 11. How to pick & scrape the NEXT batch (e.g. "next 7")
SELECT candidates from `Catalog-Data` (latest workbook, currently `Rational Solver-14.xlsx`):
- In scope: col I = TRUE AND col L == "Web", and NOT already in `data/<slug>/` (see §8 list).
- **OWNERSHIP CHECK (REQUIRED — manager-enforced 2026-06-17):** also require col **O (Spider
  Status) EMPTY** AND col **R (Scraper Name) NOT "Admin" and NOT "Akash"** (cols Q=Total Unique
  Courses, R=Scraper Name, S=Drive Link). Picking an Admin/Akash-owned row = duplicating someone
  else's work. NOTE: as of -14 nearly every clean/easy platform (CourseLeaf, acalog, populated
  Coursedog, static) is already owned by Admin/Akash; the only unassigned rows left are dynamic
  SPAs (IU sisjee [done], ASU [classes API is auth-gated 401], Ellucian Colleague Self-Service
  [JS-rendered], Banner/Class-Search) + network-blocked CurriQunet + dead Angelina Coursedog.
- EXCLUDE: `catoid=` URLs (acalog/Catod_Navoid — manager said skip), CurriQunet
  (`*.curriqunet.com`, network-blocked here), and dynamic portals (Banner Self-Service,
  IU `sisjee`, DukeHub, ASU class-search, MIT/Penn/Moorpark/Emory custom systems).
- PREFER the platforms we can do cleanly (reuse the shared spiders):
  - **CourseLeaf** (col M "AZ Sitemap", or blank but URL is a `catalog.*`/`bulletin.*`
    with `div.courseblock`) → add a `CourseLeafSpider` subclass. Parser handles 4 layouts
    (see §9). PROBE first: fetch a subject page, run `parse_courseblock`, confirm
    code/title/credits non-empty.
  - **Coursedog** (`*.catalog.prod.coursedog.com` or `app.coursedog.com`) → capture
    tenant/catalogId/effectiveDatesRange/filter-body via Playwright (see §9 Maricopa/§ Coursedog),
    add a `CoursedogSpider` subclass. Verify the catalog is 2026-2027 (check displayName /
    effective date — reject calendar-year or 2025 defaults; find the right catalogId).
  - **Los Rios** (`*.losrios.edu/2026-2027-unofficial-catalog-preview/...`) → add a
    `LosRiosSpider` subclass (program-table scrape).
- Probe ~8-10, keep the ones that parse cleanly → pick the cleanest 7. Don't ship a school
  with systemic blank credits / bad codes / wrong year.

BUILD: add a thin subclass to the relevant shared spider (name, school_id, slug,
allowed_domains, start_pages/params). Do NOT write title/credit/code/date logic in the
spider — the pipelines do title-clean, code-split (`|`), crawled_on/updated_on, and HTML
backup automatically (§5b). academic_year comes from the start URL only (§4).

QC EVERY school (both):
- Quality: 0 blank course_code/title, 0 duplicate (dept,code), leading `|`, credits filled,
  academic_year blank-or-`2026-2027`, 12 columns in the §4 order.
- COMPLETENESS (do not skip — this caught TAMU-CC's 60-vs-3298): CourseLeaf → compare index
  subjects vs scraped, code-level check unscraped subjects are empty/cross-listed not missed;
  Coursedog → CSV unique codes == API listLength; Los Rios → programs on index vs scraped.

## 12. How to push to main (data only unless told otherwise)
- Branch is `main`, push directly (manager's workflow).
- CSV: `git add -f data/<slug>/<slug>.csv` (data/ is gitignored; LFS-tracked via
  `data/**/*.csv filter=lfs`).
- HTML backups: `cd dist/html_backup && zip -rq ../../html_backups/<school_id>.zip <school_id>`
  then `git add html_backups/<school_id>.zip` (LFS; dist/ stays gitignored).
- **Commit messages: neutral, NO AI / `Co-Authored-By: Claude` trailer** (manager wants no
  AI attribution anywhere in the repo). Code files were comment-stripped for the same reason.
- Keep **code** commits separate from **data** when the manager asks to hold code; otherwise
  push together. On request, build a single bundle `course_catalog_bundle.zip` with
  `code/` (comment-stripped) + `csv/` + `html/` folders.
- Update `SCRAPE_NOTES.md` (per-school) and this HANDOFF (status/§8) each batch.

## 13. Related memory files
`project-course-catalog-scrapy` (progress), `feedback-catalog-csv-conventions`
(|-prefix / split / per-spider term rules).
