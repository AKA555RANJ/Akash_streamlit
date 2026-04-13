import json
import time
from playwright.sync_api import sync_playwright

SITE_BASE = "https://ufl.simplesyllabus.com"
LIBRARY_URL = f"{SITE_BASE}/en-US/syllabus-library"

def main():
    captured = []

    def on_response(response):
        url = response.url
        status = response.status
        content_type = response.headers.get("content-type", "")
        body_preview = ""
        if "json" in content_type or "javascript" not in content_type:
            try:
                body = response.text()
                body_preview = body[:500]
            except Exception:
                body_preview = "<could not read>"
        captured.append({
            "url": url,
            "status": status,
            "content_type": content_type,
            "body_preview": body_preview,
        })
        if any(x in url for x in ["/api/", "/Api/", "graphql", ".json", "syllab"]):
            print(f"  [{status}] {url}")
            if body_preview and "json" in content_type:
                print(f"       {body_preview[:200]}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720},
        )
        page = context.new_page()
        page.on("response", on_response)

        print("=== Loading syllabus library page ===")
        page.goto(LIBRARY_URL, wait_until="networkidle", timeout=60000)
        time.sleep(3)

        title = page.title()
        print(f"\nPage title: {title}")

        body_text = page.inner_text("body")
        print(f"\nVisible page text (first 1000 chars):\n{body_text[:1000]}")

        print("\n=== Looking for interactive elements ===")
        for sel in ["select", "button", "mat-select", "[role='listbox']",
                     "[role='combobox']", ".dropdown", "input[type='search']",
                     "a[href*='syllab']", "[class*='term']", "[class*='filter']",
                     "[class*='select']", "[class*='search']"]:
            els = page.query_selector_all(sel)
            if els:
                print(f"  {sel}: {len(els)} elements")
                for el in els[:5]:
                    try:
                        txt = el.inner_text()[:100]
                        tag = el.evaluate("el => el.tagName")
                        cls = el.get_attribute("class") or ""
                        print(f"    <{tag} class='{cls[:60]}'> {txt}")
                    except Exception:
                        pass

        print("\n=== Clicking interactive elements ===")
        clickable = page.query_selector_all("select, mat-select, [role='combobox'], button, .dropdown-toggle")
        for el in clickable[:10]:
            try:
                txt = el.inner_text()[:50]
                print(f"  Clicking: {txt}")
                el.click()
                time.sleep(2)
            except Exception as e:
                print(f"  Click failed: {e}")

        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(2)

        print("\n=== Links on page ===")
        links = page.query_selector_all("a[href]")
        for link in links[:30]:
            try:
                href = link.get_attribute("href")
                txt = link.inner_text()[:80]
                if href and ("syllab" in href.lower() or "doc" in href.lower() or "course" in href.lower()):
                    print(f"  {href} -> {txt}")
            except Exception:
                pass

        cookies = context.cookies()
        print(f"\n=== Cookies ({len(cookies)}) ===")
        for c in cookies:
            print(f"  {c['name']}: {c['value'][:50]}...")

        html = page.content()

        browser.close()

    print(f"\n=== All captured requests ({len(captured)}) ===")
    for c in captured:
        url = c["url"]
        if any(url.endswith(ext) for ext in [".js", ".css", ".woff", ".woff2", ".png", ".ico", ".svg", ".ttf"]):
            continue
        if "google" in url or "analytics" in url or "fonts." in url:
            continue
        print(f"  [{c['status']}] {c['content_type'][:30]:30s} {url}")
        if c["body_preview"] and "json" in c["content_type"]:
            print(f"       {c['body_preview'][:300]}")

    with open("/tmp/ufl_api_discovery.json", "w") as f:
        json.dump(captured, f, indent=2, default=str)
    print(f"\nFull results saved to /tmp/ufl_api_discovery.json")

if __name__ == "__main__":
    main()
