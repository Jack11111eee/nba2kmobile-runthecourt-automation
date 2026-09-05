from __future__ import annotations

import re
from dataclasses import dataclass, field

from playwright.sync_api import Page

from nba2k_web.config import WebConfig

CLAIM_ENABLED = "button[data-testid='list-view-buy-button']:not([disabled])"
FREE_GIFT_TEXT = re.compile(r"claim", re.IGNORECASE)
SUCCESS_TEXT = re.compile(
    r"(good job|successfully claimed|reward.*claimed|claimed.*reward)",
    re.IGNORECASE,
)
MAX_CLAIM_ROUNDS = 8


@dataclass
class ClaimOutcome:
    label: str
    claimed: bool
    source: str


@dataclass
class ClaimSummary:
    outcomes: list[ClaimOutcome] = field(default_factory=list)

    @property
    def claimed(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.claimed)

    @property
    def failed(self) -> int:
        return sum(1 for outcome in self.outcomes if not outcome.claimed)


def _label(button) -> str:
    return (button.inner_text() or "").strip() or (button.get_attribute("aria-label") or "")


def _key(button) -> str:
    return button.get_attribute("id") or _label(button)


def _click_and_verify(button, page: Page, config: WebConfig) -> bool:
    button.click()
    page.wait_for_timeout(int(config.post_claim_wait_seconds * 1000))
    try:
        if button.is_disabled():
            return True
    except Exception:
        pass
    try:
        if SUCCESS_TEXT.search(page.inner_text("body")):
            return True
    except Exception:
        pass
    return False


def _claim_enabled(page: Page, config: WebConfig, summary: ClaimSummary, source: str) -> None:
    clicked: set[str] = set()
    for _ in range(MAX_CLAIM_ROUNDS):
        buttons = page.query_selector_all(CLAIM_ENABLED)
        if source == "free-gift":
            buttons = [button for button in buttons if FREE_GIFT_TEXT.search(_label(button))]
        made_progress = False
        for button in buttons:
            key = _key(button)
            if key in clicked:
                continue
            clicked.add(key)
            claimed = _click_and_verify(button, page, config)
            summary.outcomes.append(ClaimOutcome(_label(button), claimed, source))
            made_progress = True
        if not made_progress:
            break


def claim_all(page: Page, config: WebConfig) -> ClaimSummary:
    summary = ClaimSummary()

    page.goto(f"{config.base_url}/dailystreak", wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    _claim_enabled(page, config, summary, source="daily-streak")

    page.goto(config.base_url, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    _claim_enabled(page, config, summary, source="free-gift")

    return summary
