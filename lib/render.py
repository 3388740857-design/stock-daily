"""
Render a self-contained HTML report (static markup + inline SVG, no JS) to PDF
using Playwright/Chromium. No JS charts are involved so there is no rendering
timing risk -- Playwright is used only because it is the most portable
headless-Chromium path across macOS/Linux/cloud sandboxes (unlike hardcoding
/Applications/Google Chrome.app, which only exists on macOS).

First run needs: pip install playwright && playwright install --with-deps chromium

Usage: python3 render.py input.html output.pdf
"""
import sys
from pathlib import Path


def render(html_path: str, pdf_path: str):
    from playwright.sync_api import sync_playwright

    html_path = Path(html_path).resolve()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"file://{html_path}")
        page.pdf(path=pdf_path, print_background=True, format="A4",
                 margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        browser.close()
    print(f"WROTE {pdf_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: python3 render.py input.html output.pdf", file=sys.stderr)
        sys.exit(1)
    render(sys.argv[1], sys.argv[2])
