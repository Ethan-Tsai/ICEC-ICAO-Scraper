from __future__ import annotations

from playwright._impl._errors import TargetClosedError
from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from playwright_stealth import stealth_async

from .config import SiteConfig


class BrowserSession:
    def __init__(self, browser: Browser, context: BrowserContext, page: Page):
        self.browser = browser
        self.context = context
        self.page = page

    async def close(self) -> None:
        try:
            await self.context.close()
        except (TargetClosedError, Exception):
            pass
        try:
            await self.browser.close()
        except (TargetClosedError, Exception):
            pass


async def start_session(cfg: SiteConfig, *, headful_override: bool) -> tuple[object, BrowserSession]:
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=not headful_override and cfg.browser.headless)
    context = await browser.new_context(
        locale=cfg.browser.locale,
        timezone_id=cfg.browser.timezone_id,
        user_agent=cfg.browser.user_agent,
        extra_http_headers={"Accept-Language": cfg.browser.accept_language},
    )
    page = await context.new_page()
    await stealth_async(page)
    
    # --- Enterprise Optimization: Block heavy media & fonts ---
    async def abort_route(route):
        await route.abort()
        
    await page.route("**/*.{png,jpg,jpeg,webp,gif,svg,ttf,woff,woff2,mp4,mp3,ico}", abort_route)
    
    return playwright, BrowserSession(browser=browser, context=context, page=page)
