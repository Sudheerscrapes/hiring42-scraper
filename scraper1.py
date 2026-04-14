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
    "sap sac",
    '"sap sac"',
    "sap bw"
]

HEADLESS_MODE = True


# ==============================
# CLEAN
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
# SEARCH
# ==============================

async def perform_search(page, keyword):

    print("\nSearching:", keyword)

    await page.goto(
        "https://www.hiring42.com/",
        timeout=60000
    )

    await page.wait_for_load_state(
        "networkidle"
    )

    await close_popup(page)

    try:

        await page.wait_for_selector(
            "text=All Jobs",
            timeout=20000
        )

        await page.click("text=All Jobs")

    except:

        print("All Jobs click skipped")

    # wait for search box

    await page.wait_for_selector(
        "textarea",
        timeout=30000
    )

    await page.fill(
        "textarea",
        keyword
    )

    await page.click(
        "button:has-text('Search')"
    )

    await page.wait_for_timeout(
        5000
    )


# ==============================
# SCROLL
# ==============================

async def scroll_page(page):

    for _ in range(6):

        before = await page.evaluate(
            "document.body.scrollHeight"
        )

        await page.evaluate(
            "window.scrollTo(0, document.body.scrollHeight)"
        )

        await page.wait_for_timeout(
            2000
        )

        after = await page.evaluate(
            "document.body.scrollHeight"
        )

        if before == after:
            break


# ==============================
# EXTRACT JOBS
# ==============================

async def extract_jobs(page, keyword):

    jobs = []

    cards = await page.query_selector_all(
        "div.rounded-2xl.border"
    )

    print("Cards found:", len(cards))

    email_pattern = re.compile(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    )

    for card in cards:

        try:

            full_text = clean(
                await card.inner_text()
            )

            lines = full_text.split("\n")

            title = lines[0] if lines else ""

            location = ""

            for line in lines:

                if "," in line and not line.startswith("Posted"):
                    location = line
                    break

            email_match = email_pattern.search(
                full_text
            )

            email = (
                email_match.group(0)
                if email_match
                else ""
            )

            # TAGS

            tags = []

            badge_elements = await card.query_selector_all(
                "span"
            )

            for badge in badge_elements:

                text = clean(
                    await badge.inner_text()
                )

                if text and text != "ACTIVE":

                    tags.append(text)

            tags_text = " | ".join(tags)

            # POSTED DATE

            posted_date = ""

            if "Posted:" in full_text:

                posted_date = (
                    full_text
                    .split("Posted:")[1]
                    .split("Score")[0]
                    .strip()
                )

            # SCORE

            score = ""

            if "Score:" in full_text:

                score = (
                    full_text
                    .split("Score:")[1]
                    .strip()
                )

            # STATUS

            status = ""

            if "ACTIVE" in full_text:

                status = "ACTIVE"

            jobs.append({

                "keyword": keyword,
                "posted_date": posted_date,
                "title": title,
                "location": location,
                "email": email,
                "tags": tags_text,
                "status": status,
                "score": score

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
# SAVE FILE
# ==============================

def save_files(jobs, keyword):

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    safe_keyword = keyword.replace(
        " ",
        "_"
    ).replace(
        '"',
        ""
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
        "score"

    ]

    # if no jobs found

    if not jobs:

        print("No roles found for:", keyword)

        jobs = [{

            "keyword": keyword,
            "posted_date": "",
            "title": "",
            "location": "",
            "email": "",
            "tags": "",
            "status": "",
            "score": ""

        }]

    with open(
        csv_file,
        "w",
        newline="",
        encoding="utf-8"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fields
        )

        writer.writeheader()

        for job in jobs:

            writer.writerow(job)

    print("Saved:", csv_file)


# ==============================
# MAIN SCRAPER
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

                await perform_search(
                    page,
                    keyword
                )

                await scroll_page(
                    page
                )

                jobs = await extract_jobs(
                    page,
                    keyword
                )

                jobs = deduplicate_jobs(
                    jobs
                )

                print(
                    "Jobs found:",
                    len(jobs)
                )

                save_files(
                    jobs,
                    keyword
                )

            except Exception as e:

                print(
                    "Keyword failed:",
                    keyword
                )

                print(e)

                save_files(
                    [],
                    keyword
                )

            finally:

                await page.close()

        await browser.close()


# ==============================
# ENTRY POINT
# ==============================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--keyword",
        help="Run single keyword"
    )

    args = parser.parse_args()

    if args.keyword:

        keywords = [
            args.keyword
        ]

    else:

        keywords = DEFAULT_KEYWORDS

    asyncio.run(
        scrape(
            keywords
        )


    )


if __name__ == "__main__":

    main()
