#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""不启动浏览器，只测登录失败文案 / 账户展示逻辑。"""

import os
import sys
import time
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


def _jwt_with_exp(exp: int) -> str:
    import base64
    import json

    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).rstrip(b"=").decode()
    return f"aaa.{payload}.sig"


def test_token_seconds_left_reads_jwt_exp():
    exp = int(time.time()) + 3 * 3600
    left = app.token_seconds_left(_jwt_with_exp(exp))
    assert left is not None
    assert 2.5 * 3600 < left < 3.5 * 3600


def test_token_seconds_left_opaque_token():
    assert app.token_seconds_left("not-a-jwt") is None


def test_should_write_when_under_48h():
    os.environ["SESSION_REFRESH_BEFORE_HOURS"] = "48"
    should, reason = app.should_write_session_token("same", "same", 47 * 3600)
    assert should is True
    assert "< 48h" in reason


def test_should_skip_when_over_48h():
    os.environ["SESSION_REFRESH_BEFORE_HOURS"] = "48"
    should, reason = app.should_write_session_token("same", "same", 72 * 3600)
    assert should is False
    assert "未写回" in reason


def test_should_not_write_when_value_changed_but_still_fresh():
    os.environ["SESSION_REFRESH_BEFORE_HOURS"] = "48"
    should, reason = app.should_write_session_token("new-token", "old-token", 168 * 3600)
    assert should is False
    assert "未写回" in reason
    assert "168.0" in reason


def test_should_force_write_after_discord():
    should, reason = app.should_write_session_token("new-token", "old-token", 99 * 3600, force=True)
    assert should is True
    assert "强制写回" in reason


def test_should_skip_when_expiry_unknown_and_unchanged():
    should, reason = app.should_write_session_token("same", "same", None)
    assert should is False
    assert "未读到有效期" in reason
    assert "未写回" in reason


if __name__ == "__main__":
    tests = [
        test_account_label_falls_back_when_email_empty,
        test_account_label_masks_email,
        test_login_failure_disconnect_does_not_ask_new_discord_token,
        test_login_failure_401_asks_discord_token,
        test_token_seconds_left_reads_jwt_exp,
        test_token_seconds_left_opaque_token,
        test_should_write_when_under_48h,
        test_should_skip_when_over_48h,
        test_should_not_write_when_value_changed_but_still_fresh,
        test_should_force_write_after_discord,
        test_should_skip_when_expiry_unknown_and_unchanged,
    ]
    for fn in tests:
        fn()
        print("ok", fn.__name__)
    print("all passed")
