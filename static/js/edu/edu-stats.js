(function () {
  'use strict';
  var C = window.Edu.Constants;
  var M = window.Edu.MathUtils;
  var Store = window.Edu.Store;
  var Speech = window.Edu.Speech;
  var Legacy = window.Edu.Legacy;

  var SUBJ_LABEL = { zh: '语文', math: '数学', en: '英语', par: '乐园' };

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  function endOfToday() { var t = new Date(); t.setHours(23, 59, 59, 999); return t.getTime(); }

  function dueWrongList() {
    var end = endOfToday();
    return (Store.state.wrong || []).filter(function (w) {
      return w.nextDue === undefined || (w.nextDue || 0) <= end;
    }).sort(function (a, b) { return (a.nextDue || 0) - (b.nextDue || 0); });
  }

  var MAP_TYPES = [
    { s:'zh', t:'poem', n:'古诗', e:'📜' }, { s:'zh', t:'zi', n:'识字', e:'🔠' }, { s:'zh', t:'stroke', n:'笔顺', e:'✍️' },
    { s:'zh', t:'pinyin', n:'声母', e:'🔤' }, { s:'zh', t:'yun', n:'韵母', e:'🔡' }, { s:'zh', t:'read', n:'拼读', e:'🗣️' },
    { s:'zh', t:'tone', n:'四声', e:'🎵' }, { s:'zh', t:'fan', n:'反义词', e:'↔️' }, { s:'zh', t:'liang', n:'量词', e:'🔢' },
    { s:'math', t:'calc', n:'口算', e:'🧮' }, { s:'math', t:'judge', n:'判断', e:'⚖️' }, { s:'math', t:'word', n:'应用题', e:'📝' },
    { s:'math', t:'order', n:'排序', e:'↕️' }, { s:'en', t:'word', n:'单词', e:'🔤' }, { s:'en', t:'dialogue', n:'对话', e:'💬' }
  ];

  function esc(s) { return String(s === undefined || s === null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'); }

  function renderStats() {
    var body = document.getElementById('eduStatsBody');
    if (!body) return;
    var kid = window.eduKids ? window.eduKids.active() : null;
    if (!kid) {
      body.innerHTML = '<div class="edu-card" style="text-align:center;"><h4>还没有孩子</h4><p class="muted">先到首页添加孩子吧～</p></div>';
      return;
    }
    var recs = Store.state.records || [];
    var total = recs.length;
    var okCount = recs.filter(function (r) { return r.ok; }).length;
    var rate = total ? Math.round(okCount * 100 / total) : 0;
    var stars = Store.state.stars || 0;
    var wrong = (Store.state.wrong || []).length;
    var dueN = dueWrongList().length;
    var badges = Object.keys(Store.state.badges || {}).filter(function (k) { return Legacy.BADGES[k]; }).length;
    var maxCombo = Store.state.maxCombo || 0;
    var u = Store.usageForToday();

    var days = [];
    var now = new Date();
    for (var d = 6; d >= 0; d--) {
      var t = new Date(now.getTime() - d * 86400000);
      var key = pad(t.getFullYear()) + '-' + pad(t.getMonth() + 1) + '-' + pad(t.getDate());
      days.push({ key: key, label: (t.getMonth() + 1) + '/' + t.getDate(), n: 0, ok: 0 });
    }
    var dayMap = {};
    days.forEach(function (x) { dayMap[x.key] = x; });
    var dateOfR = function (r) { return r && r.date ? r.date : (function (t) { var dd = new Date(t); return pad(dd.getFullYear()) + '-' + pad(dd.getMonth() + 1) + '-' + pad(dd.getDate()); })((r && r.t) || Date.now()); };
    recs.forEach(function (r) {
      var k = dateOfR(r);
      if (dayMap[k]) { dayMap[k].n++; if (r.ok) dayMap[k].ok++; }
    });
    var maxN = 1;
    days.forEach(function (x) { maxN = Math.max(maxN, x.n || 1); });
    var trend = days.map(function (x) {
      var h = x.n === 0 ? 3 : Math.max(3, Math.round(x.n / maxN * 68));
      return '<div class="bar" title="' + x.key + ' 答 ' + x.n + ' 题 ' + (x.n ? Math.round(x.ok * 100 / x.n) : 0) + '% 正确">' +
        '<span class="n">' + x.n + '</span><span class="fill" style="height:' + h + 'px;"></span><span class="d">' + x.label + '</span></div>';
    }).join('');

    var bySubj = {};
    recs.forEach(function (r) {
      (bySubj[r.subj] = bySubj[r.subj] || { n: 0, ok: 0 }).n++;
      if (r.ok) bySubj[r.subj].ok++;
    });
    // 各学科掌握率(环形进度条)
    var SUBJ_COLOR = { zh: '#ff6b4a', math: '#3b82f6', en: '#22b573', par: '#9b59b6' };
    function ring(p, c) {
      var r = 30, circ = Math.PI * 2 * r, off = circ * (1 - (Math.min(100, Math.max(0, p)) / 100));
      return '<svg viewBox="0 0 72 72" class="st-ring" aria-hidden="true">' +
        '<circle cx="36" cy="36" r="' + r + '" fill="none" stroke="var(--edu-border-2)" stroke-width="7"></circle>' +
        '<circle cx="36" cy="36" r="' + r + '" fill="none" stroke="' + c + '" stroke-width="7" stroke-linecap="round" ' +
        'stroke-dasharray="' + circ + '" stroke-dashoffset="' + off + '" transform="rotate(-90 36 36)" style="transition:stroke-dashoffset .6s ease;"></circle>' +
        '<text x="36" y="41" text-anchor="middle" font-size="15" font-weight="900" fill="' + c + '">' + p + '%</text></svg>';
    }
    var ringGrid = Object.keys(bySubj).map(function (s) {
      var v = bySubj[s];
      var p = v.n ? Math.round(v.ok * 100 / v.n) : 0;
      return '<div class="st-ring-col"><div class="st-ring-bx">' + ring(p, SUBJ_COLOR[s] || '#ff6b4a') + '</div>' +
        '<div class="st-ring-l">' + (SUBJ_LABEL[s] || s) + '</div></div>';
    }).join('') || '<p class="muted" style="grid-column:1/-1;text-align:center;">暂无做题记录</p>';
    var subjRows = Object.keys(bySubj).map(function (s) {
      var v = bySubj[s];
      var p = v.n ? Math.round(v.ok * 100 / v.n) : 0;
      return '<div class="st-subj-row"><b>' + (SUBJ_LABEL[s] || s) + '</b>' +
        '<span class="sbar"><i style="width:' + p + '%;"></i></span><span class="pct">' + p + '%</span></div>';
    }).join('') || '<p class="muted">暂无做题记录</p>';

    var dueList = dueWrongList().slice(0, 8);
    var dueCard = '<div class="edu-card"><h4>🧠 今日待复习</h4>' +
      (dueList.length
        ? dueList.map(function (w) {
            var shown = String(w.correct).split('|').join(' → ');
            return '<div class="st-wrong-row"><span class="si-emoji">📕</span><span class="st-w-t">' + esc(w.prompt) + '</span><span class="st-w-m">' + (SUBJ_LABEL[w.subj] || w.subj) + ' · ' + esc(shown) + '</span></div>';
          }).join('') + '<p class="muted" style="margin:8px 0 0;">到「错题本」即可重练</p>'
        : '<p class="muted">今天没有待复习的题目 🎉</p>') +
      '</div>';

    var adv = Store.state.adv || {};
    var mapCells = MAP_TYPES.map(function (m) {
      var rec = (adv[m.s] && adv[m.s][m.t]) || {};
      var n2 = rec.stars || 0;
      var stx = '';
      for (var si = 0; si < 3; si++) stx += si < n2 ? '<b class="on">⭐</b>' : '<b class="off">☆</b>';
      return '<div class="st-map-cell' + (rec.passed ? ' passed' : '') + '" title="' + esc(SUBJ_LABEL[m.s] || m.s) + ' · ' + esc(m.n) + '">' +
        '<span class="m-e">' + m.e + '</span><span class="m-n">' + esc(m.n) + '</span>' +
        '<span class="m-stars">' + stx + '</span>' +
        '<span class="m-pass">' + (rec.passed ? '✅' : '') + '</span></div>';
    }).join('');
    var mapCard = '<div class="edu-card"><h4>🗺️ 闯关地图</h4><div class="st-map">' + mapCells + '</div>' +
      '<p class="muted" style="margin:8px 0 0;">每关按本关最佳成绩评星：答对 5 题 ☆，7 题 ⭐⭐，全对 ⭐⭐⭐</p></div>';

    var html =
      '<div class="st-kpi">' +
        '<div class="sk"><div class="v">' + total + '</div><div class="l">累计答题</div></div>' +
        '<div class="sk"><div class="v">' + rate + '%</div><div class="l">正确率</div></div>' +
        '<div class="sk"><div class="v">⭐ ' + stars + '</div><div class="l">星星</div></div>' +
        '<div class="sk"><div class="v">' + maxCombo + '</div><div class="l">最长连对</div></div>' +
        '<div class="sk"><div class="v">' + badges + '</div><div class="l">徽章</div></div>' +
        '<div class="sk"><div class="v">' + wrong + '</div><div class="l">待巩固错题</div></div>' +
        '<div class="sk"><div class="v">' + dueN + '</div><div class="l">今日待复习</div></div>' +
      '</div>' +
      '<div class="edu-card"><h4>📈 最近 7 天答题</h4><div class="st-trend">' + trend + '</div>' +
        '<p class="muted" style="margin:6px 0 0;">今日已用 ' + (Store.minsUsed()) + ' 分钟 · ' + (u.n || 0) + ' 题</p></div>' +
      '<div class="edu-card"><h4>🎯 分科掌握率</h4><div class="st-rings">' + ringGrid + '</div>' +
        '<div class="st-subj-detail">' + subjRows + '</div></div>' +
      mapCard +
      dueCard +
      '</div>';
    body.innerHTML = html;
    anim(body);
  }

  function anim(el) {
    if (!el) return;
    el.classList.remove('page-enter');
    void el.offsetWidth;
    el.classList.add('page-enter');
  }

  window.renderStats = renderStats;
  window.Edu.Stats = {
    renderStats: renderStats,
    SUBJ_LABEL: SUBJ_LABEL,
    dueWrongList: dueWrongList,
    MAP_TYPES: MAP_TYPES
  };
})();
