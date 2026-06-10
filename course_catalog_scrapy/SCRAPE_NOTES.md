# Course Catalog Scrape Notes

Source: `Catalog-Data` sheet. In scope = `2026-2027 Catalog Available?` (col I) = TRUE
and `Type of Catalog` (col L) = `Web`. Each school scraped from its
`Catalog URL For AY2026-2027` (col K).

## academic_year policy
- `academic_year` is scraped from the page when the catalog shows it.
- If the page shows no explicit 2026-2027, `academic_year` is left blank (never
  hard-coded); course data is still scraped because col I = Yes and we crawl the
  col K AY2026-2027 URL. Such schools are flagged below as "year not on page".

## Status

| school_id | school | platform | status | rows | year on page | note |
|---|---|---|---|---|---|---|
| 3009619 | Southern Connecticut State University | Web View Rows | done | 2023 | yes (2026-2027) | UG+grad; term filtered to 2026-2027 + not-yet-offered |
| 3007266 | University of Northern Colorado | SmartCatalogIQ | done | 3333 | yes (2026-2027) | UG+grad subject pages; credits inline |
| 3035086 | Nicholls State University | Web View Rows | done | 1561 | yes (2026-2027) | 91 subject pages; credits = first of C-L-L triple; 40 blank credits (no triple) |
| 3091104 | Rhodes College | Web View Rows | done | 1420 | NO | year not on page (see note below); index + per-course detail pages for credits; term not exposed; site antibot rate-limits detail pages |
| 3050281 | Metropolitan CC-Kansas City | eLumen (SPA) | done | 939 | yes (2026-2027) | reverse-engineered eLumen JSON API (api-prod.elumenapp.com): courses -> departments -> course detail; credits inline |
| 3037159 | Williams College | class schedule (SPA) | done | 1378 | yes (2026-2027) | FlareSolverr-rendered /list/; section listing deduped to courses; credits NOT in listing (left blank); also has a PDF catalog |
| 2995726 | Palomar College | PDF (CurriQunet web unreachable) | done | 932 | yes (2026-2027) | web catalog (CurriQunet) network-unreachable; scraped the 2026-2027 PDF instead (pdf_extractors/palomar_pdf.py, column-aware); code/title/credits |
| 3037211 | University of Massachusetts-Boston | Web View Rows | done | 1569 | NO | UG+grad; 2026 Fall (col K); subjects -> listing -> course_info detail (credits in span.class-div-info); browser UA needed (default 403); year not on page |
| 2990776 | Mesa Community College | Coursedog (SPA JSON API) | done | 6149 | yes (2026-2027) | Maricopa district Coursedog; catalogId RQzc6b76uitYyaXJt27C, offerNumber=4; see Maricopa note below |
| 2990782 | Paradise Valley Community College | Coursedog (SPA JSON API) | done | 6149 | yes (2026-2027) | same Maricopa tenant; catalogId HirEuyo6daAN3xmWWf45, offerNumber=9 |
| 2990779 | Scottsdale Community College | Coursedog (SPA JSON API) | done | 6149 | yes (2026-2027) | RECOVERED (was UNDELIVERABLE); catalogId n1NpLQ9WGeg5jvC66ZRP, offerNumber=5 |
| 2995968 | American River College | Web View Rows (program tables) | done | 1579 | yes (2026-2027) | DERIVED: courses only in per-program requirement tables, deduped by code; no descriptions |
| 2996053 | Folsom Lake College | Web View Rows (program tables) | done | 525 | yes (2026-2027) | DERIVED: per-program tables, deduped; smallest Los Rios college |
| 2996026 | Sacramento City College | Web View Rows (program tables) | done | 1049 | yes (2026-2027) | DERIVED: per-program tables, deduped |

## Maricopa Coursedog note (Mesa, Paradise Valley, Scottsdale)
Maricopa CCD runs ONE Coursedog tenant (`maricopa_peoplesoft_direct`). Each college is a
separate catalog (distinct `catalogId`) selected by an `offerNumber` filter, served by a
public JSON API (`app.coursedog.com/api/v1/cm/<tenant>/courses/search/$filters`, POST, no
auth — gated on `Origin`/`Referer`). API reverse-engineered via Playwright network capture.
Because Maricopa uses **district-wide common course numbering**, all three colleges publish
an identical course bank (6149 rows; code/title/credits match exactly across colleges — the
institution differs: MCC04 / PVC09 / SCC05). The three CSVs therefore differ only by
`school_id` and `source_url`. `academic_year` = `2026-2027` parsed from the catalog
displayName ("26-27 <College> Catalog"). **Scope note:** HANDOFF s3 lists Coursedog as
EXCLUDED; these were scraped per explicit manager/user direction (corrected col K link).

## Los Rios note (American River, Folsom Lake, Sacramento City)
The "2026-2027 unofficial catalog preview" has NO standalone course-description listing and
no separate course catalog (the official home redirects to the preview). Courses appear only
inside per-program requirement tables (`Course Code | Course Title (units) | Units`). The
spider crawls every `list-of-programs/<program>` page and dedupes by course code. Result is
DERIVED and INCOMPLETE: only courses cited by some program's requirements, no descriptions,
credits = units (single value or range like `1-3`, taken from the Units cell or a trailing
`(N)`/`(1 - 4)` in the title), `graduate_type=Undergraduate`, `term` blank. Official catalog
expected ~Aug 2026.

## Notes for "year not on page" schools
Standard note: "2026-2027 not explicitly shown on the catalog page; scraped whatever
was available at the Catalog URL For AY2026-2027 (col K), which is flagged 2026-2027
Catalog Available = Yes (col I)."

- **Rhodes College (3091104)** — academic_year left blank: no 2026-2027 string appears
  on the courses index or the per-course detail pages. Scraped from col K
  (`https://catalog.rhodes.edu/courses`), col I = Yes. Term also not exposed.
- **University of Massachusetts-Boston (3037211)** — academic_year left blank: the pages
  expose only the term ("2026 Fall", the col K term) with no 2026-2027 string. Scraped
  from col K, col I = Yes. `term` = `2026 Fall`.

## Excluded after FlareSolverr inspection (actually CourseLeaf)
These were labeled "Web View Rows" but the rendered page is CourseLeaf -> out of scope:
- CSU Chico (2996064) — courseleaf (was hidden behind Cloudflare)
- RIT (3067286) — courseleaf (served 2025-2026)

## Web catalog UNREACHABLE from this environment (network-level block)
CurriQunet (curriqunet.com) and Maricopa (curriculum.maricopa.edu) refuse/time out for
every tool here (curl=000, FlareSolverr, headless+headful Playwright). PDF fallback used
where a 2026-2027 PDF exists:
- Palomar (2995726) — DONE via 2026-2027 PDF (web is CurriQunet, blocked).
- Chaffey (2995976) — NO 2026-2027 PDF published (catalog page lists PDFs only thru
  2025-2026; 2026-2027 is CurriQunet-only) -> UNDELIVERABLE from this environment.
- Riverside City (2996025) — NO 2026-2027 PDF (CurriQunet-only) -> UNDELIVERABLE here.
- ~~Scottsdale (2990779)~~ — **RECOVERED**: its 2026-2027 catalog is on the Maricopa
  Coursedog (`scottsdalecc.catalog.maricopa.edu`), which IS reachable (only the old
  `curriculum.maricopa.edu` URL was blocked). Done — see Maricopa Coursedog note above.
Chaffey & Riverside still need a different network/IP (where curriqunet.com resolves).

## Remaining target schools — ALL RESOLVED
- Mesa CC (2990776), Paradise Valley (2990782), Scottsdale (2990779): DONE via Maricopa
  Coursedog JSON API (the col K link for Mesa was corrected to the Coursedog catalog).
- UMass Boston (3037211): DONE — static multi-level catalog (courses.umb.edu).
- Los Rios (American River 2995968, Folsom Lake 2996053, Sacramento City 2996026): DONE
  via deduped program-table scrape (derived/incomplete — see Los Rios note above).
- Still UNDELIVERABLE here: Chaffey (2995976), Riverside (2996025) — CurriQunet network block.

## Tooling notes
- FlareSolverr (localhost:8191) used for Cloudflare/403 sites (Williams) and to unmask
  CSU Chico/RIT as CourseLeaf.
- Playwright (system Chrome via channel="chrome") used to capture SPA APIs; revealed
  the eLumen JSON API which the mcckc spider now calls directly.
