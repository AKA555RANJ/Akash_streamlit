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

## Notes for "year not on page" schools
Standard note: "2026-2027 not explicitly shown on the catalog page; scraped whatever
was available at the Catalog URL For AY2026-2027 (col K), which is flagged 2026-2027
Catalog Available = Yes (col I)."

- **Rhodes College (3091104)** — academic_year left blank: no 2026-2027 string appears
  on the courses index or the per-course detail pages. Scraped from col K
  (`https://catalog.rhodes.edu/courses`), col I = Yes. Term also not exposed.

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
- Scottsdale (2990779) — NO 2026-2027 PDF (archive stops at 2025-2026; 2026-2027 is the
  Maricopa web SPA, blocked) -> UNDELIVERABLE here.
These 3 need a different network/IP (where curriqunet.com / curriculum.maricopa.edu resolve).

## Remaining target schools (not yet done)
- Maricopa Mesa CC (2990776) & Paradise Valley (2990782): reachable via FlareSolverr but
  render 2025-2026 landing pages, not a clean 2026-2027 course listing. Needs review.
- UMass Boston (3037211): term-based schedule pages, multi-level; deferred.
- Los Rios (American River 2995968, Folsom Lake 2996053, Sacramento City 2996026):
  "unofficial catalog preview" has NO course-description listing; courses appear only
  inside program-requirement tables (Code|Title|Units) -> dupes/incomplete, no
  descriptions. Needs manager decision on whether a deduped program-table scrape is OK.

## Tooling notes
- FlareSolverr (localhost:8191) used for Cloudflare/403 sites (Williams) and to unmask
  CSU Chico/RIT as CourseLeaf.
- Playwright (system Chrome via channel="chrome") used to capture SPA APIs; revealed
  the eLumen JSON API which the mcckc spider now calls directly.
