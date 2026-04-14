import asyncio
import csv
import os
import re
from datetime import datetime
from playwright.async_api import async_playwright

CSV_FILE = "hiring42_jobs.csv"

KEYWORDS = [
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
    "sap PPqm",
    "sap hcm",
    "sap ewm",
    "sap abap"
]


def expand_keywords(keywords):
    """
    This will search:
    - full keyword
    - each word inside keyword
    Example:
    'sap abap' -> sap abap, sap, abap
    """
    expanded = set()

    for kw in keywords:
        kw = kw.strip().lower()

        if not kw:
            continue

        # full keyword
        expanded.add(kw)

        # split words
        parts = kw.split()

        for p in parts:
            if len(p) > 2:
                expanded.add(p)

    return list(expanded)


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

                "keyword": "",
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


def append_to_csv(jobs, keyword):

    fields = [
        "keyword",
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

    file_exists = os.path.exists(CSV_FILE)

    if file_exists:

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

        if not file_exists:

            writer.writeheader()

        if not jobs:

            writer.writerow({

                "keyword": keyword,
                "title": "",
                "location": "",
                "email": "",
                "work_type": "",
                "work_mode": "",
                "experience": "",
                "client": "",
                "posted_date": "",
                "description": "",
                "scraped_at": datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

            })

            print("[+] No jobs found — blank row added")

            return

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

        context = await browser.new_context()

        page = await context.new_page()

        page.set_default_timeout(60000)

        print("\n==============================")
        print("[+] Running keyword:", keyword)
        print("==============================")

        await page.goto(
            "https://www.hiring42.com/",
            wait_until="domcontentloaded"
        )

        await page.wait_for_timeout(8000)

        await close_popup(page)

        try:

            await page.click("text=All Jobs")

            await page.wait_for_timeout(5000)

        except:
            pass

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

        await page.wait_for_selector(
            "div.rounded-2xl.border",
            timeout=60000
        )

        await scroll_page(page)

        jobs = await extract_jobs(page)

        for j in jobs:
            j["keyword"] = keyword

        append_to_csv(jobs, keyword)

        await browser.close()


def main():

    print("[+] Starting multi-keyword scraping")

    all_keywords = expand_keywords(KEYWORDS)

    print("[+] Total keywords to search:", len(all_keywords))

    for keyword in all_keywords:

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