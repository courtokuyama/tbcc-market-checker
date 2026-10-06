#!/usr/bin/env python3
"""tokyo basic car club 出品中車両 × カーセンサー相場 チェッカー

使い方:
    python3 tbcc_market.py              # 取得→判定→ report.html / report.csv / data.json を出力
    python3 tbcc_market.py --refresh    # キャッシュを使わず取り直す
    python3 tbcc_market.py --only 78prado,95prado

依存: Python 3.9+ 標準ライブラリのみ。
アクセスは 1リクエストごとに数秒あけ、取得結果は cache/ に 12 時間保存する（同じ日に何度回しても相手サイトへは再アクセスしない）。
"""
import argparse
import csv
import datetime as dt
import hashlib
import html
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "cache")
OUT_DIR = os.path.join(HERE, "out")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129 Safari/537.36"
LINEUP_URL = "https://buy.tokyobasiccarclub.co.jp/line-up/"
CS_SEARCH = "https://www.carsensor.net/usedcar/search.php"
CACHE_TTL = 12 * 3600  # カーセンサー（相場はゆっくり動くので半日再利用）
TBCC_TTL = 5 * 60  # TBCC（新着・値下げ・SOLDをすぐ拾うため毎回ほぼ最新を取る）
REQUEST_GAP = 3.0
MAX_PAGES = 4  # 1ページ30台 → 最大120台

_last_request = 0.0
_refresh = False


# ---------------------------------------------------------------- fetch
def fetch(url, ttl=CACHE_TTL):
    global _last_request
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest() + ".html")
    if not _refresh and os.path.exists(path) and time.time() - os.path.getmtime(path) < ttl:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read()
    wait = REQUEST_GAP - (time.time() - _last_request)
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8", errors="ignore")
            break
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                raise
            print(f"  retry {url}: {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    _last_request = time.time()
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return body


def text_lines(s):
    s = re.sub(r"<script.*?</script>|<style.*?</style>|<noscript.*?</noscript>", "", s, flags=re.S)
    s = html.unescape(re.sub(r"<[^>]+>", "\n", s))
    return [l.strip() for l in s.split("\n") if l.strip()]


def to_int(s):
    s = re.sub(r"[^\d]", "", s or "")
    return int(s) if s else None


# ---------------------------------------------------------------- TBCC
def tbcc_lineup():
    s = fetch(LINEUP_URL, TBCC_TTL)
    a, b = s.find("出品中の車両"), s.find("販売実績")
    seg = s[a:b if b > a else len(s)]
    cars = []
    for art in re.findall(r'<article class="post-item.*?</article>', seg, flags=re.S):
        link = re.search(r'href="([^"]+)" class="post-item-title-link"', art)
        if not link:
            continue
        img = re.search(r'data-src="([^"]+)"', art) or re.search(r'<noscript><img[^>]+src="([^"]+)"', art)
        cars.append({"url": link.group(1), "slug": link.group(1).rstrip("/").split("/")[-1],
                     "image": img.group(1) if img else ""})
    return cars


LABELS = ["車両本体価格", "支払総額", "走行距離", "年式", "車検有効期限", "車検証上の型式", "記録簿／整備履歴",
          "ハンドル", "シフト", "定員", "排気量", "燃料"]


def tbcc_detail(car):
    s = fetch(car["url"], TBCC_TTL)
    L = text_lines(s)
    title = re.search(r"<title>(.*?)\s*\|", s)
    car["name"] = html.unescape(title.group(1)).strip() if title else car["slug"]
    try:
        i0 = L.index(car["name"])
        car["maker"] = L[i0 - 1]
    except ValueError:
        car["maker"] = ""
    stop = L.index("CLOSE") if "CLOSE" in L else len(L)
    for i, l in enumerate(L[:stop]):
        if l not in LABELS:
            continue
        nxt = L[i + 1:i + 6]
        if l in ("車両本体価格", "支払総額"):
            v = next((x for x in nxt if re.fullmatch(r"[\d,]+", x)), None)
            car["base" if l == "車両本体価格" else "total"] = to_int(v)
        elif l == "走行距離":
            v = next((x for x in nxt if re.fullmatch(r"[\d,]+", x)), None)
            car["km"] = to_int(v)
        elif l == "年式":
            car["year"] = to_int(nxt[0][:4])
        elif l == "車検有効期限":
            car["shaken"] = nxt[0]
        elif l == "車検証上の型式":
            car["katashiki"] = nxt[0]
        elif l == "記録簿／整備履歴":
            car["kirokubo"] = nxt[0]
        elif l == "ハンドル":
            car["handle"] = nxt[0]
        elif l == "シフト":
            car["shift"] = nxt[0]
        elif l == "定員":
            car["seats"] = nxt[0]
        elif l == "排気量":
            car["cc"] = to_int(nxt[0])
        elif l == "燃料":
            car["fuel"] = nxt[0]
    imgs = []
    for u in re.findall(r'(https://buy\.tokyobasiccarclub\.co\.jp/wp-content/uploads/sites/3/\d{4}/\d{2}/[^"\s,]+?\.(?:jpe?g|png|webp))', s):
        if re.search(r"-\d+x\d+\.|banner_|btn-|favicon|logo", u) or u in imgs:
            continue
        imgs.append(u)
    car["images"] = imgs[:24]
    m = re.match(r"(\d{4})年(\d{1,2})月", car.get("shaken", ""))
    today = dt.date.today()  # 常駐アプリで日付が古くならないよう毎回取る
    car["shaken_months"] = ((int(m.group(1)) - today.year) * 12 + int(m.group(2)) - today.month) if m else None
    return car


# ---------------------------------------------------------------- Carsensor
def cs_parse(s):
    out = []
    for block in re.split(r'<div class="cassette js_listTableCassette"', s)[1:]:
        block = block.split('<div class="cassetteWrap')[0]
        bid = re.search(r'id="(\w+)_cas"', block)
        maker = re.search(r"<p>([^<]{1,30})</p>\s*<h3", block)
        t = re.search(r'<h3 class="cassetteMain__title">\s*<a[^>]*>(.*?)</a>', block, flags=re.S)
        title = html.unescape(re.sub(r"<[^>]+>", "", t.group(1))).strip() if t else ""
        parts = title.split("\xa0")

        def num(cls):
            m1 = re.search(rf'{cls}__mainPriceNum">([\d,]+)</span>(?:<span class="{cls}__subPriceNum">(\.\d)</span>)?', block)
            if not m1:
                return None
            return round(float(m1.group(1).replace(",", "") + (m1.group(2) or "")) * 10000)

        spec = dict(re.findall(r'<dt class="specList__title[^"]*">([^<]+)</dt>\s*<dd class="specList__data[^"]*">(.*?)</dd>',
                               block, flags=re.S))
        spec = {k: html.unescape(re.sub(r"<[^>]+>", "", v)).strip() for k, v in spec.items()}
        km_txt = spec.get("走行距離", "")
        km = None
        mk = re.match(r"([\d.]+)\s*(万)?km", km_txt.replace(",", ""))
        if mk:
            km = round(float(mk.group(1)) * (10000 if mk.group(2) else 1))
        area = re.search(r'<div class="cassetteSub__area">\s*<p>([^<]*)</p>', block)
        out.append({
            "id": bid.group(1) if bid else "",
            "url": f"https://www.carsensor.net/usedcar/detail/{bid.group(1)}/index.html" if bid else "",
            "maker": maker.group(1).strip() if maker else "",
            "model": parts[0].strip() if parts else "",
            "grade": parts[1].strip() if len(parts) > 1 else "",
            "title": title,
            "total": num("totalPrice"),
            "base": num("basePrice"),
            "year": to_int(spec.get("年式", "")[:4]),
            "km": km,
            "shaken": spec.get("車検", ""),
            "repair": spec.get("修復歴", ""),
            "warranty": spec.get("保証", ""),
            "maint": spec.get("整備", ""),
            "cc": to_int(spec.get("排気量", "")),
            "mission": spec.get("ミッション", ""),
            "area": area.group(1) if area else "",
        })
    return out


def cs_search(kw, ymin, ymax):
    q = {"STID": "CS210610", "KW": kw, "YMIN": ymin, "YMAX": ymax}
    first = CS_SEARCH + "?" + urllib.parse.urlencode(q)
    s = fetch(first)
    m = re.search(r"([\d,]+)</span>\s*台", s)
    hits = to_int(m.group(1)) if m else 0
    items = cs_parse(s)
    nxt = re.search(r'href="(/usedcar/freeword/[^"]+?/)index2\.html\?([^"]*)"', s)
    if nxt:
        base, qs = nxt.group(1), html.unescape(nxt.group(2))
        pages = min(MAX_PAGES, math.ceil(hits / 30))
        for p in range(2, pages + 1):
            items += cs_parse(fetch(f"https://www.carsensor.net{base}index{p}.html?{qs}"))
    return first, hits, items


# ---------------------------------------------------------------- matching / valuation
def pick_rule(car, rules):
    key = f'{car.get("maker", "")} {car["name"]}'
    for r in rules:
        if re.search(r["match"], key, flags=re.I):
            return r
    return None


def wmedian(vals, ws):
    pairs = sorted(zip(vals, ws))
    half = sum(ws) / 2
    acc = 0
    for v, w in pairs:
        acc += w
        if acc >= half:
            return v
    return pairs[-1][0]


def pct(vals, q):
    v = sorted(vals)
    if not v:
        return None
    k = (len(v) - 1) * q
    f = math.floor(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


PRIOR_ELAST, PRIOR_N = -0.25, 15


def km_elasticity(comps, y):
    pts = [c for c in comps if c["km"]]
    if len(pts) < 5:
        return PRIOR_ELAST
    # log(価格) = a + b*(年式差) + e*log(距離) の重み付き最小二乗（年式は近いほど重く）
    X = [[1.0, c["year"] - y, math.log(c["km"] + 10000)] for c in pts]
    Y = [math.log(c["total"]) for c in pts]
    W = [math.exp(-abs(c["year"] - y) / 2.5) for c in pts]
    A = [[sum(w * xi[i] * xi[j] for xi, w in zip(X, W)) for j in range(3)] for i in range(3)]
    b = [sum(w * xi[i] * yi for xi, yi, w in zip(X, Y, W)) for i in range(3)]
    M = [A[i] + [b[i]] for i in range(3)]
    try:
        for i in range(3):
            p = max(range(i, 3), key=lambda r: abs(M[r][i]))
            M[i], M[p] = M[p], M[i]
            for r in range(3):
                if r != i:
                    f = M[r][i] / M[i][i]
                    M[r] = [a - f * c for a, c in zip(M[r], M[i])]
        e = M[2][3] / M[2][2]
    except ZeroDivisionError:
        return PRIOR_ELAST
    n = len(pts)
    e = (n * e + PRIOR_N * PRIOR_ELAST) / (n + PRIOR_N)
    return max(-0.6, min(0.0, e))


def evaluate(car, rules, threshold=0.10):
    rule = pick_rule(car, rules)
    y = car.get("year") or dt.date.today().year
    if rule:
        kw = rule["kw"]
        win = rule.get("year_window")
        ymin = rule.get("ymin", y - (win or 3))
        ymax = rule.get("ymax", y + (win or 3))
        if win:
            ymin, ymax = y - win, y + win
        model_re = rule.get("model")
    else:
        kw, ymin, ymax, model_re = car["name"], y - 3, y + 3, None
    search_url, hits, items = cs_search(kw, ymin, ymax)

    notes = []
    comps = [c for c in items if c["total"] and c["year"]]
    if model_re:
        also = rule.get("also", [])
        comps = [c for c in comps if re.search(model_re, c["model"])
                 or any(re.search(a["model"], c["model"]) and re.search(a["grade"], c["grade"]) for a in also)]
    if rule and rule.get("grade_exclude"):
        comps = [c for c in comps if not re.search(rule["grade_exclude"], c["grade"])]
    comps = [c for c in comps if c["km"] != 0]  # 走行0kmは不明/メーター交換の表記ゆれとみなし除外
    n_raw = len(comps)
    repaired = [c for c in comps if c["repair"].startswith("あり")]
    comps = [c for c in comps if not c["repair"].startswith("あり")]

    # ミッション・排気量が揃う個体だけに絞る（絞りすぎて5台未満なら緩める）
    shift = (car.get("shift") or "").upper()
    if shift in ("AT", "MT"):
        same = [c for c in comps if (("MT" in c["mission"] and "AT" not in c["mission"]) == (shift == "MT"))]
        if len(same) >= 5:
            comps = same
        else:
            notes.append(f"{shift}車だけだと{len(same)}台しかないため、AT/MT混在で比較")
    fuel = car.get("fuel") or ""
    if fuel:
        diesel = "ディーゼル" in fuel
        same = [c for c in comps if ("ディーゼル" in c["title"]) == diesel]
        if len(same) >= 5:
            comps = same
        else:
            notes.append(f"{'ディーゼル' if diesel else 'ガソリン'}車だけだと{len(same)}台しかないため、燃料混在で比較")
    if car.get("cc"):
        same = [c for c in comps if c["cc"] and abs(c["cc"] - car["cc"]) / car["cc"] <= 0.2]
        if len(same) >= 5:
            comps = same
        else:
            notes.append(f"排気量±20%だと{len(same)}台しかないため、排気量混在で比較")

    res = {"rule": rule["kw"] if rule else None, "search_url": search_url, "hits": hits, "fetched": len(items),
           "n_model": n_raw, "n_repaired_excluded": len(repaired), "ymin": ymin, "ymax": ymax, "notes": notes}
    if not rule:
        notes.insert(0, "models.json に該当ルールなし（タイトルのまま検索）→ 要ルール追加")
    if not comps or not car.get("total"):
        res.update(verdict="比較不可", n=len(comps), comps=[])
        return res

    # 走行距離の効き（距離2倍で何%下がるか）を比較車から推定し、各比較車の価格をTBCCと同じ距離に補正する。
    # 台数が少ないと推定がぶれるので、標準値(距離2倍で約-16%)へ寄せ、極端な値は切る。
    km_t = car.get("km") or 100000
    elast = km_elasticity(comps, y)
    for c in comps:
        c["yw"] = math.exp(-abs((c["year"] or y) - y) / 2.5)
        if c["km"]:
            c["adj"] = c["total"] * ((km_t + 10000) / (c["km"] + 10000)) ** elast
            c["w"] = c["yw"] * math.exp(-abs(math.log((c["km"] + 10000) / (km_t + 10000))) / 1.0)
        else:  # 距離不明は補正できないので素の価格・低い重み
            c["adj"] = c["total"]
            c["w"] = c["yw"] * 0.4
    ws = [c["w"] for c in comps]
    totals = [c["total"] for c in comps]
    est = wmedian([c["adj"] for c in comps], ws)
    eff_n = sum(ws) ** 2 / sum(w * w for w in ws)
    diff = (car["total"] - est) / est
    cheaper_share = sum(1 for t in totals if t < car["total"]) / len(totals)
    if diff <= -threshold:
        verdict = "お手頃"
    elif diff >= threshold:
        verdict = "割高"
    else:
        verdict = "相場並み"
    conf = "高" if eff_n >= 8 else "中" if eff_n >= 4 else "低"

    kms = [c["km"] for c in comps if c["km"]]
    med_km = pct(kms, 0.5) if kms else None
    cond = []
    if med_km and car.get("km"):
        r = car["km"] / med_km
        cond.append(f"走行距離は比較車の中央値({med_km/10000:.1f}万km)の{r:.1f}倍" +
                    ("（少なめ＝プラス材料）" if r < 0.8 else "（多め＝マイナス材料）" if r > 1.25 else "（ほぼ同等）"))
    if car.get("shaken_months") is not None:
        sm = car["shaken_months"]
        no_shaken = sum(1 for c in comps if "なし" in c["shaken"] or "無" in c["shaken"]) / len(comps)
        cond.append(f"車検残り約{sm}ヶ月" + ("（1年以上残＝プラス材料）" if sm >= 12 else "") +
                    f"／比較車の{no_shaken:.0%}は車検なし")
    if car.get("kirokubo"):
        cond.append(f"記録簿・整備履歴: {car['kirokubo']}")
    w_share = sum(1 for c in comps if c["warranty"].startswith("保証付")) / len(comps)
    cond.append(f"相場は比較車の価格を同じ走行距離に補正して算出（この車種では距離2倍で約{(2 ** elast - 1):+.0%}）")
    cond.append(f"比較車の{w_share:.0%}が保証付・{sum(1 for c in comps if '法定整備付' in c['maint'])/len(comps):.0%}が法定整備付"
                "（TBCC側の保証・整備条件は個別確認）")

    top = sorted(comps, key=lambda c: -c["w"])[:6]
    res.update(verdict=verdict, confidence=conf, n=len(comps), eff_n=round(eff_n, 1), est=est,
               median=pct(totals, 0.5), p25=pct(totals, 0.25), p75=pct(totals, 0.75),
               min=min(totals), max=max(totals), diff=diff, cheaper_share=cheaper_share,
               med_km=med_km, cond=cond,
               elasticity=round(elast, 3),
               dist=[{"total": c["total"], "adj": round(c["adj"]), "year": c["year"], "km": c["km"], "w": round(c["w"] / max(ws), 3)} for c in comps],
               comps=[{k: c[k] for k in ("url", "model", "grade", "year", "km", "total", "adj", "shaken", "warranty", "mission", "area")}
                      for c in top])
    return res


# ---------------------------------------------------------------- output
def man(v):
    return "—" if v is None else f"{v/10000:,.1f}万円"


def write_outputs(cars):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "data.json"), "w", encoding="utf-8") as f:
        json.dump({"generated": dt.datetime.now().isoformat(timespec="minutes"), "cars": cars}, f,
                  ensure_ascii=False, indent=1)
    with open(os.path.join(OUT_DIR, "report.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["判定", "車名", "メーカー", "年式", "走行距離km", "車検", "記録簿", "シフト", "TBCC支払総額", "相場推定(類似度加重中央値)",
                    "差額", "差率", "比較台数", "信頼度", "相場25%", "相場中央値", "相場75%", "TBCCより安い比較車の割合", "TBCC URL", "カーセンサー検索URL"])
        for c in cars:
            m = c["market"]
            w.writerow([m["verdict"], c["name"], c.get("maker"), c.get("year"), c.get("km"), c.get("shaken"), c.get("kirokubo"),
                        c.get("shift"), c.get("total"), m.get("est"),
                        (c["total"] - m["est"]) if m.get("est") else "", f'{m["diff"]:+.1%}' if "diff" in m else "",
                        m.get("n"), m.get("confidence"), m.get("p25"), m.get("median"), m.get("p75"),
                        f'{m["cheaper_share"]:.0%}' if "cheaper_share" in m else "", c["url"], m["search_url"]])
    tpl = open(os.path.join(HERE, "report_template.html"), encoding="utf-8").read()
    payload = json.dumps({"generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "cars": cars}, ensure_ascii=False)
    with open(os.path.join(OUT_DIR, "report.html"), "w", encoding="utf-8") as f:
        f.write(tpl.replace("/*__DATA__*/null", payload.replace("</", "<\\/")))


VERDICT_ORDER = {"お手頃": 0, "相場並み": 1, "割高": 2, "比較不可": 3}


def run(only=None, refresh=False, progress=None, threshold=0.10, rules=None):
    """全工程を実行して車両リストを返す。progress(done, total, message) で進捗を通知する。"""
    global _refresh
    _refresh = refresh
    if rules is None:
        rules = json.load(open(os.path.join(HERE, "models.json"), encoding="utf-8"))["rules"]
    say = progress or (lambda d, t, msg: print(msg, file=sys.stderr))
    say(0, 0, "TBCCの出品一覧を取得中")
    cars = tbcc_lineup()
    if only:
        cars = [c for c in cars if c["slug"] in set(only)]
    total = len(cars)
    if not cars and not only:
        raise RuntimeError("TBCCの一覧から車両を1台も読めませんでした（サイトの作りが変わった可能性。保存は見送りました）")
    for i, c in enumerate(cars):
        say(i, total, f"{c['slug']} の詳細を取得中")
        tbcc_detail(c)
    broken = [c["slug"] for c in cars if not c.get("total") or not c.get("year")]
    if cars and len(broken) > len(cars) / 2:
        raise RuntimeError(f"TBCCの詳細ページから価格・年式を読めない車両が{len(broken)}/{len(cars)}台あります"
                           "（サイトの作りが変わった可能性。保存は見送りました）")
    for i, c in enumerate(cars):
        say(i, total, f"{c.get('maker')} {c['name']} の相場を検索中")
        try:
            c["market"] = evaluate(c, rules, threshold)
        except Exception as e:  # noqa: BLE001  1台の失敗で全体を止めない
            c["market"] = {"verdict": "比較不可", "notes": [f"取得エラー: {e}"], "comps": [], "search_url": ""}
    say(total, total, "完了")
    cars.sort(key=lambda c: (VERDICT_ORDER[c["market"]["verdict"]], c["market"].get("diff", 9)))
    return cars


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="キャッシュを無視して取り直す")
    ap.add_argument("--only", help="slugをカンマ区切りで指定")
    a = ap.parse_args()
    cars = run(a.only.split(",") if a.only else None, a.refresh)
    write_outputs(cars)
    print(f"出力: {os.path.join(OUT_DIR, 'report.html')}", file=sys.stderr)


if __name__ == "__main__":
    main()
