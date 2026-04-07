"""
Slingshot Education API Discovery Script
========================================
Loads https://howardcc.slingshotedu.com/buy-books in a real browser (non-headless),
intercepts all XHR/fetch network requests, and saves the captured API calls to JSON.

Run this script, interact with the page (select Term, Dept, Course, Section),
then press Enter in the terminal to save results and exit.

Usage:
  python3.12 slingshot_discover.py
"""

import json
import os
import sys
import time
from datetime import datetime

from playwright.sync_api import sync_playwright, Request, Response

TARGET_URL = "https://howardcc.slingshotedu.com/buy-books"
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
API_JSON   = os.path.join(OUTPUT_DIR, "debug_slingshot_api.json")
HTML_FILE  = os.path.join(OUTPUT_DIR, "debug_slingshot.html")

# Capture state
captured_requests  = []
captured_responses = {}  # url -> body


def is_api_request(url: str, resource_type: str) -> bool:
    """Keep XHR/fetch requests plus anything that looks like JSON/API."""
    if resource_type in ("xhr", "fetch"):
        return True
    skip_fragments = (
        "newrelic", "nr-data.net", "hs-scripts", "hubspot",
        ".js", ".css", ".png", ".jpg", ".svg", ".woff", ".ico",
        "google-analytics", "doubleclick",
    )
    return not any(f in url for f in skip_fragments)


def on_request(request: Request):
    if not is_api_request(request.url, request.resource_type):
        return
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "method":    request.method,
        "url":       request.url,
        "headers":   dict(request.headers),
        "post_data": request.post_data,
    }
    captured_requests.append(entry)
    print(f"  [REQ] {request.method} {request.url[:120]}")


def on_response(response: Response):
    if not is_api_request(response.url, response.request.resource_type):
        return
    try:
        body = response.text()
    except Exception:
        body = "<binary or unreadable>"
    captured_responses[response.url] = {
        "status":       response.status,
        "content_type": response.headers.get("content-type", ""),
        "body_preview": body[:2000],
    }


def main():
    print("[*] Slingshot API Discovery")
    print(f"    Target: {TARGET_URL}")
    print(f"    Output: {API_JSON}")
    print()
    print("[*] Launching non-headless Chromium...")
    print("    → Interact with the page: select Term, Dept, Course, Section")
    print("    → Then return here and press Enter to save results.")
    print()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, slow_mo=300)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        # Attach listeners
        page.on("request",  on_request)
        page.on("response", on_response)

        print(f"[*] Navigating to {TARGET_URL} ...")
        page.goto(TARGET_URL, wait_until="networkidle", timeout=60000)

        # Wait a moment for initial data load
        time.sleep(5)

        # Save rendered HTML immediately after load
        rendered_html = page.content()
        with open(HTML_FILE, "w", encoding="utf-8") as f:
            f.write(rendered_html)
        print(f"[*] Rendered HTML saved → {HTML_FILE}")

        # Check for embedded JSON state
        for var in ["__INITIAL_STATE__", "__REDUX_STATE__", "__APP_STATE__", "__data__"]:
            try:
                val = page.evaluate(f"window.{var}")
                if val:
                    embedded_path = os.path.join(OUTPUT_DIR, f"debug_embedded_{var}.json")
                    with open(embedded_path, "w", encoding="utf-8") as f:
                        json.dump(val, f, indent=2, ensure_ascii=False)
                    print(f"[*] Found window.{var} → saved to {embedded_path}")
            except Exception:
                pass

        print()
        print(f"[*] Captured {len(captured_requests)} API requests so far.")
        print()
        print(">>> Interact with the page now (select terms, depts, courses).")
        print(">>> Press Enter here when done to save results and close.")
        input()

        # Re-save HTML after interaction
        rendered_html = page.content()
        with open(HTML_FILE, "w", encoding="utf-8") as f:
            f.write(rendered_html)

        browser.close()

    # Merge requests + responses
    merged = []
    for req in captured_requests:
        resp = captured_responses.get(req["url"], {})
        merged.append({**req, "response": resp})

    with open(API_JSON, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    print(f"\n[*] Saved {len(merged)} captured requests → {API_JSON}")

    # Print summary
    print("\n=== API CALL SUMMARY ===")
    seen_urls = set()
    for entry in merged:
        url = entry["url"]
        if url in seen_urls:
            continue
        seen_urls.add(url)
        ct = entry.get("response", {}).get("content_type", "")
        status = entry.get("response", {}).get("status", "?")
        print(f"  [{entry['method']}] {status} {url[:100]}")
        if "json" in ct:
            preview = entry.get("response", {}).get("body_preview", "")[:200]
            print(f"       JSON: {preview}")

    print("\n[*] Done. Check debug_slingshot_api.json for full details.")


if __name__ == "__main__":
    main()
