# BNC Virtual Textbook Scraper — Context Document

## What This Scraper Does

Scrapes textbook/course material adoption data from any institution hosted on **bncvirtual.com**. Given a URL like `https://bncvirtual.com/bsol` or a FVCUSNO ID, it discovers all terms, departments, and courses, then extracts textbook details (ISBN, title, author, adoption code) into a CSV.

## File Location

`/workspaces/Akash_streamlit/bnc_textbook_scraper.py`

## Usage

```bash
# Short URL (auto-discovers FVCUSNO)
python bnc_textbook_scraper.py --url https://bncvirtual.com/<short_code>

# Direct FVCUSNO
python bnc_textbook_scraper.py --fvcusno <number>

# With IPEDS school ID override
python bnc_textbook_scraper.py --fvcusno <number> --school-id <ipeds_id>

# All options
python bnc_textbook_scraper.py --url <url> --school-id <id> --batch-size 25 --delay 0.5 --output-dir <path>
```

## Output

CSV at `data/bnc_{fvcusno}_textbooks/bnc_{fvcusno}_textbooks.csv`

## CSV Schema

| Field | Mandatory | Notes |
|---|---|---|
| source_url | Yes | chooseCourses URL |
| school_id | Yes | FVCUSNO or `--school-id` override |
| department_code | Yes | Parsed from course code prefix (e.g. "LAW" from "LAW501") |
| course_code | Yes | Numeric/alphanumeric part (e.g. "501"). Kept as text, preserves leading zeros |
| course_title | Optional | Remaining text after code (e.g. "TORTS" from "LAW501 TORTS") |
| section | Optional | Empty — BNC site doesn't expose section info |
| section_instructor | Optional | Empty — BNC site doesn't expose instructor info |
| term | Optional | e.g. "Spring 2026" |
| isbn | Optional | Normalized: hyphens removed, anti-scrape bogus spans stripped |
| title | Optional | Textbook title |
| author | Optional | Author(s) |
| material_adoption_code | Optional | Raw value (e.g. "Required", "REQUIRED, PREVIOUS PURCHASE POSSIBLE") |
| crawled_on | Yes | ISO 8601 UTC timestamp |

## How the Site Works (BNC Virtual Architecture)

### Key Concepts
- **FVCUSNO**: Institution ID. Each school on bncvirtual.com has a unique numeric FVCUSNO.
- **CSID**: Session ID. Extracted from JavaScript on first page load. Required for all subsequent requests.
- **Encrypted keys**: Department keys and course keys are encrypted server-side. Must use as-is from responses.
- **Cloudflare**: Site is behind Cloudflare — requires `curl_cffi` with Chrome impersonation.

### Three-Step Request Flow

**Step 1 — GET chooseCourses page**
```
GET https://bncvirtual.com/vb_buy2.php?FVCUSNO={id}&ACTION=chooseCourses
```
Extracts from inline `<script>` tags:
- `var CSID = '...'` — session ID
- `selectTerm(...)` calls → term IDs + names (e.g. `'70108', 'Spring 2026'`)
- `selectDept(...)` calls → dept IDs + names + encrypted keys (e.g. `'2173021', 'Birmingham School of Law', 'DXWu7VMfrq8OTV6AZKD0'`)

**Step 2 — POST to get course list (per term/dept)**
```
POST https://bncvirtual.com/vb_crs_srch.php?CSID={csid}&FVCUSNO={id}
Body: FvTerm={term_id}&FvDept={encrypted_dept_key}&R=1
```
Returns JSON:
```json
{
  "success": {
    "<dept_id>": [
      {
        "COURSE": "32758525",
        "COURSE_DESC": "LAW501 TORTS",
        "DATE_DESC": "01/03/2026 - 04/18/2026",
        "COURSE_ENC": "n3KWKD1gW2anSnBBUENXpA--"
      }
    ]
  }
}
```
Note: `dept_courses` can be a **list** (not always a dict with index keys).

**Step 3 — POST to get textbook adoptions (batched, up to 25 courses)**
```
POST https://bncvirtual.com/vb_buy2.php?ACTION=chooseAdoptions&CSID={csid}&FVCUSNO={id}&VCHI=1
Body: fvCourseKeyList={enc_key1},{enc_key2},...
```
Returns full HTML page with textbook details.

### Adoption Page HTML Structure

```
<form id="BookMaterialBuy">
  <!-- Per-course block (repeats): -->
  <input name="supsort_d_desc_1" value="Spring 2026 |div| Birmingham School of Law">
  <input name="supsort_c_desc_1" value="LAW501 TORTS |div| 01/03/2026 - 04/18/2026">
  <div class="cmCourseHeader">...</div>
  <div class="collapse in crs_adpts_collapse">
    <!-- Per-textbook (repeats): -->
    <p class="red text-uppercase">Required</p>
    <h2 class="p0m0 h3">Book Title <span class="nobold small">Edition info</span></h2>
    <table class="cmTableBkInfo">
      <tr><td>Author: </td><td>Author Name</td></tr>
      <tr><td>ISBN-13: </td><td>979-8<span style="display: none;">bogus</span>8-920922-9-6</td></tr>
      <tr><td>ISBN-10: </td><td><span style="display: none;">bogus</span></td></tr>
      <tr><td>Edition/Copyright: </td><td>15TH 24</td></tr>
      <tr><td>Publisher: </td><td>West Academic</td></tr>
    </table>
  </div>
  <br>
  <!-- Next course block... -->
</form>
```

### ISBN Anti-Scraping

BNC injects `<span style="display: none;">bogus</span>` inside ISBN table cells. The scraper strips these hidden spans before extracting the ISBN text, then removes hyphens.

## Dependencies

All in `requirements_scraper.txt`:
- `curl_cffi` — Cloudflare bypass (Chrome TLS fingerprint)
- `beautifulsoup4` + `lxml` — HTML parsing
- `tqdm` — progress bar

## Known Limitations

- **No section/instructor data**: BNC Virtual does not expose section identifiers or instructor names in the adoption flow. These fields are always empty.
- **Single session**: CSID is session-bound. The scraper uses one `curl_cffi` session throughout — don't parallelize requests.
- **Batch limit**: Max 25 courses per chooseAdoptions POST (matches site's `alloted_crs_rows` JS variable).

## Tested Institutions

| Short URL | FVCUSNO | Institution | Courses | Result |
|---|---|---|---|---|
| `/bsol` | 11414 | Birmingham School of Law | 19 | 29 textbook rows, 23 unique ISBNs |

## Adding a New Institution

Just run with the new URL or FVCUSNO:
```bash
python bnc_textbook_scraper.py --url https://bncvirtual.com/<new_short_code>
```
No code changes needed. The scraper auto-discovers terms, departments, and courses for any BNC Virtual institution.
