#!/usr/bin/env bash
# Run script for UofPhoenix scraper in GitHub Codespace
# Usage: bash run_uofphoenix_scraper.sh [--fresh]

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "======================================"
echo " UofPhoenix Scraper - Codespace Setup"
echo "======================================"

# --- 1. System deps (Xvfb + Chromium) ---
echo ""
echo "[1/5] Installing system dependencies..."

# Remove broken Yarn repo that causes GPG errors in Codespaces
sudo rm -f /etc/apt/sources.list.d/yarn.list \
           /etc/apt/sources.list.d/yarn.list.save \
           /usr/share/keyrings/yarnkey.gpg 2>/dev/null || true
# Also kill the yarn entry if it's embedded in sources.list
sudo sed -i '/dl.yarnpkg.com/d' /etc/apt/sources.list 2>/dev/null || true

sudo apt-get update -q 2>&1 | grep -v "^W:\|^E:.*yarn" || true
sudo apt-get install -y -q xvfb

# chromium-browser in Ubuntu 24.04 Codespaces is a snap stub — not usable.
# Install real Chromium via playwright's bundled binary instead.
CHROME_BIN=$(find /root/.cache/ms-playwright /home/*/.cache/ms-playwright \
  -name "chrome" -type f 2>/dev/null | head -1)

if [ -z "$CHROME_BIN" ]; then
  echo "    Installing Playwright + Chromium..."
  pip install -q playwright
  python3 -m playwright install chromium
  CHROME_BIN=$(find /root/.cache/ms-playwright /home/*/.cache/ms-playwright \
    -name "chrome" -type f 2>/dev/null | head -1)
fi

# Install Chrome system library dependencies (libatk, libgbm, etc.)
echo "    Installing Chrome system dependencies..."
sudo python3 -m playwright install-deps chromium 2>&1 | tail -5

if [ -z "$CHROME_BIN" ]; then
  echo "[ERROR] Could not find or install Chromium."
  exit 1
fi
echo "    Chrome binary: $CHROME_BIN"

# --- 2. Python deps ---
echo ""
echo "[2/5] Installing Python dependencies..."
pip install -q requests tqdm bottle waitress prometheus_client DrissionPage nodriver

# func-timeout needs manual install (build issues on some systems)
if ! python3 -c "import func_timeout" 2>/dev/null; then
  pip download func-timeout -d /tmp/ft_dl -q
  tar xzf /tmp/ft_dl/func_timeout-*.tar.gz -C /tmp/
  SITE=$(python3 -c 'import site; print(site.getsitepackages()[0])')
  cp -r /tmp/func_timeout-*/func_timeout "$SITE/"
  echo "    func_timeout installed manually"
fi

# xvfbwrapper stub (we manage Xvfb ourselves)
python3 -c "import xvfbwrapper" 2>/dev/null || python3 -c "
import site, os
stub = 'class Xvfb:\n    def __init__(self, *a, **k): pass\n    def start(self): pass\n    def stop(self): pass\n    def __enter__(self): return self\n    def __exit__(self, *a): pass\n'
path = os.path.join(site.getsitepackages()[0], 'xvfbwrapper.py')
open(path, 'w').write(stub)
print('    xvfbwrapper stub created')
"

pip install -q flaresolverr --no-deps

# Patch FlareSolverr utils.py to remove bot-detection signals:
#   - Remove --no-zygote (unusual flag, fingerprint-detectable)
#   - Remove --auto-open-devtools-for-tabs (DevTools open = bot signal for PerimeterX)
#   - Add --disable-blink-features=AutomationControlled
FLARE_UTILS=$(python3 -c "import flaresolverr.utils as u; print(u.__file__)")
echo "    Patching $FLARE_UTILS for stealth..."
python3 - "$FLARE_UTILS" <<'PYEOF'
import sys, re

path = sys.argv[1]
src = open(path).read()

# Remove --no-zygote line
src = re.sub(r"\s*options\.set_argument\('--no-zygote'\)[^\n]*\n", "\n", src)

# Remove --auto-open-devtools-for-tabs line
src = re.sub(r"\s*options\.set_argument\(\"--auto-open-devtools-for-tabs\"\)[^\n]*\n", "\n", src)

# Add stealth flags after --use-gl=swiftshader if not already present
if "--disable-blink-features=AutomationControlled" not in src:
    src = src.replace(
        "options.set_argument('--use-gl=swiftshader')",
        "options.set_argument('--use-gl=swiftshader')\n"
        "    options.set_argument('--disable-blink-features=AutomationControlled')\n"
        "    options.set_argument('--disable-features=IsolateOrigins,site-per-process')\n"
        "    options.set_argument('--disable-ipc-flooding-protection')"
    )

open(path, 'w').write(src)
print("    Stealth patch applied OK")
PYEOF

# Patch FlareSolverr flaresolverr_service.py to add request.fetch_post command
# (uses JS fetch() inside the browser — bypasses Akamai which blocks direct HTTP POSTs)
FLARE_SVC=$(python3 -c "import flaresolverr.flaresolverr_service as s; print(s.__file__)")
echo "    Patching $FLARE_SVC for JS fetch_post..."
python3 - "$FLARE_SVC" <<'PYEOF'
import sys
path = sys.argv[1]
src = open(path).read()

# Add fetch_post command dispatch if not already patched
if "request.fetch_post" not in src:
    src = src.replace(
        "    elif req.cmd == 'request.post':\n        res = _cmd_request_post(req)\n    else:",
        "    elif req.cmd == 'request.post':\n        res = _cmd_request_post(req)\n"
        "    elif req.cmd == 'request.fetch_post':\n        res = _cmd_request_fetch_post(req)\n    else:"
    )

# Add the implementation before _cmd_sessions_create
impl = '''
def _cmd_request_fetch_post(req) -> V1ResponseBase:
    """POST via JS fetch() inside FlareSolverr browser — bypasses Akamai bot checks."""
    import json as _json
    if req.postData is None:
        raise Exception("postData is required for request.fetch_post")
    if not req.session:
        raise Exception("session is required for request.fetch_post")
    session, _ = SESSIONS_STORAGE.get(req.session)
    driver = session.driver
    timeout_s = int(req.maxTimeout) / 1000
    js_run = """
    window.__fetchResult = null; window.__fetchError = null;
    (async function() {
        try {
            const r = await fetch(""" + _json.dumps(req.url) + """, {
                method: "POST",
                headers: {"Content-Type": "application/json", "Accept": "application/json, text/plain, */*"},
                body: """ + _json.dumps(req.postData) + """
            });
            const text = await r.text();
            window.__fetchResult = {status: r.status, body: text};
        } catch(e) { window.__fetchError = e.toString(); }
    })();
    """
    driver.run_js(js_run)
    result = None
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(0.5)
        result = driver.run_js("return window.__fetchResult;")
        err = driver.run_js("return window.__fetchError;")
        if result is not None or err:
            if err:
                raise Exception(f"JS fetch error: {err}")
            break
    if result is None:
        raise Exception(f"JS fetch timed out after {timeout_s}s")
    challenge_res = ChallengeResolutionResultT({})
    challenge_res.url = req.url
    challenge_res.status = result.get("status", 0)
    challenge_res.response = result.get("body", "")
    challenge_res.cookies = driver.cookies()
    challenge_res.userAgent = utils.get_user_agent(driver)
    res = V1ResponseBase({})
    res.status = STATUS_OK
    res.message = f"JS fetch POST OK (HTTP {challenge_res.status})"
    res.result = challenge_res
    return res

'''

if "_cmd_request_fetch_post" not in src:
    src = src.replace("def _cmd_sessions_create(", impl + "def _cmd_sessions_create(")

open(path, 'w').write(src)
print("    fetch_post patch applied OK")
PYEOF

echo "    Python deps OK"

# --- 3. Start Xvfb ---
echo ""
echo "[3/5] Starting Xvfb virtual display..."
pkill -f "Xvfb :99" 2>/dev/null || true
sleep 1

# Codespaces runs as non-root; Xvfb needs /tmp/.X11-unix to exist first
sudo mkdir -p /tmp/.X11-unix
sudo chmod 1777 /tmp/.X11-unix

Xvfb :99 -screen 0 1920x1080x24 &
XVFB_PID=$!
sleep 3

# Verify the display socket actually exists
if [ ! -S /tmp/.X11-unix/X99 ]; then
  echo "[ERROR] Xvfb display :99 socket not found. Xvfb may have failed."
  echo "        Falling back to Chromium headless mode (--headless=new)..."
  kill $XVFB_PID 2>/dev/null || true
  XVFB_PID=""
  USE_HEADLESS=true
else
  USE_HEADLESS=false
  echo "    Xvfb PID: $XVFB_PID (display :99 OK)"
fi

# --- 4. Start FlareSolverr ---
echo ""
echo "[4/5] Starting FlareSolverr (HEADLESS=false, stealth mode)..."
pkill -f "flaresolverr" 2>/dev/null || true
sleep 1

if [ "$USE_HEADLESS" = "true" ]; then
  DISPLAY="" CHROME_EXE_PATH="$CHROME_BIN" HEADLESS=true \
  HOST=0.0.0.0 PORT=8191 LANG=en-US \
    python3 -m flaresolverr > /tmp/flaresolverr.log 2>&1 &
else
  DISPLAY=:99 CHROME_EXE_PATH="$CHROME_BIN" HEADLESS=false \
  HOST=0.0.0.0 PORT=8191 LANG=en-US \
    python3 -m flaresolverr > /tmp/flaresolverr.log 2>&1 &
fi
FLARE_PID=$!

# Wait for FlareSolverr to be ready (print log every 5 attempts)
STATUS=""
LAST_LOG_LINE=0
for i in $(seq 1 40); do
  sleep 3
  # Print any new log lines so user can see what's happening
  CURRENT_LINES=$(wc -l < /tmp/flaresolverr.log 2>/dev/null || echo 0)
  if [ "$CURRENT_LINES" -gt "$LAST_LOG_LINE" ]; then
    tail -n +"$((LAST_LOG_LINE + 1))" /tmp/flaresolverr.log | sed 's/^/    [flaresolverr] /'
    LAST_LOG_LINE=$CURRENT_LINES
  fi
  # Check if process is still running
  if ! kill -0 $FLARE_PID 2>/dev/null; then
    echo "    [!] FlareSolverr process exited early."
    break
  fi
  STATUS=$(curl -s http://localhost:8191/v1 -X POST \
    -H "Content-Type: application/json" \
    -d '{"cmd":"sessions.list"}' 2>/dev/null \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null || true)
  if [ "$STATUS" = "ok" ]; then
    echo "    FlareSolverr ready! (attempt $i)"
    break
  fi
done

if [ "$STATUS" != "ok" ]; then
  echo "[ERROR] FlareSolverr did not start. Last logs:"
  tail -30 /tmp/flaresolverr.log
  exit 1
fi
echo ""
echo "    FlareSolverr startup log:"
cat /tmp/flaresolverr.log

# --- 5. Run scraper ---
echo ""
echo "[5/5] Running scraper..."
echo "--------------------------------------"
DISPLAY=:99 python3 uofphoenix_textbook_scraper.py "$@"

# Cleanup
echo ""
echo "Cleaning up..."
kill $FLARE_PID 2>/dev/null || true
kill $XVFB_PID 2>/dev/null || true

echo "Done."
