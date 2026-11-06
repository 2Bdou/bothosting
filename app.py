#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, re, sys, time, random, requests, subprocess,ctypes
from seleniumbase import SB

from notify import send_notification, load_smtp_config  # 通知渠道沿用 2Bdou/bothosting（TG + SMTP，可并存）

# 环境变量配置(可以直接私库在双引号里填写)
EMAIL         = os.environ.get("EMAIL") or ""           # 邮箱必填，登录和通知使用
PASSWORD      = os.environ.get("PASSWORD") or ""        # 主用密码登录方式, 失败时才使用,必须填写
# 通知：见 notify.py（与 dnshe-renewal 对齐；可用 TG_BOT_TOKEN/TG_CHAT_ID 或 TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID）
#   Telegram: TG_BOT_TOKEN + TG_CHAT_ID（或 TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID）
#   邮件:     SMTP_CONFIG（JSON）

BASE_URL = "https://bot-hosting.net"

if not (EMAIL and PASSWORD):
    print("ℹ️ 未配置 EMAIL 和 PASSWORD,脚本终止。")
    sys.exit(1)

NOTIFY_TITLE = "Bot-hosting 续期通知"


def _account_label() -> str:
    raw = (EMAIL or "").strip()
    if "@" not in raw:
        try:
            cfg = load_smtp_config()
            if cfg and cfg.get("to"):
                raw = str(cfg["to"]).split(",")[0].strip()
        except Exception:
            pass
    if "@" in raw:
        name, domain = raw.split("@", 1)
        if len(name) > 4:
            return f"{name[:2]}****{name[-2:]}@{domain}"
        return f"{name}@{domain}"
    if raw:
        return raw[:2] + "****"
    return "（未配置 EMAIL）"


def send_telegram_message(message: str) -> bool:
    """推送通知（TG + SMTP，失败不阻断主流程）；沿用 2Bdou/bothosting 的 notify 模块。"""
    try:
        return send_notification(message, title=NOTIFY_TITLE)
    except Exception as e:
        print(f"通知调用异常: {e}")
        print(f"::warning::通知调用异常: {e}")
        return False

# 通知格式
def format_notification(status: str, extra: str = "", error: str = "", expiry_date: str = "") -> str:
    local_time = time.gmtime(time.time() + 8 * 3600)
    now = time.strftime("%Y-%m-%d %H:%M:%S", local_time)
    masked_email = _account_label()

    lines = [
        "🇫🇮 Bot-hosting 续期通知",
        "",
        f"{status}",
        f"👤 登录账户: {masked_email}",
        "🔐 登录方式: Email/Password",
    ]
    if expiry_date:
        lines.append(f"📅 到期时间: {expiry_date}")
    if extra:
        lines.append(extra)
    if error:
        lines.append(f"⚠️ 错误信息: {error}")
    lines.append(f"⏱️ 登录时间: {now}")
    return "\n".join(lines)

# ---------- 基础工具 ----------
def js(sb, script, default=None, errors=None):
    try:
        result = sb.execute_script(script)
        return default if result is None else result
    except Exception as e:
        if errors is not None:
            errors.append(f"execute_script: {type(e).__name__}: {e}")
        try:
            result = sb.cdp.evaluate("(function(){ " + script + " })()")
            return default if result is None else result
        except Exception as e2:
            if errors is not None:
                errors.append(f"cdp.evaluate: {type(e2).__name__}: {e2}")
            return default

# Turnstile 定位失败时的现场诊断快照
def diag_turnstile_dom(sb, errors=None):
    snap = js(sb, """
        var out = [];
        var ifr = document.querySelectorAll('iframe');
        out.push('top-doc iframes: ' + ifr.length);
        for (var i = 0; i < ifr.length; i++) {
            var r = ifr[i].getBoundingClientRect();
            out.push('iframe w=' + Math.round(r.width) + ' h=' + Math.round(r.height) + ' src=' + (ifr[i].src || '').slice(0, 90));
        }
        var ts = document.querySelectorAll('[class*="turnstile"], [id*="turnstile"], input[name="cf-turnstile-response"]');
        out.push('turnstile-ish elements: ' + ts.length);
        for (var j = 0; j < ts.length; j++) {
            var rr = ts[j].getBoundingClientRect();
            var cls = (typeof ts[j].className === 'string') ? ts[j].className : (ts[j].getAttribute('class') || '');
            out.push(' - ' + ts[j].tagName + ' class=' + cls + ' w=' + Math.round(rr.width) + ' h=' + Math.round(rr.height));
        }
        out.push('window.turnstile=' + (typeof window.turnstile) + ' readyState=' + document.readyState);
        return out.join('\\n');
    """, "")
    for line in str(snap).splitlines():
        print("   [diag] " + line)
    if errors:
        for err in errors:
            print("   [diag][exec-error] " + str(err)[:200])
