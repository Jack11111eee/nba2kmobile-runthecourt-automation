from __future__ import annotations

import json
import time
from typing import Any

from playwright.sync_api import BrowserContext, Page, sync_playwright

from nba2k_web.config import WebConfig

ACCESS_TOKEN_COOKIE = "__Host-AccessToken"
PLAYER_ID_INPUT = "input#userid-input"
CLAIM_ENABLED = "button[data-testid='list-view-buy-button']:not([disabled])"


def load_state(config: WebConfig) -> dict[str, Any] | None:
    if not config.state_path.exists():
        return None
    try:
        return json.loads(config.state_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def save_state(context: BrowserContext, config: WebConfig) -> None:
    config.state_path.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(config.state_path))


def is_logged_in(page: Page) -> bool:
    return any(
        cookie["name"] == ACCESS_TOKEN_COOKIE and cookie.get("value")
        for cookie in page.context.cookies()
    )


def _open_verify_modal(page: Page) -> None:
    buttons = page.query_selector_all(CLAIM_ENABLED)
    if buttons:
        buttons[0].click()
        page.wait_for_timeout(3000)


def complete_login(page: Page, player_id: str, config: WebConfig) -> bool:
    """在已出现 Verify Player ID 弹窗的页面上完成手动登录，返回是否成功。"""
    if is_logged_in(page):
        return True

    verify = page.get_by_role("button", name="Verify")
    if verify.count() == 0:
        return False
    verify.first.click()
    page.wait_for_timeout(1000)

    player_input = page.locator(PLAYER_ID_INPUT)
    if player_input.count() == 0:
        return False
    player_input.fill(player_id)

    submit = page.get_by_role("button", name="SUBMIT")
    if submit.count() == 0:
        return False
    submit.first.click()

    deadline = time.monotonic() + config.login_timeout_seconds
    while time.monotonic() < deadline:
        if is_logged_in(page):
            return True
        page.wait_for_timeout(500)
    return False


def ensure_logged_in(page: Page, player_id: str, config: WebConfig) -> bool:
    """确保已登录：已登录则直接成功，否则触发弹窗并尝试手动登录。"""
    if is_logged_in(page):
        return True
    _open_verify_modal(page)
    return complete_login(page, player_id, config)


def run_login(config: WebConfig, player_id: str) -> bool:
    """有头浏览器登录：自动尝试手动输入，失败则人工介入，最终保存会话。"""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(storage_state=load_state(config))
        page = context.new_page()
        page.goto(f"{config.base_url}/dailystreak", wait_until="domcontentloaded")
        page.wait_for_timeout(4000)

        if ensure_logged_in(page, player_id, config):
            save_state(context, config)
            print("登录成功，会话已保存。")
            browser.close()
            return True

        print("未能自动登录。请在打开的浏览器中手动输入 Player ID 并完成验证。")
        print("完成后回到本终端按回车保存会话……")
        input()
        save_state(context, config)
        print("会话已保存。")
        browser.close()
        return True
