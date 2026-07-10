"""Helius API Key Farmer — Playwright-based, anti-detect, parallel contexts."""

import asyncio
import json
import re
import random
import sys
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

CONCURRENCY = 10  # number of parallel tabs
ACCOUNT_TYPE = "Personal"  # Helius onboarding "Personal or Developer" step — which option to pick

# Connect to the running "Lam - Chrome (Bot)" instance instead of launching a
# fresh Chromium. Start it first via the desktop shortcut, which runs:
#   chrome.exe --remote-debugging-port=9222 --user-data-dir="C:/Users/ASUS/ChromeDebug"
CDP_URL = "http://localhost:9222"
USE_CDP = True  # False → fall back to launching a fresh Playwright Chromium

ACCOUNTS_FILE = Path(r"C:\Users\ASUS\Documents\Claude Work\autoclick\helius_accounts.txt")
OUTPUT_FILE = Path(r"C:\Users\ASUS\Documents\Claude Work\autoclick\helius_keys.json")
OUTPUT_TXT = Path(r"C:\Users\ASUS\Documents\Claude Work\autoclick\helius_keys.txt")
LOG_FILE = Path(r"C:\Users\ASUS\Documents\Claude Work\autoclick\helius.log")

HELIUS_SIGNUP_URL = "https://dashboard.helius.dev/signup"
HELIUS_API_KEYS_URL = "https://dashboard.helius.dev/api-keys"

# Windows console defaults to cp1252 → force utf-8 so unicode (→, emoji) in
# log messages doesn't raise UnicodeEncodeError on the stdout StreamHandler.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ─── Account parsing ─────────────────────────────────────────────

def parse_accounts(filepath: Path) -> list[tuple[str, str]]:
    """Parse whitespace/newline-separated `email|password` tokens."""
    content = filepath.read_text(encoding="utf-8").strip()
    accounts = []
    for token in content.split():
        if "|" not in token:
            continue
        email, password = token.split("|", 1)
        email, password = email.strip(), password.strip()
        if email and password:
            accounts.append((email, password))
    return accounts


# ─── Anti-detect helpers ─────────────────────────────────────────

async def human_delay(min_s=0.3, max_s=1.0):
    await asyncio.sleep(random.uniform(min_s, max_s))


async def human_type(locator, text: str, min_delay=50, max_delay=150):
    for char in text:
        await locator.press(char)
        await asyncio.sleep(random.uniform(min_delay, max_delay) / 1000)


async def create_stealth_context(browser):
    w = random.randint(1280, 1440)
    h = random.randint(800, 900)
    ctx = await browser.new_context(
        viewport={"width": w, "height": h},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{random.randint(125, 145)}.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        timezone_id="Asia/Ho_Chi_Minh",
        color_scheme="dark",
        permissions=["clipboard-read", "clipboard-write"],
    )
    await ctx.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en', 'vi'] });
        window.chrome = { runtime: {} };
        const origQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (p) =>
            p.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : origQuery(p);
    """)
    return ctx


# ─── Helius signup flow ─────────────────────────────────────────

async def signup_one(browser, email: str, password: str) -> str:
    """Full signup flow for one account. Returns API key or empty string."""
    ctx = await create_stealth_context(browser)
    page = await ctx.new_page()

    try:
        # Step 1: Helius signup page
        log.info(f"Opening Helius signup...")
        await page.goto(HELIUS_SIGNUP_URL, wait_until="domcontentloaded", timeout=30000)
        await human_delay(1, 2)

        # Step 2: Click Google button
        google_btn = page.locator('button:has-text("Google")')
        if await google_btn.count() > 0:
            await google_btn.first.click()
            log.info("Clicked Google")
        else:
            log.error("Google button not found")
            return ""

        await human_delay(0.5, 1.5)

        # Step 3: Google email
        email_input = page.locator('input#identifierId, input[type="email"], input[name="identifier"]').first
        try:
            await email_input.wait_for(timeout=15000)
            await email_input.fill(email)
            log.info(f"Filled email: {email}")

            next_btn = page.locator('#identifierNext, button:has-text("Next"), button:has-text("Tiếp theo")')
            await next_btn.first.click()
            await human_delay(1, 2)
        except Exception as e:
            log.error(f"Email input error: {e}")
            return ""

        # Step 4: Google password
        pw_input = page.locator('input[type="password"]:visible, input[name="Passwd"]:visible').first
        try:
            await pw_input.wait_for(timeout=15000)
            await pw_input.fill(password)
            log.info("Filled password")

            next_btn = page.locator('#passwordNext, button:has-text("Next"), button:has-text("Tiếp theo")')
            await next_btn.first.click()
            await human_delay(1, 2)
        except Exception as e:
            log.error(f"Password input error: {e}")
            return ""

        # Step 5: Handle Google intermediate pages (ToS, speedbump, consent)
        for attempt in range(15):
            await human_delay(1, 2)
            url = page.url

            # Already on Helius? (must START with helius URL, not just contain it in redirect params)
            if url.startswith("https://dashboard.helius.dev"):
                log.info("Reached Helius!")
                break

            # Speedbump / ToS — force click via JS
            if "speedbump" in url or "gaplustos" in url or "termsofservice" in url:
                log.info("Speedbump/ToS page — JS force click")
                await page.evaluate("""
                    window.scrollTo(0, document.body.scrollHeight);
                    const btns = [...document.querySelectorAll('button, input[type="button"], input[type="submit"]')];
                    const btn = btns.find(b => {
                        const t = (b.textContent || b.value || '').toLowerCase();
                        return t.includes('understand') || t.includes('hiểu') || t.includes('agree') || t.includes('đồng ý') || t.includes('accept');
                    });
                    if (btn) { btn.disabled = false; btn.removeAttribute('disabled'); btn.click(); }
                """)
                await human_delay(1.5, 3)
                continue

            # OAuth consent
            if "oauth" in url or "consent" in url:
                log.info("OAuth consent page")
                consent = page.locator('button:has-text("Continue"), button:has-text("Cho phép"), button:has-text("Tiếp tục"), #submit_approve_access')
                try:
                    await consent.first.wait_for(timeout=5000)
                    await human_delay(0.5, 1)
                    await consent.first.click()
                    log.info("Clicked consent")
                    await human_delay(1.5, 3)
                except Exception:
                    pass
                continue

            # Chrome new profile popup / SetSID
            if "SetSID" in url or "signin/chrome" in url:
                log.info("Chrome profile popup")
                no_thanks = page.locator('button:has-text("No thanks"), button:has-text("Không")')
                try:
                    if await no_thanks.count() > 0:
                        await no_thanks.first.click()
                        await human_delay(1, 2)
                except Exception:
                    pass
                continue

            # Generic Google page — try all known buttons via JS
            if "google.com" in url:
                log.info(f"Google page [{attempt}]: {url[:80]}")
                await page.evaluate("""
                    window.scrollTo(0, document.body.scrollHeight);
                    const texts = ['understand', 'hiểu', 'agree', 'đồng ý', 'accept', 'no thanks', 'không',
                                   'continue', 'tiếp tục', 'allow', 'cho phép', 'next', 'tiếp theo'];
                    const btns = [...document.querySelectorAll('button, input[type="button"], input[type="submit"]')];
                    for (const t of texts) {
                        const btn = btns.find(b => (b.textContent || b.value || '').toLowerCase().includes(t));
                        if (btn && btn.offsetParent !== null) {
                            btn.disabled = false;
                            btn.removeAttribute('disabled');
                            btn.click();
                            break;
                        }
                    }
                """)
                await human_delay(1.5, 3)
                continue

        # Step 6: Helius onboarding wizard (new flow from Jul 2026 video):
        #   Choose plan → What are you building → How well do you know Solana → Dashboard
        await human_delay(1, 2)
        log.info(f"Helius URL: {page.url[:80]}")

        for attempt in range(12):
            await human_delay(0.8, 1.5)

            # Already landed on api-keys or dashboard with a project — stop onboarding
            if "api-keys" in page.url or "projectId=" in page.url:
                log.info("Onboarding complete")
                break

            # 6a. "Choose your plan" → Continue with Free plan
            free_plan = page.get_by_text("Continue with Free plan", exact=False)
            if await free_plan.count() > 0:
                await human_delay(0.5, 1)
                await free_plan.first.click()
                log.info("Continue with Free plan")
                await human_delay(1.5, 3)
                continue

            # 6a2. "Personal or Developer" account-type step → pick ACCOUNT_TYPE.
            # Checked AFTER 6a so the plan page (which may list a "Developer" tier)
            # is handled first and never reaches this branch.
            type_order = [ACCOUNT_TYPE, "Developer" if ACCOUNT_TYPE == "Personal" else "Personal"]
            picked_type = None
            for label in type_order:
                opt = page.get_by_text(label, exact=False)
                if await opt.count() > 0:
                    try:
                        await opt.first.click()
                        picked_type = label
                        await human_delay(0.4, 0.9)
                        break
                    except Exception:
                        continue
            if picked_type:
                log.info(f"Account type: picked {picked_type}")
                nxt = page.locator('button:has-text("Continue"), button:has-text("Next"), button:has-text("Get started")')
                if await nxt.count() > 0:
                    try:
                        await nxt.first.click()
                    except Exception:
                        pass
                await human_delay(1.5, 3)
                continue

            # 6b. "What are you building?" → pick a category then Continue
            if await page.get_by_text("What are you building", exact=False).count() > 0:
                for cat in ("Infrastructure", "AI agents", "DeFi & trading", "Something else"):
                    card = page.get_by_text(cat, exact=False)
                    if await card.count() > 0:
                        try:
                            await card.first.click()
                            log.info(f"Picked build category: {cat}")
                            await human_delay(0.4, 0.9)
                            break
                        except Exception:
                            continue
                cont = page.locator('button:has-text("Continue")')
                if await cont.count() > 0:
                    await cont.first.click()
                    await human_delay(1.5, 3)
                continue

            # 6c. "How well do you know Solana?" → pick "Experienced builder"
            if await page.get_by_text("know Solana", exact=False).count() > 0:
                opt = page.get_by_text("Experienced builder", exact=False)
                if await opt.count() == 0:
                    opt = page.get_by_text("New to Solana", exact=False)
                if await opt.count() > 0:
                    await opt.first.click()
                    log.info("Picked Solana experience")
                    await human_delay(1, 2)
                nxt = page.locator('button:has-text("Continue"), button:has-text("Finish"), button:has-text("Get started")')
                if await nxt.count() > 0:
                    await nxt.first.click()
                    await human_delay(1.5, 3)
                continue

            # 6c2. "/setup" contact-channel screen → skip Slack integration.
            # This screen's buttons ARE the choices (no "Continue"), so 6d
            # generic misses it. Pick "Just email for now" to reach the dashboard.
            email_only = page.get_by_text("Just email for now", exact=False)
            if await email_only.count() > 0:
                try:
                    await email_only.first.click()
                    log.info("Setup: Just email for now (skip Slack)")
                    await human_delay(1.5, 3)
                    continue
                except Exception:
                    pass

            # Fallback: legacy onboarding buttons
            legacy = page.locator('button:has-text("Create free project"), button:has-text("Get Started")')
            if await legacy.count() > 0:
                await legacy.first.click()
                log.info("Legacy onboarding button")
                await human_delay(2, 4)
                continue

            # 6d. Generic pass-through for any UNRECOGNIZED multi-choice step
            # (covers "Personal or Developer" and future onboarding screens even if
            # exact text differs): pick the first selectable option, then Continue.
            nxt = page.locator(
                'button:has-text("Continue"), button:has-text("Next"), '
                'button:has-text("Get started"), button:has-text("Finish")'
            )
            if await nxt.count() > 0:
                choice = page.locator(
                    '[role="radio"], [role="option"], label:has(input[type="radio"]), '
                    'div[class*="card" i], button[class*="card" i], '
                    'div[class*="option" i], [data-testid*="option" i]'
                ).first
                try:
                    if await choice.count() > 0:
                        await choice.click(timeout=2000)
                        await human_delay(0.3, 0.7)
                except Exception:
                    pass
                try:
                    await nxt.first.click()
                    log.info("Generic onboarding step → picked option + Continue")
                    await human_delay(1.5, 3)
                    continue
                except Exception:
                    pass

        # Wait for any project creation redirect to settle
        for _ in range(15):
            if "project-creation" in page.url:
                log.info("Creating project...")
                await human_delay(2, 3)
            else:
                break

        # Step 7: Go to API Keys page
        await human_delay(1.5, 3)
        if "api-keys" not in page.url:
            await page.goto(HELIUS_API_KEYS_URL, wait_until="domcontentloaded", timeout=15000)
            await human_delay(1.5, 3)

        # Step 8: Extract API key
        api_key = await extract_api_key(page)
        return api_key

    except Exception as e:
        log.error(f"Error: {e}")
        return ""
    finally:
        await ctx.close()


async def extract_api_key(page) -> str:
    """Extract API key from Helius /api-keys page using clipboard intercept."""
    await human_delay(0.5, 1.5)
    log.info("Extracting API key...")

    # Monkey-patch clipboard
    try:
        await page.evaluate("""
            window.__copiedKey = '';
            if (navigator.clipboard && navigator.clipboard.writeText) {
                const orig = navigator.clipboard.writeText.bind(navigator.clipboard);
                navigator.clipboard.writeText = async (text) => {
                    window.__copiedKey = text;
                    return orig(text);
                };
            }
        """)
    except Exception:
        pass

    # Try clicking copy buttons
    copy_selectors = [
        'button[aria-label*="opy" i]',
        'button[title*="opy" i]',
        '[data-testid*="copy" i]',
    ]
    for sel in copy_selectors:
        try:
            btn = page.locator(sel)
            if await btn.count() > 0:
                await btn.first.click()
                await human_delay(0.5, 1)
                copied = await page.evaluate("window.__copiedKey")
                if copied and len(copied) > 15:
                    log.info(f"Key from clipboard: {copied[:16]}...")
                    return copied.strip()
        except Exception:
            continue

    # Try 2nd icon button in key row (eye=1st, copy=2nd)
    try:
        icon_btns = page.locator('tr button:has(svg), td button:has(svg)')
        if await icon_btns.count() >= 2:
            await icon_btns.nth(1).click()
            await human_delay(0.5, 1)
            copied = await page.evaluate("window.__copiedKey")
            if copied and len(copied) > 15:
                log.info(f"Key from 2nd icon: {copied[:16]}...")
                return copied.strip()
    except Exception:
        pass

    # Click all small icon buttons to reveal key
    try:
        icon_btns = page.locator('button:has(svg)')
        count = await icon_btns.count()
        for i in range(min(count, 10)):
            try:
                bbox = await icon_btns.nth(i).bounding_box()
                if bbox and bbox['width'] < 50 and bbox['height'] < 50:
                    await icon_btns.nth(i).click()
                    await human_delay(0.3, 0.5)
            except Exception:
                continue
    except Exception:
        pass

    # Scan page text for key patterns
    try:
        text = await page.inner_text("body")
        url = page.url

        # Long alphanumeric strings
        for m in re.findall(r'[a-zA-Z0-9_-]{30,}', text):
            if m.startswith(("http", "data:", "function", "return", "project", "shadow")):
                continue
            if m in url:
                continue
            if any(x in m.lower() for x in ["classname", "style", "color", "button", "container"]):
                continue
            log.info(f"Key from text: {m[:16]}...")
            return m

        # UUID pattern
        for m in re.findall(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', text):
            if m not in url:
                log.info(f"Key UUID: {m[:16]}...")
                return m
    except Exception:
        pass

    # Diagnostics: capture where the flow stalled so onboarding gaps can be fixed.
    try:
        dbg = Path(r"C:\Users\ASUS\Documents\Claude Work\autoclick\debug")
        dbg.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%H%M%S_%f")
        await page.screenshot(path=str(dbg / f"stuck_{stamp}.png"))
        btns = await page.evaluate(
            "[...document.querySelectorAll('button,[role=button],a')]"
            ".map(b => (b.textContent||'').trim()).filter(t => t && t.length < 40).slice(0, 30)"
        )
        log.warning(f"STUCK at {page.url[:70]} | clickables: {btns}")
    except Exception:
        pass

    log.warning("Could not extract API key")
    return ""


# ─── Output helpers ──────────────────────────────────────────────

def load_keys() -> list[dict]:
    if OUTPUT_FILE.exists():
        return json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    return []


_file_lock = asyncio.Lock()


async def save_result(email: str, api_key: str, keys: list[dict]):
    async with _file_lock:
        keys.append({
            "email": email,
            "api_key": api_key,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        OUTPUT_FILE.write_text(json.dumps(keys, indent=2, ensure_ascii=False), encoding="utf-8")

        with open(OUTPUT_TXT, "a", encoding="utf-8") as f:
            f.write(f"{email}|{api_key}\n")


def get_completed_emails() -> set[str]:
    keys = load_keys()
    return {k["email"] for k in keys if k["api_key"] != "FAILED"}


def get_failed_emails() -> list[str]:
    keys = load_keys()
    return [k["email"] for k in keys if k["api_key"] == "FAILED"]


def get_account_map(filepath: Path) -> dict[str, str]:
    accounts = parse_accounts(filepath)
    return {email: pw for email, pw in accounts}


# ─── Main ────────────────────────────────────────────────────────

async def run(retry_failed=False):
    from playwright.async_api import async_playwright

    log.info("=" * 60)
    if retry_failed:
        log.info(f"Helius — RETRY FAILED — {CONCURRENCY}x Parallel")
    else:
        log.info(f"Helius API Key Farmer — {CONCURRENCY}x Parallel")
    log.info("=" * 60)

    account_map = get_account_map(ACCOUNTS_FILE)
    all_accounts = parse_accounts(ACCOUNTS_FILE)
    log.info(f"Total accounts: {len(all_accounts)}")

    if retry_failed:
        failed = get_failed_emails()
        to_process = [(e, account_map[e]) for e in failed if e in account_map]
        log.info(f"Retrying {len(to_process)} failed accounts")
    else:
        to_process_raw = all_accounts
        completed = get_completed_emails()
        to_process = [(e, p) for e, p in to_process_raw if e not in completed]
        log.info(f"Already done: {len(completed)}, to process: {len(to_process)}")

    keys = load_keys()
    stats = {"ok": 0, "fail": 0}
    total = len(to_process)
    sem = asyncio.Semaphore(CONCURRENCY)

    async def process_one(browser, idx, email, password):
        async with sem:
            log.info(f"[{idx}/{total}] {email}")
            api_key = await signup_one(browser, email, password)

            if api_key:
                await save_result(email, api_key, keys)
                stats["ok"] += 1
                log.info(f"OK: {email} → {api_key[:16]}...")
            else:
                await save_result(email, "FAILED", keys)
                stats["fail"] += 1
                log.warning(f"FAILED: {email}")

            done = stats["ok"] + stats["fail"]
            log.info(f"Stats: {stats['ok']} ok / {stats['fail']} fail / {total - done} left")
            await asyncio.sleep(random.uniform(0.5, 1.5))

    async with async_playwright() as p:
        connected = False
        if USE_CDP:
            try:
                browser = await p.chromium.connect_over_cdp(CDP_URL)
                connected = True
                log.info(f"Connected to Chrome Bot via CDP: {CDP_URL}")
            except Exception as e:
                log.error(f"CDP connect failed ({e}). Start 'Lam - Chrome (Bot)' first.")
                log.info("Falling back to fresh Chromium launch...")

        if not connected:
            browser = await p.chromium.launch(headless=False)

        tasks = []
        for idx, (email, password) in enumerate(to_process, start=1):
            tasks.append(process_one(browser, idx, email, password))

        await asyncio.gather(*tasks)

        # For a CDP connection this just detaches (Chrome keeps running);
        # for a launched Chromium it terminates the process.
        await browser.close()

    log.info(f"DONE — {stats['ok']} success, {stats['fail']} failed")
    log.info(f"Keys saved to: {OUTPUT_FILE}")


def main():
    retry = "--retry" in sys.argv
    asyncio.run(run(retry_failed=retry))


if __name__ == "__main__":
    main()
