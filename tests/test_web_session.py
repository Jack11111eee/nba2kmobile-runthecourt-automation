from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from nba2k_web.config import WebConfig, load_player_id, save_player_id
from nba2k_web.session import complete_login, is_logged_in


class FakeLocator:
    def __init__(self, count: int, click_cb=None) -> None:
        self._count = count
        self._click_cb = click_cb

    def count(self) -> int:
        return self._count

    @property
    def first(self) -> "FakeLocator":
        return self

    def click(self) -> None:
        if self._click_cb is not None:
            self._click_cb()


class FakeInputLocator(FakeLocator):
    def __init__(self, count: int, fill_cb=None) -> None:
        super().__init__(count)
        self._fill_cb = fill_cb

    def fill(self, value: str) -> None:
        if self._fill_cb is not None:
            self._fill_cb(value)


class FakePage:
    def __init__(self, *, logged_in: bool = False, has_verify: bool = True,
                 has_submit: bool = True, has_input: bool = True,
                 login_on_submit: bool = True) -> None:
        self._logged_in = logged_in
        self._has_verify = has_verify
        self._has_submit = has_submit
        self._has_input = has_input
        self._login_on_submit = login_on_submit
        self.filled_player_id: str | None = None

    @property
    def context(self) -> "FakePage":
        return self

    def cookies(self) -> list[dict[str, str]]:
        if self._logged_in:
            return [{"name": "__Host-AccessToken", "value": "token"}]
        return []

    def get_by_role(self, role: str, name: str | None = None) -> FakeLocator:
        if name == "Verify":
            return FakeLocator(1 if self._has_verify else 0)
        if name == "SUBMIT":
            callback = (lambda: setattr(self, "_logged_in", True)) if self._login_on_submit else None
            return FakeLocator(1 if self._has_submit else 0, click_cb=callback)
        return FakeLocator(0)

    def locator(self, selector: str) -> FakeLocator:
        if selector == "input#userid-input":
            return FakeInputLocator(
                1 if self._has_input else 0,
                fill_cb=lambda value: setattr(self, "filled_player_id", value),
            )
        return FakeLocator(0)

    def query_selector_all(self, selector: str) -> list:
        return []

    def wait_for_timeout(self, milliseconds: int) -> None:
        return None


class LoginTests(unittest.TestCase):
    def test_is_logged_in_detects_cookie(self) -> None:
        self.assertTrue(is_logged_in(FakePage(logged_in=True)))
        self.assertFalse(is_logged_in(FakePage(logged_in=False)))

    def test_complete_login_success(self) -> None:
        page = FakePage(logged_in=False)
        self.assertTrue(complete_login(page, "12345", WebConfig()))
        self.assertEqual(page.filled_player_id, "12345")

    def test_complete_login_already_logged_in(self) -> None:
        page = FakePage(logged_in=True)
        self.assertTrue(complete_login(page, "12345", WebConfig()))
        self.assertIsNone(page.filled_player_id)

    def test_complete_login_missing_verify(self) -> None:
        self.assertFalse(complete_login(FakePage(has_verify=False), "12345", WebConfig()))

    def test_complete_login_missing_input(self) -> None:
        self.assertFalse(complete_login(FakePage(has_input=False), "12345", WebConfig()))

    def test_complete_login_submit_fails(self) -> None:
        config = WebConfig(login_timeout_seconds=0.1)
        self.assertFalse(
            complete_login(FakePage(login_on_submit=False), "12345", config)
        )


class PlayerIdConfigTests(unittest.TestCase):
    def test_save_and_load_player_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = WebConfig(runtime_dir=Path(tmp) / "web")
            save_player_id(config, "ABC123")
            self.assertEqual(load_player_id(config), "ABC123")

    def test_env_var_takes_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = WebConfig(runtime_dir=Path(tmp) / "web")
            save_player_id(config, "file-id")
            os.environ["NBA2K_PLAYER_ID"] = "env-id"
            try:
                self.assertEqual(load_player_id(config), "env-id")
            finally:
                del os.environ["NBA2K_PLAYER_ID"]


if __name__ == "__main__":
    unittest.main()
