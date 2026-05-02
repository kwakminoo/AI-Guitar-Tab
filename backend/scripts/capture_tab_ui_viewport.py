"""Headless Playwright: open localhost ScoreViewer, run YouTube analyze, screenshot viewport."""
from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--youtube-url", required=True)
    parser.add_argument("--out", required=True, help="PNG path")
    parser.add_argument("--origin", default="http://127.0.0.1:3000")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--timeout-ms", type=int, default=1_800_000)
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("pip install playwright && playwright install chromium", file=sys.stderr)
        raise SystemExit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": args.width, "height": args.height})
        page.goto(args.origin, wait_until="domcontentloaded", timeout=120_000)
        page.get_by_placeholder("https://www.youtube.com/watch?v=").fill(args.youtube_url)
        page.get_by_role("button", name="불러오기").click()
        page.get_by_text("표시할 악보를 준비했습니다.").wait_for(timeout=args.timeout_ms)
        page.screenshot(path=args.out)
        browser.close()
    print(args.out)


if __name__ == "__main__":
    main()
