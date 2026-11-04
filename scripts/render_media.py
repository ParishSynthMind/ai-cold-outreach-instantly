"""Render the README images headless with Playwright (no browser window opens).

  python scripts/render_media.py REVIEW_HTML TRANSCRIPT_TXT EMAIL_TXT

1. media/review-queue.png    the approval page for the sample leads (real Claude drafts)
2. media/live-run.png        terminal transcript of the live test run (addresses masked)
3. media/delivered-email.png the first test email as it arrived (addresses masked)
"""
import html
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

MEDIA = Path(__file__).resolve().parent.parent / "media"
MONO = "'SF Mono', Menlo, Consolas, monospace"
FONT = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"


def terminal_page(text):
    lines = []
    for line in html.escape(text).splitlines():
        if line.startswith("$ "):
            line = f"<span style='color:#7ee787'>$</span> <b style='color:#fff'>{line[2:]}</b>"
        line = line.replace("[OK  ]", "<span style='color:#3fb950'>[OK  ]</span>")
        line = line.replace("[WARN]", "<span style='color:#d29922'>[WARN]</span>")
        line = line.replace("[FAIL]", "<span style='color:#f85149'>[FAIL]</span>")
        lines.append(line)
    return f"""<html><body style="margin:0;background:#fff">
<div id=wrap style="display:inline-block;padding:24px">
<div style="background:#0d1117;color:#c9d1d9;border-radius:10px;padding:18px 22px;font:14px/1.55 {MONO};
 box-shadow:0 4px 18px rgba(0,0,0,.18);max-width:1180px">
<div style="margin-bottom:10px"><span style="color:#f85149">&#9679;</span> <span style="color:#d29922">&#9679;</span>
 <span style="color:#3fb950">&#9679;</span> <span style="color:#8b949e;margin-left:8px">python -m outreach (live test, Instantly free trial)</span></div>
<pre style="margin:0;white-space:pre-wrap;font:inherit">{chr(10).join(lines)}</pre></div></div></body></html>"""


def email_page(meta, body):
    rows = "".join(f"<div><span style='color:#666;display:inline-block;width:110px'>{html.escape(k)}</span>"
                   f"{html.escape(v)}</div>" for k, v in meta)
    return f"""<html><body style="margin:0;background:#f3f4f6">
<div id=wrap style="display:inline-block;padding:28px">
<div style="background:#fff;border-radius:12px;padding:22px 28px;width:760px;font:15px/1.5 {FONT};
 box-shadow:0 4px 18px rgba(0,0,0,.12)">
<div style="font-size:20px;font-weight:700;margin-bottom:10px">Delivered: the first test email, as received</div>
<div style="font-size:13px;border-bottom:1px solid #e5e7eb;padding-bottom:10px;margin-bottom:14px">{rows}</div>
<pre style="white-space:pre-wrap;font:16px/1.55 Georgia,serif;margin:0">{html.escape(body)}</pre></div></div>
</body></html>"""


def shoot(page, html_text, out, selector="#wrap"):
    page.set_content(html_text)
    page.wait_for_timeout(300)
    page.locator(selector).screenshot(path=str(out))
    print("wrote", out)


def main(review_html, transcript, email_txt):
    MEDIA.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 900, "height": 900}, device_scale_factor=2)
        page.goto(Path(review_html).resolve().as_uri())
        page.screenshot(path=str(MEDIA / "review-queue.png"), full_page=True)
        print("wrote", MEDIA / "review-queue.png")
        page = browser.new_page(viewport={"width": 1250, "height": 900}, device_scale_factor=2)
        shoot(page, terminal_page(Path(transcript).read_text()), MEDIA / "live-run.png")
        raw = Path(email_txt).read_text()
        head, _, body = raw.partition("\n\n")
        meta = [tuple(x.split(": ", 1)) for x in head.splitlines()]
        page = browser.new_page(viewport={"width": 900, "height": 900}, device_scale_factor=2)
        shoot(page, email_page(meta, body), MEDIA / "delivered-email.png")
        browser.close()


if __name__ == "__main__":
    main(*sys.argv[1:4])
