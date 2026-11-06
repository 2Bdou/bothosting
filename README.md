## 🚀 Bot-hosting 自动续期（GitHub Actions）

这是一个基于 GitHub Actions 的自动化脚本，用于定时登录自动续期 [Bot-hosting](https://bot-hosting.net) 服务。

⚠️ 有cf盾,太垃圾的机房节点可能过不了，建议用稍微干净点的节点,[B2proxy住宅代理](https://www.b2proxy.com/signup?code=0F5133)

━━━━━━━━━━━━━━━━━━━━━━

> 登录与续期逻辑：来自 [eooce/Auto-Renew-Bothosting](https://github.com/eooce/Auto-Renew-Bothosting)（邮箱 + 密码登录，密码不过期，稳定）
> 通知渠道：沿用 [2Bdou/bothosting](https://github.com/2Bdou/bothosting) 的 `notify.py`（Telegram + SMTP，可并存）
> 之前用 Discord Token 登录的方式仍然可用，Discord token 有时会变化，用账号密码更稳定。

━━━━━━━━━━━━━━━━━━━━━━

### 🔐 Secrets 配置说明

| Secret 名称         | 是否必填 | 说明                                              |
|---------------------|----------|---------------------------------------------------|
| EMAIL              | ✅ 必填  | 登录和通知使用的 Email，必须填写                          |
| PASSWORD           | ✅ 必填  | 登录密码，必须填写，在控制台右上角头像里去设置                 |
| NODE_LINK          | ❌ 可选  | 代理链接（如 vless:// vmess:// trojan:// hysteria2:// tuic:// anytls:// socks5:// )|
| TG_BOT_TOKEN       | ❌ 可选  | Telegram Bot Token（用于发送通知；或用 TELEGRAM_BOT_TOKEN）                      |
| TG_CHAT_ID         | ❌ 可选  | Telegram Chat ID（接收通知的用户或群组 ID；或用 TELEGRAM_CHAT_ID）               |
| SMTP_CONFIG        | ❌ 可选  | 邮件 JSON（与 TG 可并存；格式见 NOTIFY.md）              |

> 通知建议 **TG + SMTP 平行配置**，任一通道挂了另一条还能叫。邮件主题为 `Bot-hosting 续期通知`。

━━━━━━━━━━━━━━━━━━━━━━

## 部署步骤
1：fork 本项目，在 actions 菜单允许工作流

2：在 `setting` ➡ `secrets and variables` ➡ `Actions` 里添加上方必填的 secrets

3：去 actions 菜单手动试运行工作流，根据自己的服务到期日期自行在 [renew.yml](.github/workflows/renew.yml) 里调整 cron 运行时间

## 注意事项
* 必填变量必须要填写
* NODE_LINK 支持的代理协议有：vmess, vless, hysteria2, tuic, anytls, socks5 等
* 自动续期不代表可以无底线的薅羊毛，不建议多账号
* cron 运行时间不一定准确，得根据实际到期时间修改，可在设置里暂停 actions 功能再开启
* 脚本未捕获异常时也会尝试发通知；通知失败会在 Actions 日志打 `::warning::`
* 工作流默认**保留最近 10 次** run 记录，便于对照定时/手动日志

## ⚠️ 免责声明
* 本程序仅供学习了解，非盈利目的，如转载须注明来源。
* 使用本程序必循遵守部署服务器所在地、所在国家和用户所在国家的法律法规，程序作者不对使用者任何不当行为负责。
