(function () {
  'use strict';
  var C = window.Edu.Constants;
  var Store = window.Edu.Store;
  var M = window.Edu.MathUtils;
  var Speech = window.Edu.Speech;
  var Legacy = window.Edu.Legacy;

  // =====================================================================
  // 家长端看板: 学习报告可视化(掌握率环/雷达/饼图/柱状/星星曲线),
  // 每条记录可回放错题, 一键导出PDF报告. 覆写「报告」Tab 的渲染入口.
  // 参考 萌芽学前家长看板 · 幼小衔接工作台成长报告 · 芽芽星三端协同.
  // =====================================================================

  var SUBJ_LABEL = { zh: '语文', math: '数学', en: '英语', go: '围棋', par: '乐园' };
  var SUBJ_COLOR = { zh: '#ff6b4a', math: '#3b82f6', en: '#22b573', par: '#9b59b6' };
  var PALETTE = ['#ff6b4a', '#ffb64a', '#22b573', '#3b82f6', '#9b59b6', '#e879f9', '#14b8a6', '#f43f5e'];
  var MAP_TYPES = (window.Edu.Stats && window.Edu.Stats.MAP_TYPES) || [
    { s:'zh', t:'poem', n:'古诗', e:'📜' }, { s:'zh', t:'zi', n:'识字', e:'🔠' }, { s:'zh', t:'stroke', n:'笔顺', e:'✍️' },
    { s:'zh', t:'pinyin', n:'声母', e:'🔤' }, { s:'zh', t:'yun', n:'韵母', e:'🔡' }, { s:'zh', t:'read', n:'拼读', e:'🗣️' },
    { s:'zh', t:'tone', n:'四声', e:'🎵' }, { s:'zh', t:'fan', n:'反义词', e:'↔️' }, { s:'zh', t:'liang', n:'量词', e:'🔢' },
    { s:'math', t:'calc', n:'口算', e:'🧮' }, { s:'math', t:'judge', n:'判断', e:'⚖️' }, { s:'math', t:'word', n:'应用题', e:'📝' },
    { s:'math', t:'order', n:'排序', e:'↕️' }, { s:'en', t:'word', n:'单词', e:'🔤' }, { s:'en', t:'dialogue', n:'对话', e:'💬' }
  ];

  var dashRecs = [];

  function esc(s) { return String(s === undefined || s === null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'); }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function keyOf(d) { return pad(d.getFullYear()) + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function dateOf(r) { return (r && r.date) ? r.date : keyOf(new Date((r && r.t) || Date.now())); }

  function labelOf(subj, type) {
    if (subj === 'en' && type === 'word') return '单词';
    if (subj === 'math' && type === 'word') return '应用题';
    var m = { zi: '识字', pinyin: '拼音', yun: '韵母', read: '拼读', tone: '四声', ciyu: '词语', poem: '古诗', stroke: '笔顺', trace: '描红', fan: '反义词', liang: '量词',
      calc: '口算', judge: '判断', order: '排序', wrong: '错题本', daily: '每日挑战', dialogue: '对话', match: '配对',
      color: '认颜色', shape: '认形状', number: '数数字', animal: '认动物', fruit: '认水果' };
    return m[type] || type || '练习';
  }

  function endOfToday() { var t = new Date(); t.setHours(23, 59, 59, 999); return t.getTime(); }
  function dueWrongList() {
    var end = endOfToday();
    return (Store.state.wrong || []).filter(function (w) {
      return w.nextDue === undefined || (w.nextDue || 0) <= end;
    }).sort(function (a, b) { return (a.nextDue || 0) - (b.nextDue || 0); });
  }

  function lastDays(n) {
    var days = [], now = new Date();
    for (var d = n - 1; d >= 0; d--) {
      var t = new Date(now.getTime() - d * 86400000);
      var k = keyOf(t);
      days.push({ key: k, label: (t.getMonth() + 1) + '/' + t.getDate(), n: 0, ok: 0, secs: 0, stars: 0 });
    }
    var map = {};
    days.forEach(function (x) { map[x.key] = x; });
    (Store.state.records || []).forEach(function (r) {
      var k = dateOf(r);
      if (map[k]) { map[k].n++; if (r.ok) map[k].ok++; }
    });
    var dsec = Store.state.dailySecs || {};
    var slog = Store.state.starLog || [];
    slog.forEach(function (s) { if (s && map[s.date]) map[s.date].stars += (s.s || s.delta || 0); });
    Object.keys(dsec).forEach(function (k) { if (map[k]) map[k].secs += (dsec[k] || 0); });
    return days;
  }

  // ---- 图表(纯 SVG, 无外部依赖) ----

  function barTrendHtml(days) {
    var maxN = 1;
    days.forEach(function (x) { maxN = Math.max(maxN, x.n || 1); });
    return days.map(function (x) {
      var h = x.n === 0 ? 3 : Math.max(3, Math.round(x.n / maxN * 68));
      return '<div class="bar" title="' + x.key + ' 答 ' + x.n + ' 题 ' + (x.n ? Math.round(x.ok * 100 / x.n) : 0) + '% 正确">' +
        '<span class="n">' + x.n + '</span><span class="fill" style="height:' + h + 'px;"></span><span class="d">' + x.label + '</span></div>';
    }).join('');
  }

  function ring(p, c) {
    var r = 30, circ = Math.PI * 2 * r, off = circ * (1 - (Math.min(100, Math.max(0, p)) / 100));
    return '<svg viewBox="0 0 72 72" class="st-ring" aria-hidden="true">' +
      '<circle cx="36" cy="36" r="' + r + '" fill="none" stroke="var(--edu-border-2)" stroke-width="7"></circle>' +
      '<circle cx="36" cy="36" r="' + r + '" fill="none" stroke="' + c + '" stroke-width="7" stroke-linecap="round" ' +
      'stroke-dasharray="' + circ + '" stroke-dashoffset="' + off + '" transform="rotate(-90 36 36)" style="transition:stroke-dashoffset .6s ease;"></circle>' +
      '<text x="36" y="41" text-anchor="middle" font-size="15" font-weight="900" fill="' + c + '">' + p + '%</text></svg>';
  }

  function radarSvg(axes) {
    var n = axes.length, W = 190, H = 190, cx = W / 2, cy = H / 2, R = 62;
    function pt(i, r) { var a = -Math.PI / 2 + i * 2 * Math.PI / n; return [cx + r * Math.cos(a), cy + r * Math.sin(a)]; }
    var ringPoly = function (f) { return axes.map(function (_, i) { return pt(i, R * f).join(','); }).join(' '); };
    var grid = [0.34, 0.67, 1].map(function (f) {
      return '<polygon class="radar-grid" points="' + ringPoly(f) + '"></polygon>';
    }).join('');
    var spokes = axes.map(function (_, i) {
      var p = pt(i, R);
      return '<line class="radar-spoke" x1="' + cx + '" y1="' + cy + '" x2="' + p[0] + '" y2="' + p[1] + '"></line>';
    }).join('');
    var vals = axes.map(function (a) { return Math.min(100, Math.max(0, a.value || 0)) / 100; });
    var poly = axes.map(function (_, i) { return pt(i, R * vals[i]).join(','); }).join(' ');
    var dots = axes.map(function (_, i) {
      var p = pt(i, R * vals[i]);
      return '<circle class="radar-dot" cx="' + p[0] + '" cy="' + p[1] + '" r="3"></circle>';
    }).join('');
    var labels = axes.map(function (a, i) {
      var p = pt(i, R + 17);
      return '<text class="radar-label" x="' + p[0] + '" y="' + p[1] + '" text-anchor="middle">' + esc(a.label) + ' ' + (a.value || 0) + '%</text>';
    }).join('');
    return '<svg class="dash-radar" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="技能雷达图">' +
      grid + spokes + '<polygon class="radar-area" points="' + poly + '"></polygon>' + dots + labels + '</svg>';
  }

  function donutSvg(segs) {
    var total = 0, i;
    for (i = 0; i < segs.length; i++) total += segs[i].value;
    var size = 132, r = 52, w = 26, cx = size / 2, cy = size / 2;
    var circ = Math.PI * 2 * r, acc = 0;
    var parts = segs.map(function (s, idx) {
      var frac = total ? (s.value / total) : 0;
      var dash = Math.max(0.6, frac * circ - 1.5) + ' ' + (circ - Math.max(0.6, frac * circ - 1.5));
      var off = -acc * circ;
      acc += frac;
      return '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="none" stroke="' + (s.color || PALETTE[idx % PALETTE.length]) + '" ' +
        'stroke-width="' + w + '" stroke-dasharray="' + dash + '" stroke-dashoffset="' + off + '" transform="rotate(-90 ' + cx + ' ' + cy + ')"></circle>';
    }).join('');
    return '<svg class="dash-donut" viewBox="0 0 ' + size + ' ' + size + '" role="img" aria-label="薄弱知识点分布饼图">' +
      parts + '<text x="' + cx + '" y="' + (cy + 6) + '" class="donut-total" text-anchor="middle">' + total + '</text></svg>';
  }

  function lineSvg(points) {
    var W = 330, H = 96, padL = 34, padB = 22, padT = 10;
    var max = 1;
    points.forEach(function (p) { max = Math.max(max, p.v || 0); });
    var n = Math.max(2, points.length);
    var innerW = W - padL - 10, innerH = H - padB - padT;
    function pt(i) {
      var x = padL + (n === 1 ? innerW / 2 : (i / (n - 1)) * innerW);
      var y = H - padB - ((points[i].v || 0) / max) * innerH;
      return [Math.round(x), Math.round(y)];
    }
    var line = points.map(function (_, i) { return pt(i).join(','); }).join(' ');
    var dots = points.map(function (p, i) {
      var c = pt(i);
      return '<circle class="line-dot" cx="' + c[0] + '" cy="' + c[1] + '" r="3"><title>' + esc(p.label) + ' 获得 ' + p.v + ' 星</title></circle>';
    }).join('');
    var labels = points.map(function (p, i) {
      if (i % 2 !== 0 && i !== n - 1) return '';
      var c = pt(i);
      return '<text class="line-label" x="' + c[0] + '" y="' + (H - 4) + '" text-anchor="middle">' + esc(p.label) + '</text>';
    }).join('');
    return '<svg class="dash-line" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="星星获取曲线">' +
      '<polyline class="line-path" points="' + line + '"></polyline>' + dots + labels + '</svg>';
  }

  function minutesBars(days) {
    var maxM = 1;
    days.forEach(function (x) { maxM = Math.max(maxM, Math.ceil((x.secs || 0) / 60)); });
    return days.map(function (x) {
      var m = Math.round((x.secs || 0) / 60 * 10) / 10;
      var h = m <= 0 ? 3 : Math.max(4, Math.round((m / (maxM || 1)) * 64));
      return '<div class="bar secs" title="' + x.key + ' 学习 ' + m + ' 分钟">' +
        '<span class="n">' + m + '</span><span class="fill" style="height:' + h + 'px;"></span><span class="d">' + x.label + '</span></div>';
    }).join('');
  }

  // ---- 数据聚合 ----

  function subjMastery() {
    var bySubj = {};
    (Store.state.records || []).forEach(function (r) {
      (bySubj[r.subj] = bySubj[r.subj] || { n: 0, ok: 0 }).n++;
      if (r.ok) bySubj[r.subj].ok++;
    });
    return Object.keys(bySubj).map(function (s) {
      var v = bySubj[s];
      return { subj: s, n: v.n, ok: v.ok, p: v.n ? Math.round(v.ok * 100 / v.n) : 0 };
    });
  }

  function radarAxes() {
    var defs = [
      { label: '识字', test: function (r) { return r.subj === 'zh' && ['zi', 'pinyin', 'yun', 'read', 'tone'].indexOf(r.type) >= 0; } },
      { label: '古诗文', test: function (r) { return r.subj === 'zh' && ['poem', 'ciyu', 'stroke', 'trace'].indexOf(r.type) >= 0; } },
      { label: '口算', test: function (r) { return r.subj === 'math' && r.type === 'calc'; } },
      { label: '数学应用', test: function (r) { return r.subj === 'math' && ['judge', 'word', 'order'].indexOf(r.type) >= 0; } },
      { label: '英语', test: function (r) { return r.subj === 'en'; } }
    ];
    var recs = Store.state.records || [];
    return defs.map(function (a) {
      var hit = recs.filter(a.test);
      var ok = hit.filter(function (r) { return r.ok; }).length;
      return { label: a.label, value: hit.length ? Math.round(ok * 100 / hit.length) : 0 };
    });
  }

  function weakDist() {
    var map = {};
    (Store.state.wrong || []).forEach(function (w) {
      if (!w || !w.subj) return;
      var key = w.subj + ':' + w.type;
      map[key] = map[key] || { subj: w.subj, type: w.type, n: 0 };
      map[key].n++;
    });
    var arr = Object.keys(map).map(function (k) { return map[k]; }).sort(function (a, b) { return b.n - a.n; });
    var top = arr.slice(0, 5);
    var other = arr.slice(5).reduce(function (s, x) { return s + x.n; }, 0);
    if (other > 0) top.push({ subj: '', type: '', n: other, other: true });
    return top.map(function (x, i) {
      return { label: x.other ? '其他' : (SUBJ_LABEL[x.subj] || x.subj) + '·' + labelOf(x.subj, x.type), value: x.n, color: PALETTE[i % PALETTE.length] };
    });
  }

  // ---- 详细答题记录(含错题回放) ----

  function recordsTable(limit) {
    dashRecs = (Store.state.records || []).slice(0, limit || 12);
    if (!dashRecs.length) return '<p class="muted" style="grid-column:1/-1;">还没有答题记录，先去闯一关吧～</p>';
    return dashRecs.map(function (r, i) {
      return '<div class="dash-rec' + (r.ok ? ' ok' : ' no') + '">' +
        '<span class="dr-date">' + (dateOf(r).slice(5)) + '</span>' +
        '<span class="dr-tag">' + (SUBJ_LABEL[r.subj] || r.subj) + '·' + labelOf(r.subj, r.type) + '</span>' +
        '<span class="dr-q" title="' + esc(r.prompt) + '">' + esc(String(r.prompt).slice(0, 12)) + '</span>' +
        '<span class="dr-st">' + (r.ok ? '✅' : '❌') + '</span>' +
        '<button type="button" class="dr-replay" onclick="window.Edu.Dash.openReplay(' + i + ')" aria-label="回放此题">🔁 回放</button>' +
        '</div>';
    }).join('') + '<p class="muted" style="grid-column:1/-1;margin-top:4px;">点「回放」可查看孩子当时的作答与正确答案</p>';
  }

  // ---- 回放 ----

  window.Edu.Dash = window.Edu.Dash || {};

  window.Edu.Dash.openReplay = function (idx) {
    var r = dashRecs[idx];
    if (!r) return;
    var body = document.getElementById('detailBody');
    var title = document.getElementById('detailTitle');
    var sub = document.getElementById('detailSub');
    if (!body) return;
    if (title) title.textContent = '✍️ 答题记录回放';
    if (sub) sub.textContent = (SUBJ_LABEL[r.subj] || r.subj) + ' · ' + labelOf(r.subj, r.type) + ' · ' + dateOf(r);
    var got = String(r.got === undefined || r.got === null ? '' : r.got);
    var correct = String(r.correct === undefined || r.correct === null ? '' : r.correct);
    body.innerHTML =
      '<div class="replay-card">' +
        '<div class="rp-prompt"><span class="rp-l">题目</span><div class="rp-v">' + esc(r.prompt) + '</div></div>' +
        '<div class="rp-row ' + (r.ok ? 'rp-ok' : 'rp-no') + '"><span class="rp-l">孩子作答</span><span class="rp-v">' + (got === '' ? '<em>未作答</em>' : esc(got)) + '</span>' +
          (r.ok ? ' <b class="rp-badge">✓</b>' : ' <b class="rp-badge">✗</b>') + '</div>' +
        '<div class="rp-row rp-c"><span class="rp-l">正确答案</span><span class="rp-v">' + esc(correct) + '</span></div>' +
      '</div>';
    var mask = document.getElementById('eduMaskDetail');
    if (mask) mask.style.display = 'flex';
  };

  // ---- 导出PDF报告(打印友好) ----

  window.Edu.Dash.buildPdfHtml = function () {
    var kid = window.eduKids ? window.eduKids.active() : null;
    var name = kid ? (kid.name || '宝贝') : '宝贝';
    var recs = Store.state.records || [];
    var total = recs.length;
    var ok = recs.filter(function (r) { return r.ok; }).length;
    var rate = total ? Math.round(ok * 100 / total) : 0;
    var stars = Store.state.stars || 0;
    var streak = (function () {
      var daySet = {};
      recs.forEach(function (r) { if (dateOf(r)) daySet[dateOf(r)] = 1; });
      var d = new Date(), s = 0;
      if (!daySet[keyOf(d)]) d = new Date(d.getTime() - 86400000);
      while (daySet[keyOf(d)]) { s++; d = new Date(d.getTime() - 86400000); }
      return s;
    })();
    var todaySecs = (Store.state.dailySecs || {})[keyOf(new Date())] || 0;
    var mins = Math.round(todaySecs / 60);
    var master = subjMastery();
    var weak = weakDist();
    var now = new Date();
    var rows = recs.slice(0, 30).map(function (r) {
      return '<tr><td>' + esc(dateOf(r)) + '</td><td>' + esc(SUBJ_LABEL[r.subj] || r.subj) + '</td><td>' + esc(labelOf(r.subj, r.type)) + '</td>' +
        '<td>' + esc(String(r.prompt).slice(0, 18)) + '</td><td>' + (r.ok ? '✓' : '✗') + '</td></tr>';
    }).join('') || '<tr><td colspan="5">暂无答题记录</td></tr>';
    return '<div class="pdf-report">' +
      '<div class="pr-head"><h1>📊 学习报告</h1>' +
      '<div class="pr-sub">' + esc(name) + ' · 统计至 ' + now.getFullYear() + '年' + (now.getMonth() + 1) + '月' + now.getDate() + '日（数据仅存本机）</div></div>' +
      '<div class="pr-kpis">' +
        '<span><b>' + total + '</b>累计题数</span><span><b>' + rate + '%</b>总正确率</span>' +
        '<span><b>⭐' + stars + '</b>星星</span><span><b>' + streak + '天</b>连续打卡</span><span><b>' + mins + '分</b>今日用时</span>' +
      '</div>' +
      '<h2>分科正确率</h2><table class="pr-table"><thead><tr><th>学科</th><th>题数</th><th>答对</th><th>正确率</th></tr></thead><tbody>' +
        (master.map(function (s) { return '<tr><td>' + esc(SUBJ_LABEL[s.subj] || s.subj) + '</td><td>' + s.n + '</td><td>' + s.ok + '</td><td>' + s.p + '%</td></tr>'; }).join('') || '<tr><td colspan="4">暂无</td></tr>') +
      '</tbody></table>' +
      '<h2>薄弱知识点</h2><ul class="pr-weak">' + (weak.map(function (w) { return '<li>' + esc(w.label) + '：' + w.value + ' 次</li>'; }).join('') || '<li>暂无错题记录</li>') + '</ul>' +
      '<h2>最近答题明细</h2><table class="pr-table"><thead><tr><th>日期</th><th>学科</th><th>题型</th><th>题目</th><th>结果</th></tr></thead><tbody>' + rows + '</tbody></table>' +
      '</div>';
  };

  window.Edu.Dash.exportPdfReport = function () {
    var wrap = document.getElementById('pdfReportWrap');
    if (!wrap && typeof document !== 'undefined' && document.createElement) {
      try {
        wrap = document.createElement('div');
        wrap.id = 'pdfReportWrap';
        document.body.appendChild(wrap);
      } catch (e) {}
    }
    if (!wrap) { if (Speech && Speech.toast) Speech.toast('无法导出PDF'); return; }
    wrap.innerHTML = window.Edu.Dash.buildPdfHtml();
    wrap.classList.add('show-print');
    if (typeof window.print === 'function') { window.print(); }
    else if (Speech && Speech.toast) Speech.toast('请在浏览器中选择「打印」保存为PDF');
  };

  window.Edu.Dash.switchKid = function (id) {
    if (!window.eduKids) return;
    Store.saveState(); Store.saveWb();
    window.eduKids.setActive(id);
    Store.loadAllState();
    renderDash();
    if (typeof window.renderKidBar === 'function') window.renderKidBar();
  };

  // ---- 渲染 ----

  function renderDash() {
    var body = document.getElementById('eduStatsBody');
    if (!body) return;
    var kid = window.eduKids ? window.eduKids.active() : null;
    if (!kid) {
      body.innerHTML = '<div class="edu-card" style="text-align:center;"><h4>还没有孩子</h4><p class="muted">先到「我的」添加孩子吧～</p></div>';
      return;
    }
    var recs = Store.state.records || [];
    var total = recs.length;
    var okCount = recs.filter(function (r) { return r.ok; }).length;
    var rate = total ? Math.round(okCount * 100 / total) : 0;
    var stars = Store.state.stars || 0;
    var wrong = (Store.state.wrong || []).length;
    var badges = Object.keys(Store.state.badges || {}).filter(function (k) { return Legacy.BADGES[k]; }).length;
    var streak = (function () {
      var daySet = {};
      recs.forEach(function (r) { daySet[dateOf(r)] = 1; });
      var d = new Date(), s = 0;
      if (!daySet[keyOf(d)]) d = new Date(d.getTime() - 86400000);
      while (daySet[keyOf(d)]) { s++; d = new Date(d.getTime() - 86400000); }
      return s;
    })();
    var todaySecs = (Store.state.dailySecs || {})[keyOf(new Date())] || 0;
    var todayMins = Math.round(todaySecs / 60);
    var u = Store.usageForToday ? Store.usageForToday() : {};

    var trend = barTrendHtml(lastDays(7));
    var minsBars = minutesBars(lastDays(7));

    var master = subjMastery();
    var stEmpty = master.length ? '' : '<p class="muted" style="text-align:center;margin:8px 0;">暂无做题记录</p>';
    var ringGrid = master.map(function (s) {
      return '<div class="st-ring-col"><div class="st-ring-bx">' + ring(s.p, SUBJ_COLOR[s.subj] || '#ff6b4a') + '</div>' +
        '<div class="st-ring-l">' + (SUBJ_LABEL[s.subj] || s.subj) + '</div></div>';
    }).join('');
    var subjRows = master.map(function (s) {
      return '<div class="st-subj-row"><b>' + (SUBJ_LABEL[s.subj] || s.subj) + '</b>' +
        '<span class="sbar"><i style="width:' + s.p + '%;"></i></span><span class="pct">' + s.p + '%</span></div>';
    }).join('');

    var radarAx = radarAxes();
    var weakSegs = weakDist();
    var donutLegend = weakSegs.map(function (s, i) {
      return '<div class="dk-legend"><span class="dk-chip" style="background:' + (s.color || PALETTE[i % PALETTE.length]) + '"></span>' +
        '<span class="dk-name">' + esc(s.label) + '</span><span class="dk-n">' + s.value + '</span></div>';
    }).join('');

    var starCurve = lastDays(14).map(function (x) { return { label: x.label, v: x.stars || 0 }; });
    var kids = (window.eduKids ? window.eduKids.all() : []) || [];
    var kidChips = kids.length > 1 ? kids.map(function (k) {
      var on = kid && k.id === kid.id;
      var ava = (k.avatar) || (window.eduKids && window.eduKids.genderIcon ? window.eduKids.genderIcon(k.gender) : '🧒');
      return '<button type="button" class="dash-kid' + (on ? ' on' : '') + '" onclick="window.Edu.Dash.switchKid(\'' + k.id + '\')">' +
        '<span class="dk-ava">' + ava + '</span><span>' + esc(k.name || '宝贝') + '</span></button>';
    }).join('') : '';

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

    var ava = (kid.avatar) || (window.eduKids && window.eduKids.genderIcon ? window.eduKids.genderIcon(kid.gender) : '🧒');

    body.innerHTML =
      '<div class="dash-top">' +
        '<div class="dash-hero">' +
          '<span class="dh-ava">' + ava + '</span>' +
          '<div class="dh-meta"><div class="dh-name">' + esc(kid.name || '宝贝') + ' 的学习报告</div>' +
          '<div class="dh-sub">数据仅保存在设备本地 · 家长专属</div></div>' +
          '<button type="button" class="btn-soft dh-pdf" onclick="window.Edu.Dash.exportPdfReport()">📄 导出PDF</button>' +
        '</div>' +
        (kidChips ? '<div class="dash-kids">' + kidChips + '</div>' : '') +
      '</div>' +
      '<div class="st-kpi">' +
        '<div class="sk"><div class="v">' + total + '</div><div class="l">累计答题</div></div>' +
        '<div class="sk"><div class="v">' + rate + '%</div><div class="l">正确率</div></div>' +
        '<div class="sk"><div class="v">⭐ ' + stars + '</div><div class="l">星星</div></div>' +
        '<div class="sk"><div class="v">🔥 ' + streak + '</div><div class="l">连续打卡</div></div>' +
        '<div class="sk"><div class="v">' + badges + '</div><div class="l">徽章</div></div>' +
        '<div class="sk"><div class="v">' + todayMins + '</div><div class="l">今日分钟</div></div>' +
      '</div>' +
      '<div class="dash-grid">' +
        '<div class="edu-card"><h4>📈 正确率趋势 <span class="dash-hint">最近7天 · 每日答题</span></h4><div class="st-trend">' + trend + '</div></div>' +
        '<div class="edu-card"><h4>⏱️ 用时分析 <span class="dash-hint">最近7天 · 分钟</span></h4><div class="st-trend">' + minsBars + '</div>' +
          '<p class="muted" style="margin:6px 0 0;">今日已用 ' + todayMins + ' 分钟 · ' + (u.n || 0) + ' 题</p></div>' +
        '<div class="edu-card"><h4>🎯 分科掌握率</h4>' + (stEmpty || ('<div class="st-rings">' + ringGrid + '</div>' +
          '<div class="st-subj-detail">' + subjRows + '</div>')) + '</div>' +
        '<div class="edu-card"><h4>🛰️ 技能雷达</h4><div class="dash-radar-wrap">' + radarSvg(radarAx) + '</div></div>' +
        '<div class="edu-card"><h4>📉 薄弱知识点分布</h4><div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap;">' +
          '<div>' + donutSvg(weakSegs) + '</div><div class="dk-legend-col">' + (donutLegend || '<p class="muted">暂无数据</p>') + '</div></div></div>' +
        '<div class="edu-card"><h4>⭐ 星星获取曲线 <span class="dash-hint">最近14天</span></h4><div class="dash-line-wrap">' + lineSvg(starCurve) + '</div></div>' +
      '</div>' +
      mapCard +
      '</div>';
    anim(body);
  }

  function anim(el) {
    if (!el) return;
    el.classList.remove('page-enter');
    void el.offsetWidth;
    el.classList.add('page-enter');
  }

  if (window.Edu.Stats) window.Edu.Stats.SUBJ_LABEL = SUBJ_LABEL;

  window.Edu.Dash.renderDash = renderDash;
  window.Edu.Dash.SUBJ_LABEL = SUBJ_LABEL;
  window.Edu.Dash.radarSvg = radarSvg;
  window.Edu.Dash.donutSvg = donutSvg;
  window.Edu.Dash.lineSvg = lineSvg;
  window.Edu.Dash.weakDist = weakDist;
  window.Edu.Dash.radarAxes = radarAxes;
  window.Edu.Dash.recordsTable = recordsTable;
  window.Edu.Dash.getRecs = function () { return dashRecs; };
})();