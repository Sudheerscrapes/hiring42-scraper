import asyncio
import argparse
import csv
import os
import re
from datetime import datetime
from playwright.async_api import async_playwright

CSV_FILE = "hiring42_jobs.csv"


def clean(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


async def close_popup(page):
    try:
        await page.wait_for_timeout(2000)

        if await page.locator("button[aria-label='Close']").count():
            await page.click("button[aria-label='Close']")
            print("[+] Popup closed")

    except:
        pass


async def open_site(page):

    print("[+] Opening Hiring42")

    await page.goto(
        "https://www.hiring42.com/",
        timeout=60000
    )

    await page.wait_for_timeout(4000)

    await close_popup(page)

    try:
        print("[+] Clicking All Jobs")

        await page.click("text=All Jobs")

        await page.wait_for_timeout(3000)

    except:
        pass


async def search_jobs(page, keyword):

    print("[+] Searching:", keyword)

    await page.fill(
        "textarea",
        keyword
    )

    await page.click(
        "button:has-text('Search')"
    )

    print("[+] Waiting for results")

    await page.wait_for_selector(
        "div.rounded-2xl.border",
        timeout=15000
    )


async def scroll_page(page):

    for i in range(10):

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
                "score": score

            })

        except Exception as e:

            print("Parse error:", e)

    return jobs


def append_to_csv(jobs):

    fields = [

        "title",
        "location",
        "email",
        "work_type",
        "work_mode",
        "experience",
        "posted_date",
        "score"

    ]

    existing_keys = set()

    if os.path.exists(CSV_FILE):

        with open(
            CSV_FILE,
            newline="",
            encoding="utf-8"
        ) as f:

            reader = csv.DictReader(f)

            for row in reader:

                key = row["title"] + row["email"]

                existing_keys.add(key)

    new_count = 0

    with open(
        CSV_FILE,
        "a",
        newline="",
        encoding="utf-8"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fields
        )

        if os.stat(CSV_FILE).st_size == 0:
            writer.writeheader()

        for job in jobs:

            key = job["title"] + job["email"]

            if key not in existing_keys:

                writer.writerow(job)

                new_count += 1

    print("[+] New jobs appended:", new_count)


async def scrape(keyword):

    async with async_playwright() as p:

        browser = await p.chromium.launch(

            headless=True,

            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]

        )

        page = await browser.new_page()

        await open_site(page)

        await search_jobs(page, keyword)

        await scroll_page(page)

        jobs = await extract_jobs(page)

        print("[+] Jobs scraped:", len(jobs))

        append_to_csv(jobs)

        await browser.close()


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--keyword",
        default="sap sac"
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
