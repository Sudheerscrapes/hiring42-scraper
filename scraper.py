import asyncio
import argparse
import json
import csv
import re
from datetime import datetime
from playwright.async_api import async_playwright


# ==============================
# SETTINGS
# ==============================

DEFAULT_KEYWORDS = [
    "sap sac",
    '"sap sac"'
]

HEADLESS_MODE = True


# ==============================
# CLEAN TEXT
# ==============================

def clean(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


# ==============================
# CLOSE POPUP
# ==============================

async def close_popup(page):
    try:
        await page.wait_for_timeout(2000)
        for selector in [
            "button[aria-label='Close']",
            "button[aria-label='close']",
            "button:has-text('Close')",
            "button:has-text('×')",
            "[class*='modal'] button",
            "[class*='dialog'] button",
        ]:
            if await page.locator(selector).count():
                await page.locator(selector).first.click()
                await page.wait_for_timeout(1000)
                break
    except:
        pass


# ==============================
# SEARCH
# ==============================

async def perform_search(page, keyword):

    print("\nSearching:", keyword)

    await page.goto(
        "https://www.hiring42.com/",
        wait_until="domcontentloaded",
        timeout=60000
    )

    # Wait for page to fully settle
    await page.wait_for_timeout(5000)

    await close_popup(page)

    # Try clicking "All Jobs" tab
    try:
        await page.click("text=All Jobs", timeout=5000)
        await page.wait_for_timeout(3000)
    except:
        print("  'All Jobs' tab not found — continuing")

    await close_popup(page)

    # ── Find the search textarea ──────────────────────────────────
    # Try multiple selectors in order of specificity
    textarea_selectors = [
        "textarea[placeholder]",
        "textarea",
        "input[type='search']",
        "input[placeholder*='search' i]",
        "input[placeholder*='job' i]",
        "input[placeholder*='keyword' i]",
    ]

    textarea = None

    for sel in textarea_selectors:
        try:
            await page.wait_for_selector(sel, timeout=8000)
            textarea = sel
            print(f"  Found input via: {sel}")
            break
        except:
            continue

    if not textarea:
        # Debug: dump visible input elements
        inputs = await page.evaluate("""
            () => Array.from(document.querySelectorAll('input,textarea'))
                       .map(el => ({
                           tag: el.tagName,
                           type: el.type,
                           placeholder: el.placeholder,
                           name: el.name,
                           id: el.id,
                           visible: el.offsetParent !== null
                       }))
        """)
        print("  Available inputs on page:", json.dumps(inputs, indent=2))
        raise Exception("No search input found on page")

    # Clear and fill
    await page.click(textarea)
    await page.fill(textarea, "")
    await page.type(textarea, keyword, delay=50)
    await page.wait_for_timeout(500)

    # ── Click Search button ───────────────────────────────────────
    search_btn_selectors = [
        "button:has-text('Search')",
        "button[type='submit']",
        "input[type='submit']",
        "[class*='search'] button",
    ]

    clicked = False
    for btn_sel in search_btn_selectors:
        try:
            await page.click(btn_sel, timeout=5000)
            clicked = True
            print(f"  Clicked search via: {btn_sel}")
            break
        except:
            continue

    if not clicked:
        # Fallback: press Enter
        await page.press(textarea, "Enter")
        print("  Pressed Enter to search")

    # ── Wait for results ──────────────────────────────────────────
    result_selectors = [
        "div.rounded-2xl.border",
        "[class*='job-card']",
        "[class*='card']",
        "article",
    ]

    for res_sel in result_selectors:
        try:
            await page.wait_for_selector(res_sel, timeout=15000)
            print(f"  Results loaded via: {res_sel}")
            break
        except:
            continue


# ==============================
# SCROLL
# ==============================

async def scroll_page(page):
    for _ in range(8):
        before = await page.evaluate("document.body.scrollHeight")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)
        after = await page.evaluate("document.body.scrollHeight")
        if before == after:
            break


# ==============================
# EXTRACT JOBS
# ==============================

async def extract_jobs(page, keyword):

    jobs = []

    cards = await page.query_selector_all("div.rounded-2xl.border")

    if not cards:
        # Fallback selectors
        cards = await page.query_selector_all("[class*='job-card'], article")

    email_pattern = re.compile(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    )

    for card in cards:
        try:
            full_text = clean(await card.inner_text())
            lines = full_text.split("\n")
            title = lines[0] if lines else ""

            location = ""
            for line in lines:
                if "," in line and not line.startswith("Posted"):
                    location = line
                    break

            email_match = email_pattern.search(full_text)
            email = email_match.group(0) if email_match else ""

            tags = []
            badge_elements = await card.query_selector_all("span")
            for badge in badge_elements:
                text = clean(await badge.inner_text())
                if text and text != "ACTIVE":
                    tags.append(text)
            tags_text = " | ".join(tags)

            posted_date = ""
            if "Posted:" in full_text:
                posted_date = (
                    full_text.split("Posted:")[1].split("Score")[0].strip()
                )

            score = ""
            if "Score:" in full_text:
                score = full_text.split("Score:")[1].strip()

            status = "ACTIVE" if "ACTIVE" in full_text else ""

            jobs.append({
                "keyword": keyword,
                "posted_date": posted_date,
                "title": title,
                "location": location,
                "email": email,
                "tags": tags_text,
                "status": status,
                "score": score,
            })

        except Exception as e:
            print("Parse error:", e)

    return jobs


# ==============================
# DEDUPLICATE
# ==============================

def deduplicate_jobs(jobs):
    seen = set()
    unique = []
    for job in jobs:
        key = job["title"] + job["email"]
        if key not in seen:
            seen.add(key)
            unique.append(job)
    return unique


# ==============================
# SAVE FILE
# ==============================

def save_files(jobs, keyword):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_keyword = keyword.replace(" ", "_").replace('"', "")
    csv_file = f"{safe_keyword}_{timestamp}.csv"

    fields = [
        "keyword", "posted_date", "title",
        "location", "email", "tags", "status", "score"
    ]

    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for job in jobs:
            writer.writerow(job)

    print("Saved:", csv_file)


# ==============================
# MAIN
# ==============================

async def scrape(keywords):

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=HEADLESS_MODE,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ]
        )

        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )

        # Hide webdriver flag
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        page = await context.new_page()

        for keyword in keywords:
            try:
                await perform_search(page, keyword)
                await scroll_page(page)
                jobs = await extract_jobs(page, keyword)
                jobs = deduplicate_jobs(jobs)
                print("Jobs found:", len(jobs))
                save_files(jobs, keyword)
            except Exception as e:
                print(f"Error for keyword '{keyword}':", e)

        await browser.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", help="Run single keyword")
    args = parser.parse_args()

    keywords = [args.keyword] if args.keyword else DEFAULT_KEYWORDS
    asyncio.run(scrape(keywords))


if __name__ == "__main__":
    main()
