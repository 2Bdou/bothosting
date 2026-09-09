## 🚀 Bot-hosting 自动续期（GitHub Actions）

这是一个基于 GitHub Actions 的自动化脚本，用于定时登录自动续期 [Bot-hosting](https://bot-hosting.net) 服务。

⚠️ 有cf盾,太垃圾的机房节点可能过不了，建议用稍微干净点的节点,[B2proxy住宅代理](https://www.b2proxy.com/signup?code=0F5133)

━━━━━━━━━━━━━━━━━━━━━━

### 🔐 Secrets 配置说明

| Secret 名称         | 是否必填 | 说明                                              |
|---------------------|----------|---------------------------------------------------|
| EMAIL              | ❌ 可选  | 通知里显示的登录账户；不填则回退 `SMTP_CONFIG.to`，不影响登录 |
| SESSION_TOKEN      | ❌ 可选  | Bot-hosting session_token，cookie里获取               |
| DISCORD_TOKEN      | ✅ 必填  | Discord Token，SESSION_TOKEN失效时自动OAuth登录        |
| GH_TOKEN           | ✅ 强烈建议 | GitHub classic PAT，**只勾 `repo`**。`SESSION_TOKEN` 剩余不足 48 小时、值变化或 Discord 换票时写回 |
| NODE_LINK          | ❌ 可选  | 代理链接（如 vless:// vmess:// trojan:// hysteria2:// tuic:// anytls:// socks5:// )|
| TG_BOT_TOKEN       | ❌ 可选  | Telegram Bot Token（用于发送通知）                      |
| TG_CHAT_ID         | ❌ 可选  | Telegram Chat ID（接收通知的用户或群组 ID）               |
| SMTP_CONFIG        | ❌ 可选  | 邮件 JSON（与 TG 可并存；格式见 NOTIFY.md）              |

> 通知建议 **TG + SMTP 平行配置**，任一通道挂了另一条还能叫。邮件主题为 `Bot-hosting 续期通知`。

━━━━━━━━━━━━━━━━━━━━━━

## 部署步骤
1：fork 本项目，在actions菜单允许工作流

2：在`setting`➡`secrets and variables`➡`Actions` 里添加上方必填的secrets

3：去actions菜单手动试运行工作流,根据自己的服务到期日期自行在[renew.yml](.github/workflows/renew.yml)里调整cron运行时间

### SESSION_TOKEN 获取
登录你的账号,按F12或页面空白处 右键➡检查➡选择应用程序或appcations 找到对应的字段点击获取对应的值，详情如图
<img width="1200" height="600" alt="image" src="https://github.com/user-attachments/assets/e532b0d6-9f12-45fd-8af9-69e1029a1a92" />

### DISCORD_TOKEN 获取（用于 SESSION_TOKEN 失效后备用登录
1. 浏览器登录 Discord（网页版）
2. 按 F12 打开开发者工具 ➡ 网络 ➡ 点击任意频道 ➡ 选择左侧的任意api 
3. 找到名为 `authorization字段` 的 值，即为discord token,详情如图所示
<img width="1200" height="600" alt="image" src="https://github.com/user-attachments/assets/7276d62d-31ff-452c-9e13-165af8323f53" />


> **作用**：当 `SESSION_TOKEN` 过期时，脚本会先清掉旧 cookie，再用 Discord Token 走 OAuth 重新登录，并**立刻写回**新的 `SESSION_TOKEN`。SESSION_TOKEN 登录成功时，只在 **剩余有效期不足 48 小时**（或 cookie 值变了）才写回 Secrets，机制对齐 [puratya-renew](https://github.com/2Bdou/puratya-renew)。可用环境变量 `SESSION_REFRESH_BEFORE_HOURS` 改阈值（默认 `48`）。这需要配置 `GH_TOKEN`。


### 获取 `GH_TOKEN`(GitHub Personal Access Token)
1：点击GitHub 账户右上角头像 → Settings（设置）。

2：左侧菜单底部点击 Developer settings（开发者设置）。

3：点击 Personal access tokens → Tokens (classic)。

4：点击 Generate new token → Generate new token (classic)。

填写信息：
- Note：起一个描述性名称（如 bothosting-secret-update）。
- Expiration：建议选 **No expiration**（PAT 过期后 cookie 无法自动写回）。
- Select scopes：**只勾 `repo`**，不要全选。
- 点击 Generate token，立即复制并妥善保存（离开页面后不能再查看）。

`GITHUB_TOKEN`（Actions 自带）不能改 Secrets，必须用上面这个 PAT，Secret 名称为 `GH_TOKEN`。

有效期仍充足时日志会写 `无需写回`；不足 48 小时、token 值变化或 Discord 换票后应出现 `SESSION_TOKEN 已写回 Secrets`。登录失败时 workflow 会标红。

## 注意事项
* 必填变量必须要填写
* NODE_LINK支持的代理协议有：vmess,vless,hysteria2,tuic,anytls,socks5等
* 自动续期不代表可以无底线的薅羊毛,不建议多账号
* cron运行时间不一定准确,得根据实际到期时间修改,可在设置里暂停actions功能再开启
* 脚本未捕获异常时也会尝试发「脚本异常」通知；通知失败会在 Actions 日志打 `::warning::`
* 登录失败会让 job 失败（不再绿勾空转）；邮件会写明是 Discord 401 还是 `error=disconnect`
* 工作流默认**保留最近 10 次** run 记录，便于对照定时/手动日志

## ⚠️ 免责声明
* 本程序仅供学习了解, 非盈利目的，如转载须注明来源。
* 使用本程序必循遵守部署服务器所在地、所在国家和用户所在国家的法律法规, 程序作者不对使用者任何不当行为负责。
