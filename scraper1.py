import asyncio
import argparse
import csv
import re
from datetime import datetime
from playwright.async_api import async_playwright


# ==============================
# SETTINGS
# ==============================

DEFAULT_KEYWORDS = [
    "sap mm",
    '"sap mm"'
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

        await page.wait_for_timeout(3000)

        for selector in [
            "button[aria-label='Close']",
            "button[aria-label='close']",
            "button.close",
            "[class*='modal'] button",
            "[class*='popup'] button",
        ]:

            try:

                loc = page.locator(selector)

                if await loc.count():

                    await loc.first.click()

                    print("Popup closed via:", selector)

                    await page.wait_for_timeout(1000)

                    break

            except:

                pass

    except:

        pass


# ==============================
# CLICK ALL JOBS (BEST EFFORT)
# ==============================

async def click_all_jobs(page):

    selectors = [
        "text=All Jobs",
        "a:has-text('All Jobs')",
        "button:has-text('All Jobs')",
        "[href*='all']",
        "nav a",
    ]

    for selector in selectors:

        try:

            loc = page.locator(selector)

            if await loc.count():

                await loc.first.click()

                await page.wait_for_timeout(2000)

                print("All Jobs clicked via:", selector)

                return True

        except:

            pass

    print("All Jobs button not found — skipping")

    return False


# ==============================
# FIND SEARCH BOX
# ==============================

async def find_and_fill_search(page, keyword):

    selectors = [
        "textarea",
        "input[type='search']",
        "input[placeholder*='search' i]",
        "input[placeholder*='keyword' i]",
        "input[name*='search' i]",
        "input[name*='keyword' i]",
        "input[type='text']",
    ]

    for selector in selectors:

        try:

            loc = page.locator(selector).first

            await loc.wait_for(timeout=10000)

            await loc.fill(keyword)

            print("Search box found via:", selector)

            return True

        except:

            pass

    print("ERROR: No search box found with any selector")

    return False


# ==============================
# CLICK SEARCH BUTTON
# ==============================

async def click_search_button(page):

    selectors = [
        "button:has-text('Search')",
        "input[type='submit']",
        "button[type='submit']",
        "[class*='search'] button",
        "button:has-text('Find')",
    ]

    for selector in selectors:

        try:

            loc = page.locator(selector).first

            if await loc.count():

                await loc.click()

                print("Search button clicked via:", selector)

                return True

        except:

            pass

    try:

        await page.keyboard.press("Enter")

        print("Search triggered via Enter key")

        return True

    except:

        pass

    return False


# ==============================
# ROBUST SEARCH (WITH RETRY)
# ==============================

async def perform_search(page, keyword):

    print("\nSearching:", keyword)

    for attempt in range(1, 4):

        try:

            print("Attempt:", attempt)

            await page.goto(
                "https://www.hiring42.com/",
                timeout=60000
            )

            await page.wait_for_load_state("domcontentloaded")

            await page.wait_for_timeout(3000)

            await close_popup(page)

            await click_all_jobs(page)

            filled = await find_and_fill_search(page, keyword)

            if not filled:

                raise Exception("Could not find search box")

            await click_search_button(page)

            await page.wait_for_timeout(6000)

            return

        except Exception as e:

            print("Retry due to:", e)

            if attempt == 3:

                raise

            await page.wait_for_timeout(5000)


# ==============================
# SCROLL + LOAD MORE
# ==============================

async def scroll_page(page):

    for i in range(10):

        before = await page.evaluate(
            "document.body.scrollHeight"
        )

        await page.evaluate(
            "window.scrollTo(0, document.body.scrollHeight)"
        )

        await page.wait_for_timeout(2000)

        try:

            for btn_text in ["Load More", "Show More", "Next"]:

                load_more = page.locator(
                    f"button:has-text('{btn_text}')"
                )

                if await load_more.count():

                    await load_more.first.click()

                    print(f"'{btn_text}' clicked at scroll {i + 1}")

                    await page.wait_for_timeout(3000)

                    break

        except:

            pass

        after = await page.evaluate(
            "document.body.scrollHeight"
        )

        if before == after:

            print("Scroll end reached at iteration", i + 1)

            break


# ==============================
# GET OUTERMOST CARDS VIA JS
# KEY FIX: parent must NOT contain 'Posted:' — eliminates nested duplicates
# ==============================

async def get_outermost_cards(page):

    # Use JS to grab element handles for outermost Posted: containers

    result = await page.evaluate("""
        () => {
            const all = Array.from(document.querySelectorAll('*'));

            const withPosted = all.filter(el =>
                el.innerText && el.innerText.includes('Posted:')
            );

            // Keep only outermost: parent must NOT contain 'Posted:'
            const outermost = withPosted.filter(el => {
                const parent = el.parentElement;
                return !parent || !parent.innerText.includes('Posted:');
            });

            // Return enough info to re-locate them
            return outermost.map((el, i) => {
                el.setAttribute('data-scrape-id', String(i));
                return i;
            });
        }
    """)

    count = len(result) if result else 0

    print(f"JS outermost cards found: {count}")

    cards = []

    for i in range(count):

        try:

            loc = page.locator(f"[data-scrape-id='{i}']")

            if await loc.count():

                cards.append(loc.first)

        except:

            pass

    return cards


# ==============================
# EXTRACT JOBS
# ==============================

async def extract_jobs(page, keyword):

    jobs = []

    # Save debug HTML

    try:

        html = await page.content()

        safe_kw = keyword.replace(" ", "_").replace('"', "")

        debug_file = f"debug_{safe_kw}.html"

        with open(debug_file, "w", encoding="utf-8") as f:

            f.write(html)

        print("Debug HTML saved:", debug_file)

    except:

        pass

    # Wait for any Posted: content

    try:

        await page.wait_for_selector(
            "div:has-text('Posted:')",
            timeout=15000
        )

    except:

        print("No job content detected on page")

        return jobs

    # Get outermost cards only (no nested duplicates)

    cards = await get_outermost_cards(page)

    if not cards:

        print("No cards found")

        return jobs

    print(f"Processing {len(cards)} outermost cards")

    email_pattern = re.compile(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    )

    for card in cards:

        try:

            raw_text = await card.inner_text()

            # Must contain Posted: and only ONE job

            if "Posted:" not in raw_text:

                continue

            if raw_text.count("Posted:") > 1:

                continue

            # Split BEFORE cleaning to preserve lines

            lines = [
                clean(line)
                for line in raw_text.split("\n")
                if clean(line)
            ]

            full_text = " ".join(lines)

            if len(full_text) < 10:

                continue

            # Title = first meaningful line (length > 3)

            title = ""

            for line in lines:

                if len(line) > 3:

                    title = line

                    break

            # Location = first line with comma, no date/email/score

            location = ""

            for line in lines:

                if (
                    "," in line
                    and "Posted" not in line
                    and "Score" not in line
                    and "@" not in line
                    and not re.search(r"\d{4}", line)
                ):

                    location = line

                    break

            # Email

            email_match = email_pattern.search(full_text)

            email = email_match.group(0) if email_match else ""

            # Tags from span elements

            tags = []

            try:

                spans = await card.locator("span").all()

                for s in spans:

                    txt = clean(await s.inner_text())

                    if txt and txt not in ("ACTIVE", ""):

                        tags.append(txt)

            except:

                pass

            tags_text = " | ".join(tags)

            # Posted date

            posted_date = ""

            if "Posted:" in full_text:

                raw_posted = full_text.split("Posted:")[1]

                for stopper in ["Score", "ACTIVE", "Apply", "View"]:

                    if stopper in raw_posted:

                        raw_posted = raw_posted.split(stopper)[0]

                posted_date = clean(raw_posted)

            # Score

            score = ""

            if "Score:" in full_text:

                raw_score = full_text.split("Score:")[1]

                for stopper in ["ACTIVE", "Apply", "View", "Posted"]:

                    if stopper in raw_score:

                        raw_score = raw_score.split(stopper)[0]

                score = clean(raw_score)

            # Status

            status = "ACTIVE" if "ACTIVE" in full_text else ""

            jobs.append({
                "keyword":     keyword,
                "posted_date": posted_date,
                "title":       title,
                "location":    location,
                "email":       email,
                "tags":        tags_text,
                "status":      status,
                "score":       score,
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

        key = (
            job.get("title", "")
            + job.get("email", "")
            + job.get("posted_date", "")
        )

        if key not in seen:

            seen.add(key)
            unique.append(job)

    return unique


# ==============================
# SAVE CSV
# ==============================

def save_files(jobs, keyword):

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    safe_keyword = (
        keyword
        .replace(" ", "_")
        .replace('"', "")
    )

    csv_file = f"{safe_keyword}_{timestamp}.csv"

    fields = [
        "keyword",
        "posted_date",
        "title",
        "location",
        "email",
        "tags",
        "status",
        "score",
    ]

    with open(csv_file, "w", newline="", encoding="utf-8") as f:

        writer = csv.DictWriter(f, fieldnames=fields)

        writer.writeheader()

        if jobs:

            for job in jobs:

                writer.writerow(job)

        else:

            print("No roles found for:", keyword)
            print("Header-only CSV created:", csv_file)

    print("Saved:", csv_file)


# ==============================
# MAIN SCRAPE LOOP
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
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )

        for keyword in keywords:

            print("\n--------------------------")
            print("Processing:", keyword)
            print("--------------------------")

            page = await context.new_page()

            try:

                await perform_search(page, keyword)

                await scroll_page(page)

                jobs = await extract_jobs(page, keyword)

                jobs = deduplicate_jobs(jobs)

                print("Unique jobs found:", len(jobs))

                save_files(jobs, keyword)

            except Exception as e:

                print("Keyword failed:", keyword)
                print(e)

                save_files([], keyword)

            finally:

                await page.close()

        await context.close()

        await browser.close()


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--keyword",
        help="Run single keyword (overrides DEFAULT_KEYWORDS)"
    )

    args = parser.parse_args()

    keywords = [args.keyword] if args.keyword else DEFAULT_KEYWORDS

    asyncio.run(scrape(keywords))


if __name__ == "__main__":

    main()
