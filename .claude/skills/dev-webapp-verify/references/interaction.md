# 操作を確かめるスクリプトの型

足した操作ごとに、小さなスクリプトを書いて動かす。スクリプトは、作業用の一時の場所に置く (リポジトリに入れない)。

## 型

1. ページを開く。
2. 状態を数える関数を 1 つ用意する (DOM から、数と文字を読む)。
3. 操作の前の状態を記録する。
4. 操作する (入力、クリック、幅の変更、読み直し)。
5. 操作の後の状態を記録する。必要なら撮る。
6. すべての状態と、コンソールのエラーを、JSON で出す。

```python
import json, os, sys
from playwright.sync_api import sync_playwright

BASE, OUT = sys.argv[1].rstrip("/"), sys.argv[2]
CHROME = os.environ.get("ABATLAS_CHROME")
# 状態を数える: 残っている箱の数、線の数、件数の文字、横のはみ出し
INFO = """() => ({
  count: document.querySelector('.layers-tools .count')?.textContent,
  keptBoxes: document.querySelectorAll('svg.layers [data-n].keep').length,
  keptLines: document.querySelectorAll('svg.layers [data-f].keep').length,
  scrollW: document.documentElement.scrollWidth,
  clientW: document.documentElement.clientWidth,
})"""

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, **({"executable_path": CHROME} if CHROME else {}))
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{BASE}/#/overview")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(900)
    out = {"before": page.evaluate(INFO)}
    page.fill(".layers-tools input[type=search]", "rdb")   # 合う語
    page.wait_for_timeout(300)
    out["hit"] = page.evaluate(INFO)
    page.screenshot(path=f"{OUT}/filter-hit.png")
    page.fill(".layers-tools input[type=search]", "zzz-no-such")   # 合わない語
    page.wait_for_timeout(200)
    out["miss"] = page.evaluate(INFO)
    out["errors"] = errors
    print(json.dumps(out, ensure_ascii=False))
    browser.close()
```

## 確かめる状態の選び方

| 操作 | 確かめる状態 |
|---|---|
| 絞り込み | 絞り込み前、合う語、合わない語 (0 件)、消した後 |
| 開閉 | 閉じた状態、開いた状態、すべて開いた状態 |
| 状態を覚える操作 (畳む、タブ) | 操作の後、読み直した後、幅を変えた後、元に戻した後 |
| 選ぶ操作 (行を選ぶ) | 選ぶ前、選んだ後 (連動する部分が変わること) |

## 気を付けること

- 条件によって出ない部品がある (例: 確かめられていない線が無い見本では、その絞り込みのボタンが出ない)。部品があるかを調べてから操作し、無かったら「確かめていない」と報告する。
- ハッシュだけの移動では、ページは読み直されない。状態を引き継ぎたくないときは、読み直す。
- 待ち時間は、通信が落ち着くのを待ってから、短く足す。
