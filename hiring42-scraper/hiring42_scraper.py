import asyncio
import argparse
import json
import csv
import re
from datetime import datetime
from playwright.async_api import async_playwright


# ==============================
# DEFAULT SETTINGS
# ==============================

DEFAULT_KEYWORD = "sap sac"
HEADLESS_MODE = False


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

            print("[+] Popup closed")

        else:

            print("[+] No popup detected")

    except:

        print("[+] Popup handling skipped")


# ==============================
# SEARCH
# ==============================

async def perform_search(page, keyword):

    print("[+] Opening Hiring42")

    await page.goto(
        "https://www.hiring42.com/",
        timeout=60000
    )

    await page.wait_for_timeout(4000)

    await close_popup(page)

    print("[+] Clicking All Jobs")

    try:

        await page.click("text=All Jobs")

        await page.wait_for_timeout(3000)

    except:

        print("[!] All Jobs click skipped")

    print("[+] Typing keyword:", keyword)

    await page.fill(
        "textarea",
        keyword
    )

    print("[+] Clicking Search")

    await page.click(
        "button:has-text('Search')"
    )

    print("[+] Waiting for results")

    await page.wait_for_selector(
        "div.rounded-2xl.border",
        timeout=15000
    )


# ==============================
# SCROLL
# ==============================

async def scroll_page(page):

    for i in range(5):

        before = await page.evaluate(
            "document.body.scrollHeight"
        )

        await page.evaluate(
            "window.scrollTo(0, document.body.scrollHeight)"
        )

        await page.wait_for_timeout(2000)

        after = await page.evaluate(
            "document.body.scrollHeight"
        )

        print(
            f"scroll {i+1}:",
            before,
            "→",
            after
        )

        if before == after:

            print("[+] End of page")

            break


# ==============================
# EXTRACT JOBS
# ==============================

async def extract_jobs(page):

    jobs = []

    cards = await page.query_selector_all(
        "div.rounded-2xl.border"
    )

    print("[+] Found cards:", len(cards))

    email_pattern = re.compile(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    )

    date_pattern = re.compile(
        r"Posted:\s*(.*)"
    )

    score_pattern = re.compile(
        r"Score:\s*([0-9.]+%)"
    )

    for card in cards:

        try:

            text = await card.inner_text()

            email_match = email_pattern.search(text)

            if not email_match:
                continue

            email = email_match.group(0)

            lines = [
                clean(l)
                for l in text.split("\n")
                if clean(l)
            ]

            title = lines[0] if lines else ""

            location = ""

            for line in lines:

                if "," in line:

                    location = line
                    break

            posted_date = ""

            date_match = date_pattern.search(text)

            if date_match:

                posted_date = date_match.group(1)

            score = ""

            score_match = score_pattern.search(text)

            if score_match:

                score = score_match.group(1)

            work_type = ""
            work_mode = ""
            experience = ""

            for line in lines:

                if "C2C" in line:

                    work_type = "C2C"

                if "REMOTE" in line or "ONSITE" in line:

                    work_mode = line

                if "YR" in line or "EXP" in line:

                    experience = line

            jobs.append({

                "title": title,
                "location": location,
                "email": email,
                "work_type": work_type,
                "work_mode": work_mode,
                "experience": experience,
                "posted_date": posted_date,
                "score": score,
                "full_text": text

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
# SAVE FILES
# ==============================

def save_files(jobs, keyword):

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    json_file = f"hiring42_{keyword}_{timestamp}.json"
    csv_file = f"hiring42_{keyword}_{timestamp}.csv"

    fields = [

        "title",
        "location",
        "email",
        "work_type",
        "work_mode",
        "experience",
        "posted_date",
        "score",
        "full_text"

    ]

    with open(json_file, "w", encoding="utf-8") as f:

        json.dump(
            jobs,
            f,
            indent=2
        )

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

    return json_file, csv_file


# ==============================
# MAIN SCRAPER
# ==============================

async def scrape(keyword):

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=HEADLESS_MODE
        )

        page = await browser.new_page()

        await perform_search(page, keyword)

        await scroll_page(page)

        jobs = await extract_jobs(page)

        jobs = deduplicate_jobs(jobs)

        print("\n[+] Jobs found:", len(jobs))

        json_file, csv_file = save_files(
            jobs,
            keyword
        )

        print("\n[+] JSON →", json_file)
        print("[+] CSV  →", csv_file)

        print(
            f"\n── {len(jobs)} jobs scraped ──"
        )

        for job in jobs[:10]:

            print(
                " •",
                job["title"],
                job["location"],
                job["email"]
            )

        await browser.close()


# ==============================
# ENTRY POINT
# ==============================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--keyword",
        default=DEFAULT_KEYWORD,
        help="Search keyword"
    )

    args = parser.parse_args()

    print("[+] Using keyword:", args.keyword)

    asyncio.run(
        scrape(
            args.keyword
        )
    )


if __name__ == "__main__":
    main()