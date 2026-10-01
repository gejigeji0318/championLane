"""
OP.GGのレーン別チャンピオン一覧から、チャンピオンごとに
ピック率が一番高いレーンを求めて docs/data.json に保存する。
GitHub Actions から1日1回実行される想定。

データ出典: OP.GG (https://op.gg)
"""
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

POSITIONS = ["top", "jungle", "mid", "adc", "support"]
URL = "https://op.gg/lol/champions?position={}"
WAIT_SEC = 3          # ページ間の待機（サーバー負荷対策）
MIN_CHAMPIONS = 100   # これ未満なら取得失敗とみなして上書きしない
OUT = Path(__file__).resolve().parent.parent / "docs" / "data.json"


def parse_pct(text):
    m = re.search(r"([\d.]+)\s*%", text)
    return float(m.group(1)) if m else None


def read_rows(page, pick_idx, result):
    """今表示されている行を読み取り result に追加する。新しく増えた数を返す"""
    before = len(result)
    for row in page.query_selector_all("table tbody tr"):
        link = row.query_selector('a[href*="/champions/"]')
        cells = row.query_selector_all("td")
        if not link or len(cells) <= pick_idx:
            continue
        m = re.search(r"/champions/([^/?#]+)", link.get_attribute("href") or "")
        rate = parse_pct(cells[pick_idx].inner_text())
        if m and rate is not None:
            result[m.group(1)] = rate
    return len(result) - before


def scrape_position(page, pos):
    page.goto(URL.format(pos), wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector("table tbody tr", timeout=30000)

    headers = [h.inner_text().strip() for h in page.query_selector_all("table thead th")]
    pick_idx = next(
        (i for i, h in enumerate(headers) if re.search(r"pick|ピック", h, re.I)), None
    )
    if pick_idx is None:
        raise RuntimeError(f"{pos}: ピック率の列が見つかりません。headers={headers}")

    # 表はスクロールで続きが読み込まれるので、増えなくなるまで下へスクロールしながら読む
    result = {}
    read_rows(page, pick_idx, result)
    idle = 0
    for _ in range(60):
        rows = page.query_selector_all("table tbody tr")
        if rows:
            rows[-1].scroll_into_view_if_needed()
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(1000)
        idle = 0 if read_rows(page, pick_idx, result) else idle + 1
        if idle >= 3:
            break
    print(f"{pos}: {len(result)}体取得")
    return result


def main():
    rates = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            locale="ja-JP",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
            ),
        )
        for pos in POSITIONS:
            for champ, rate in scrape_position(page, pos).items():
                rates.setdefault(champ, {})[pos] = rate
            time.sleep(WAIT_SEC)
        browser.close()

    if len(rates) < MIN_CHAMPIONS:
        print(f"取得数が少なすぎます({len(rates)}体)。data.jsonは更新しません。")
        sys.exit(1)

    champions = []
    for name in sorted(rates):
        main_lane = max(rates[name], key=rates[name].get)
        champions.append(
            {"name": name, "main": main_lane, "rate": rates[name][main_lane], "rates": rates[name]}
        )

    OUT.write_text(
        json.dumps(
            {
                "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": "OP.GG (https://op.gg)",
                "champions": champions,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"完了: {len(champions)}体 -> {OUT}")


if __name__ == "__main__":
    main()
