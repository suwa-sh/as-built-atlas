"""Exercise both published languages and the site's interactive sections in Chromium."""

from pathlib import Path

import pytest
from starlette.staticfiles import StaticFiles

from lp_language import check_languages
from lp_motion import (
    check_late_script,
    check_motion,
    check_reveal_timing,
    check_touch_rotation,
    check_video_fallback,
)


@pytest.fixture
def site(serve_app):
    with serve_app(
        StaticFiles(directory=Path(__file__).resolve().parents[2] / "site", html=True)
    ) as url:
        yield url


def test_languages(browser, site):
    check_languages(browser, site)


@pytest.mark.parametrize("locale", ["ja", "en"])
def test_experience_heading_fits_on_desktop(browser, site, locale):
    page = browser.new_page(locale=locale, viewport={"width": 1440, "height": 900})
    try:
        page.goto(site + ("en/" if locale == "en" else ""))
        heading = page.locator("#experience h2")
        assert heading.evaluate(
            "el => el.clientHeight <= Math.ceil(parseFloat(getComputedStyle(el).lineHeight))"
        )
    finally:
        page.close()


@pytest.mark.parametrize("preference", ["no-preference", "reduce"])
def test_motion(browser, site, preference):
    check_motion(browser, site, preference)


@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_reveal(browser, site, width, height):
    check_reveal_timing(browser, site, {"width": width, "height": height})


@pytest.mark.parametrize(
    "check", [check_video_fallback, check_touch_rotation, check_late_script]
)
def test_loading_and_controls(browser, site, check):
    check(browser, site)
