"""指定した幅で、画面のページを撮る。コンソールのエラーと、横のはみ出しも調べる。

使い方: uv run --with playwright python -I shoot.py <画面の URL> <出力先> <幅> <full|view> <名前=ハッシュ>...
  例:   ... shoot.py http://localhost:8765 /tmp/shots 1440 view "arch=#/overview" "entries=#/entries"
出力:   <出力先>/<名前>.png と、標準出力に JSON ({名前: {scrollW, clientW}, errors: [...]})。scrollW と clientW が違えば、横にはみ出している。
ブラウザの場所を指定したいときは、環境変数 ABATLAS_CHROME に実行ファイルのパスを入れる。
"""
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

if len(sys.argv) < 6:
    sys.exit(__doc__)
BASE, OUT, WIDTH, MODE = sys.argv[1].rstrip("/"), Path(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
OUT.mkdir(parents=True, exist_ok=True)
CHROME = os.environ.get("ABATLAS_CHROME")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, **({"executable_path": CHROME} if CHROME else {}))
    page = browser.new_page(viewport={"width": WIDTH, "height": 900 if WIDTH > 600 else 844})
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    out: dict = {}
    for spec in sys.argv[5:]:
        name, h = spec.split("=", 1)
        page.goto(f"{BASE}/{h}")
        page.reload()  # ハッシュだけの移動では読み直されないので、毎回読み直す
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(900)
        page.screenshot(path=str(OUT / f"{name}.png"), full_page=MODE == "full")
        out[name] = page.evaluate("() => ({scrollW: document.documentElement.scrollWidth, clientW: document.documentElement.clientWidth})")
    out["errors"] = errors
    print(json.dumps(out, ensure_ascii=False))
    browser.close()
