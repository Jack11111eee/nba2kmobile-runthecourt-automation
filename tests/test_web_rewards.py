from __future__ import annotations

import unittest

from nba2k_web.config import WebConfig
from nba2k_web.rewards import claim_all

DAILY_STREAK_URL = "https://www.nba2kmobile.com/dailystreak"
HOME_URL = "https://www.nba2kmobile.com"


class FakeButton:
    def __init__(self, ident: str, text: str = "", *, disabled: bool = False,
                 claim_succeeds: bool = True) -> None:
        self.ident = ident
        self.text = text
        self._disabled = disabled
        self.claim_succeeds = claim_succeeds
        self.clicked = 0

    def inner_text(self) -> str:
        return self.text

    def get_attribute(self, name: str) -> str | None:
        if name == "id":
            return self.ident
        if name == "aria-label":
            return None
        return None

    def is_disabled(self) -> bool:
        return self._disabled

    def click(self) -> None:
        self.clicked += 1
        if self.claim_succeeds:
            self._disabled = True


class FakePage:
    def __init__(self, buttons_by_url: dict[str, list[FakeButton]]) -> None:
        self.buttons_by_url = buttons_by_url
        self.url = ""
        self.body_text = ""

    def goto(self, url: str, wait_until: str | None = None) -> None:
        self.url = url

    def wait_for_timeout(self, milliseconds: int) -> None:
        return None

    def query_selector_all(self, selector: str) -> list[FakeButton]:
        buttons = self.buttons_by_url.get(self.url, [])
        return [button for button in buttons if not button.is_disabled()]

    def inner_text(self, selector: str) -> str:
        return self.body_text


class ClaimAllTests(unittest.TestCase):
    def test_clicks_enabled_claim_buttons_and_skips_locked_and_buy(self) -> None:
        daily = [
            FakeButton("day1", "CLAIM", disabled=True),
            FakeButton("day7", "CLAIM"),
            FakeButton("final", "CLAIM FINAL REWARD"),
        ]
        home = [
            FakeButton("gift", "CLAIM GIFT"),
            FakeButton("paid-pack", "BUY"),
        ]
        page = FakePage({DAILY_STREAK_URL: daily, HOME_URL: home})
        summary = claim_all(page, WebConfig())

        self.assertEqual(summary.claimed, 3)
        self.assertEqual(summary.failed, 0)

        self.assertEqual(daily[0].clicked, 0)  # 已锁定
        self.assertEqual(daily[1].clicked, 1)
        self.assertEqual(daily[2].clicked, 1)
        self.assertEqual(home[0].clicked, 1)  # 免费礼物
        self.assertEqual(home[1].clicked, 0)  # 付费商品不可点

    def test_final_reward_unlocks_after_daily_claim(self) -> None:
        # 第 7 天：领完日常奖励后最终大奖才解锁，需要多轮领取
        daily = FakeButton("day7", "CLAIM")
        final = FakeButton("final", "CLAIM FINAL REWARD", disabled=True)
        buttons = [daily, final]

        def query(selector: str) -> list[FakeButton]:
            if page.url != DAILY_STREAK_URL:
                return []
            if daily.clicked and final.is_disabled():
                final._disabled = False
            return [b for b in buttons if not b.is_disabled()]

        page = FakePage({DAILY_STREAK_URL: buttons, HOME_URL: []})
        page.query_selector_all = query  # type: ignore[method-assign]
        summary = claim_all(page, WebConfig())

        self.assertEqual(daily.clicked, 1)
        self.assertEqual(final.clicked, 1)
        self.assertEqual(summary.claimed, 2)

    def test_records_failure_when_button_stays_enabled(self) -> None:
        home = [FakeButton("gift", "CLAIM GIFT", claim_succeeds=False)]
        page = FakePage({DAILY_STREAK_URL: [], HOME_URL: home})
        summary = claim_all(page, WebConfig())
        self.assertEqual(summary.claimed, 0)
        self.assertEqual(summary.failed, 1)


if __name__ == "__main__":
    unittest.main()
