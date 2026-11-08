/* AgriSense Lab front end: live polling, Studio blocks, charts, picture sign-in. No libraries. */
(function () {
  "use strict";
  var CSRF = (document.querySelector('meta[name="csrf"]') || {}).content || "";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  function getJSON(url) {
    return fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } }).then(function (r) { return r.json(); });
  }
  function postJSON(url, body) {
    return fetch(url, { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF": CSRF, Accept: "application/json" },
      body: JSON.stringify(body) }).then(function (r) { return r.json(); });
  }
  function toast(msg) {
    var t = document.createElement("div"); t.className = "toast"; t.setAttribute("role", "status"); t.textContent = msg;
    document.body.appendChild(t); setTimeout(function () { t.remove(); }, 3800);
  }
  function fmt(v, unit) {
    if (v === null || v === undefined || v === "") return "—";
    var n = Number(v);
    var s = isNaN(n) ? String(v) : (Math.abs(n) >= 100 ? Math.round(n).toString() : (Math.round(n * 10) / 10).toString());
    return s + (unit && unit !== "ON/OFF" && unit !== "OK/LOW" && unit !== "HIGH/LOW" ? " " + unit : "");
  }
  function ago(ts) {
    if (!ts) return "no data yet";
    var s = Math.max(0, Math.round((Date.now() - Date.parse(ts)) / 1000));
    if (s < 60) return s + " s ago"; if (s < 3600) return Math.round(s / 60) + " min ago";
    if (s < 86400) return Math.round(s / 3600) + " h ago"; return Math.round(s / 86400) + " d ago";
  }
  function every(ms, fn) { fn(); var id = setInterval(function () { if (!document.hidden) fn(); }, ms); return id; }

  /* ---------- SVG line chart ---------- */
  var NS = "http://www.w3.org/2000/svg";
  function el(tag, attrs) { var e = document.createElementNS(NS, tag); for (var k in attrs) e.setAttribute(k, attrs[k]); return e; }
  function lineChart(box, pts, opt) {
    opt = opt || {};
    box.innerHTML = "";
    var W = 600, H = opt.height || 150, P = { l: 38, r: 10, t: 10, b: 22 };
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": opt.label || "chart", preserveAspectRatio: "none" });
    var data = pts.filter(function (p) { return p.v !== null && p.v !== undefined && !isNaN(p.v); });
    if (!data.length) {
      var tx = el("text", { x: W / 2, y: H / 2, "text-anchor": "middle", fill: "var(--muted)", "font-size": 14 }); tx.textContent = "No readings in this time range yet";
      svg.appendChild(tx); box.appendChild(svg); return;
    }
    var xs = data.map(function (p) { return Date.parse(p.t); }), ys = data.map(function (p) { return Number(p.v); });
    var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs); if (x1 === x0) x1 = x0 + 1;
    var y0 = opt.min !== undefined ? opt.min : Math.min.apply(null, ys), y1 = opt.max !== undefined ? opt.max : Math.max.apply(null, ys);
    if (y1 === y0) { y0 -= 1; y1 += 1; } var pad = (y1 - y0) * 0.08; if (opt.min === undefined) y0 = (y0 >= 0 && y0 - pad < 0) ? 0 : y0 - pad; if (opt.max === undefined) y1 += pad;
    var X = function (x) { return P.l + (x - x0) / (x1 - x0) * (W - P.l - P.r); };
    var Y = function (y) { return H - P.b - (y - y0) / (y1 - y0) * (H - P.t - P.b); };
    for (var i = 0; i <= 3; i++) {
      var gy = y0 + (y1 - y0) * i / 3, yy = Y(gy);
      svg.appendChild(el("line", { x1: P.l, x2: W - P.r, y1: yy, y2: yy, stroke: "var(--line-2)", "stroke-width": 1 }));
      var lab = el("text", { x: P.l - 6, y: yy + 4, "text-anchor": "end", fill: "var(--faint)", "font-size": 11 }); lab.textContent = Math.round(gy * 10) / 10;
      svg.appendChild(lab);
    }
    [x0, x1].forEach(function (xv, j) {
      var d = new Date(xv), t = el("text", { x: j ? W - P.r : P.l, y: H - 5, "text-anchor": j ? "end" : "start", fill: "var(--faint)", "font-size": 11 });
      t.textContent = d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); svg.appendChild(t);
    });
    if (opt.band) {
      var b = opt.band; svg.appendChild(el("rect", { x: P.l, width: W - P.l - P.r, y: Y(b[1]), height: Math.max(0, Y(b[0]) - Y(b[1])), fill: "var(--brand-soft)", opacity: .7 }));
    }
    var d = data.map(function (p, k) { return (k ? "L" : "M") + X(xs[k]).toFixed(1) + " " + Y(ys[k]).toFixed(1); }).join(" ");
    svg.appendChild(el("path", { d: d, fill: "none", stroke: opt.color || "var(--brand)", "stroke-width": 2.2, "vector-effect": "non-scaling-stroke", "stroke-linejoin": "round" }));
    var last = data.length - 1;
    svg.appendChild(el("circle", { cx: X(xs[last]), cy: Y(ys[last]), r: 4, fill: opt.color || "var(--brand)" }));
    box.appendChild(svg);
  }
  window.AgriChart = lineChart;

  $$("[data-series]").forEach(function (box) {
    var load = function () {
      getJSON(box.dataset.series).then(function (j) {
        if (!j.ok) return;
        lineChart(box, j.points, { label: box.dataset.label, min: box.dataset.min ? +box.dataset.min : undefined,
          max: box.dataset.max ? +box.dataset.max : undefined, band: box.dataset.band ? box.dataset.band.split(",").map(Number) : null });
      });
    };
    every(+(box.dataset.every || 30000), load);
  });

  /* ---------- live class bench ---------- */
  var live = $("[data-live-class]");
  if (live) {
    every(3000, function () {
      getJSON("/api/class/" + live.dataset.liveClass + "/live").then(function (j) {
        if (!j.ok) return;
        var running = {}; (j.running || []).forEach(function (r) { running[r.tray_id] = r; });
        j.trays.forEach(function (t) {
          var tile = $('[data-tray="' + t.id + '"]'); if (!tile) return;
          var set = function (k, v) { var n = $('[data-k="' + k + '"]', tile); if (n) n.textContent = v; };
          set("moisture", t.moisture === null || t.moisture === undefined ? "—" : (Math.round(t.moisture * 10) / 10));
          set("temp", fmt(t.temp, "°C")); set("ec", t.ec === null || t.ec === undefined ? "dry" : fmt(t.ec, ""));
          set("ph", fmt(t.ph, "")); set("at", t.simulated ? "simulated · day " + t.sim_day + " " + t.sim_clock : ago(t.at));
          var fill = $(".soilbar-fill", tile);
          if (fill && t.moisture !== null && t.moisture !== undefined) fill.style.width = Math.min(100, t.moisture / 45 * 100) + "%";
          var a = t.advice, flag = $('[data-k="flag"]', tile), labels = { wilting: "Wilting risk", water: "Water now", wet: "Too wet", ok: "OK" };
          if (flag) {
            if (t.stale && !t.simulated) { flag.textContent = "No recent data"; flag.className = "pill bad"; }
            else if (a) { flag.textContent = labels[a.status]; flag.className = "pill " + a.tone; }
          }
          set("advice", a ? a.text : "");
          tile.classList.toggle("running", !!running[t.id]);
        });
        var pc = $("[data-pending-count]"); if (pc) pc.textContent = j.pending;
      });
    });
  }

  /* ---------- IoT Studio dashboard ---------- */
  var dash = $("[data-studio-team]");
  if (dash) {
    var team = dash.dataset.studioTeam;
    var blocks = $$(".block[data-feed]", dash);
    var feeds = blocks.map(function (b) { return b.dataset.feed; }).filter(function (v, i, a) { return a.indexOf(v) === i; });
    var lockNote = $("[data-lock-note]");
    var state = {};
    var paint = function (b) {
      var s = state[b.dataset.feed] || {}, v = s.value, type = b.dataset.type;
      var at = $(".block-at", b); if (at) at.textContent = (s.simulated ? "simulated · " : "") + ago(s.at);
      if (type === "toggle") {
        var sw = $(".switch", b), on = String(v).toUpperCase() === "ON";
        if (!sw.dataset.busy) sw.setAttribute("aria-checked", on ? "true" : "false");
        $(".toggle-state", b).textContent = v ? String(v).toUpperCase() : "OFF";
      } else if (type === "slider") {
        var r = $("input[type=range]", b); if (document.activeElement !== r && v !== null && v !== undefined) r.value = v;
        $(".big", b).textContent = fmt(v, s.unit);
      } else if (type === "gauge") {
        var mn = +b.dataset.min || 0, mx = +b.dataset.max || 100, n = Math.max(mn, Math.min(mx, Number(v)));
        var frac = isNaN(n) ? 0 : (n - mn) / (mx - mn), arc = $(".gauge-arc", b);
        if (arc) arc.setAttribute("stroke-dasharray", (frac * 220).toFixed(1) + " 300");
        $(".big", b).textContent = fmt(v, s.unit);
      } else if (type === "value") {
        $(".big", b).textContent = fmt(v, s.unit);
      } else if (type === "indicator") {
        var want = (b.dataset.on || "ON").toUpperCase(), isOn = v !== null && v !== undefined && String(v).toUpperCase() === want;
        var lamp = $(".lamp", b); lamp.classList.toggle("on", isOn); lamp.classList.toggle("alarm", v !== null && v !== undefined && !isOn);
        $(".big", b).textContent = v === null || v === undefined ? "—" : String(v);
      } else if (type === "soilwater") {
        var bar = $(".soilbar", b), n = Number(v), st = $(".soil-status", b);
        $(".big", b).textContent = fmt(v, s.unit);
        if (v !== null && v !== undefined && !isNaN(n)) {
          $(".soilbar-fill", b).style.width = Math.min(100, n / 45 * 100) + "%";
          var wp = +bar.dataset.wp, rf = +bar.dataset.refill, fc = +bar.dataset.fc;
          st.textContent = n < wp ? "Wilting risk: water now" : n <= rf ? "At the refill point: water now" : n > fc + 1 ? "Too wet: let it drain" : "Healthy range";
          st.style.color = n <= rf ? "var(--warn-ink)" : n > fc + 1 ? "var(--info)" : "var(--brand-ink)";
        }
      } else if (type === "stream") {
        var list = $(".stream", b);
        if (v !== null && v !== undefined && list.dataset.last !== s.at) {
          list.dataset.last = s.at;
          var row = document.createElement("div"); row.innerHTML = "<span></span><span></span>";
          row.firstChild.textContent = new Date(s.at).toLocaleTimeString(); row.lastChild.textContent = fmt(v, s.unit);
          list.insertBefore(row, list.firstChild); while (list.children.length > 30) list.lastChild.remove();
        }
      }
    };
    var poll = function () {
      var q = feeds.map(function (f) { return "feed=" + encodeURIComponent(f); }).join("&");
      getJSON("/api/studio/" + team + "/state?" + q).then(function (j) {
        if (!j.ok) return;
        state = j.feeds; blocks.forEach(paint);
        var locked = !j.unlocked && !j.may_switch;
        $$(".switch, input[type=range]", dash).forEach(function (c) { c.disabled = !j.may_switch && !j.unlocked; });
        if (lockNote) lockNote.hidden = j.unlocked || j.may_switch;
        void locked;
      });
    };
    every(2000, poll);
    var send = function (feed, value, ctl) {
      return postJSON("/api/studio/" + team + "/set", { feed: feed, value: value }).then(function (j) {
        if (!j.ok) { toast(j.error || "That didn't work."); }
        else { state[feed] = { value: j.value, at: new Date().toISOString().slice(0, 19) + "Z", unit: (state[feed] || {}).unit }; }
        if (ctl) delete ctl.dataset.busy;
        blocks.forEach(paint);
      }).catch(function () { if (ctl) delete ctl.dataset.busy; toast("No connection. Try again."); });
    };
    $$(".block[data-type=toggle] .switch", dash).forEach(function (sw) {
      sw.addEventListener("click", function () {
        var on = sw.getAttribute("aria-checked") !== "true";
        sw.dataset.busy = "1"; sw.setAttribute("aria-checked", on ? "true" : "false");
        send(sw.closest(".block").dataset.feed, on ? "ON" : "OFF", sw);
      });
    });
    $$(".block[data-type=slider] input[type=range]", dash).forEach(function (r) {
      r.addEventListener("change", function () { send(r.closest(".block").dataset.feed, r.value); });
    });
    $$(".block[data-type=chart]", dash).forEach(function (b) {
      var box = $(".chart", b);
      every(10000, function () {
        getJSON("/api/studio/" + team + "/series?feed=" + encodeURIComponent(b.dataset.feed) + "&hours=" + (b.dataset.hours || 1))
          .then(function (j) { if (j.ok) lineChart(box, j.points, { label: b.dataset.feed }); });
      });
    });
  }

  /* ---------- picture password ---------- */
  var picForm = $("[data-pic-form]");
  if (picForm) {
    var chosen = [], hidden = $("input[name=pics]", picForm), go = $("button[type=submit]", picForm), out = $("[data-chosen]", picForm);
    $$(".pic", picForm).forEach(function (p) {
      p.addEventListener("click", function () {
        var n = p.dataset.pic, i = chosen.indexOf(n);
        if (i >= 0) chosen.splice(i, 1); else if (chosen.length < 2) chosen.push(n);
        $$(".pic", picForm).forEach(function (q) { q.setAttribute("aria-pressed", chosen.indexOf(q.dataset.pic) >= 0 ? "true" : "false"); });
        hidden.value = chosen.join(","); go.disabled = chosen.length !== 2;
        out.textContent = chosen.length ? chosen.join(" + ") : "Tap your two pictures";
      });
    });
  }

  /* ---------- small helpers ---------- */
  $$("form[data-confirm]").forEach(function (f) {
    f.addEventListener("submit", function (e) { if (!window.confirm(f.dataset.confirm)) e.preventDefault(); });
  });
  $$("[data-copy]").forEach(function (b) {
    b.addEventListener("click", function () {
      var t = document.getElementById(b.dataset.copy); if (!t) return;
      navigator.clipboard.writeText(t.textContent.trim()).then(function () { toast("Copied"); });
    });
  });
  $$("[data-print]").forEach(function (b) { b.addEventListener("click", function () { window.print(); }); });
  $$("[data-add-row]").forEach(function (b) {
    b.addEventListener("click", function () {
      var body = document.getElementById(b.dataset.addRow), tpl = body.querySelector("tr");
      var row = tpl.cloneNode(true); $$("input", row).forEach(function (i) { i.value = ""; }); body.appendChild(row);
    });
  });
  $$("select[data-autosubmit]").forEach(function (s) { s.addEventListener("change", function () { s.form.submit(); }); });
  $$("[data-show-when]").forEach(function (box) {
    var parts = box.dataset.showWhen.split("="), ctl = document.querySelector('[name="' + parts[0] + '"]');
    if (!ctl) return;
    var upd = function () { box.hidden = parts[1].split("|").indexOf(ctl.value) < 0; };
    ctl.addEventListener("change", upd); upd();
  });
})();
