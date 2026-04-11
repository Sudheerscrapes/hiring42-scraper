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

        await page.wait_for_timeout(3000)

        buttons = [
            "button[aria-label='Close']",
            "text=Maybe Later",
            "button:has-text('Close')",
            "button:has-text('Skip')"
        ]

        for b in buttons:

            if await page.locator(b).count():

                await page.click(b)

                print("[+] Popup closed")

                await page.wait_for_timeout(2000)

                break

    except:

        pass


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
            work_type = ""
            work_mode = ""
            experience = ""
            client = ""
            posted_date = ""

            for line in lines:

                if "," in line and not location:
                    location = line

                if "C2C" in line or "W2" in line:
                    work_type = line

                if (
                    "REMOTE" in line
                    or "ONSITE" in line
                    or "HYBRID" in line
                ):
                    work_mode = line

                if (
                    "YR" in line
                    or "EXP" in line
                    or "YEARS" in line
                ):
                    experience = line

                if "Client" in line:
                    client = line

            date_match = date_pattern.search(text)

            if date_match:

                posted_date = date_match.group(1)

            description = text

            jobs.append({

                "title": title,
                "location": location,
                "email": email,
                "work_type": work_type,
                "work_mode": work_mode,
                "experience": experience,
                "client": client,
                "posted_date": posted_date,
                "description": description,
                "scraped_at": datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

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
        "client",
        "posted_date",
        "description",
        "scraped_at"

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

        if not os.path.exists(CSV_FILE) or os.stat(CSV_FILE).st_size == 0:

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
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled"
            ]

        )

        context = await browser.new_context(

            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),

            viewport={
                "width": 1366,
                "height": 768
            },

            locale="en-US",

            timezone_id="America/New_York"
        )

        page = await context.new_page()

        page.set_default_timeout(60000)

        page.set_default_navigation_timeout(60000)

        print("[+] Opening Hiring42")

        await page.goto(
            "https://www.hiring42.com/",
            wait_until="domcontentloaded"
        )

        await page.wait_for_timeout(8000)

        await close_popup(page)

        print("[+] Clicking All Jobs")

        try:

            await page.click("text=All Jobs")

            await page.wait_for_timeout(5000)

        except:

            pass

        print("[+] Searching:", keyword)

        await page.wait_for_selector(
            "input[type='text'], textarea",
            timeout=60000
        )

        search_box = page.locator(
            "input[type='text'], textarea"
        ).first

        await search_box.fill(keyword)

        await page.wait_for_timeout(1000)

        await page.click(
            "button:has-text('Search')"
        )

        print("[+] Waiting for results")

        await page.wait_for_selector(
            "div.rounded-2xl.border",
            timeout=60000
        )

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
