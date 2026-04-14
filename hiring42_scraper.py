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


async def load_site(page):

    print("[+] Opening website...", flush=True)

    for attempt in range(3):

        try:

            print(f"[+] Attempt {attempt+1}", flush=True)

            await page.goto(
                "https://www.hiring42.com/all_jobs",
                wait_until="domcontentloaded",
                timeout=90000
            )

            print("[+] Website loaded", flush=True)

            return True

        except:

            print("[!] Load failed — retrying", flush=True)

            await page.wait_for_timeout(5000)

    return False


async def get_search_box(page):

    print("[+] Locating search box...", flush=True)

    await page.wait_for_selector("body")

    await page.wait_for_timeout(5000)

    inputs = page.locator("input")

    count = await inputs.count()

    print(f"[+] Inputs detected: {count}", flush=True)

    for i in range(count):

        box = inputs.nth(i)

        try:

            visible = await box.is_visible()

            if visible:

                print(
                    f"[+] Using input index {i}",
                    flush=True
                )

                return box

        except:

            pass

    return None


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

            jobs.append({

                "keyword": "",
                "title": title,
                "location": "",
                "email": email,
                "work_type": "",
                "work_mode": "",
                "experience": "",
                "client": "",
                "posted_date": "",
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

        page.set_default_timeout(90000)

        success = await load_site(page)

        if not success:

            print("[!] Could not load website", flush=True)

            await browser.close()

            return

        search_box = await get_search_box(page)

        if not search_box:

            print(
                "[!] Search box not found",
                flush=True
            )

            await browser.close()

            return

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

                await page.wait_for_selector(
                    "div.rounded-2xl.border",
                    timeout=30000
                )

                await scroll_page(page)

                jobs = await extract_jobs(page)

                for j in jobs:
                    j["keyword"] = keyword

                append_to_csv(
                    jobs,
                    keyword
                )

            except Exception as e:

                print(
                    f"[!] Error with {keyword}",
                    flush=True
                )

                print(e, flush=True)

        await browser.close()

        print(
            "\n[+] All keywords completed",
            flush=True
        )


def main():
    asyncio.run(scrape_all())


if __name__ == "__main__":
    main()
