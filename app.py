#!/usr/bin/env python3
"""TBCC 相場ボード（Webアプリ）

    python3 app.py            # → http://127.0.0.1:8765 をブラウザで開く
    python3 app.py --port 9000 --host 0.0.0.0   # 社内LANから見せる場合

追加インストール不要（Python 3.9+ 標準ライブラリ＋SQLite）。
データは data/ （SQLite: data/tbcc.db、取得キャッシュ: data/cache/）に保存される。
"""
import argparse
import csv
import datetime as dt
import io
import json
import mimetypes
import os
import re
import sqlite3
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("TBCC_DATA_DIR", os.path.join(HERE, "data"))
DB_PATH = os.path.join(DATA_DIR, "tbcc.db")
STATIC = os.path.join(HERE, "static")
RULES_PATH = os.path.join(HERE, "models.json")
os.makedirs(DATA_DIR, exist_ok=True)

import tbcc_market as core  # noqa: E402

core.CACHE_DIR = os.path.join(DATA_DIR, "cache")

DEFAULT_SETTINGS = {"threshold": 0.10, "auto_refresh": True, "auto_refresh_hour": 9}
VERDICTS = ["お手頃", "相場並み", "割高", "比較不可"]


# ---------------------------------------------------------------- DB
def db():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS runs(
            id INTEGER PRIMARY KEY, started TEXT, finished TEXT, status TEXT, n_cars INTEGER, error TEXT);
        CREATE TABLE IF NOT EXISTS snapshots(
            run_id INTEGER, slug TEXT, data TEXT, PRIMARY KEY(run_id, slug));
        CREATE TABLE IF NOT EXISTS events(
            id INTEGER PRIMARY KEY, run_id INTEGER, at TEXT, slug TEXT, kind TEXT, title TEXT, detail TEXT);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        """)


def get_settings():
    with db() as con:
        rows = {r["key"]: json.loads(r["value"]) for r in con.execute("SELECT * FROM settings")}
    return {**DEFAULT_SETTINGS, **rows}


def put_settings(new):
    cur = get_settings()
    clean = {}
    if "threshold" in new:
        clean["threshold"] = max(0.01, min(0.5, float(new["threshold"])))
    if "auto_refresh" in new:
        clean["auto_refresh"] = bool(new["auto_refresh"])
    if "auto_refresh_hour" in new:
        clean["auto_refresh_hour"] = int(new["auto_refresh_hour"]) % 24
    with db() as con:
        for k, v in clean.items():
            con.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, json.dumps(v)))
    return {**cur, **clean}


def latest_run(con, status="done"):
    return con.execute("SELECT * FROM runs WHERE status=? ORDER BY id DESC LIMIT 1", (status,)).fetchone()


def verdict_for(diff, th):
    if diff is None:
        return "比較不可"
    return "お手頃" if diff <= -th else "割高" if diff >= th else "相場並み"


def apply_threshold(car, th):
    m = car["market"]
    m["verdict"] = verdict_for(m.get("diff"), th) if m.get("est") else "比較不可"
    return car


# ---------------------------------------------------------------- refresh job
JOB = {"running": False, "done": 0, "total": 0, "message": "", "started": None, "run_id": None, "error": None}
JOB_LOCK = threading.Lock()


def man(v):
    return f"{v/10000:,.1f}万円"


def diff_events(prev, cur):
    """前回の結果との差分（新着・売却/掲載終了・値下げ/値上げ・判定変化）"""
    ev = []
    for slug, c in cur.items():
        name = f"{c.get('maker', '')} {c['name']}".strip()
        p = prev.get(slug)
        if p is None:
            ev.append((slug, "new", f"新着：{name}", f"支払総額 {man(c['total'])}" if c.get("total") else ""))
            continue
        if c.get("total") and p.get("total") and c["total"] != p["total"]:
            d = c["total"] - p["total"]
            ev.append((slug, "price_down" if d < 0 else "price_up", f"{'値下げ' if d < 0 else '値上げ'}：{name}",
                       f"{man(p['total'])} → {man(c['total'])}（{'+' if d > 0 else ''}{d/10000:,.1f}万円）"))
        pv, cv = p["market"].get("verdict"), c["market"].get("verdict")
        if pv != cv:
            ev.append((slug, "verdict", f"判定変化：{name}", f"{pv} → {cv}"))
    for slug, p in prev.items():
        if slug not in cur:
            ev.append((slug, "gone", f"掲載終了：{p.get('maker', '')} {p['name']}".strip(), "SOLD または非公開になった可能性"))
    return ev


def do_refresh(force=False):
    with JOB_LOCK:
        if JOB["running"]:
            return False
        JOB.update(running=True, done=0, total=0, message="開始", started=time.time(), error=None)
    threading.Thread(target=_refresh_worker, args=(force,), daemon=True).start()
    return True


def _refresh_worker(force):
    now = dt.datetime.now().isoformat(timespec="seconds")
    with db() as con:
        run_id = con.execute("INSERT INTO runs(started,status) VALUES(?,?)", (now, "running")).lastrowid
    JOB["run_id"] = run_id

    def progress(d, t, msg):
        JOB.update(done=d, total=t, message=msg)

    try:
        s = get_settings()
        rules = json.load(open(RULES_PATH, encoding="utf-8"))["rules"]
        cars = core.run(refresh=force, progress=progress, threshold=s["threshold"], rules=rules)
        with db() as con:
            prev_run = latest_run(con)
            prev = {}
            if prev_run:
                prev = {r["slug"]: json.loads(r["data"]) for r in
                        con.execute("SELECT * FROM snapshots WHERE run_id=?", (prev_run["id"],))}
            cur = {c["slug"]: c for c in cars}
            for c in cars:
                con.execute("INSERT INTO snapshots VALUES(?,?,?)", (run_id, c["slug"], json.dumps(c, ensure_ascii=False)))
            fin = dt.datetime.now().isoformat(timespec="seconds")
            for slug, kind, title, detail in diff_events(prev, cur) if prev_run else []:
                con.execute("INSERT INTO events(run_id,at,slug,kind,title,detail) VALUES(?,?,?,?,?,?)",
                            (run_id, fin, slug, kind, title, detail))
            con.execute("UPDATE runs SET finished=?, status='done', n_cars=? WHERE id=?", (fin, len(cars), run_id))
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        JOB["error"] = str(e)
        with db() as con:
            con.execute("UPDATE runs SET finished=?, status='error', error=? WHERE id=?",
                        (dt.datetime.now().isoformat(timespec="seconds"), str(e), run_id))
    finally:
        JOB["running"] = False


def scheduler():
    """アプリ起動中、毎日設定した時刻に自動更新する。"""
    while True:
        time.sleep(60)
        try:
            s = get_settings()
            if not s["auto_refresh"]:
                continue
            now = dt.datetime.now()
            if now.hour != s["auto_refresh_hour"]:
                continue
            with db() as con:
                last = latest_run(con)
            if last and last["started"][:10] == now.date().isoformat():
                continue
            do_refresh()
        except Exception:  # noqa: BLE001
            traceback.print_exc()


# ---------------------------------------------------------------- API
def api_board():
    th = get_settings()["threshold"]
    with db() as con:
        run = latest_run(con)
        if not run:
            return {"run": None, "cars": [], "events": [], "runs": 0}
        cars = [apply_threshold(json.loads(r["data"]), th) for r in
                con.execute("SELECT data FROM snapshots WHERE run_id=?", (run["id"],))]
        first_seen = {r["slug"]: r["first"] for r in con.execute(
            "SELECT slug, MIN(r.started) AS first FROM snapshots s JOIN runs r ON r.id=s.run_id GROUP BY slug")}
        events = [dict(r) for r in con.execute("SELECT * FROM events ORDER BY id DESC LIMIT 30")]
        nruns = con.execute("SELECT COUNT(*) FROM runs WHERE status='done'").fetchone()[0]
    for c in cars:
        c["first_seen"] = first_seen.get(c["slug"])
        # 一覧では重い配列を削る（詳細APIで返す）
        c["market"] = {k: v for k, v in c["market"].items() if k not in ("dist", "comps")}
        c["images"] = (c.get("images") or [])[:1]
    cars.sort(key=lambda c: (VERDICTS.index(c["market"]["verdict"]), c["market"].get("diff", 9)))
    return {"run": dict(run), "cars": cars, "events": events, "runs": nruns, "threshold": th}


def api_car(slug):
    th = get_settings()["threshold"]
    with db() as con:
        run = latest_run(con)
        row = con.execute("SELECT s.data FROM snapshots s WHERE slug=? ORDER BY run_id DESC LIMIT 1", (slug,)).fetchone()
        if not row:
            return None
        hist = []
        for r in con.execute("SELECT r.started, s.data FROM snapshots s JOIN runs r ON r.id=s.run_id "
                             "WHERE slug=? AND r.status='done' ORDER BY r.id", (slug,)):
            d = json.loads(r["data"])
            hist.append({"at": r["started"], "total": d.get("total"), "est": d["market"].get("est"),
                         "diff": d["market"].get("diff")})
        events = [dict(r) for r in con.execute("SELECT * FROM events WHERE slug=? ORDER BY id DESC", (slug,))]
    car = apply_threshold(json.loads(row["data"]), th)
    car["history"] = hist
    car["events"] = events
    car["on_sale"] = bool(run and con_has(run["id"], slug))
    return car


def con_has(run_id, slug):
    with db() as con:
        return con.execute("SELECT 1 FROM snapshots WHERE run_id=? AND slug=?", (run_id, slug)).fetchone() is not None


def api_csv():
    b = api_board()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["判定", "メーカー", "車名", "年式", "走行距離km", "車検", "記録簿", "シフト", "TBCC支払総額", "相場推定",
                "差額", "差率", "比較台数", "信頼度", "TBCC URL", "カーセンサー検索URL"])
    for c in b["cars"]:
        m = c["market"]
        w.writerow([m["verdict"], c.get("maker"), c["name"], c.get("year"), c.get("km"), c.get("shaken"),
                    c.get("kirokubo"), c.get("shift"), c.get("total"), round(m["est"]) if m.get("est") else "",
                    round(c["total"] - m["est"]) if m.get("est") and c.get("total") else "",
                    f'{m["diff"]:+.1%}' if m.get("diff") is not None else "", m.get("n"), m.get("confidence"),
                    c["url"], m.get("search_url")])
    return ("﻿" + out.getvalue()).encode("utf-8")


def validate_rules(rules):
    if not isinstance(rules, list):
        raise ValueError("rules は配列で指定してください")
    for i, r in enumerate(rules, 1):
        for k in ("match", "kw"):
            if not str(r.get(k, "")).strip():
                raise ValueError(f"{i}行目：{k} が空です")
        for k in ("match", "model", "grade_exclude"):
            if r.get(k):
                try:
                    re.compile(r[k])
                except re.error as e:
                    raise ValueError(f"{i}行目：{k} の正規表現が不正です（{e}）")
        for k in ("ymin", "ymax", "year_window"):
            if r.get(k) in ("", None):
                r.pop(k, None)
            elif k in r:
                r[k] = int(r[k])
    return rules


def rules_match_preview(rules):
    """現在の出品車がどのルールに当たるか"""
    with db() as con:
        run = latest_run(con)
        cars = [json.loads(r["data"]) for r in con.execute("SELECT data FROM snapshots WHERE run_id=?", (run["id"],))] if run else []
    out = []
    for c in cars:
        r = core.pick_rule(c, rules)
        out.append({"slug": c["slug"], "name": f"{c.get('maker', '')} {c['name']}".strip(),
                    "rule": rules.index(r) if r else None})
    return out


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "TBCCBoard/1.0"

    def log_message(self, fmt, *args):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)) or body is None:
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        try:
            if p == "/api/board":
                return self.send(200, api_board())
            if p.startswith("/api/cars/"):
                car = api_car(p.split("/")[-1])
                return self.send(200 if car else 404, car or {"error": "not found"})
            if p == "/api/status":
                j = dict(JOB)
                j["elapsed"] = round(time.time() - j["started"]) if j["started"] else None
                return self.send(200, j)
            if p == "/api/settings":
                return self.send(200, get_settings())
            if p == "/api/rules":
                data = json.load(open(RULES_PATH, encoding="utf-8"))
                return self.send(200, {"rules": data["rules"], "preview": rules_match_preview(data["rules"])})
            if p == "/api/export.csv":
                name = f"tbcc_souba_{dt.date.today():%Y%m%d}.csv"
                return self.send(200, api_csv(), "text/csv; charset=utf-8",
                                 {"Content-Disposition": f'attachment; filename="{name}"'})
            return self.static(p)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return self.send(500, {"error": str(e)})

    def do_POST(self):
        p = urlparse(self.path).path
        try:
            if p == "/api/refresh":
                b = self.body()
                started = do_refresh(force=bool(b.get("force")))
                return self.send(202 if started else 409, {"started": started})
            if p == "/api/settings":
                return self.send(200, put_settings(self.body()))
            if p == "/api/rules":
                b = self.body()
                rules = validate_rules(b.get("rules"))
                if b.get("dry_run"):
                    return self.send(200, {"preview": rules_match_preview(rules)})
                data = json.load(open(RULES_PATH, encoding="utf-8"))
                data["rules"] = rules
                tmp = RULES_PATH + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, RULES_PATH)
                return self.send(200, {"ok": True, "preview": rules_match_preview(rules)})
            return self.send(404, {"error": "not found"})
        except ValueError as e:
            return self.send(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return self.send(500, {"error": str(e)})

    def static(self, p):
        if p in ("/", "") or not os.path.splitext(p)[1]:
            p = "/index.html"
        full = os.path.normpath(os.path.join(STATIC, p.lstrip("/")))
        if not full.startswith(STATIC) or not os.path.isfile(full):
            return self.send(404, {"error": "not found"})
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            return self.send(200, f.read(), ctype)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    init_db()
    with db() as con:
        con.execute("UPDATE runs SET status='error', error='中断' WHERE status='running'")
        empty = latest_run(con) is None
    threading.Thread(target=scheduler, daemon=True).start()
    if empty:
        print("初回起動：相場の取得を開始します（3〜5分）")
        do_refresh()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    url = f"http://{'127.0.0.1' if a.host == '0.0.0.0' else a.host}:{a.port}"
    print(f"TBCC 相場ボード: {url}  （止めるときは Ctrl+C）")
    if not a.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
