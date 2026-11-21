"""Check language selection and links on a running landing page. Pass its root URL."""

import os
import sys
from urllib.parse import urljoin

from playwright.sync_api import expect, sync_playwright


def check_languages(browser, root):
    for locale, expected, width in (("ja-JP", "ja", 390), ("en-GB", "en", 1440), ("fr-FR", "en", 320)):
        page = browser.new_page(locale=locale, viewport={"width": width, "height": 880})
        page.goto(root + "#impact")
        expect(page.locator("html")).to_have_attribute("lang", expected)
        expect(page.locator("#impact")).to_be_visible()
        for language in (expected, "ja" if expected == "en" else "en"):
            section = "README.md#10-minute-quickstart" if language == "en" else "README.ja.md#10-分で試す"
            for link in page.locator(".hero .button, #experience .wrap > .link, #start .button").all():
                assert link.get_attribute("href").endswith(section)
            assert page.evaluate("innerWidth === document.documentElement.scrollWidth")
            page.get_by_role("tab").last.click()
            if language == expected:
                page.locator(".language-link").click()
                expect(page.locator("#source")).to_be_visible()
        page.goto(root)
        expect(page.locator("html")).to_have_attribute("lang", "ja" if expected == "en" else "en")
        page.close()

    for path, lang in (("en/", "en"), ("?lang=ja", "ja")):
        page = browser.new_page(java_script_enabled=False)
        page.goto(urljoin(root, path))
        expect(page.locator("html")).to_have_attribute("lang", lang)
        expect(page.locator(".language-link")).to_be_visible()
        page.close()


if __name__ == "__main__":
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ.get("ABATLAS_CHROME"))
        check_languages(browser, sys.argv[1])
        browser.close()
