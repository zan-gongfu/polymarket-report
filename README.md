# Polymarket Report

自动查询 Polymarket 活跃持仓并发送飞书卡片通知，支持持仓变化自动检测。

## 功能

- 📊 查询 Polymarket 公开 API 获取活跃持仓
- 🔔 持仓变化时自动推送飞书卡片通知
- 📄 自动更新金山文档持仓跟踪表

## 使用方法

```bash
# 手动查询并发送
python3 report.py

# 仅持仓变化时发送（用于定时检测）
python3 report.py --check
```

## 配置

编辑 `report.py` 顶部：

| 变量 | 说明 |
|------|------|
| `WALLET` | Polymarket 钱包地址 |
| `WEBHOOK_URL` | 飞书机器人 webhook 地址 |

## cron 定时

每分钟检测持仓变化：

```
* * * * * cd /path/to/polymarket-report && python3 report.py --check >> logs/check.log 2>&1
```
