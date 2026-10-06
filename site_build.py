#!/usr/bin/env python3
"""GitHub Pages 版の相場ボードを作る（GitHub Actions から毎朝実行）

    python3 site_build.py             # 取得・判定して state/ と _site/ を更新
    python3 site_build.py --no-fetch  # 取得せず、state/ の最新データで _site/ だけ作り直す（画面の修正を反映するとき）

state/ はリポジトリにコミットして次回に引き継ぐ（最新の全データ・推移・変化の記録）。
_site/ は公開するページ一式（コミットしない）。
"""
import argparse
import datetime as dt
import json
import os
import shutil
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state")
SITE = os.path.join(HERE, "_site")
JST = dt.timezone(dt.timedelta(hours=9))
REPO = os.environ.get("GITHUB_REPOSITORY", "courtokuyama/tbcc-market-checker")
THRESHOLD = 0.10
MAX_EVENTS = 500
MAX_HISTORY = 400

sys.path.insert(0, HERE)
os.environ.setdefault("TBCC_DATA_DIR", os.path.join(HERE, "data"))
import tbcc_market as core  # noqa: E402
from app import diff_events  # noqa: E402


def load(name, default):
    p = os.path.join(STATE, name)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return default


def save(name, obj, base=STATE):
    p = os.path.join(base, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def now():
    return dt.datetime.now(JST).isoformat(timespec="seconds")


def fetch_and_update():
    started = now()
    rules = json.load(open(os.path.join(HERE, "models.json"), encoding="utf-8"))["rules"]
    cars = core.run(threshold=THRESHOLD, rules=rules)
    finished = now()

    prev = load("cars.json", {})
    cur = {c["slug"]: c for c in cars}
    events = load("events.json", [])
    next_id = (events[0]["id"] + 1) if events else 1
    new = []
    if prev:
        for slug, kind, title, detail in diff_events(prev, cur):
            new.append({"id": next_id, "at": finished, "slug": slug, "kind": kind, "title": title, "detail": detail})
            next_id += 1
    events = (list(reversed(new)) + events)[:MAX_EVENTS]

    history = load("history.json", {})
    first_seen = load("first_seen.json", {})
    for c in cars:
        m = c["market"]
        history.setdefault(c["slug"], []).append({"at": started, "total": c.get("total"), "est": m.get("est"), "diff": m.get("diff")})
        history[c["slug"]] = history[c["slug"]][-MAX_HISTORY:]
        first_seen.setdefault(c["slug"], started)
    # 掲載終了した車の詳細も残す（変化タブから開けるように）
    gone = {s: {**p, "on_sale": False} for s, p in prev.items() if s not in cur}
    meta = load("meta.json", {"runs": 0})
    meta.update(runs=meta.get("runs", 0) + 1, run={"started": started, "finished": finished, "status": "done"}, last_error=None)

    save("cars.json", cur)
    save("gone.json", {**load("gone.json", {}), **gone})
    save("events.json", events)
    save("history.json", history)
    save("first_seen.json", first_seen)
    save("meta.json", meta)
    print(f"更新: {len(cars)}台 / 変化 {len(new)}件", file=sys.stderr)


def record_error(msg):
    meta = load("meta.json", {"runs": 0})
    meta["last_error"] = {"started": now(), "error": msg}
    save("meta.json", meta)


def build_site():
    cars = load("cars.json", {})
    meta = load("meta.json", {})
    if not cars or not meta.get("run"):
        raise SystemExit("state/ にデータがありません。先に取得を実行してください")
    events = load("events.json", [])
    history = load("history.json", {})
    first_seen = load("first_seen.json", {})
    gone = load("gone.json", {})

    if os.path.exists(SITE):
        shutil.rmtree(SITE)
    shutil.copytree(os.path.join(HERE, "static"), SITE)
    d = os.path.join(SITE, "data")

    light = []
    for slug, c in cars.items():
        x = json.loads(json.dumps(c))
        x["first_seen"] = first_seen.get(slug)
        x["market"] = {k: v for k, v in x["market"].items() if k not in ("dist", "comps")}
        x["images"] = (x.get("images") or [])[:1]
        light.append(x)
    order = {"お手頃": 0, "相場並み": 1, "割高": 2, "比較不可": 3}
    light.sort(key=lambda c: (order.get(c["market"]["verdict"], 3), c["market"].get("diff", 9)))
    board = {"run": meta["run"], "cars": light, "events": events[:30], "runs": meta.get("runs", 1),
             "threshold": THRESHOLD, "last_error": meta.get("last_error")}
    save("board.json", board, d)
    for slug, c in {**gone, **cars}.items():
        full = {**c, "history": history.get(slug, []), "events": [e for e in events if e["slug"] == slug],
                "on_sale": slug in cars}
        save(f"cars/{slug}.json", full, d)
    models = json.load(open(os.path.join(HERE, "models.json"), encoding="utf-8"))
    save("rules.json", models["rules"], d)
    save("rules_meta.json", {"_説明": models.get("_説明", "")}, d)

    # ページを静的サイト版に切り替え、検索エンジンに載せない
    build = dt.datetime.now(JST).strftime("%Y%m%d%H%M")
    p = os.path.join(SITE, "index.html")
    html = open(p, encoding="utf-8").read()
    html = html.replace('<meta name="viewport"', '<meta name="robots" content="noindex,nofollow">\n<meta name="viewport"', 1)
    html = html.replace('href="/app.css"', f'href="app.css?v={build}"')
    html = html.replace('<script src="/app.js"></script>',
                        f'<script>window.TBCC_STATIC={json.dumps({"repo": REPO, "threshold": THRESHOLD, "build": build})};</script>\n'
                        f'<script src="app.js?v={build}"></script>')
    open(p, "w", encoding="utf-8").write(html)
    open(os.path.join(SITE, "robots.txt"), "w").write("User-agent: *\nDisallow: /\n")
    open(os.path.join(SITE, ".nojekyll"), "w").close()
    print(f"サイト: {SITE}（{len(light)}台）", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true")
    a = ap.parse_args()
    if not a.no_fetch:
        try:
            fetch_and_update()
        except Exception as e:  # noqa: BLE001  失敗しても前回のデータでページは出す
            traceback.print_exc()
            record_error(str(e))
            build_site()
            sys.exit(1)
    build_site()


if __name__ == "__main__":
    main()
