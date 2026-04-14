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
    "sap hcm",
    "sap abap"
]


def clean(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


async def close_popup(page):
    try:
        await page.wait_for_timeout(2000)

        buttons = [
            "button[aria-label='Close']",
            "text=Maybe Later",
            "button:has-text('Close')",
            "button:has-text('Skip')"
        ]

        for b in buttons:
            if await page.locator(b).count():
                await page.click(b)
                print("[+] Popup closed", flush=True)
                break

    except:
        pass


async def scroll_page(page):

    for i in range(6):

        before = await page.evaluate(
            "document.body.scrollHeight"
        )

        await page.evaluate(
            "window.scrollTo(0, document.body.scrollHeight)"
        )

        await page.wait_for_timeout(1500)

        after = await page.evaluate(
            "document.body.scrollHeight"
        )

        print(f"[+] Scroll {i+1}", flush=True)

        if before == after:
            break


async def extract_jobs(page):

    jobs = []

    cards = await page.query_selector_all(
        "div.rounded-2xl.border"
    )

    print("[+] Found cards:", len(cards), flush=True)

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
                    or "ONSITE"
                    or "HYBRID"
                ):
                    work_mode = line

                if (
                    "YR" in line
                    or "EXP"
                    or "YEARS"
                ):
                    experience = line

                if "Client" in line:
                    client = line

            date_match = date_pattern.search(text)

            if date_match:
                posted_date = date_match.group(1)

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
                "description": text,
                "scraped_at": datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

            })

        except Exception as e:
            print("Parse error:", e, flush=True)

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

    file_exists = os.path.exists(CSV_FILE)

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

        for job in jobs:
            writer.writerow(job)

    print(
        f"[+] {len(jobs)} jobs saved for {keyword}",
        flush=True
    )


async def scrape_all():

    print("[+] Starting scraper", flush=True)

    async with async_playwright() as p:

        browser = await p.chromium.launch(

            headless=True,

            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]

        )

        context = await browser.new_context()

        page = await context.new_page()

        page.set_default_timeout(45000)

        await page.goto(
            "https://www.hiring42.com/",
            wait_until="domcontentloaded"
        )

        await close_popup(page)

        try:
            await page.click("text=All Jobs")
        except:
            pass

        await page.wait_for_selector(
            "input[type='text'], textarea"
        )

        search_box = page.locator(
            "input[type='text'], textarea"
        ).first

        for keyword in KEYWORDS:

            print(
                f"\n[+] Processing keyword: {keyword}",
                flush=True
            )

            try:

                await search_box.fill("")

                await search_box.fill(keyword)

                await page.click(
                    "button:has-text('Search')"
                )

                try:

                    await page.wait_for_selector(
                        "div.rounded-2xl.border",
                        timeout=30000
                    )

                except:
                    print(
                        "[!] No results",
                        flush=True
                    )
                    append_to_csv([], keyword)
                    continue

                await scroll_page(page)

                jobs = await extract_jobs(page)

                for j in jobs:
                    j["keyword"] = keyword

                append_to_csv(jobs, keyword)

            except Exception as e:

                print(
                    f"[!] Error with {keyword}",
                    e,
                    flush=True
                )

        await browser.close()

        print(
            "\n[+] All keywords completed",
            flush=True
        )


def main():
    asyncio.run(scrape_all())


if __name__ == "__main__":
    main()
