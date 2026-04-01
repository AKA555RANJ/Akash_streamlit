#!/usr/bin/env python3
"""
Patches the installed FlareSolverr to add a request.fetch_post command.
This executes a JSON POST via JS fetch() inside the browser, bypassing
Akamai Bot Manager which blocks direct HTTP POST requests.

Usage: python3 patch_flaresolverr.py
"""
import importlib
import os
import sys
import time


def patch_service():
    import flaresolverr.flaresolverr_service as svc_mod
    path = svc_mod.__file__

    src = open(path).read()

    # --- Patch 1: register the command ---
    old_dispatch = "    elif req.cmd == 'request.post':\n        res = _cmd_request_post(req)\n    else:"
    new_dispatch = (
        "    elif req.cmd == 'request.post':\n"
        "        res = _cmd_request_post(req)\n"
        "    elif req.cmd == 'request.fetch_post':\n"
        "        res = _cmd_request_fetch_post(req)\n"
        "    else:"
    )
    if "request.fetch_post" not in src:
        if old_dispatch not in src:
            print("[ERROR] Could not find dispatch block to patch — FlareSolverr version mismatch?")
            sys.exit(1)
        src = src.replace(old_dispatch, new_dispatch)
        print("  [+] Registered request.fetch_post command")
    else:
        print("  [=] request.fetch_post already registered")

    # --- Patch 2: add implementation ---
    IMPL = '''
def _cmd_request_fetch_post(req) -> V1ResponseBase:
    """POST via JS fetch() inside FlareSolverr browser - bypasses Akamai bot checks."""
    import json as _j
    if req.postData is None:
        raise Exception("postData is required for request.fetch_post")
    if not req.session:
        raise Exception("session is required for request.fetch_post")

    session, _fresh = SESSIONS_STORAGE.get(req.session, None)
    driver = session.driver
    timeout_s = int(req.maxTimeout) / 1000

    url_safe  = _j.dumps(req.url)
    body_safe = _j.dumps(req.postData)
    js = (
        "window.__fr = null; window.__fe = null;"
        "(async function(){"
        "try{"
        "var r = await fetch(" + url_safe + ",{"
        "method:'POST',"
        "headers:{'Content-Type':'application/json','Accept':'application/json,text/plain,*/*'},"
        "body:" + body_safe
        + "});"
        "var t = await r.text();"
        "window.__fr = {s: r.status, b: t};"
        "}catch(e){window.__fe = e.toString();}"
        "})();"
    )
    driver.run_js(js)

    result = None
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(0.4)
        result = driver.run_js("return window.__fr;")
        err    = driver.run_js("return window.__fe;")
        if result is not None or err:
            if err:
                raise Exception("JS fetch error: " + str(err))
            break

    if result is None:
        raise Exception("JS fetch timed out after " + str(timeout_s) + "s")

    challenge_res = ChallengeResolutionResultT({})
    challenge_res.url      = req.url
    challenge_res.status   = result.get("s", 0)
    challenge_res.response = result.get("b", "")
    challenge_res.cookies  = driver.cookies()
    challenge_res.userAgent = utils.get_user_agent(driver)

    res = V1ResponseBase({})
    res.status  = STATUS_OK
    res.message = "JS fetch POST OK (HTTP " + str(challenge_res.status) + ")"
    res.solution = challenge_res
    return res

'''

    if "def _cmd_request_fetch_post(" not in src:
        marker = "def _cmd_sessions_create("
        if marker not in src:
            print("[ERROR] Could not find insertion point in flaresolverr_service.py")
            sys.exit(1)
        src = src.replace(marker, IMPL + marker)
        print("  [+] Added _cmd_request_fetch_post implementation")
    else:
        print("  [=] _cmd_request_fetch_post function already present")

    open(path, "w").write(src)
    print(f"  [OK] Patched: {path}")


def patch_utils():
    import flaresolverr.utils as utils_mod
    path = utils_mod.__file__
    src = open(path).read()
    changed = False

    if "--no-zygote" in src:
        import re
        src = re.sub(r"\s*options\.set_argument\('--no-zygote'\)[^\n]*\n", "\n", src)
        changed = True
        print("  [+] Removed --no-zygote")

    if '"--auto-open-devtools-for-tabs"' in src:
        import re
        src = re.sub(r'\s*options\.set_argument\("--auto-open-devtools-for-tabs"\)[^\n]*\n', "\n", src)
        changed = True
        print("  [+] Removed --auto-open-devtools-for-tabs")

    if "--disable-blink-features=AutomationControlled" not in src:
        src = src.replace(
            "options.set_argument('--use-gl=swiftshader')",
            "options.set_argument('--use-gl=swiftshader')\n"
            "    options.set_argument('--disable-blink-features=AutomationControlled')\n"
            "    options.set_argument('--disable-features=IsolateOrigins,site-per-process')\n"
            "    options.set_argument('--disable-ipc-flooding-protection')"
        )
        changed = True
        print("  [+] Added stealth flags")

    if changed:
        open(path, "w").write(src)
        print(f"  [OK] Patched: {path}")
    else:
        print("  [=] utils.py already patched")


if __name__ == "__main__":
    print("[*] Patching FlareSolverr utils.py (stealth flags)...")
    patch_utils()
    print("[*] Patching FlareSolverr flaresolverr_service.py (fetch_post command)...")
    patch_service()
    print("[*] All patches applied.")
