#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""北京 Apple Store iPhone Duo 现货监控（含 GitHub Actions 接力模式）"""

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
LOCATION = "100005"  # 北京东城区邮编
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")

BEIJING_STORES = {
    "R320": "三里屯", "R448": "王府井", "R388": "西单大悦城",
    "R479": "华贸购物中心", "R645": "朝阳大悦城", "R792": "北京荟聚",
}

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
BARK_KEY = os.environ.get("NOTIFY_BARK_KEY", "")
BARK_URL = os.environ.get("NOTIFY_WEBHOOK", "")
APPLE_PAGE = "https://www.apple.com.cn/shop/buy-iphone/iphone-duo"


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def fetch_stores(parts):
    params = ["pl=true", "searchNearby=true", f"location={LOCATION}"]
    params += [f"parts.{i}={p}" for i, p in enumerate(parts)]
    url = f"{API}?{'&'.join(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r).get("body", {}).get("stores", [])


def desktop_notify(title, msg):
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["osascript", "-e",
                              f'display notification "{msg}" with title "{title}" sound name "Glass"'])
        elif sys.platform.startswith("linux"):
            subprocess.Popen(["notify-send", title, msg])
    except Exception:
        pass


def bark_notify(title, msg, jump_url=APPLE_PAGE):
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


def alert(store_name, avail):
    msg = f"{store_name} 现货：\n" + "\n".join(avail)
    log("=" * 60)
    log(">>> 发现现货！<<<")
    log(msg)
    log("=" * 60)
    desktop_notify("iPhone Duo 北京有货！", f"{store_name}：{avail[0]} 等 {len(avail)} 款")
    bark_notify("iPhone Duo 北京有货！", f"{store_name}：{avail[0]} 等 {len(avail)} 款")


def query(filter_stores, filter_parts):
    parts = list(filter_parts)
    stores = fetch_stores(parts)
    now = datetime.now().strftime("%H:%M:%S")
    available = {}
    rows = []
    for s in stores:
        code = s.get("storeNumber", "?")
        name = s.get("storeName", "?")
        if s.get("city", "") != "北京" or (filter_stores and code not in filter_stores):
            continue
        avail, marks = [], []
        for p in parts:
            pa = (s.get("partsAvailability") or {}).get(p, {})
            desc = filter_parts.get(p, p)
            if pa.get("pickupDisplay") == "available":
                avail.append(desc)
                marks.append("有货")
            else:
                marks.append("—")
        rows.append((name, marks))
        if avail:
            available[name] = avail
    def col(desc):
        m = re.match(r"iPhone Duo (\S+)\s+(\S+)", desc)
        return m.group(1) + "/" + m.group(2)[:1] if m else desc[:8]
    print(f"\n[{now}] 查询 {len(parts)} 个货号 × 北京门店（有货/—）：")
    print(f"{'门店':<8}" + "".join(f"{col(v):>10}" for v in filter_parts.values()))
    for name, marks in rows:
        print(f"{name:<8}" + "".join(f"{m:>10}" for m in marks))
    return available


def main():
    ap = argparse.ArgumentParser(description="北京 Apple Store iPhone Duo 库存监控")
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--stores", default="")
    ap.add_argument("--parts", default="")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--ci", action="store_true")
    ap.add_argument("--max-runtime", type=int, default=0)
    args = ap.parse_args()

    filter_stores = {s.strip().upper() for s in args.stores.split(",") if s.strip()}
    if args.parts:
        sel = [p.strip() for p in args.parts.split(",") if p.strip()]
        filter_parts = {p: ALL_PARTS.get(p, p) for p in sel}
    else:
        filter_parts = dict(ALL_PARTS)

    log(f"开始监控：机型数={len(filter_parts)}，间隔={args.interval}s")
    log(f"Bark={'开' if BARK_KEY else '未配置'}")
    start_ts = time.time()

    seen = {}
    confirmed = set()
    state_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
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
                    continue
                seen[store] = items
                if store not in confirmed:
                    confirmed.add(store)
                    alert(store, items)
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
        if args.max_runtime and time.time() - start_ts >= args.max_runtime:
            log(f"达到最长运行时间 {args.max_runtime}s，本次接力结束")
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()

