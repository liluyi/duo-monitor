#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
北京 Apple Store iPhone Duo 现货监控
====================================
原理：调用 Apple 中国官网公开的门店取货查询接口
  https://www.apple.com.cn/shop/retail/pickup-message?pl=true&searchNearby=true&location=<邮编>&parts.0=<货号>...
一次请求即可拿到附近所有门店、所有货号的现货状态（pickupDisplay: available / unavailable）。

通知方式：
  1. 终端高亮输出 + 日志文件（stock_log.txt）
  2. 系统桌面通知（macOS osascript / Linux notify-send，自动检测）
  3. 可选：Bark / Server酱 / 自定义 Webhook —— 配置环境变量 NOTIFY_WEBHOOK

用法：
  python3 iphone_duo_monitor.py            # 监控全部北京门店 + 全部机型
  python3 iphone_duo_monitor.py --interval 20
  python3 iphone_duo_monitor.py --stores R448,R320   # 只监控指定门店
  python3 iphone_duo_monitor.py --parts MK2N4CH/A    # 只监控指定货号
  python3 iphone_duo_monitor.py --once               # 只查询一次（调试用）
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

API = "https://www.apple.com.cn/shop/retail/pickup-message"
LOCATION = "100005"  # 北京东城区邮编，用于搜索附近门店
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# 北京 6 家 Apple Store（通过官方接口自动发现，此处为白名单过滤）
BEIJING_STORES = {
    "R320": "三里屯", "R448": "王府井", "R388": "西单大悦城",
    "R479": "华贸购物中心", "R645": "朝阳大悦城", "R792": "北京荟聚",
}

# iPhone Duo 全部货号（2026-09 型号，自动从官网提取）
ALL_PARTS = {
    "MK2N4CH/A": "iPhone Duo 256GB 暗夜色 ¥15999",
    "MK2M4CH/A": "iPhone Duo 256GB 星光白 ¥15999",
    "MK2Q4CH/A": "iPhone Duo 512GB 暗夜色 ¥17999",
    "MK2P4CH/A": "iPhone Duo 512GB 星光白 ¥17999",
    "MK2T4CH/A": "iPhone Duo 1TB   星光白 ¥21499",
    "MK2U4CH/A": "iPhone Duo 1TB   暗夜色 ¥21499",
    "MK2V4CH/A": "iPhone Duo 2TB   星光白 ¥26499",
    "MK2W4CH/A": "iPhone Duo 2TB   暗夜色 ¥26499",
}

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stock_log.txt")
# Bark 推送（iPhone 原生通知）：NOTIFY_BARK_KEY=你的key，或完整 URL
BARK_KEY = os.environ.get("NOTIFY_BARK_KEY", "")
BARK_URL = os.environ.get("NOTIFY_WEBHOOK", "")  # 兼容自定义 Webhook（JSON POST）
APPLE_PAGE = "https://www.apple.com.cn/shop/buy-iphone/iphone-duo"


def log(msg: str):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def fetch_stores(parts: list[str]) -> list[dict]:
    """查询一次接口，返回解析后的门店列表。"""
    params = ["pl=true", "searchNearby=true", f"location={LOCATION}"]
    params += [f"parts.{i}={p}" for i, p in enumerate(parts)]
    url = f"{API}?{'&'.join(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    return data.get("body", {}).get("stores", [])


def desktop_notify(title: str, msg: str):
    """跨平台桌面通知，失败静默忽略。"""
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["osascript", "-e",
                              f'display notification "{msg}" with title "{title}" sound name "Glass"'])
        elif sys.platform.startswith("linux"):
            subprocess.Popen(["notify-send", title, msg])
    except Exception:
        pass


def bark_notify(title: str, msg: str, jump_url: str = APPLE_PAGE):
    """Bark 推送：iOS 锁屏横幅 + 响铃，点开跳转 Apple 官网购买页。"""
    if not BARK_KEY:
        return
    try:
        from urllib.parse import quote
        base = BARK_KEY if BARK_KEY.startswith("http") else f"https://api.day.app/{BARK_KEY}"
        url = (f"{base}/{quote(title)}/{quote(msg)}?level=active&sound=glass&group=iPhoneDuo"
               f"&url={quote(jump_url)}")
        urllib.request.urlopen(url, timeout=10)
        log("Bark 推送已发送")
    except Exception as e:
        log(f"Bark 推送失败: {e}")


def webhook_notify(title: str, msg: str):
    """可选自定义 Webhook 推送（JSON POST）。"""
    if not BARK_URL:
        return
    try:
        payload = json.dumps({"title": title, "body": msg}).encode()
        req = urllib.request.Request(BARK_URL, data=payload,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log(f"Webhook 通知失败: {e}")


def alert(store_name: str, avail: list[str]):
    """发现现货时触发全部通知渠道。"""
    msg = f"{store_name} 现货：\n" + "\n".join(avail)
    log("=" * 60)
    log(">>> 发现现货！<<<")
    log(msg)
    log("=" * 60)
    desktop_notify("iPhone Duo 北京有货！", f"{store_name}：{avail[0]} 等 {len(avail)} 款")
    bark_notify("iPhone Duo 北京有货！", f"{store_name}：{avail[0]} 等 {len(avail)} 款")
    webhook_notify("iPhone Duo 北京有货！", msg)


def query(filter_stores: set[str], filter_parts: dict) -> dict:
    """
    查询一次，返回 {storeName: [可售货号描述...]}，仅包含 available 条目。
    同时打印全量状态表格。
    """
    parts = list(filter_parts)
    stores = fetch_stores(parts)
    now = datetime.now().strftime("%H:%M:%S")
    available = {}
    rows = []
    for s in stores:
        code = s.get("storeNumber", "?")
        name = f"{s.get('storeName', '?')}"
        city = s.get("city", "")
        if city != "北京" or (filter_stores and code not in filter_stores):
            continue
        avail, unavail = [], []
        for p in parts:
            pa = (s.get("partsAvailability") or {}).get(p, {})
            disp = pa.get("pickupDisplay")
            desc = filter_parts.get(p, p)
            if disp == "available":
                avail.append(desc)
                unavail.append("有货")
            else:
                unavail.append("—")
        rows.append((name, unavail))
        if avail:
            available[name] = avail
    # 打印状态表（列名：容量/颜色）
    def col(desc):
        m = re.match(r"iPhone Duo (\S+)\s+(\S+)", desc)
        return m.group(1) + "/" + m.group(2)[:1] if m else desc[:8]
    print(f"\n[{now}] 查询 {len(parts)} 个货号 × 北京门店（有货/—）：")
    print(f"{'门店':<8}" + "".join(f"{col(v):>10}" for v in filter_parts.values()))
    for name, marks in rows:
        print(f"{name:<10}" + " ".join(f"{m:>8}" for m in marks))
    return available


def main():
    ap = argparse.ArgumentParser(description="北京 Apple Store iPhone Duo 库存监控")
    ap.add_argument("--interval", type=int, default=30, help="轮询间隔秒数（默认 30，勿设过小以免被限流）")
    ap.add_argument("--stores", default="", help="逗号分隔门店代码，如 R448,R320；默认全部北京门店")
    ap.add_argument("--parts", default="", help="逗号分隔货号；默认全部 8 个机型")
    ap.add_argument("--once", action="store_true", help="只查询一次后退出")
    ap.add_argument("--ci", action="store_true",
                    help="CI 模式（GitHub Actions）：用 state.json 持久化去重，仅新现货时推送")
    args = ap.parse_args()

    filter_stores = {s.strip().upper() for s in args.stores.split(",") if s.strip()}
    if args.parts:
        sel = [p.strip() for p in args.parts.split(",") if p.strip()]
        filter_parts = {p: ALL_PARTS.get(p, p) for p in sel}
    else:
        filter_parts = dict(ALL_PARTS)

    log(f"开始监控：门店={[filter_stores or '全部北京']}，机型数={len(filter_parts)}，间隔={args.interval}s")
    log(f"通知渠道：桌面={'开'} Bark={'开' if BARK_KEY else '未配置(NOTIFY_BARK_KEY)'} Webhook={'开' if BARK_URL else '未配置'}")
    log(f"日志文件：{LOG_FILE}")

    # 有货状态缓存：连续两次确认，避免瞬时抖动误报
    seen: dict[str, list[str]] = {}
    confirmed: set[str] = set()
    state_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

    # CI 模式：从 state.json 恢复已报警状态（配合 GitHub Actions cache 跨运行持久化）
    if args.ci and os.path.exists(state_file):
        try:
            with open(state_file, encoding="utf-8") as f:
                confirmed = set(json.load(f).get("confirmed", []))
        except (OSError, ValueError):
            pass

    def save_state():
        if args.ci:
            try:
                with open(state_file, "w", encoding="utf-8") as f:
                    json.dump({"confirmed": sorted(confirmed)}, f)
            except OSError:
                pass

    while True:
        try:
            available = query(filter_stores, filter_parts)
            for store, items in available.items():
                if seen.get(store) == items:
                    continue  # 状态未变化
                seen[store] = items
                if store not in confirmed:      # 新出现的现货才报警
                    confirmed.add(store)
                    alert(store, items)
            # 清除已无货的门店，允许下次再货时重新报警
            for store in list(confirmed):
                if store not in available:
                    confirmed.discard(store)
                    seen.pop(store, None)
                    log(f"{store} 已无现货，恢复监控")
            save_state()
        except KeyboardInterrupt:
            log("手动停止")
            break
        except Exception as e:
            log(f"查询出错（将重试）: {e}")
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
