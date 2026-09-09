#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, re, sys, time, json, base64, requests, subprocess
import urllib.request, urllib.parse, urllib.error
from datetime import datetime
from seleniumbase import SB

from notify import send_notification, load_smtp_config  # 通用通知（TG + SMTP），可被其它项目复用

# 环境变量配置(可以直接私库在双引号里填写)
EMAIL         = os.environ.get("EMAIL") or ""           # 展示用；为空则回退 SMTP_CONFIG.to
SESSION_TOKEN = (os.environ.get("SESSION_TOKEN") or "").strip()   # session token，默认登录方式,非必须
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN") or ""   # Discord Token 备用登录方式, 失败时才使用,必须填写
GH_TOKEN      = os.environ.get("GH_TOKEN") or ""        # GitHub classic PAT（repo 权限），到期前写回 SESSION_TOKEN
# 通知：见 notify.py
#   Telegram: TG_BOT_TOKEN + TG_CHAT_ID（或 TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID）
#   邮件:     SMTP_CONFIG（JSON，与 dnshe-renewal 相同） 

# 解析 DISCORD_TOKEN
DC_TOKEN = ""
if DISCORD_TOKEN:
    _parts = DISCORD_TOKEN.split(",", 1)
    DC_TOKEN = _parts[-1].strip()

if not SESSION_TOKEN and not DC_TOKEN:
    print("ℹ️ 未配置 SESSION_TOKEN 和 DISCORD_TOKEN,脚本终止。")
    try:
        send_notification(
            "未配置 SESSION_TOKEN 和 DISCORD_TOKEN，脚本终止。",
            title="Bot-hosting 续期通知",
        )
    except Exception:
        pass
    sys.exit(1)

# 构造cookie
COOKIES = {
    "session_token": SESSION_TOKEN,
    "login": "true",
    "theme": "system",
}

# 记录本次登录方式（用于通知）
_LOGIN_METHOD = "SESSION_TOKEN"
_SESSION_PERSIST_MSG = "尚未检查 SESSION_TOKEN 写回"
_DISCORD_DETAIL = ""
_LAST_FAIL_URL = ""
_KNOWN_SESSION_TOKEN = SESSION_TOKEN  # 进程内已写回的值，避免 Discord 后重复 gh secret set

# 获取cookie到期时间
def get_cookie_info(sb, name):
    cookies = sb.get_cookies()
    for c in cookies:
        if c.get('name') == name:
            value = c.get('value')
            expiry_ts = c.get('expiry')
            expiry_dt = datetime.fromtimestamp(expiry_ts) if expiry_ts else None
            return value, expiry_dt
    return None, None


def refresh_before_hours() -> int:
    """剩余不足该小时数才写回 Secret。默认 48，可用 SESSION_REFRESH_BEFORE_HOURS 覆盖。"""
    try:
        return int(os.environ.get("SESSION_REFRESH_BEFORE_HOURS", "48") or "48")
    except (TypeError, ValueError):
        return 48


def token_seconds_left(token: str):
    """读 JWT exp，不校验签名（与 puratya-renew 相同）。解析失败返回 None。"""
    try:
        parts = (token or "").split(".")
        if len(parts) < 2:
            return None
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        exp = data.get("exp")
        if exp is None:
            return None
        return int(exp) - int(time.time())
    except Exception:
        return None


def session_seconds_left(token: str, expiry_dt):
    """综合 JWT exp 与浏览器 Cookie expiry，取更短的剩余秒数。"""
    jwt_left = token_seconds_left(token)
    cookie_left = None
    if expiry_dt:
        cookie_left = (expiry_dt - datetime.now()).total_seconds()
    candidates = [x for x in (jwt_left, cookie_left) if x is not None]
    if not candidates:
        return None
    return min(candidates)


def should_write_session_token(new_token, old_token, seconds_left, force: bool = False):
    """是否写回 SESSION_TOKEN。返回 (should_write, reason)。

    对齐 puratya-renew：有效期不足阈值才换票；Discord 换到的新票强制写回。
    """
    if force:
        return True, "Discord 登录换到新 session，强制写回"
    if not new_token:
        return False, "浏览器中未读到 session_token，无法写回"
    if new_token != (old_token or "").strip():
        return True, "session_token 值已变化，写回 Secrets"
    hours_limit = refresh_before_hours()
    if seconds_left is None:
        return False, "未读到有效期且 token 未变化，跳过写回"
    hours_left = seconds_left / 3600.0
    if seconds_left < hours_limit * 3600:
        return True, (
            f"session_token 剩余约 {hours_left:.1f} 小时（<{hours_limit}h），写回 Secrets"
        )
    return False, (
        f"session_token 剩余约 {hours_left:.1f} 小时（≥{hours_limit}h），无需写回"
    )


def clear_stale_session_cookies(sb, wipe_all_if_stuck: bool = False) -> None:
    """删掉过期的 session_token / login，避免 bot-hosting 一直返回 error=disconnect。

    Discord OAuth 开始前可以在删不掉时 wipe 全部 cookie。
    打开回调 URL 前只删这两条，保留 /login/discord 种下的 OAuth 会话 cookie。
    """
    print("🧹 清除过期的 session_token / login Cookie...")
    try:
        url = sb.get_current_url() or ""
    except Exception:
        url = ""
    if "bot-hosting.net" not in url:
        try:
            sb.open("https://bot-hosting.net/")
            sb.wait_for_ready_state_complete()
            sb.sleep(1)
        except Exception as e:
            print(f"⚠️ 无法打开 bot-hosting 以清 Cookie: {e}")
            return

    for name in ("session_token", "login"):
        try:
            sb.delete_cookie(name)
            print(f"✅ 已删除 Cookie: {name}")
        except Exception as e:
            print(f"⚠️ delete_cookie({name}) 失败: {e}")

    try:
        leftover = [
            c.get("name")
            for c in (sb.get_cookies() or [])
            if c.get("name") in ("session_token", "login")
        ]
    except Exception as e:
        print(f"⚠️ 复查 Cookie 失败: {e}")
        leftover = []

    if leftover:
        print(f"⚠️ 仍残留 Cookie: {leftover}")
        if wipe_all_if_stuck:
            try:
                sb.delete_all_cookies()
                print("✅ 已 delete_all_cookies")
            except Exception as e:
                print(f"⚠️ delete_all_cookies 失败: {e}")


def persist_session_token(sb, force: bool = False) -> bool:
    """按有效期写回 SESSION_TOKEN：剩余 < 48h、值变化、或 Discord 换票时才 gh secret set。"""
    global _SESSION_PERSIST_MSG, _KNOWN_SESSION_TOKEN
    print("🔄 检查 SESSION_TOKEN 是否需要写回 Secrets")
    new_token, token_expiry = get_cookie_info(sb, "session_token")
    seconds_left = session_seconds_left(new_token or "", token_expiry)
    if token_expiry:
        print(f"📅 浏览器 Cookie 到期时间: {token_expiry}")
    jwt_left = token_seconds_left(new_token or "")
    if jwt_left is not None:
        print(f"📅 JWT exp 剩余约 {jwt_left / 3600.0:.1f} 小时")
    if seconds_left is not None:
        print(f"📅 session_token 剩余约 {seconds_left / 3600.0:.1f} 小时")

    should, reason = should_write_session_token(
        new_token, _KNOWN_SESSION_TOKEN, seconds_left, force=force
    )
    print(f"ℹ️ {reason}")
    _SESSION_PERSIST_MSG = reason
    if not should:
        return False
    if not new_token:
        return False
    masked = new_token[:4] + "..." + new_token[-4:] if len(new_token) > 8 else "***"
    print(f"📋 当前 session_token: {masked}")
    if not GH_TOKEN:
        _SESSION_PERSIST_MSG = "未设置 GH_TOKEN，无法写回 Secrets"
        print(f"⚠️ {_SESSION_PERSIST_MSG}")
        print(f"📋 请手动设置 SESSION_TOKEN = {masked}")
        return False
    if update_github_secret("SESSION_TOKEN", new_token):
        _KNOWN_SESSION_TOKEN = new_token
        _SESSION_PERSIST_MSG = "SESSION_TOKEN 已写回 Secrets"
        print(f"✅ {_SESSION_PERSIST_MSG}")
        return True
    _SESSION_PERSIST_MSG = "写回 Secrets 失败，请检查 GH_TOKEN 的 repo 权限"
    print(f"⚠️ {_SESSION_PERSIST_MSG}")
    return False


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


def _login_failure_message() -> str:
    detail = (_DISCORD_DETAIL or "").strip()
    fail_url = _LAST_FAIL_URL or ""
    if "401" in detail or "Discord Token 已失效" in detail:
        return detail
    if "disconnect" in detail.lower() or "error=disconnect" in fail_url:
        return (
            "SESSION_TOKEN 已失效；Discord 已拿到授权码，"
            "但 bot-hosting 返回 error=disconnect。"
            "不要急着换 Discord Token；请看 Actions 是否已清除旧 Cookie。"
        )
    if "fraud" in detail.lower():
        return detail
    if not SESSION_TOKEN and DC_TOKEN:
        return detail or "Discord OAuth 登录失败"
    if SESSION_TOKEN and DC_TOKEN:
        return detail or "SESSION_TOKEN 和 Discord OAuth 均失败"
    return detail or "Cookie 已失效或页面异常"

# 更新cookie到secrets
def update_github_secret(secret_name, new_value):
    if not new_value:
        print(f"⚠️ 跳过更新 {secret_name}：新值为空")
        return False
    masked = new_value[:4] + "..." + new_value[-4:] if len(new_value) > 8 else "***"
    print(f"🔄 更新 Secret: {secret_name} (新值: {masked})")
    try:
        env = os.environ.copy()
        if GH_TOKEN:
            env["GH_TOKEN"] = GH_TOKEN
        proc = subprocess.run(
            ["gh", "secret", "set", secret_name, "--body", new_value],
            capture_output=True, text=True, timeout=30, check=False,
            env=env
        )
        if proc.returncode == 0:
            return True
        else:
            print(f"❌ 更新失败: {proc.stderr.strip()}")
            return False
    except Exception as e:
        print(f"❌ 异常: {e}")
        return False

# 业务文案交给通用 notify 模块（TG + SMTP，失败不阻断）
NOTIFY_TITLE = "Bot-hosting 续期通知"


def notify(message: str) -> bool:
    """推送通知；返回是否成功（未配置通道视为成功）。"""
    try:
        return send_notification(message, title=NOTIFY_TITLE)
    except Exception as e:
        print(f"通知调用异常: {e}")
        print(f"::warning::通知调用异常: {e}")
        return False


# 通知格式（业务文案，与推送通道无关）
def format_notification(status: str, extra: str = "", error: str = "", expiry_date: str = "") -> str:
    local_time = time.gmtime(time.time() + 8 * 3600)
    now = time.strftime("%Y-%m-%d %H:%M:%S", local_time)
    masked_email = _account_label()

    lines = [
        "🇫🇮 Bot-hosting 续期通知",
        "",
        f"{status}",
        f"👤 登录账户: {masked_email}",
        f"🔐 登录方式: {_LOGIN_METHOD}",
    ]
    if _SESSION_PERSIST_MSG:
        lines.append(f"🔑 {_SESSION_PERSIST_MSG}")
    if expiry_date:
        lines.append(f"📅 到期时间: {expiry_date}")
    if extra:
        lines.append(extra)
    if error:
        lines.append(f"⚠️ 错误信息: {error}")
    lines.append(f"⏱️ 登录时间: {now}")
    return "\n".join(lines)

# 等待Turnstile验证通过
def wait_for_turnstile_pass(sb, timeout=30):
    start = time.time()
    cf_indicators = ["verify you are human", "确认您是真人", "troubleshoot", "just a moment"]
    while time.time() - start < timeout:
        page_lower = sb.get_page_source().lower()
        if not any(x in page_lower for x in cf_indicators):
            print("✅ Turnstile 验证已通过")
            # sb.save_screenshot("turnstile_passed.png")
            return True
        sb.sleep(1)
    print("❌ Turnstile 验证超时未通过")
    return False
    
# 获取当前出口ip
def get_current_ip(proxy_server: str = "") -> str:
    proxies = None
    if proxy_server:
        proxies = {"http": proxy_server, "https": proxy_server}
    response = requests.get("https://api.ip.sb/ip", proxies=proxies, timeout=15)
    response.raise_for_status()
    return response.text.strip()

# 时间格式化
def format_countdown(countdown_str: str) -> str:
    try:
        h, m, _ = countdown_str.split(':')
        h = int(h)
        m = int(m)
        if h > 0:
            return f"{h}h{m}min"
        else:
            return f"{m}min"
    except:
        return countdown_str

# 获取过期日期
def extract_expiry_date(page_source: str) -> str:
    patterns = [
        r"[Ee]xpires\s*[:\-]?\s*(\d{4}/\d{2}/\d{2})",   # Expires 2026/07/07
        r"[Ee]xpires\s*[:\-]?\s*(\d{2}/\d{2}/\d{4})",   # Expires 07/07/2026 (MM/DD/YYYY)
        r"(\d{4}/\d{2}/\d{2})\s*[\-–]\s*renew",        # 2026/07/07 - renew
        r"(\d{2}/\d{2}/\d{4})\s*[\-–]\s*renew",        # 07/07/2026 - renew
        r"(\d{4}/\d{2}/\d{2})\s*[\-–]\s*renew manually to extend for 4 days", # 2026/07/07 - renew manually to extend for 4 days
    ]
    for pattern in patterns:
        match = re.search(pattern, page_source)
        if match:
            date_str = match.group(1)
            # 如果是 MM/DD/YYYY 格式，转换为 YYYY/MM/DD
            if len(date_str.split('/')[-1]) == 4:  # 年份长度4
                parts = date_str.split('/')
                if len(parts[0]) == 2:  # 第一部分是2位（月）
                    # 修正：将 MM/DD/YYYY 转为 YYYY/MM/DD
                    return f"{parts[2]}/{parts[0]}/{parts[1]}"
            return date_str
    return None

#   Discord OAuth 登录（SESSION_TOKEN 失效时的备用方案）
DISCORD_CLIENT_ID   = "884382422530158623"
OAUTH_REDIRECT_URI  = "https://bot-hosting.net/login"
OAUTH_SCOPE         = "identify email guilds"
DISCORD_API         = "https://discord.com/api/v9/oauth2/authorize"
DISCORD_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
)
STATE_RE = re.compile(r"[?&]state=([^&]+)")


def capture_discord_state(sb) -> str:
    """打开 /login/discord，从落地页 URL 里提取本次会话的 state"""
    print("🔎 获取 Discord OAuth state...")
    sb.uc_open_with_reconnect("https://bot-hosting.net/login/discord", reconnect_time=4)
    time.sleep(2)

    url = sb.get_current_url()
    if "discord.com" not in url:
        print(f"⚠️ 未跳转到 Discord 相关页面，当前 URL：{url}")
        return ""

    m = STATE_RE.search(url)
    if not m:
        print(f"❌ 未能从 URL 中解析出 state，当前 URL：{url}")
        return ""

    state = urllib.parse.unquote(m.group(1))
    print(f"✅ 已捕获 state（当前落地页：{urllib.parse.urlparse(url).path}）")
    return state


def discord_authorize(state: str) -> str:
    """用 DC_TOKEN 直接完成 Discord 侧授权，返回跳转回 bot-hosting.net 的 location"""
    global _DISCORD_DETAIL
    query = urllib.parse.urlencode({
        "client_id":     DISCORD_CLIENT_ID,
        "response_type": "code",
        "redirect_uri":  OAUTH_REDIRECT_URI,
        "scope":         OAUTH_SCOPE,
        "state":         state,
    })
    authorize_url = f"{DISCORD_API}?{query}"

    referer = (
        "https://discord.com/oauth2/authorize?" +
        urllib.parse.urlencode({
            "client_id":     DISCORD_CLIENT_ID,
            "redirect_uri":  OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope":         OAUTH_SCOPE,
            "state":         state,
        })
    )

    headers = {
        "accept":           "*/*",
        "authorization":    DC_TOKEN,
        "content-type":     "application/json",
        "origin":           "https://discord.com",
        "referer":          referer,
        "user-agent":       DISCORD_UA,
        "x-discord-locale": "zh-CN",
    }

    body = json.dumps({
        "permissions": "0",
        "authorize": True,
        "integration_type": 0,
        "location_context": {
            "guild_id": "10000",
            "channel_id": "10000",
            "channel_type": 10000,
        },
    })

    # 如果配置了代理，Discord API 请求也走代理
    proxies = None
    _is_proxy = os.environ.get("IS_PROXY", "false").lower() == "true"
    _proxy_server = os.environ.get("PROXY_SERVER", "").strip() or "http://127.0.0.1:1080"
    if _is_proxy:
        proxies = {"http": _proxy_server, "https": _proxy_server}

    try:
        resp = requests.post(authorize_url, headers=headers, data=body, proxies=proxies, timeout=20)
        if resp.status_code != 200:
            snippet = (resp.text or "")[:300]
            print(f"❌ Discord OAuth2 授权失败: HTTP {resp.status_code} - {snippet}")
            if resp.status_code == 401:
                _DISCORD_DETAIL = "Discord Token 已失效（HTTP 401），需要更新 DISCORD_TOKEN"
            else:
                _DISCORD_DETAIL = f"Discord OAuth2 授权失败: HTTP {resp.status_code}"
            return ""
        resp_data = resp.json()
    except Exception as e:
        print(f"❌ Discord OAuth2 授权异常: {e}")
        _DISCORD_DETAIL = f"Discord OAuth2 授权异常: {e}"
        return ""

    location = resp_data.get("location", "")
    if not location:
        print(f"❌ 授权响应中未找到 location 字段: {resp_data}")
        _DISCORD_DETAIL = "Discord 授权响应中没有 location（未拿到回调 code）"
        return ""

    masked = re.sub(r"code=[^&]+", "code=***", location)
    print(f"✅ 拿到回调 URL: {masked}")
    return location


def do_discord_login(sb) -> bool:
    """通过 Discord Token 走完整 OAuth 流程登录 bot-hosting.net"""
    global _DISCORD_DETAIL, _LAST_FAIL_URL
    print("\n🔑 通过 Discord Token 登录...")

    state = capture_discord_state(sb)
    if not state:
        _DISCORD_DETAIL = "未能从 Discord 落地页解析 OAuth state"
        sb.save_screenshot("login_no_state.png")
        return False

    location = discord_authorize(state)
    if not location:
        return False

    # 只去掉过期 session，保留刚才 /login/discord 种下的 OAuth cookie
    clear_stale_session_cookies(sb, wipe_all_if_stuck=False)

    print("↩️ 携带授权码打开回调链接...")
    sb.uc_open_with_reconnect(location, reconnect_time=4)
    time.sleep(3)

    url = sb.get_current_url()
    _LAST_FAIL_URL = url

    if "/error/banned" in url:
        print("🚫 账号已被封禁")
        _DISCORD_DETAIL = "账号已被 bot-hosting 封禁"
        sb.save_screenshot("login_banned.png")
        return False

    if "bot-hosting.net" not in url:
        print(f"❌ 回调后未跳转至 bot-hosting.net，当前 URL：{url}")
        _DISCORD_DETAIL = f"回调后未回到 bot-hosting.net：{url}"
        sb.save_screenshot("login_no_redirect.png")
        return False

    try:
        body_text = sb.get_text("body")
    except Exception:
        body_text = ""
    if "fraud" in body_text.lower():
        print("🚫 触发风控（fraud attempt），可能是 IP 被拦截")
        _DISCORD_DETAIL = "触发风控（fraud attempt），可能是代理 IP 被拦截"
        sb.save_screenshot("login_fraud.png")
        return False

    for _ in range(30):
        url = sb.get_current_url()
        _LAST_FAIL_URL = url
        path = urllib.parse.urlparse(url).path
        if "error=disconnect" in url:
            continue
        if "bot-hosting.net" in url and path != "/login" and not path.startswith("/login/discord"):
            print(f"✅ Discord OAuth 登录成功！当前页面：{url}")
            return True
        time.sleep(0.5)

    print(f"❌ 登录超时或未跳转成功，最终停留在：{url}")
    if "error=disconnect" in (url or ""):
        _DISCORD_DETAIL = (
            "Discord 已拿到授权码，但回调停留在 error=disconnect"
        )
    else:
        _DISCORD_DETAIL = f"Discord 回调超时，停留在：{url}"
    try:
        body_text = sb.get_text("body")
        print(f"📄 页面正文片段：{body_text[:200].strip()!r}")
    except Exception:
        pass
    sb.save_screenshot("login_timeout.png")
    return False


def inject_session_cookies(sb, cookies: dict) -> bool:
    """
    在 bot-hosting.net 域下注入 cookie。
    - value 会 strip
    - 补 path/secure，多组 domain 写法兜底（适配新版 Chrome）
    - 单条失败只打日志，不抛异常，便于降级 Discord 登录
    返回：是否至少成功注入一条有意义的 cookie
    """
    try:
        url = sb.get_current_url() or ""
    except Exception:
        url = ""
    if "bot-hosting.net" not in url:
        print(f"⚠️ 当前不在 bot-hosting 域，跳过 Cookie 注入。URL={url}")
        return False

    ok_any = False
    for name, value in cookies.items():
        if not value:
            continue
        val = str(value).strip()
        if not val:
            continue
        # 依次尝试：不写 domain / 点域 / 裸域
        variants = [
            {"name": name, "value": val, "path": "/", "secure": True},
            {"name": name, "value": val, "path": "/", "secure": True, "domain": ".bot-hosting.net"},
            {"name": name, "value": val, "path": "/", "secure": True, "domain": "bot-hosting.net"},
        ]
        last_err = None
        injected = False
        for cookie in variants:
            try:
                sb.add_cookie(cookie)
                injected = True
                ok_any = True
                break
            except Exception as e:
                last_err = e
        if injected:
            print(f"✅ Cookie 已注入: {name}")
        else:
            print(f"⚠️ Cookie 注入失败: {name} → {last_err}")
    return ok_any


# 主流程
def run() -> None:
    print("#" * 25)
    print("   Bot-hosting 自动续期")
    print("#" * 25)

    IS_PROXY = os.environ.get("IS_PROXY", "false").lower() == "true"
    PROXY_SERVER = os.environ.get("PROXY_SERVER", "").strip() or "http://127.0.0.1:1080"
    HEADLESS = os.environ.get("HEADLESS", "false").lower() == "true"

    sb_kwargs = {"uc": True, "headless": HEADLESS}

    if IS_PROXY:
        print(f"🔗 挂载代理: {PROXY_SERVER}")
        sb_kwargs["proxy"] = PROXY_SERVER
    else:
        print("🍭 未使用代理，直连访问")

    global _LOGIN_METHOD, _LAST_FAIL_URL, _DISCORD_DETAIL

    with SB(**sb_kwargs) as sb:
        try:
            ip = get_current_ip(PROXY_SERVER if IS_PROXY else "")
            print(f"📍 当前出口IP: {ip}")
        except Exception as e:
            print(f"⚠️ 获取出口 IP 失败: {e}")

        login_ok = False

        # 方式1: SESSION_TOKEN Cookie 登录（默认）
        if SESSION_TOKEN:
            print("🚀 启动浏览器（SESSION_TOKEN）...")
            try:
                sb.open("https://bot-hosting.net/")
                sb.wait_for_ready_state_complete()
                sb.sleep(2)

                print("📝 注入 Cookie...")
                inject_session_cookies(sb, COOKIES)

                print("🌐 访问 https://bot-hosting.net/a/billings ...")
                sb.open("https://bot-hosting.net/a/billings")
                sb.wait_for_ready_state_complete()
                sb.sleep(3)
                current_url = sb.get_current_url()
                current_title = sb.get_title()
                print(f"📝 当前URL: {current_url}, Title: {current_title}")

                if "/a/billings" in current_url and "/login" not in current_url and "error=" not in current_url:
                    login_ok = True
                    print("✅ SESSION_TOKEN 登录成功, 当前已到达账单页")
                else:
                    _LAST_FAIL_URL = current_url or ""
                    print(f"❌ SESSION_TOKEN 登录失败，当前URL: {current_url}, 当前标题: {current_title}")
            except Exception as e:
                # 例如 UnableToSetCookieException：不再让整个 job 直接崩，交给 Discord 备用登录
                print(f"❌ SESSION_TOKEN 登录流程异常（将尝试 Discord）: {e}")

        # 方式2: Discord OAuth 登录（备用）
        if not login_ok and DC_TOKEN:
            _LOGIN_METHOD = "Discord Token"
            print("\n🔄 SESSION_TOKEN 登录失败或未配置，尝试 Discord OAuth 登录...")
            clear_stale_session_cookies(sb, wipe_all_if_stuck=True)
            if do_discord_login(sb):
                print("🌐 访问 https://bot-hosting.net/a/billings ...")
                sb.open("https://bot-hosting.net/a/billings")
                sb.wait_for_ready_state_complete()
                sb.sleep(3)
                current_url = sb.get_current_url()
                current_title = sb.get_title()
                print(f"📝 当前URL: {current_url}, Title: {current_title}")

                if "a/billings" in current_url and "error=" not in current_url:
                    login_ok = True
                    print("✅ Discord OAuth 登录成功,当前已到达账单页")
                else:
                    _LAST_FAIL_URL = current_url or ""
                    print(f"❌ Discord OAuth 登录后仍未到达账单页，当前URL: {current_url}")
                    if "error=disconnect" in (current_url or ""):
                        _DISCORD_DETAIL = (
                            "Discord 登录后仍停留在 error=disconnect"
                        )
            else:
                print("❌ Discord OAuth 登录失败")

        if not login_ok:
            error_msg = _login_failure_message()
            notify(format_notification("❌ 登录失败", error=error_msg))
            print("::error::登录失败，workflow 以失败退出")
            sys.exit(1)

        if _LOGIN_METHOD == "Discord Token":
            print("ℹ️ 本次使用 Discord OAuth 登录，立即写回新的 SESSION_TOKEN")

        # Discord 换票强制写回；SESSION_TOKEN 登录则仅在剩余 < 48h 或值变化时写回
        persist_session_token(sb, force=(_LOGIN_METHOD == "Discord Token"))

        # 提取当前到期日期
        sb.sleep(2)
        page_source = sb.get_page_source()
        current_expiry = extract_expiry_date(page_source)
        if current_expiry:
            print(f"📅 当前到期日期: {current_expiry}")
        else:
            print("⚠️ 未能提取当前到期日期")

        # 寻找外部续期按钮
        outer_renew_selector = None
        countdown_text = None
        possible_selectors = [
            'button:contains("Renew")',
            'button:contains("Renew free plan")',
            'a:contains("Renew")',
            '[class*="renew"]',
            '[class*="Renew"]',
        ]

        for selector in possible_selectors:
            try:
                if sb.is_element_visible(selector):
                    button_text = sb.get_text(selector)
                    if "Renew in" in button_text:
                        match = re.search(r"Renew in (\d{2}:\d{2}:\d{2})", button_text)
                        if match:
                            countdown_text = match.group(1)
                        break
                    elif "Renew" in button_text and "in" not in button_text.lower():
                        outer_renew_selector = selector
                        print(f"✅ 续期按钮可用: '{button_text}'")
                        break
            except Exception:
                pass

        # 点击外部续期按钮等待弹窗
        if outer_renew_selector:
            print("🔄 点击外部续期按钮，等待验证窗口...")
            try:
                sb.sleep(2)
                sb.click(outer_renew_selector)
                sb.sleep(15)  # 等待模态框加载，可能因网络因素加载慢
            except Exception as e:
                print(f"❌ 点击外部按钮失败: {e}")
                notify(format_notification("❌ 续期失败", error="点击外部续期按钮出错"))
                return

            # 处理弹窗中的 Turnstile
            print("🔒 检测弹窗中的 Turnstile 验证...")
            turnstile_passed = False
            for attempt in range(1, 4):
                try:
                    sb.uc_gui_click_captcha()
                    time.sleep(12)
                except Exception as e:
                    print(f"⚠️ 点击 Turnstile 出错: {e}")

                if wait_for_turnstile_pass(sb, timeout=20):
                    turnstile_passed = True
                    break
                else:
                    print(f"⏳ 第 {attempt} 次未通过，重试点击...")

            if not turnstile_passed:
                print("❌ Turnstile 验证最终未通过，脚本退出")
                notify(format_notification("❌ 续期失败", error="Turnstile 验证未通过"))
                return

            # 点击续期按钮
            print("⏳ 等待续期按钮可用并点击...")
            time.sleep(5)

            try:
                sb.click('button:contains("Renew for 4 days")', timeout=8)
                print("✅ 已点击续期按钮")
            except Exception as e:
                print(f"续期按钮点击失败: {e}")

            print("⏳ 等待新的过期时间...")
            sb.sleep(6)

            # 提取新的到期日期和倒计时
            new_page_text = sb.get_page_source()
            new_expiry = extract_expiry_date(new_page_text)
            new_match = re.search(r"Renew in (\d{2}:\d{2}:\d{2})", new_page_text)
            if new_match:
                new_countdown = new_match.group(1)
                print(f"✅ 续期成功！新的倒计时: {new_countdown}")
                if new_expiry:
                    print(f"📅 新的到期日期: {new_expiry}")
                notify(
                    format_notification(
                        "✅ 续期成功",
                        extra=f"⏱️ 可续期时间: {format_countdown(new_countdown)}后",
                        expiry_date=new_expiry or "（未获取到）"
                    )
                )
            else:
                if new_expiry and new_expiry != current_expiry:
                    print(f"✅ 续期成功，到期日期已更新为: {new_expiry}")
                    notify(
                        format_notification(
                            "✅ 续期成功",
                            extra="到期日期已更新",
                            expiry_date=new_expiry
                        )
                    )
                else:
                    print("⚠️ 续期结果未知，到期日期未变化，请手动检查")
                    notify(
                        format_notification(
                            "⚠️ 续期可能未成功",
                            extra="请登录后台检查",
                            expiry_date=current_expiry or "（未获取到）"
                        )
                    )

        else:
            if countdown_text:
                friendly = format_countdown(countdown_text)
                print(f"⏳ 未到续期时间，倒计时: {countdown_text} ({friendly})")
                notify(
                    format_notification(
                        "⏳ 未到续期时间",
                        extra=f"⏱️ 可续期时间: {friendly}后",
                        expiry_date=current_expiry or "（未获取到）"
                    )
                )
            else:
                print("ℹ️ 未找到续期按钮或倒计时，状态未知")
                notify(
                    format_notification(
                        "ℹ️ 无需续期",
                        extra="当前状态未知，请手动检查",
                        expiry_date=current_expiry or "（未获取到）"
                    )
                )

        # 续期过程中 cookie 可能被站点刷新；仍按 48h / 值变化判断，避免每天打 Secrets
        persist_session_token(sb)

        print("🏁 脚本执行完毕")


def main() -> None:
    """入口：捕获未处理异常并尽量发通知，避免 job 静默挂掉。"""
    try:
        run()
    except Exception as e:
        err = str(e).strip() or type(e).__name__
        print(f"❌ 未捕获异常: {err}")
        print(f"::error::Bot-hosting 续期脚本异常: {err}")
        try:
            notify(
                format_notification(
                    "❌ 脚本异常",
                    error=err[:500],
                    extra="Selenium/页面/网络等未预期错误，请查看 Actions 日志",
                )
            )
        except Exception as ne:
            print(f"异常通知也失败: {ne}")
        sys.exit(1)


if __name__ == "__main__":
    main()
