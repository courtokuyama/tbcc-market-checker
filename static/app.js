"use strict";
// ------------------------------------------------------------ helpers
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const man = v => v == null ? "—" : (v / 10000).toLocaleString("ja-JP", { maximumFractionDigits: 1, minimumFractionDigits: 1 });
const manU = v => v == null ? "—" : `${man(v)}<small>万円</small>`;
const kmS = v => v == null ? "—" : `${(v / 10000).toLocaleString("ja-JP", { maximumFractionDigits: 1 })}万km`;
const pctS = d => d == null ? "—" : `${d > 0 ? "+" : ""}${(d * 100).toFixed(1)}%`;
const sign = d => d == null ? "" : d < 0 ? "neg" : d > 0 ? "pos" : "";
const fmtDT = s => { if (!s) return "—"; const d = new Date(s); return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; };
const ago = s => { if (!s) return ""; const m = Math.round((Date.now() - new Date(s)) / 60000); return m < 1 ? "たった今" : m < 60 ? `${m}分前` : m < 1440 ? `${Math.round(m / 60)}時間前` : `${Math.round(m / 1440)}日前`; };
const VERDICTS = ["お手頃", "相場並み", "割高", "比較不可"];
const VCOLOR = { "お手頃": "var(--good)", "相場並み": "var(--chart-dot)", "割高": "var(--bad)", "比較不可": "var(--line)" };
const ICON = {
  search: '<svg viewBox="0 0 24 24" class="ic"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>',
  grid: '<svg viewBox="0 0 24 24" class="ic"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>',
  list: '<svg viewBox="0 0 24 24" class="ic"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/></svg>',
  close: '<svg viewBox="0 0 24 24" class="ic"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  left: '<svg viewBox="0 0 24 24" class="ic"><path d="M15 6l-6 6 6 6"/></svg>',
  right: '<svg viewBox="0 0 24 24" class="ic"><path d="M9 6l6 6-6 6"/></svg>',
  ext: '<svg viewBox="0 0 24 24" class="ic"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>',
  dl: '<svg viewBox="0 0 24 24" class="ic"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>',
  new: '<svg viewBox="0 0 24 24" class="ic"><path d="M12 5v14M5 12h14"/></svg>',
  price_down: '<svg viewBox="0 0 24 24" class="ic"><path d="M12 5v14M6 13l6 6 6-6"/></svg>',
  price_up: '<svg viewBox="0 0 24 24" class="ic"><path d="M12 19V5M6 11l6-6 6 6"/></svg>',
  gone: '<svg viewBox="0 0 24 24" class="ic"><path d="M5 12h14"/></svg>',
  verdict: '<svg viewBox="0 0 24 24" class="ic"><path d="M4 12h12M12 6l6 6-6 6"/></svg>',
  plus: '<svg viewBox="0 0 24 24" class="ic"><path d="M12 5v14M5 12h14"/></svg>',
  trash: '<svg viewBox="0 0 24 24" class="ic"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/></svg>',
};
const store = {
  get(k, d) { try { const v = localStorage.getItem("tbcc." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("tbcc." + k, JSON.stringify(v)); } catch { } },
};
async function api(path, opt = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opt, body: opt.body ? JSON.stringify(opt.body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (!r.ok && r.status !== 409) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
}
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => t.hidden = true, 3200);
}

// ------------------------------------------------------------ state
const S = {
  board: null,
  filter: store.get("filter", "all"),
  sort: store.get("sort", "verdict"),
  view: store.get("view", "grid"),
  q: "",
};

// ------------------------------------------------------------ router
function route() {
  const h = location.hash.replace(/^#/, "") || "/";
  const [, page, arg] = h.split("/");
  document.querySelectorAll(".tabs a").forEach(a => a.classList.toggle("active", a.dataset.route === (page || "board") || (page === "car" && a.dataset.route === "board")));
  const pg = page === "car" ? "board" : (page || "board");
  if (pg !== S.page || route.force) {
    S.page = pg; route.force = false;
    if (pg === "changes") renderChanges();
    else if (pg === "settings") renderSettings();
    else renderBoard();
  }
  if (page === "car" && arg) openCar(decodeURIComponent(arg)); else closeDrawer(true);
}
window.addEventListener("hashchange", route);

// ------------------------------------------------------------ board
async function loadBoard() {
  S.board = await api("/api/board");
  const r = S.board.run;
  $("#updated").textContent = r ? `最終更新 ${fmtDT(r.finished)}（${ago(r.finished)}）` : "未取得";
  const seen = store.get("seenEvent", 0);
  const latest = S.board.events[0]?.id || 0;
  $("#changesDot").hidden = !(latest > seen);
  return S.board;
}

function kpis(b) {
  const cars = b.cars;
  const cnt = Object.fromEntries(VERDICTS.map(v => [v, cars.filter(c => c.market.verdict === v).length]));
  const comp = cars.filter(c => c.market.est != null && c.total);
  const saving = comp.filter(c => c.market.diff < 0).reduce((a, c) => a + (c.market.est - c.total), 0);
  const avg = comp.length ? comp.reduce((a, c) => a + c.market.diff, 0) / comp.length : null;
  const best = comp.slice().sort((a, b) => a.market.diff - b.market.diff)[0];
  const mix = VERDICTS.filter(v => cnt[v]).map(v => `<span style="flex:${cnt[v]};background:${VCOLOR[v]}" title="${v} ${cnt[v]}台"></span>`).join("");
  return `<section class="kpis">
    <div class="kpi"><div class="k">出品中</div><div class="v num">${cars.length}<small>台</small></div>
      <div class="mix">${mix}</div><div class="s">${VERDICTS.filter(v => cnt[v]).map(v => `${v} ${cnt[v]}`).join("・")}</div></div>
    <div class="kpi good"><div class="k">相場よりお手頃</div><div class="v num">${cnt["お手頃"]}<small>台</small></div>
      <div class="s">相場より${Math.round(b.threshold * 100)}%以上安い車両</div></div>
    <div class="kpi"><div class="k">相場との差（お得分の合計）</div><div class="v num" style="color:var(--good)">${man(saving)}<small>万円</small></div>
      <div class="s">平均差率 <b class="diff ${sign(avg)}">${pctS(avg)}</b></div></div>
    <div class="kpi"><div class="k">いちばんお手頃</div><div class="v" style="font-size:17px;line-height:1.4;margin-top:6px">${best ? esc(best.name) : "—"}</div>
      <div class="s">${best ? `相場 ${man(best.market.est)}万円 → <b class="diff neg">${pctS(best.market.diff)}</b>` : ""}</div></div>
  </section>`;
}

function evStrip(events) {
  if (!events.length) return "";
  return `<div class="strip">${events.slice(0, 8).map(e => `
    <div class="ev" data-slug="${esc(e.slug)}"><span class="ev-ic k-${e.kind}">${ICON[e.kind] || ""}</span>
      <div><div class="t">${esc(e.title)}</div><div class="d">${esc(e.detail)}・${ago(e.at)}</div></div></div>`).join("")}</div>`;
}

function gauge(d, th) {
  if (d == null) return `<div class="gauge"><div class="track" style="opacity:.4"></div></div>`;
  const x = v => Math.max(2, Math.min(98, 50 + v / 0.4 * 50));
  return `<div class="gauge" title="相場との差 ${pctS(d)}">
    <div class="track"></div><div class="zero"></div>
    <div class="th" style="left:${x(-th)}%"></div><div class="th" style="left:${x(th)}%"></div>
    <div class="mark ${sign(d)}" style="left:${x(d)}%"></div></div>`;
}

function isNew(c) { return c.first_seen && (Date.now() - new Date(c.first_seen)) < 7 * 864e5 && S.board.runs > 1; }

function carCard(c) {
  const m = c.market;
  return `<article class="car" tabindex="0" data-slug="${esc(c.slug)}">
    <div class="ph"><img src="${esc(c.images?.[0] || c.image)}" alt="" loading="lazy">
      <div class="badges"><span class="badge v-${m.verdict}">${m.verdict}${m.confidence ? `<span class="conf">・信頼度${m.confidence}</span>` : ""}</span>${isNew(c) ? '<span class="badge new">NEW</span>' : ""}</div></div>
    <div class="bd">
      <div><div class="maker">${esc(c.maker)}</div><h3 class="cname">${esc(c.name)}</h3></div>
      <div class="prices">
        <div><div class="lbl">支払総額</div><div class="tb num">${manU(c.total)}</div></div>
        <div class="mk"><div class="lbl">相場 ${m.est != null ? man(m.est) + "万円" : "—"}</div>
          <div class="val num"><span class="diff ${sign(m.diff)}">${pctS(m.diff)}</span>${m.est != null ? `（${c.total - m.est > 0 ? "+" : ""}${man(c.total - m.est)}万）` : ""}</div></div>
      </div>
      ${gauge(m.diff, S.board.threshold)}
      <div class="chips"><span class="chip">${c.year ?? "—"}年</span><span class="chip">${kmS(c.km)}</span>
        <span class="chip">車検 ${c.shaken_months != null ? `残${c.shaken_months}ヶ月` : "—"}</span>
        <span class="chip">${esc(c.shift || "")}${c.cc ? ` ${c.cc.toLocaleString()}cc` : ""}</span>${c.kirokubo ? `<span class="chip">記録簿 ${esc(c.kirokubo)}</span>` : ""}</div>
    </div></article>`;
}

const SORTS = {
  verdict: ["判定順", (a, b) => VERDICTS.indexOf(a.market.verdict) - VERDICTS.indexOf(b.market.verdict) || (a.market.diff ?? 9) - (b.market.diff ?? 9)],
  diff: ["お手頃な順", (a, b) => (a.market.diff ?? 9) - (b.market.diff ?? 9)],
  saving: ["お得額が大きい順", (a, b) => ((b.market.est ?? 0) - b.total) - ((a.market.est ?? 0) - a.total)],
  price: ["価格が安い順", (a, b) => a.total - b.total],
  priceDesc: ["価格が高い順", (a, b) => b.total - a.total],
  year: ["年式が新しい順", (a, b) => (b.year ?? 0) - (a.year ?? 0)],
  km: ["走行距離が少ない順", (a, b) => (a.km ?? 1e9) - (b.km ?? 1e9)],
};

function visibleCars() {
  const q = S.q.trim().toLowerCase();
  return S.board.cars
    .filter(c => S.filter === "all" || c.market.verdict === S.filter)
    .filter(c => !q || `${c.maker} ${c.name} ${c.katashiki || ""} ${c.year}`.toLowerCase().includes(q))
    .sort(SORTS[S.sort][1]);
}

function table(cars) {
  return `<div class="tablewrap"><table>
    <thead><tr><th>車両</th><th>判定</th><th class="r">支払総額</th><th class="r">相場</th><th class="r">差額</th><th class="r">差率</th><th class="r">年式</th><th class="r">走行</th><th>車検</th><th class="r">比較</th></tr></thead>
    <tbody>${cars.map(c => { const m = c.market; return `<tr data-slug="${esc(c.slug)}">
      <td><img class="thumb" src="${esc(c.images?.[0] || c.image)}" alt="" loading="lazy"><b>${esc(c.name)}</b> <span style="color:var(--sub);font-size:12px">${esc(c.maker)}</span></td>
      <td><span class="badge v-${m.verdict}">${m.verdict}</span></td>
      <td class="r num"><b>${man(c.total)}</b>万</td><td class="r num">${man(m.est)}万</td>
      <td class="r num"><span class="diff ${sign(m.diff)}">${m.est != null ? (c.total - m.est > 0 ? "+" : "") + man(c.total - m.est) + "万" : "—"}</span></td>
      <td class="r num"><span class="diff ${sign(m.diff)}">${pctS(m.diff)}</span></td>
      <td class="r num">${c.year ?? "—"}</td><td class="r num">${kmS(c.km)}</td><td>${esc(c.shaken || "—")}</td>
      <td class="r num">${m.n ?? 0}台・${m.confidence ?? "—"}</td></tr>`; }).join("")}</tbody></table></div>`;
}

function renderList() {
  const cars = visibleCars();
  const el = $("#list");
  if (!cars.length) { el.innerHTML = `<div class="empty"><h2>該当する車両がありません</h2>絞り込み条件を変えてください。</div>`; return; }
  el.innerHTML = S.view === "table" ? table(cars) : `<div class="grid">${cars.map(carCard).join("")}</div>`;
}

async function renderBoard() {
  const v = $("#view");
  if (!S.board) v.innerHTML = `<div class="kpis">${'<div class="skel" style="height:110px"></div>'.repeat(4)}</div><div class="grid">${'<div class="skel" style="height:380px"></div>'.repeat(6)}</div>`;
  const b = await loadBoard().catch(e => { v.innerHTML = `<div class="empty"><h2>読み込めませんでした</h2>${esc(e.message)}</div>`; });
  if (!b) return;
  if (!b.run) {
    v.innerHTML = `<div class="empty"><h2>まだ相場データがありません</h2>右上の「相場を更新」を押すと、出品中の全車両を取得して判定します（3〜5分）。</div>`;
    return;
  }
  const cnt = Object.fromEntries(VERDICTS.map(x => [x, b.cars.filter(c => c.market.verdict === x).length]));
  v.innerHTML = `
    <div class="hero"><div><h1>出品中の車両と相場</h1><p>カーセンサー掲載の同車種・同世代と比較（走行距離補正済み）。カードを押すと根拠を確認できます。</p></div>
      <a class="btn" href="/api/export.csv">${ICON.dl}<span>CSVで書き出し</span></a></div>
    ${kpis(b)}
    ${evStrip(b.events)}
    <div class="toolbar">
      <label class="search">${ICON.search}<input id="q" type="search" placeholder="車名・メーカー・型式で検索" value="${esc(S.q)}"></label>
      <div class="seg" id="filters">
        <button data-f="all" class="${S.filter === "all" ? "on" : ""}">すべて<b>${b.cars.length}</b></button>
        ${VERDICTS.filter(x => cnt[x]).map(x => `<button data-f="${x}" class="${S.filter === x ? "on" : ""}">${x}<b>${cnt[x]}</b></button>`).join("")}
      </div>
      <select class="select" id="sort" aria-label="並び替え">${Object.entries(SORTS).map(([k, [l]]) => `<option value="${k}" ${S.sort === k ? "selected" : ""}>${l}</option>`).join("")}</select>
      <div class="seg" id="views">
        <button data-v="grid" class="${S.view === "grid" ? "on" : ""}" aria-label="カード表示">${ICON.grid}</button>
        <button data-v="table" class="${S.view === "table" ? "on" : ""}" aria-label="表で表示">${ICON.list}</button>
      </div>
    </div>
    <div id="list"></div>
    <p class="foot">判定：相場より${Math.round(b.threshold * 100)}%以上安い＝お手頃／${Math.round(b.threshold * 100)}%以上高い＝割高（設定で変更可）。TBCCの支払総額は一都三県の納車費用(11万円)込み、カーセンサーは店頭納車前提。保証・内外装・改造の有無は比較に入らないため、最終判断は現車で。比較元データはカーセンサー.netの公開掲載情報（社内検討用）。</p>`;
  renderList();
  if (S.filter !== "all" && !cnt[S.filter]) { S.filter = "all"; }
  $("#q").addEventListener("input", e => { S.q = e.target.value; renderList(); });
  $("#filters").addEventListener("click", e => { const t = e.target.closest("button"); if (!t) return; S.filter = t.dataset.f; store.set("filter", S.filter); $("#filters").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === t)); renderList(); });
  $("#sort").addEventListener("change", e => { S.sort = e.target.value; store.set("sort", S.sort); renderList(); });
  $("#views").addEventListener("click", e => { const t = e.target.closest("button"); if (!t) return; S.view = t.dataset.v; store.set("view", S.view); $("#views").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === t)); renderList(); });
}

document.addEventListener("click", e => {
  const t = e.target.closest("[data-slug]");
  if (t && !e.target.closest("a")) location.hash = `#/car/${encodeURIComponent(t.dataset.slug)}`;
});
document.addEventListener("keydown", e => {
  if (e.key === "Enter" && e.target.matches?.(".car")) location.hash = `#/car/${encodeURIComponent(e.target.dataset.slug)}`;
  if (e.key === "Escape" && $("#drawer").classList.contains("open")) closeDrawer();
});

// ------------------------------------------------------------ drawer
function closeDrawer(silent) {
  const d = $("#drawer");
  if (!d.classList.contains("open")) return;
  d.classList.remove("open"); d.setAttribute("aria-hidden", "true");
  $("#backdrop").hidden = true; document.body.style.overflow = "";
  if (!silent && location.hash.startsWith("#/car/")) history.back();
}
$("#backdrop").addEventListener("click", () => closeDrawer());

function scatter(c) {
  const m = c.market, pts = (m.dist || []).filter(p => p.km);
  if (!pts.length || m.est == null) return `<div class="help">比較できる車両がありません。</div>`;
  const W = 680, H = 300, L = 54, R = 16, T = 14, B = 40;
  const kms = pts.map(p => p.km).concat([c.km || 0]);
  const prices = pts.map(p => p.total).concat([c.total, m.est]);
  const xmax = Math.max(...kms) * 1.06, xmin = 0;
  let ymin = Math.min(...prices) * 0.9, ymax = Math.max(...prices) * 1.06;
  const x = v => L + (v - xmin) / (xmax - xmin) * (W - L - R);
  const y = v => T + (1 - (v - ymin) / (ymax - ymin)) * (H - T - B);
  const step = niceStep((ymax - ymin) / 5), kstep = niceStep(xmax / 6);
  let grid = "";
  for (let v = Math.ceil(ymin / step) * step; v <= ymax; v += step) grid += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="var(--chart-grid)"/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${(v / 10000).toLocaleString()}万</text>`;
  for (let v = 0; v <= xmax; v += kstep) grid += `<text x="${x(v)}" y="${H - B + 18}" text-anchor="middle">${(v / 10000).toLocaleString()}万km</text>`;
  // 相場線：TBCCと同じ年式の車が、その走行距離ならいくらか
  const kt = c.km || 100000, e = m.elasticity ?? -0.25;
  let path = "";
  for (let i = 0; i <= 60; i++) { const k = xmax * i / 60; const p = m.est * Math.pow((k + 1e4) / (kt + 1e4), e); if (p >= ymin && p <= ymax) path += `${path ? "L" : "M"}${x(k).toFixed(1)},${y(p).toFixed(1)}`; }
  const yr = c.year;
  const dots = pts.sort((a, b) => a.w - b.w).map(p => {
    const dy = Math.abs((p.year ?? yr) - yr);
    return `<circle cx="${x(p.km).toFixed(1)}" cy="${y(p.total).toFixed(1)}" r="${(3 + p.w * 3).toFixed(1)}" fill="${dy <= 1 ? "var(--ink-2)" : "var(--chart-dot)"}" fill-opacity="${(0.25 + p.w * 0.6).toFixed(2)}"><title>${p.year}年・${kmS(p.km)}・${man(p.total)}万円</title></circle>`;
  }).join("");
  const tx = x(c.km || 0), ty = y(c.total);
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="走行距離と価格の相場マップ">
    ${grid}
    <path d="${path}" fill="none" stroke="var(--sub)" stroke-width="2" stroke-dasharray="6 5"/>
    ${dots}
    <line x1="${tx}" x2="${tx}" y1="${ty}" y2="${y(m.est * 1)}" stroke="${m.diff < 0 ? "var(--good)" : "var(--bad)"}" stroke-width="2"/>
    <circle cx="${tx}" cy="${ty}" r="9" fill="${m.diff < 0 ? "var(--good)" : m.diff > 0 ? "var(--bad)" : "var(--ink)"}" stroke="var(--surface)" stroke-width="3"/>
    <text x="${tx + (tx > W - 140 ? -14 : 14)}" y="${ty + 4}" text-anchor="${tx > W - 140 ? "end" : "start"}" style="fill:var(--ink);font-weight:700;font-size:12px">この車 ${man(c.total)}万</text>
  </svg>
  <div class="legend"><span><i style="background:var(--good)"></i>この車</span><span><i style="background:var(--ink-2)"></i>比較車（年式±1年）</span><span><i style="background:var(--chart-dot)"></i>比較車（それ以外）</span><span>- - 相場線（この年式で、その走行距離ならいくらか）</span></div>`;
}
function niceStep(raw) { const p = Math.pow(10, Math.floor(Math.log10(raw))); const n = raw / p; return (n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10) * p; }

function historyChart(h) {
  if (!h || h.length < 2) return `<div class="help">更新を重ねると、価格と相場の推移がここに出ます（現在${h?.length || 0}回分）。</div>`;
  const W = 680, H = 160, L = 54, R = 16, T = 10, B = 26;
  const vals = h.flatMap(p => [p.total, p.est]).filter(v => v != null);
  const ymin = Math.min(...vals) * 0.95, ymax = Math.max(...vals) * 1.05;
  const x = i => L + i / (h.length - 1) * (W - L - R), y = v => T + (1 - (v - ymin) / (ymax - ymin)) * (H - T - B);
  const line = (k, col, dash) => `<path d="${h.map((p, i) => p[k] == null ? "" : `${i ? "L" : "M"}${x(i)},${y(p[k])}`).join("")}" fill="none" stroke="${col}" stroke-width="2.5" ${dash ? 'stroke-dasharray="6 5"' : ""}/>`;
  return `<svg viewBox="0 0 ${W} ${H}">
    <text x="${L - 8}" y="${y(ymax) + 10}" text-anchor="end">${man(ymax)}万</text><text x="${L - 8}" y="${y(ymin)}" text-anchor="end">${man(ymin)}万</text>
    ${line("est", "var(--sub)", true)}${line("total", "var(--ink)")}
    ${h.map((p, i) => `<text x="${x(i)}" y="${H - 6}" text-anchor="middle">${fmtDT(p.at).split(" ")[0]}</text>`).join("")}
  </svg><div class="legend"><span><i style="background:var(--ink)"></i>TBCC支払総額</span><span>- - 相場推定</span></div>`;
}

function condIcon(s) { return /プラス/.test(s) ? ["p", "+"] : /マイナス/.test(s) ? ["m", "−"] : ["n", "・"]; }

async function openCar(slug) {
  const d = $("#drawer");
  d.innerHTML = `<div class="dhead"><span class="t">読み込み中…</span><button class="btn ghost" id="dclose" aria-label="閉じる">${ICON.close}</button></div><div class="dbody"><div class="skel" style="height:360px"></div><div class="skel" style="height:200px"></div></div>`;
  d.classList.add("open"); d.setAttribute("aria-hidden", "false"); $("#backdrop").hidden = false; document.body.style.overflow = "hidden";
  $("#dclose").onclick = () => closeDrawer();
  let c;
  try { c = await api(`/api/cars/${encodeURIComponent(slug)}`); } catch (e) { d.querySelector(".dbody").innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const m = c.market, imgs = c.images?.length ? c.images : [c.image];
  const gap = m.est != null ? c.total - m.est : null;
  const vtext = {
    "お手頃": `同じ年式・走行距離の相場より <b>${man(-gap)}万円（${pctS(-m.diff).replace("+", "")}）安い</b> 価格です。`,
    "相場並み": `相場とほぼ同じ水準です（差 ${pctS(m.diff)}）。`,
    "割高": `同じ条件の相場より <b>${man(gap)}万円（${pctS(m.diff)}）高い</b> 価格です。`,
    "比較不可": `比較できる掲載車が見つかりませんでした。設定の「車種ルール」を確認してください。`,
  }[m.verdict];
  d.innerHTML = `
    <div class="dhead"><span class="t">${esc(c.maker)} ${esc(c.name)}</span>
      <div style="display:flex;gap:6px"><a class="btn" href="${esc(c.url)}" target="_blank" rel="noopener">${ICON.ext}<span>TBCCで見る</span></a><button class="btn ghost" id="dclose" aria-label="閉じる">${ICON.close}</button></div></div>
    <div class="dbody">
      <div class="gallery"><div class="main"><img id="gmain" src="${esc(imgs[0])}" alt="">
        ${imgs.length > 1 ? `<button class="nav l" id="gprev" aria-label="前の写真">${ICON.left}</button><button class="nav r" id="gnext" aria-label="次の写真">${ICON.right}</button>` : ""}
        <span class="count" id="gcount">1 / ${imgs.length}</span></div>
        ${imgs.length > 1 ? `<div class="thumbs" id="thumbs">${imgs.map((u, i) => `<img src="${esc(u)}" data-i="${i}" class="${i ? "" : "on"}" loading="lazy" alt="">`).join("")}</div>` : ""}</div>

      <div class="title-row"><div><div class="maker">${esc(c.maker)}</div><h2>${esc(c.name)}</h2>
        ${c.on_sale ? "" : '<span class="badge v-割高">掲載終了</span>'}</div>
        <span class="badge v-${m.verdict}" style="font-size:14px;padding:6px 14px">${m.verdict}${m.confidence ? `<span class="conf">・信頼度${m.confidence}</span>` : ""}</span></div>

      <section class="panel">
        <div class="compare">
          <div><div class="k">TBCC 支払総額</div><div class="v num">${manU(c.total)}</div><div class="s">本体 ${man(c.base)}万円</div></div>
          <div><div class="k">相場推定（距離補正後）</div><div class="v num">${manU(m.est)}</div><div class="s">相場幅 ${man(m.p25)}〜${man(m.p75)}万円</div></div>
          <div><div class="k">差額</div><div class="v num diff ${sign(m.diff)}">${gap == null ? "—" : `${gap > 0 ? "+" : ""}${man(gap)}<small>万円</small>`}</div><div class="s">差率 <b class="diff ${sign(m.diff)}">${pctS(m.diff)}</b>／比較${m.n ?? 0}台</div></div>
        </div>
        <div class="verdict-line v-${m.verdict}">${vtext}${m.cheaper_share != null ? ` 比較車のうち、この車より安いのは${Math.round(m.cheaper_share * 100)}%。` : ""}</div>
      </section>

      <section class="panel chart"><h3>相場マップ（走行距離 × 支払総額）</h3>${scatter(c)}</section>

      <section class="panel"><h3>条件・コンディション</h3>
        <div class="specs">
          <div><div class="k">年式</div><div class="v">${c.year ?? "—"}年</div></div>
          <div><div class="k">走行距離</div><div class="v">${c.km != null ? c.km.toLocaleString() + "km" : "—"}</div></div>
          <div><div class="k">車検</div><div class="v">${esc(c.shaken || "—")}</div></div>
          <div><div class="k">記録簿・整備履歴</div><div class="v">${esc(c.kirokubo || "—")}</div></div>
          <div><div class="k">シフト／ハンドル</div><div class="v">${esc(c.shift || "—")}／${esc(c.handle || "—")}</div></div>
          <div><div class="k">排気量／燃料</div><div class="v">${c.cc ? c.cc.toLocaleString() + "cc" : "—"}／${esc(c.fuel || "—")}</div></div>
          <div><div class="k">型式</div><div class="v">${esc(c.katashiki || "—")}</div></div>
          <div><div class="k">定員</div><div class="v">${esc(c.seats || "—")}</div></div>
        </div>
        <ul class="cond" style="margin-top:14px">${(m.cond || []).map(s => { const [k, g] = condIcon(s); return `<li><span class="ci ${k}">${g}</span><span>${esc(s)}</span></li>`; }).join("")}</ul>
        ${(m.notes?.length || m.n_repaired_excluded) ? `<div class="notes">※ ${[...(m.notes || []), m.n_repaired_excluded ? `修復歴ありの${m.n_repaired_excluded}台は比較から除外` : ""].filter(Boolean).map(esc).join("／")}</div>` : ""}
      </section>

      <section class="panel"><h3>近い比較車 <a class="btn ghost" style="font-size:12px;padding:4px 8px" href="${esc(m.search_url)}" target="_blank" rel="noopener">カーセンサーの検索結果 ${ICON.ext}</a></h3>
        <div class="help" style="margin-bottom:6px">検索語「${esc(m.rule ?? c.name)}」・年式 ${m.ymin ?? "—"}〜${m.ymax ?? "—"}年／ヒット${m.hits ?? 0}台 → 同車種${m.n_model ?? 0}台 → 比較${m.n ?? 0}台</div>
        <div class="tablewrap" style="box-shadow:none"><table class="comps"><thead><tr><th>車名・グレード</th><th class="r">年式</th><th class="r">走行</th><th class="r">支払総額</th><th class="r">距離補正後</th><th>車検</th><th>保証</th><th>地域</th></tr></thead>
        <tbody>${(m.comps || []).map(x => `<tr onclick="window.open('${esc(x.url)}','_blank','noopener')"><td>${esc(x.model)} <span style="color:var(--sub)">${esc((x.grade || "").slice(0, 26))}</span></td><td class="r num">${x.year}</td><td class="r num">${kmS(x.km)}</td><td class="r num">${man(x.total)}万</td><td class="r num">${man(x.adj)}万</td><td>${esc(x.shaken)}</td><td>${esc(x.warranty)}</td><td>${esc(x.area)}</td></tr>`).join("")}</tbody></table></div>
      </section>

      <section class="panel chart"><h3>価格と相場の推移</h3>${historyChart(c.history)}
        ${c.events?.length ? `<ul class="cond" style="margin-top:12px">${c.events.map(e => `<li><span class="ci n">${ICON[e.kind] ? "•" : ""}</span><span><b>${esc(e.title.split("：")[0])}</b> ${esc(e.detail)} <span style="color:var(--sub)">${fmtDT(e.at)}</span></span></li>`).join("")}</ul>` : ""}
      </section>
    </div>`;
  $("#dclose").onclick = () => closeDrawer();
  let gi = 0;
  const show = i => { gi = (i + imgs.length) % imgs.length; $("#gmain").src = imgs[gi]; $("#gcount").textContent = `${gi + 1} / ${imgs.length}`; d.querySelectorAll("#thumbs img").forEach((t, k) => t.classList.toggle("on", k === gi)); d.querySelector(`#thumbs img[data-i="${gi}"]`)?.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" }); };
  $("#gprev") && ($("#gprev").onclick = () => show(gi - 1));
  $("#gnext") && ($("#gnext").onclick = () => show(gi + 1));
  $("#thumbs")?.addEventListener("click", e => { const t = e.target.closest("img"); if (t) show(+t.dataset.i); });
  d.scrollTop = 0;
}

// ------------------------------------------------------------ changes
async function renderChanges() {
  const v = $("#view");
  const b = S.board || await loadBoard();
  const evs = b.events;
  if (evs[0]) { store.set("seenEvent", evs[0].id); $("#changesDot").hidden = true; }
  const byDay = {};
  evs.forEach(e => (byDay[e.at.slice(0, 10)] ||= []).push(e));
  v.innerHTML = `<div class="hero"><div><h1>変化</h1><p>更新のたびに、新着・値下げ/値上げ・掲載終了・判定の変化を記録します。</p></div></div>
    ${evs.length ? `<div class="timeline">${Object.entries(byDay).map(([day, list]) => `<div class="tl-day"><h3>${day.replace(/-/g, "/")}</h3><div class="tl-list">${list.map(e => `
      <div class="tl-item" data-slug="${esc(e.slug)}"><span class="ev-ic k-${e.kind}">${ICON[e.kind] || ""}</span><div><div class="t">${esc(e.title)}</div><div class="d">${esc(e.detail)}</div></div></div>`).join("")}</div></div>`).join("")}</div>`
      : `<div class="empty"><h2>まだ変化の記録はありません</h2>2回目以降の更新から、前回との違いがここに並びます。</div>`}`;
}

// ------------------------------------------------------------ settings
async function renderSettings() {
  const v = $("#view");
  const [s, r] = await Promise.all([api("/api/settings"), api("/api/rules")]);
  let rules = r.rules.map(x => ({ ...x }));
  v.innerHTML = `<div class="hero"><div><h1>設定</h1><p>判定の基準・自動更新・車種ごとの比較ルール</p></div></div>
  <div class="settings">
    <section class="panel"><h3>判定</h3>
      <div class="row"><div><div class="k">「お手頃」「割高」の境目</div><div class="s">相場との差がこの割合を超えたら判定を付けます</div></div>
        <div style="display:flex;align-items:center;gap:12px"><input type="range" id="th" min="3" max="25" step="1" value="${Math.round(s.threshold * 100)}"><b class="num" id="thv" style="width:44px">±${Math.round(s.threshold * 100)}%</b></div></div>
    </section>
    <section class="panel"><h3>自動更新</h3>
      <div class="row"><div><div class="k">毎日自動で相場を更新</div><div class="s">このアプリが起動している間、指定時刻に1日1回取得します</div></div>
        <label class="switch"><input type="checkbox" id="auto" ${s.auto_refresh ? "checked" : ""}><span></span></label></div>
      <div class="row"><div><div class="k">更新する時刻</div></div>
        <select class="select" id="hour">${Array.from({ length: 24 }, (_, h) => `<option value="${h}" ${h === s.auto_refresh_hour ? "selected" : ""}>${h}:00</option>`).join("")}</select></div>
      <div class="row"><div><div class="k">キャッシュを使わずに取り直す</div><div class="s">通常の更新は12時間以内の取得結果を再利用します。今すぐ最新にしたいときに</div></div>
        <button class="btn" id="force">今すぐ全部取り直す</button></div>
    </section>
    <section class="panel"><h3>車種ルール <span style="display:flex;gap:6px"><button class="btn" id="addRule">${ICON.plus}<span>行を追加</span></button><button class="btn primary" id="saveRules">保存</button></span></h3>
      <div id="unmatched"></div>
      <p class="help">TBCCの車名に<b>判定キー</b>（正規表現）が当たったら、その行のルールでカーセンサーを検索します（上の行が優先）。
        <code>検索語</code>＝カーセンサーで検索する言葉、<code>年式</code>＝比較する世代の範囲（空欄なら<code>±年</code>で自動）、<code>車名</code>＝カーセンサー上の車名に一致させる正規表現、<code>除外グレード</code>＝世代違い・ボディ違いを外す正規表現。保存後、「相場を更新」で反映されます。</p>
      <div class="tablewrap" style="box-shadow:none"><table class="rules"><thead><tr><th>判定キー</th><th>検索語</th><th>年式 から</th><th>まで</th><th>±年</th><th>車名</th><th>除外グレード</th><th>当たる出品車</th><th></th></tr></thead><tbody id="rulesBody"></tbody></table></div>
    </section>
  </div>`;
  const preview = p => {
    const hits = {}; p.forEach(x => { if (x.rule != null) (hits[x.rule] ||= []).push(x.name); });
    document.querySelectorAll("#rulesBody tr").forEach((tr, i) => tr.querySelector(".hits").textContent = (hits[i] || []).join("、"));
    const un = p.filter(x => x.rule == null);
    $("#unmatched").innerHTML = un.length ? `<div class="alert" style="margin-bottom:12px"><b>ルールが無い出品車があります：</b>${un.map(x => esc(x.name)).join("、")}。行を追加すると比較の精度が上がります。</div>` : "";
  };
  const F = [["match", ""], ["kw", ""], ["ymin", "w-s"], ["ymax", "w-s"], ["year_window", "w-s"], ["model", ""], ["grade_exclude", ""]];
  const draw = () => {
    $("#rulesBody").innerHTML = rules.map((x, i) => `<tr data-i="${i}">${F.map(([k, cls]) => `<td><input class="${cls}" data-k="${k}" value="${esc(x[k] ?? "")}"></td>`).join("")}<td class="hits"></td><td><button class="btn ghost danger" data-del="${i}" aria-label="削除">${ICON.trash}</button></td></tr>`).join("");
  };
  draw(); preview(r.preview);
  let tm;
  const dry = () => { clearTimeout(tm); tm = setTimeout(async () => { try { preview((await api("/api/rules", { method: "POST", body: { rules: clean(), dry_run: true } })).preview); } catch { } }, 400); };
  const clean = () => rules.map(x => { const o = { ...x }; for (const k of Object.keys(o)) if (o[k] === "") delete o[k]; return o; });
  $("#rulesBody").addEventListener("input", e => { const tr = e.target.closest("tr"); rules[+tr.dataset.i][e.target.dataset.k] = e.target.value; dry(); });
  $("#rulesBody").addEventListener("click", e => { const b = e.target.closest("[data-del]"); if (!b) return; rules.splice(+b.dataset.del, 1); draw(); dry(); });
  $("#addRule").onclick = () => { rules.unshift({ match: "", kw: "" }); draw(); dry(); $("#rulesBody input").focus(); };
  $("#saveRules").onclick = async () => { try { const res = await api("/api/rules", { method: "POST", body: { rules: clean() } }); preview(res.preview); toast("車種ルールを保存しました。「相場を更新」で反映されます"); } catch (e) { toast(e.message); } };
  const th = $("#th");
  th.oninput = () => $("#thv").textContent = `±${th.value}%`;
  th.onchange = async () => { await api("/api/settings", { method: "POST", body: { threshold: th.value / 100 } }); S.board = null; toast(`判定の境目を±${th.value}%にしました`); };
  $("#auto").onchange = async e => { await api("/api/settings", { method: "POST", body: { auto_refresh: e.target.checked } }); toast(e.target.checked ? "自動更新をオンにしました" : "自動更新をオフにしました"); };
  $("#hour").onchange = async e => { await api("/api/settings", { method: "POST", body: { auto_refresh_hour: +e.target.value } }); toast(`毎日${e.target.value}:00に更新します`); };
  $("#force").onclick = () => startRefresh(true);
}

// ------------------------------------------------------------ refresh
async function startRefresh(force = false) {
  const r = await api("/api/refresh", { method: "POST", body: { force } });
  if (!r.started) toast("すでに更新中です");
  poll();
}
async function poll() {
  const btn = $("#refreshBtn"), bar = $("#progressBar"), wrap = $("#progress");
  const st = await api("/api/status").catch(() => null);
  if (!st) return;
  if (st.running) {
    btn.disabled = true; btn.classList.add("spinning");
    btn.querySelector("span").textContent = st.total ? `更新中 ${st.done}/${st.total}` : "更新中…";
    btn.title = st.message;
    wrap.hidden = false; bar.style.width = `${st.total ? Math.max(4, st.done / st.total * 100) : 3}%`;
    poll._wasRunning = true;
    setTimeout(poll, 1500);
  } else {
    btn.disabled = false; btn.classList.remove("spinning"); btn.querySelector("span").textContent = "相場を更新"; btn.title = "";
    wrap.hidden = true;
    if (poll._wasRunning) {
      poll._wasRunning = false;
      toast(st.error ? `更新に失敗しました：${st.error}` : "相場を更新しました");
      S.board = null; route.force = true; route();
    }
  }
}
$("#refreshBtn").addEventListener("click", () => startRefresh(false));

route();
poll();
if (!S.board) loadBoard().catch(() => { });
