"""LP の動画、スクロールとタブの動きを配信中のページで確かめる。

初回は uv run --with playwright playwright install chromium を実行する。
手元の Chrome を使う場合は ABATLAS_CHROME に実行ファイルのパスを指定する。
実行コマンド: uv run --with playwright python tests/browser/lp_motion.py <URL>
"""

import os
import sys

from playwright.sync_api import expect, sync_playwright


def scroll_to_height(element, fraction):
    element.evaluate(
        "(el, fraction) => window.scrollBy(0, el.getBoundingClientRect().top - innerHeight * fraction)",
        fraction,
    )


def check_motion(browser, url, preference):
    page = browser.new_page(reduced_motion=preference)
    requested_paths = []
    page.on("request", lambda req: requested_paths.append(req.url))
    page.goto(url)
    rotation = page.locator(".hero-rotation")
    video = page.locator(".hero-media video")
    video.scroll_into_view_if_needed()
    expect(video).to_have_js_property("controls", False)
    expect(video).to_have_js_property("loop", True)
    if preference == "reduce":
        expect(video).to_have_js_property("paused", True)
        assert not any(path.endswith(".mp4") for path in requested_paths)
        expect(rotation).to_have_accessible_name("3D図の回転を再生")
        rotation.press("Enter")
    page.wait_for_function("document.querySelector('video').currentTime > 0")
    expect(rotation).to_have_accessible_name("3D図の回転を一時停止")
    video.evaluate("""el => new Promise(done => {
        el.addEventListener('seeked', () => done(), { once: true });
        el.currentTime = el.duration - 0.5;
    })""")
    page.wait_for_function("""() => {
        const v = document.querySelector('video');
        return !v.paused && v.currentTime > 0 && v.currentTime < 1;
    }""")
    if preference == "no-preference":
        page.emulate_media(reduced_motion="reduce")
        expect(video).to_have_js_property("paused", True)
        page.emulate_media(reduced_motion=preference)
        expect(video).to_have_js_property("paused", False)
    page.locator("footer").scroll_into_view_if_needed()
    expect(video).to_have_js_property("paused", True)
    rotation.scroll_into_view_if_needed()
    expect(video).to_have_js_property("paused", False)
    rotation.press("Space")
    expect(rotation).to_have_accessible_name("3D図の回転を再生")
    page.locator("footer").scroll_into_view_if_needed()
    rotation.scroll_into_view_if_needed()
    expect(video).to_have_js_property("paused", True)

    heading = page.locator("#profiles h2")
    lead = page.locator("#profiles .description")
    expect(heading).to_have_css("animation-name", "none")
    if preference == "no-preference":
        expect(lead).to_have_css("opacity", "0")
    scroll_to_height(heading, 0.30)
    if preference == "reduce":
        for text in (heading, lead):
            expect(text).to_have_css("animation-name", "none")
            expect(text).to_have_css("opacity", "1")
    else:
        for text in (heading, lead):
            expect(text).to_have_css("animation-name", "text-in")
        expect(lead).to_have_css("animation-delay", "0.12s")
        lead.evaluate("el => Promise.all(el.getAnimations().map(a => a.finished))")
        expect(lead).to_have_css("opacity", "1")
        page.locator("header").scroll_into_view_if_needed()
        lead.scroll_into_view_if_needed()
        assert lead.evaluate("el => el.getAnimations().length") == 0

    diagram = page.locator(".concept-map")
    scroll_to_height(diagram, 0.40)
    expect(diagram.get_by_role("img")).to_have_accessible_name(
        "コードから読み取った関係をYAMLに保存し、集計結果をWebappとMCPに届ける流れ"
    )
    trace = diagram.locator(".flow-trace")
    if preference == "reduce":
        expect(trace).to_have_css("display", "none")
    else:
        expect(trace).to_have_css("animation-name", "trace-routes")
        trace.evaluate("el => Promise.all(el.getAnimations().map(a => a.finished))")
        page.locator("header").scroll_into_view_if_needed()
        diagram.scroll_into_view_if_needed()
        assert trace.evaluate("el => el.getAnimations().length") == 0

    tab = page.get_by_role("tab", name="影響候補を確認")
    panel = page.locator("#impact")
    panel_heading = panel.locator("h3")
    panel_heading.evaluate("""el => {
        window.panelStarts = 0;
        el.addEventListener('transitionstart', event => {
            if (event.target === el && event.propertyName === 'opacity') window.panelStarts++;
        });
    }""")
    tab.click()
    scroll_to_height(panel, 0.35)
    expect(panel).to_be_visible()
    page.wait_for_function("document.querySelector('#impact').classList.contains('in-view')")
    if preference == "reduce":
        expect(panel_heading).to_have_css("transition-duration", "0s")
        assert page.evaluate("window.panelStarts") == 0
    else:
        page.wait_for_function("window.panelStarts === 1")
        panel_heading.evaluate("el => Promise.all(el.getAnimations().map(a => a.finished))")
        page.get_by_role("tab", name="根拠を確認").click()
        tab.click()
        assert panel_heading.evaluate("el => el.getAnimations().length") == 0
    page.close()


def check_reveal_timing(browser, url, viewport):
    page = browser.new_page(viewport=viewport, reduced_motion="no-preference")
    page.goto(url)
    first_panel = page.locator("#structure")
    assert first_panel.evaluate("el => !el.classList.contains('in-view') && !el.getAnimations().length")
    expect(first_panel).to_have_css("opacity", "1")
    expect(first_panel.locator("figure img")).to_have_css("opacity", "1")
    for selector in ("#experience h2", "#structure", "#profiles h2", ".concept-map", ".process li"):
        element = page.locator(selector).first
        scroll_to_height(element, 0.94)
        # 画面の下端で読み手が待っても、登場アニメーションは消費しない。
        page.wait_for_timeout(900)
        assert not element.evaluate("el => el.classList.contains('in-view')"), selector
        if selector == "#experience h2":
            expect(element).to_have_css("opacity", "0")
            # 見出しの中央が画面の89%に来た時点で、フェードが始まる。
            element.evaluate("""el => {
                const rect = el.getBoundingClientRect();
                window.scrollBy(0, rect.top + rect.height / 2 - innerHeight * 0.89);
            }""")
            expect(element).to_have_css("animation-name", "text-in")
            start, early, middle = element.evaluate("""el => {
                const animation = el.getAnimations()[0];
                return [0, 0.25, 0.5].map(fraction => {
                    animation.currentTime = animation.effect.getTiming().duration * fraction;
                    return Number(getComputedStyle(el).opacity);
                });
            }""")
            assert 0 < start < 0.1 and start < early < 0.25 and 0.45 < middle < 0.65
            expect(element).to_have_css("opacity", "1")
        elif selector == "#profiles h2":
            # 一瞬で通過した見出しは次に読むときまで残し、低速スクロール中には動かす。
            scroll_to_height(element, 0.42)
            page.locator("header").scroll_into_view_if_needed()
            page.wait_for_timeout(350)
            assert not element.evaluate("el => el.classList.contains('in-view')")
            scroll_to_height(element, 0.70)
            assert element.evaluate("""async el => {
                const start = performance.now();
                const y = scrollY;
                while (performance.now() - start < 2000) {
                    await new Promise(requestAnimationFrame);
                    scrollTo(0, y + innerHeight * (performance.now() - start) / 8000);
                    if (el.classList.contains('in-view')) return true;
                }
                return false;
            }""")
        else:
            scroll_to_height(element, 0.42)
        page.wait_for_function("s => document.querySelector(s).classList.contains('in-view')", arg=selector)

    page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    page.wait_for_function("document.querySelector('#start [data-reveal=lead]').classList.contains('in-view')")
    page.close()


def check_video_fallback(browser, url):
    page = browser.new_page(has_touch=True, reduced_motion="no-preference")
    page.route("**/architecture-3d.mp4", lambda route: route.abort())
    page.goto(url)
    page.locator(".hero-media").scroll_into_view_if_needed()
    still = page.get_by_role("link", name="ことり書店の3D図を原寸で開く")
    expect(still).to_be_visible()
    expect(page.locator(".hero-touch-hint")).to_be_hidden()
    assert still.locator("img").evaluate("async el => { await el.decode(); return el.naturalWidth > 0 }")
    page.close()

    page = browser.new_page(java_script_enabled=False)
    page.goto(url)
    expect(page.get_by_role("link", name="ことり書店の3D図を原寸で開く")).to_be_visible()
    expect(page.locator(".hero-rotation")).to_be_hidden()
    expect(page.locator("#experience h2")).to_have_css("opacity", "1")
    page.close()


def check_touch_rotation(browser, url):
    page = browser.new_page(has_touch=True, viewport={"width": 390, "height": 844}, reduced_motion="reduce")
    page.goto(url)
    expect(page.locator(".hero-touch-hint")).to_be_visible()
    rotation = page.get_by_role("button", name="3D図の回転を再生")
    rotation.tap()
    page.get_by_role("button", name="3D図の回転を一時停止").tap()
    expect(rotation).to_be_visible()
    page.close()


def check_late_script(browser, url):
    page = browser.new_page(reduced_motion="no-preference")
    held = []
    page.route("**/experience.js", lambda route: held.append(route))
    page.goto(url, wait_until="commit")
    heading = page.locator("#hero-title")
    expect(heading).to_be_in_viewport()
    expect(heading).to_have_css("opacity", "1")
    page.evaluate("() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)))")
    page.wait_for_function("""!('PerformancePaintTiming' in window)
        || performance.getEntriesByName('first-contentful-paint', 'paint').length > 0""")
    held[0].continue_()
    page.wait_for_function("document.querySelector('#profiles h2').classList.contains('reveal-pending')")
    assert heading.evaluate("el => !el.matches('.in-view, .reveal-pending')")
    expect(heading).to_have_css("opacity", "1")
    page.close()


if __name__ == "__main__":
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("ABATLAS_CHROME"))
        for preference in ("no-preference", "reduce"):
            check_motion(browser, sys.argv[1], preference)
        for viewport in ({"width": 1440, "height": 900}, {"width": 390, "height": 844}):
            check_reveal_timing(browser, sys.argv[1], viewport)
        check_video_fallback(browser, sys.argv[1])
        check_touch_rotation(browser, sys.argv[1])
        check_late_script(browser, sys.argv[1])
        browser.close()
