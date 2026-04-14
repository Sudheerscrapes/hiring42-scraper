import asyncio
import csv
import os
import re
from datetime import datetime
from playwright.async_api import async_playwright

CSV_FILE = "hiring42_jobs.csv"

HEADLESS_MODE = True

BASE_KEYWORDS = [

    "sap sac",
    "sap datasphere",
    "sap pi",
    "sap po",
    "sap cpi",
    "sap btp",
    "sap sd",
    "sap ewm",
    "sap mm",
    "dot net",
    ".net",
    "sap basis",
    "power bi",
    "powerbi",
    "sap pp",
    "sap qm",
    "sap hcm",
    "sap abap"

]


def generate_keywords():

    keywords = []

    for k in BASE_KEYWORDS:

        keywords.append(k)
        keywords.append(f'"{k}"')

    return keywords


KEYWORDS = generate_keywords()


def clean(text):

    if not text:
        return ""

    return re.sub(r"\s+", " ", text).strip()


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

        pass


async def perform_search(page, keyword):

    print("\n==============================")
    print("[+] Running keyword:", keyword)
    print("==============================")

    await page.goto(
        "https://www.hiring42.com/",
        timeout=60000
    )

    await page.wait_for_timeout(4000)

    await close_popup(page)

    try:

        await page.click("text=All Jobs")

        await page.wait_for_timeout(3000)

    except:

        print("[!] All Jobs click skipped")

    await page.fill(
        "textarea",
        keyword
    )

    await page.click(
        "button:has-text('Search')"
    )

    await page.wait_for_selector(
        "div.rounded-2xl.border",
        timeout=15000
    )


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

            for line in lines:

                if "," in line:

                    location = line
                    break

            posted_date = ""

            date_match = date_pattern.search(text)

            if date_match:

                posted_date = date_match.group(1)

            jobs.append({

                "keyword": "",
                "title": title,
                "location": location,
                "email": email,
                "posted_date": posted_date,
                "scraped_at": datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

            })

        except:

            pass

    return jobs


def append_to_csv(jobs, keyword):

    fields = [

        "keyword",
        "title",
        "location",
        "email",
        "posted_date",
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

        if not os.path.exists(CSV_FILE):

            writer.writeheader()

        if not jobs:

            writer.writerow({

                "keyword": keyword,
                "title": "",
                "location": "",
                "email": "",
                "posted_date": "",
                "scraped_at": datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

            })

            print("[+] No jobs — blank row added")

            return

        for job in jobs:

            key = job["title"] + job["email"]

            if key not in existing_keys:

                writer.writerow(job)


async def scrape(keyword):

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=HEADLESS_MODE,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        )

        page = await browser.new_page()

        await perform_search(page, keyword)

        await scroll_page(page)

        jobs = await extract_jobs(page)

        for j in jobs:

            j["keyword"] = keyword

        append_to_csv(jobs, keyword)

        await browser.close()


def main():

    print("[+] Starting scraper")

    for keyword in KEYWORDS:

        try:

            asyncio.run(
                scrape(keyword)
            )

        except Exception as e:

            print(
                "[!] Error with keyword:",
                keyword
            )

            print(e)

    print("\n[+] All keywords completed")


if __name__ == "__main__":

    main()
