"""On-demand, non-persistent ATS PDF rendering."""

from __future__ import annotations

from pathlib import Path


class ResumePdfError(RuntimeError):
    """Raised when the optional browser renderer is unavailable."""


def _browser_launch_options(playwright) -> dict[str, str]:
    bundled = Path(playwright.chromium.executable_path)
    if bundled.exists():
        return {}
    candidates = (
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-browser"),
    )
    for candidate in candidates:
        if candidate.exists():
            return {"executable_path": str(candidate)}
    return {}


async def render_resume_pdf(html: str) -> bytes:
    try:
        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import async_playwright
    except ImportError as error:
        raise ResumePdfError(
            "尚未安装 Playwright。可先下载打印 HTML，或安装 Chromium 后重试。"
        ) from error
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                **_browser_launch_options(playwright)
            )
            page = await browser.new_page()
            await page.set_content(html, wait_until="load")
            content = await page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "14mm", "right": "15mm", "bottom": "14mm", "left": "15mm"},
            )
            await browser.close()
            return content
    except PlaywrightError as error:
        raise ResumePdfError(
            "Chromium 不可用。请运行 `python -m playwright install chromium` 后重试。"
        ) from error
