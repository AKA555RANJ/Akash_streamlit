"""
Smoke test for BNC Virtual spider.
For each URL: discovers FVCUSNO → inits session → fetches first term's courses.
Does NOT write any CSV. Exits cleanly with a pass/fail summary.
"""
import sys
import traceback

from bnc_textbook_scraper import (
    make_session,
    resolve_fvcusno,
    discover_fvcusno,
    init_session,
    fetch_courses,
    fs_bootstrap,
    FLARESOLVERR_DEFAULT_URL,
)

URLS = [
    "https://bncvirtual.com/vb_home.php?FVCUSNO=2348",
    "https://bncvirtual.com/vb_home.php?FVCUSNO=2663",
    "https://www.mystcstore.com/home",
    "https://bncvirtual.com/pacenyc.htm",
    "https://bncvirtual.com/abilenechristian",
]

USE_FLARESOLVERR = True
FLARESOLVERR_URL = FLARESOLVERR_DEFAULT_URL


def probe(url: str) -> dict:
    result = {"url": url, "fvcusno": None, "terms": [], "depts": 0, "sample_courses": 0, "error": None}
    try:
        raw = resolve_fvcusno(url, None)
        session = make_session()

        if raw.isdigit():
            fvcusno = raw
        else:
            print(f"    Resolving FVCUSNO from {raw}...")
            try:
                fvcusno = discover_fvcusno(session, raw)
            except Exception as e:
                result["error"] = f"FVCUSNO discovery failed: {e}"
                return result

        result["fvcusno"] = fvcusno
        print(f"    FVCUSNO: {fvcusno}")

        print(f"    Trying plain curl_cffi first...")
        try:
            info = init_session(session, fvcusno)
        except Exception as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if USE_FLARESOLVERR and status == 403:
                print(f"    Got 403 — falling back to FlareSolverr...")
                cookies, ua, preloaded_html = fs_bootstrap(fvcusno, FLARESOLVERR_URL)
                session = make_session(cookies=cookies, user_agent=ua)
                info = init_session(session, fvcusno, preloaded_html=preloaded_html)
            else:
                raise

        terms = info["terms"]
        depts = info["depts"]
        result["terms"] = [t[1] for t in terms]
        result["depts"] = len(depts)

        if not terms or not depts:
            result["error"] = "No terms or depts found"
            return result

        term_id, term_name = terms[0]
        dept_id, dept_name, dept_enc = depts[0]
        print(f"    Probing first combo: term={term_name!r}, dept={dept_name!r}")
        courses = fetch_courses(session, info["csid"], fvcusno, term_id, dept_id, dept_enc, delay=0.3)
        result["sample_courses"] = len(courses)

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    return result


def main():
    print("=" * 65)
    print("BNC Virtual Smoke Test")
    print("=" * 65)

    results = []
    for url in URLS:
        print(f"\n[>] {url}")
        r = probe(url)
        results.append(r)
        if r["error"]:
            print(f"    FAIL  — {r['error']}")
        else:
            print(f"    PASS  — FVCUSNO={r['fvcusno']}, terms={r['terms']}, "
                  f"depts={r['depts']}, sample_courses={r['sample_courses']}")

    print("\n" + "=" * 65)
    print("SUMMARY")
    print("=" * 65)
    passed = 0
    for r in results:
        status = "PASS" if not r["error"] else "FAIL"
        if status == "PASS":
            passed += 1
        print(f"  {status}  {r['url']}")
        if r["fvcusno"]:
            print(f"       FVCUSNO={r['fvcusno']}, terms={r['terms']}")
        if r["error"]:
            print(f"       Error: {r['error']}")
    print(f"\n{passed}/{len(URLS)} passed")


if __name__ == "__main__":
    main()
