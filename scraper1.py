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

        await page.wait_for_timeout(2000)

        if await page.locator(
            "button[aria-label='Close']"
        ).count():

            await page.click(
                "button[aria-label='Close']"
            )

    except:

        pass


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

            await page.wait_for_load_state(
                "networkidle"
            )

            await close_popup(page)

            # Click All Jobs

            try:

                await page.wait_for_selector(
                    "text=All Jobs",
                    timeout=30000
                )

                await page.click("text=All Jobs")

                await page.wait_for_timeout(2000)

                print("All Jobs clicked")

            except:

                print("All Jobs not required")

            # Wait for search box

            await page.wait_for_selector(
                "textarea",
                timeout=60000
            )

            print("Search box found")

            await page.fill(
                "textarea",
                keyword
            )

            await page.click(
                "button:has-text('Search')"
            )

            print("Search clicked")

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

        # Click Load More if present

        try:

            load_more = page.locator(
                "button:has-text('Load More')"
            )

            if await load_more.count():

                await load_more.click()

                print("Load More clicked (scroll", i + 1, ")")

                await page.wait_for_timeout(3000)

        except:

            pass

        after = await page.evaluate(
            "document.body.scrollHeight"
        )

        if before == after:

            print("Scroll end reached at iteration", i + 1)

            break


# ==============================
# EXTRACT JOBS
# ==============================

async def extract_jobs(page, keyword):

    jobs = []

    # Save debug HTML so you can inspect if 0 cards found

    try:

        html = await page.content()

        safe_kw = keyword.replace(" ", "_").replace('"', "")

        with open(f"debug_{safe_kw}.html", "w", encoding="utf-8") as f:

            f.write(html)

        print("Debug HTML saved: debug_{}.html".format(safe_kw))

    except:

        pass

    # Wait for job cards

    try:

        await page.wait_for_selector(
            "div:has-text('Posted:')",
            timeout=15000
        )

    except:

        print("No job cards detected")

        return jobs

    cards = await page.locator(
        "div:has-text('Posted:')"
    ).all()

    print("Cards found:", len(cards))

    email_pattern = re.compile(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    )

    for card in cards:

        try:

            # FIX: split BEFORE cleaning so lines are preserved

            raw_text = await card.inner_text()

            lines = [
                clean(line)
                for line in raw_text.split("\n")
                if clean(line)
            ]

            full_text = " ".join(lines)

            # Title = first non-empty line

            title = lines[0] if lines else ""

            # Location = first line with comma that isn't a date/posted line

            location = ""

            for line in lines:

                if (
                    "," in line
                    and "Posted" not in line
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

            spans = await card.locator("span").all()

            for s in spans:

                txt = clean(await s.inner_text())

                if txt and txt not in ("ACTIVE", ""):

                    tags.append(txt)

            tags_text = " | ".join(tags)

            # Posted date

            posted_date = ""

            if "Posted:" in full_text:

                raw_posted = full_text.split("Posted:")[1]

                # Strip trailing fields like Score, status etc.

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
            headless=HEADLESS_MODE
        )

        for keyword in keywords:

            print("\n--------------------------")
            print("Processing:", keyword)
            print("--------------------------")

            page = await browser.new_page()

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
