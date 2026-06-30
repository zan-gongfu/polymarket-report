---
name: polymarket-report
description: 查询 Polymarket 活跃持仓并发送飞书卡片报告，支持持仓变化自动通知。
---

# Polymarket Report Skill

查询 Polymarket 公开 API 获取活跃持仓，按指定格式发送飞书机器人卡片。**自带持仓变化检测**，持仓变动时自动推送飞书。

## 用法

| 命令 | 触发方式 | 行为 |
|------|---------|------|
| `/polymarket-report` 或 `poly-report` | 手动 | 强制查询并发送当前持仓到飞书 |
| `poly-report --check` | cron 调用 | 仅持仓变化时发送，无变化跳过 |

## 自动定时

由 cron 驱动，全部后台静默运行：

| cron | 频率 | 模式 | 行为 |
|------|------|------|------|
| `* * * * *` | 每分钟 | `--check` | 有变化立即推送飞书 |
| `0 * * * *` | 每整点 | 强制 | 无论变没变都发一次 |

## 运行流程

```
cron 每分钟
   ↓
run(force=False)
   ├─ get_positions()       ← API 查持仓，过滤 currentValue>0
   ├─ fingerprint()         ← 生成指纹 (condition_id|size|currentValue)
   ├─ load_old_fp()         ← 读 .position_state.json
   ├─ 旧指纹 == 新指纹 → 跳过（无变化）
   └─ 旧指纹 ≠ 新指纹 → 发送


cron 每整点
   ↓
run(force=True)
   ├─ 同上流程，但跳过指纹对比
   └─ 直接发送


/polymarket-report（手动）
   ↓
run(force=True)  ← 同上，强制发送
```

## 精简说明

| 改动 | 原因 |
|------|------|
| 去除 `--monitor` 模式 | 被 cron 替代，死代码 |
| 去除 `safe_float()` | try/except 永不到达，直接 `float(x or 0)` |
| 去除 `format_end_date()` 独立函数 | 仅输 `03:00` 固定值，内联为 `end_date()` |
| 去除 `os.makedirs` | 目录已在 skill 安装时存在 |
| 合并 `check_and_send()` + `build_card()` + `send_to_feishu()` | 6 个函数 → 4 个，职责更清晰 |
| 删除 `fingerprint()` 双重排序 | `sorted()` 已够，`sort_keys` 多余 |
| **行数：154 → 97，减少 37%** | |

## 发送效果

```
📍 地址： `0xD679...91A0`
📋 活跃持仓（1 个）

🟢 #1 Argentina vs. Algeria: O/U 8.5 Total Corners  🕐06/17 03:00
方向：Under　份额：5.0
买入价：47.0¢ (2.13x)
成本：$2.35　赢利：$+2.65
```

## 配置

编辑 `report.py` 顶部：

| 变量 | 说明 |
|------|------|
| `WALLET` | Polymarket 钱包地址 |
| `WEBHOOK_URL` | 飞书机器人 webhook 地址 |
