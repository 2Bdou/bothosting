#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""不启动浏览器，只测登录失败文案 / 账户展示逻辑。"""

import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("SESSION_TOKEN", "test-session-token")
os.environ.setdefault("DISCORD_TOKEN", "test-discord-token")

fake_sb = types.ModuleType("seleniumbase")


class _SB:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


fake_sb.SB = _SB
sys.modules.setdefault("seleniumbase", fake_sb)
sys.path.insert(0, str(ROOT))

import app  # noqa: E402


def test_account_label_falls_back_when_email_empty():
    app.EMAIL = ""
    label = app._account_label()
    assert "未配置" in label or "@" in label


def test_account_label_masks_email():
    app.EMAIL = "abcdefg@example.com"
    assert app._account_label() == "ab****fg@example.com"


def test_login_failure_disconnect_does_not_ask_new_discord_token():
    app._DISCORD_DETAIL = "Discord 已拿到授权码，但回调停留在 error=disconnect"
    app._LAST_FAIL_URL = "https://bot-hosting.net/login?error=disconnect&redirect=/a"
    msg = app._login_failure_message()
    assert "401" not in msg
    assert "disconnect" in msg.lower()
    assert "不要急着换 Discord Token" in msg


def test_login_failure_401_asks_discord_token():
    app._DISCORD_DETAIL = "Discord Token 已失效（HTTP 401），需要更新 DISCORD_TOKEN"
    app._LAST_FAIL_URL = ""
    msg = app._login_failure_message()
    assert "401" in msg
    assert "DISCORD_TOKEN" in msg


if __name__ == "__main__":
    tests = [
        test_account_label_falls_back_when_email_empty,
        test_account_label_masks_email,
        test_login_failure_disconnect_does_not_ask_new_discord_token,
        test_login_failure_401_asks_discord_token,
    ]
    for fn in tests:
        fn()
        print("ok", fn.__name__)
    print("all passed")
