import os, json, requests, subprocess
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# ====== 配置 ======
WALLET = "0xD67942cD1c1AF4287F80Fe5F11A01DB65Cf491A0"
WEBHOOK_URL = "https://open.larksuite.com/open-apis/bot/v2/hook/54884721-c854-43eb-9353-d87240dee4e7"
STATE_FILE = os.path.join(os.path.dirname(__file__), ".position_state.json")
# =================

API = f"https://data-api.polymarket.com/positions?user={WALLET}&closed=false&limit=250"
CST = timezone(timedelta(hours=8))
KDOCS_CLI = "/Users/po-ov/.local/bin/kdocs-cli"
KDOCS_FILE_NAME = "Polymarket持仓跟踪.otl"
SHORT_WALLET = f"{WALLET[:6]}...{WALLET[-4:]}"


def get_active():
    """获取活跃持仓（currentValue > 0）"""
    raw = requests.get(API, timeout=10).json()
    return [p for p in raw if float(p.get("currentValue") or 0) > 0]


def get_settled(asset_ids):
    """查询已结算比赛结果 → dict[aid]={"title","outcome","result","profit"}"""
    if not asset_ids:
        return {}
    raw = requests.get(
        f"https://data-api.polymarket.com/positions?user={WALLET}&closed=true&limit=500",
        timeout=15
    ).json()
    results = {}
    for p in raw:
        aid = p.get("asset")
        if aid in asset_ids:
            val = float(p.get("currentValue") or 0)
            cost = float(p.get("initialValue") or 0)
            results[aid] = {
                "title": (p.get("title") or "未知").strip(),
                "outcome": p.get("outcome") or "",
                "result": "✅ 赢" if val > 0 else "❌ 输",
                "profit": val - cost,
            }
    for aid in asset_ids:
        if aid not in results:
            results[aid] = {"title": "未知", "outcome": "", "result": "❓ 未知", "profit": 0}
    return results


def fetch_event_times(positions):
    """并行查询开赛时间 → dict[eventId]="MM/DD HH:MM" 北京时间"""
    eids = {p["eventId"] for p in positions if p.get("eventId")}
    if not eids:
        return {}
    times, futs = {}, {}
    with ThreadPoolExecutor(max_workers=min(len(eids), 8)) as ex:
        for eid in eids:
            futs[ex.submit(requests.get, f"https://gamma-api.polymarket.com/events/{eid}", timeout=10)] = eid
        for f in as_completed(futs):
            try:
                st = f.result().json().get("startTime")
                if st:
                    utc = datetime.fromisoformat(st.replace("Z", "+00:00"))
                    times[futs[f]] = utc.astimezone(CST).strftime("%m/%d %H:%M")
            except Exception:
                pass
    return times


def parse_positions(raw, event_times):
    """一次遍历 raw，同时产出展示字段 / 指纹 / 份额字典（替代独立的 snapshot）"""
    items, sizes, fp_parts = [], {}, []
    for p in raw:
        sz = float(p.get("size") or 0)
        avg = float(p.get("avgPrice") or 0)
        aid = p["asset"]
        items.append({
            "aid": aid,
            "title": (p.get("title") or "未知").strip(),
            "outcome": p.get("outcome") or "",
            "size": sz,
            "price": f"{avg*100:.1f}¢ ({1/avg:.2f}x)" if avg else "N/A",
            "cost": float(p.get("initialValue") or 0),
            "profit": sz * (1 - avg),
            "end": event_times.get(p.get("eventId"), "待定"),
        })
        sizes[aid] = sz
        fp_parts.append(f"{aid}|{sz}")
    items.sort(key=lambda x: x["end"] if x["end"] != "待定" else "99/99 99:99")
    return items, json.dumps(sorted(fp_parts)), sizes


def card(items, old_sizes, settled=None):
    """飞书卡片消息体"""
    lines = [f"📍 地址： `{SHORT_WALLET}`", f"📋 活跃持仓（{len(items)} 个）"]
    for i, d in enumerate(items):
        old_sz = old_sizes.get(d["aid"])
        changed = old_sz is None or d["size"] != old_sz
        icon = "🔴" if changed else "🟢"
        tag = " 🆕" if changed else ""
        seg = f"{d['size']:.1f}" if old_sz is None else f"{d['size']:.1f}({old_sz:.1f})" if changed else f"{d['size']:.1f}"
        lines += ["",
                  f"{icon} #{i+1}{tag} {d['title']}  🕐{d['end']}",
                  f"方向：{d['outcome']}　份额：{seg}",
                  f"买入价：{d['price']}",
                  f"成本：${d['cost']:.2f}　赢利：${d['profit']:+.2f}"]
    if settled:
        lines += ["", f"📊 已结算（{len(settled)} 场）"]
        for s in settled:
            lines += [f"  {s['result']} {s['title']} → {s['outcome']}"]
    return {"msg_type": "interactive", "card": {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": f"💰 Polymarket 持仓                    {datetime.now().strftime('%H:%M')}"}, "template": "green"},
        "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}]
    }}


def send(payload):
    """发送飞书消息"""
    resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
    ok = resp.status_code == 200 and resp.json().get("StatusCode") == 0
    print("✅ 发送成功" if ok else f"❌ 发送失败: {resp.status_code}")
    return ok


def kdocs_md(items):
    """生成金山文档 Markdown（单次遍历 items 同时产出表格 + 详情）"""
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M")
    if not items:
        return f"更新于: {now} (北京时间)\n\n当前无活跃持仓。\n"

    table, details = ["| # | 赛事 | 方向 | 份额 | 买入价 | 成本 | 盈亏 | 开赛 |",
                      "|---|------|------|------|--------|------|------|------|"], []
    for i, d in enumerate(items):
        table.append(f"| {i+1} | {d['title']} | {d['outcome']} | {d['size']:.1f} | {d['price']} | ${d['cost']:.2f} | ${d['profit']:+.2f} | {d['end']} |")
        details += [f"### #{i+1} {d['title']}",
                    f"- **方向**：{d['outcome']}",
                    f"- **份额**：{d['size']:.1f}",
                    f"- **买入价**：{d['price']}",
                    f"- **成本**：${d['cost']:.2f}",
                    f"- **盈亏**：${d['profit']:+.2f}",
                    f"- **开赛时间**：{d['end']}",
                    ""]
    return "\n".join([f"更新于: {now} (北京时间)\n",
                      "## 持仓概览\n",
                      *table,
                      "\n## 持仓详情\n",
                      *details])


def _kdocs_cli(*args):
    return json.loads(subprocess.run([KDOCS_CLI, *args], capture_output=True, text=True, timeout=30).stdout)


def _kdocs_search():
    """搜索已有文档，返回 (id, link_url) 或 None"""
    try:
        resp = _kdocs_cli("drive", "search-files",
                           json.dumps({"query": KDOCS_FILE_NAME, "type": "file_name", "limit": 5}))
        for item in resp.get("data", {}).get("data", {}).get("items", []):
            f = item["file"]
            if f["name"] == KDOCS_FILE_NAME:
                return f["id"], f["link_url"]
    except Exception:
        pass
    return None


def update_kdocs(items, state):
    """写入/更新金山文档（优先用 state 缓存 file_id）"""
    body = kdocs_md(items)
    fid, url = state.get("kdocs_file_id"), state.get("kdocs_link_url")

    # 缓存未命中 → 搜索或新建
    if not fid or not url:
        found = _kdocs_search()
        if found:
            fid, url = found
        else:
            resp = _kdocs_cli("drive", "create-file",
                               json.dumps({"name": KDOCS_FILE_NAME, "on_name_conflict": "overwrite"}))
            if resp.get("code") != 0:
                print(f"❌ 金山文档创建失败: {resp.get('message', '未知错误')}")
                return state
            d = resp["data"]["data"]
            fid, url = d["id"], d.get("link_url", "")
            print(f"📄 金山文档已创建: {url}")

    if (_kdocs_cli("otl", "insert-content",
                    json.dumps({"file_id": fid, "content": f"# Polymarket 持仓跟踪\n\n{body}",
                                "format": "markdown", "mode": "replace"})).get("code") == 0):
        print("✅ 金山文档更新成功")
        state["kdocs_file_id"] = fid
        state["kdocs_link_url"] = url
    else:
        print("❌ 金山文档更新失败")
    return state


def run(force=False):
    """查持仓 → 判变化 → 发飞书 → 更文档"""
    raw = get_active()
    try:
        with open(STATE_FILE) as f:
            old = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        old = None

    event_times = fetch_event_times(raw) if raw else {}
    items, fp, sizes = parse_positions(raw, event_times)
    old_sizes = old.get("sizes") if old else {}

    if not force and old and old.get("fingerprint") == fp:
        print("📊 无变化，跳过")
        return

    # 检测减少的持仓 → 查结算结果
    settled = []
    if old_sizes:
        removed = set(old_sizes.keys()) - {d["aid"] for d in items}
        if removed:
            raw_settled = get_settled(removed)
            settled = [raw_settled[aid] for aid in sorted(raw_settled)]
            print(f"📉 {len(settled)} 场已结算")

    reason = "首次运行" if old is None else "持仓变化" if old.get("fingerprint") != fp else "手动触发"
    print(f"📊 {len(items)} 个活跃 | {reason}")
    if event_times:
        print(f"⏰ 已获取 {len(event_times)} 个赛事开赛时间")

    state = {"fingerprint": fp, "sizes": sizes, "updated_at": datetime.now().isoformat()}
    if old:
        state = {**old, **state}

    send(card(items, old_sizes, settled))
    state = update_kdocs(items, state)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


if __name__ == "__main__":
    import sys
    run(force="--check" not in sys.argv)
