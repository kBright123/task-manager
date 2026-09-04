(function () {
  'use strict';
  var C = window.Edu.Constants;
  var M = window.Edu.MathUtils;
  var Store = window.Edu.Store;
  var Speech = window.Edu.Speech;
  var Kids = window.Edu.Kids;
  var Nav = window.Edu.Nav;
  var QuizEngine = window.Edu.QuizEngine;
  var ZhWorkbench = window.Edu.ZhWorkbench;
  var MathWorkbench = window.Edu.MathWorkbench;
  var EnWorkbench = window.Edu.EnWorkbench;
  var Daily = window.Edu.Daily;
  var Legacy = window.Edu.Legacy;

  var SUBJ_LABEL = { zh: '语文', math: '数学', en: '英语', par: '乐园' };

  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function keyOf(d) { return pad(d.getFullYear()) + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function todayStr() { return keyOf(new Date()); }
  function endOfToday() { var t = new Date(); t.setHours(23, 59, 59, 999); return t.getTime(); }
  function esc(s) { return String(s === undefined || s === null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'); }

  function kidAvatar(k) {
    if (k && k.avatar) return k.avatar;
    return k && k.gender === 'female' ? '👧' : '👦';
  }
  function kidLevel(k) {
    return Math.max(1, (window.eduKids && window.eduKids.ageOf ? window.eduKids.ageOf(k && k.birthYear) : 6));
  }
  // 统一的问候页头: 早上好/{名字}/今天也要开开心心学习哦 + ⭐ Lv + 宝贝切换
  // 用于 学习/勋章/星愿/我的 各页, 避免反复出现重复大标题。
  function welcomeBarHtml(act, dropId, subtitle) {
    var kids = window.eduKids ? window.eduKids.all() : [];
    var hour = new Date().getHours();
    var greet = hour < 6 ? '夜深了' : (hour < 12 ? '早上好' : (hour < 18 ? '下午好' : '晚上好'));
    var actName = act ? (act.name || '宝贝') : '宝贝';
    var sub = subtitle || '今天也要开开心心学习哦';
    var top = '<section class="home-top">' +
      '<div class="ht-greet">' +
        '<span class="ht-hello">' + greet + '，<b>' + esc(actName) + '</b></span>' +
        '<span class="ht-sub">' + esc(sub) + '</span>' +
      '</div>' +
      '<div class="ht-actions">' +
        '<span class="ht-lv">⭐ ' + (Store.state && Store.state.stars || 0) + ' 星 · 连续打卡 ' + (loginStreak(Store.state && Store.state.records || []) || 0) + ' 天</span>' +
        '<button type="button" class="ht-icon" data-kid aria-label="宝贝切换" onclick="window.homeOpenKid(\'' + dropId + '\')">' +
          kidAvatar(act) + '</button>' +
      '</div>' +
      '</section>' +
      '<div class="ht-kiddrop" id="' + dropId + '"></div>';
    return top;
  }
  function renderWelcomeInto(containerId, subtitle) {
    var host = document.getElementById(containerId);
    if (!host) return;
    var act = window.eduKids ? window.eduKids.active() : null;
    host.innerHTML = welcomeBarHtml(act || {}, containerId + 'Dr', subtitle);
  }
  window.Edu.Home = window.Edu.Home || {};
  window.Edu.Home.welcomeBarHtml = welcomeBarHtml;
  window.Edu.Home.renderWelcomeInto = renderWelcomeInto;
  window.Edu.Home.kidAvatar = kidAvatar;
  window.renderWelcomeInto = renderWelcomeInto;

  function loginStreak(recs) {
    var daySet = {};
    (recs || []).forEach(function (r) { if (r.date) daySet[r.date] = 1; });
    var d = new Date();
    var streak = 0;
    if (!daySet[keyOf(d)]) d = new Date(d.getTime() - 86400000);
    while (daySet[keyOf(d)]) { streak++; d = new Date(d.getTime() - 86400000); }
    return streak;
  }
  function todayAccuracy(recs) {
    var n = 0, ok = 0;
    var t = todayStr();
    (recs || []).forEach(function (r) {
      var d = r.date || (r.t ? keyOf(new Date(r.t)) : '');
      if (d === t) { n++; if (r.ok) ok++; }
    });
    return n ? Math.round(ok * 100 / n) : 0;
  }
  function dueWrongListFor(stL) {
    var errs = (stL.wrong) || [];
    var end = endOfToday();
    return errs.filter(function (w) { return w.nextDue === undefined || (w.nextDue || 0) <= end; })
      .sort(function (a, b) { return (a.nextDue || 0) - (b.nextDue || 0); });
  }
  function minsUsedP() {
    var u = Store.usageForToday ? (Store.usageForToday() || {}) : {};
    if (!u.secs) return 0;
    return Math.ceil((u.secs || 0) / 60);
  }
  function homeDashData(act) {
    var stL = Store.state;
    var recs = stL.records || [];
    var u = Store.usageForToday ? (Store.usageForToday() || {}) : {};
    var today = (u.n || 0);
    var goal = 10;
    var st = Store.curSettings();
    if (st && st.dailyQ && st.dailyQ > 0) goal = st.dailyQ;
    var pctToday = todayAccuracy(recs);
    var overall = recs.length ? Math.round(recs.filter(function (r) { return r.ok; }).length * 100 / recs.length) : 0;
    var pct = today ? pctToday : overall;
    var badKeys = Object.keys(stL.badges || {}).filter(function (x) { return Legacy.BADGES[x]; });
    var wList = stL.wishes || [];
    var wDone = wList.filter(function (w) { return w.done; }).length;
    var zishi = recs.filter(function (r) { return r.subj === 'zh' && r.type === 'zi' && r.ok; }).length;
    var due = dueWrongListFor(stL).slice(0, 3).map(function (w) { return String(w.prompt).trim().charAt(0); });
    var days = [];
    var now = new Date();
    for (var d = 6; d >= 0; d--) {
      var t = new Date(now.getTime() - d * 86400000);
      var key = keyOf(t);
      days.push({ key: key, label: (t.getMonth() + 1) + '/' + t.getDate(), n: 0 });
    }
    var dayMap = {};
    days.forEach(function (x) { dayMap[x.key] = x; });
    recs.forEach(function (r) { if (dayMap[r.date]) dayMap[r.date].n++; });
    var maxN = 1;
    days.forEach(function (x) { maxN = Math.max(maxN, x.n || 1); });
    var prevWeek = 0;
    for (var p = 7; p <= 13; p++) {
      var tp = new Date(now.getTime() - p * 86400000);
      recs.forEach(function (r) { if (r.date === keyOf(tp)) prevWeek++; });
    }
    return {
      today: today, goal: goal, pct: pct, mins: minsUsedP(act), honor: badKeys.length,
      streak: loginStreak(recs), badges: badKeys.length, zishi: zishi,
      dueChars: due.slice(0, 3), dueN: dueWrongListFor(stL).length,
      days: days, maxN: maxN, prevWeek: prevWeek, wList: wList, wDone: wDone,
      stars: stL.stars || 0
    };
  }
  function miniLine(days, maxN, color) {
    var w = 100, h = 34;
    var pts = days.map(function (x, i) {
      var v = (x.n || 0) / (maxN || 1);
      var px = i * (w / (days.length - 1 || 1));
      var py = h - 4 - v * (h - 8);
      return px.toFixed(1) + ',' + py.toFixed(1);
    }).join(' ');
    var area = '0,' + h + ' ' + pts + ' ' + w + ',' + h;
    return '<svg viewBox="0 0 ' + w + ' ' + h + '" class="mini-line" aria-hidden="true">' +
      '<polygon points="' + area + '" fill="' + color + '" opacity="0.18"></polygon>' +
      '<polyline points="' + pts + '" fill="none" stroke="' + color + '" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"></polyline>' +
      '</svg>';
  }
  function todayQuote(k, d) {
    var name = esc(k.name || '宝贝');
    if (d.done >= d.goal) return '🎉 今日目标已达成，' + name + ' 太棒了，明天继续闯关攒星星！';
    if (d.remaining > 0) return '💪 再答 <b>' + d.remaining + '</b> 题就能突破今日目标，加油！';
    return '从第一题开始，答对题 + 攒星星，' + name + ' 冲鸭！';
  }
  function anim(el) {
    if (!el) return;
    el.classList.remove('page-enter');
    void el.offsetWidth;
    el.classList.add('page-enter');
  }

  function renderHome() {
    var body = document.getElementById('eduHomeBody');
    if (!body) return;
    var kids = window.eduKids ? window.eduKids.all() : [];
    if (!kids.length) {
      body.innerHTML = '<div class="home-hero">' +
        '<div class="edu-hero empty-hero"><div style="font-size:2.6rem;line-height:1;">👶</div>' +
        '<h2 style="margin:10px 0 4px;">欢迎来到教育乐园</h2>' +
        '<p style="color:var(--edu-muted);margin:0;">先登记一个宝贝，就能开始闯关攒星星咯</p>' +
        '<button type="button" class="home-cta" onclick="kidAdd()">➕ 添加宝贝</button></div></div>';
      anim(body);
      return;
    }
    var act = window.eduKids.active() || kids[0];
    if (!window.eduKids.active()) window.eduKids.setActive(act.id);
    var d = homeDashData(act);
    var done = Math.min(d.today, d.goal);
    var remaining = Math.max(0, d.goal - d.today);
    var barW = Math.round(Math.min(100, d.today * 100 / Math.max(1, d.goal)));

    // ===== 顶部条: 问候单行 + 副标题同行 + 等级/宝贝/声音/通知/模式 收纳 =====
    var hour = new Date().getHours();
    var greet = hour < 6 ? '夜深了' : (hour < 12 ? '早上好' : (hour < 18 ? '下午好' : '晚上好'));
    var curMode = Nav.currentMode ? Nav.currentMode() : 'workbench';
    var modeToggle = '<select id="modeSelect" class="mode-select" aria-label="学习模式" onchange="switchMode(this.value)">' +
      '<option value="workbench"' + (curMode === 'workbench' ? ' selected' : '') + '>🏫 幼小衔接</option>' +
      '<option value="paradise"' + (curMode === 'paradise' ? ' selected' : '') + '>🌈 快乐乐园</option>' +
      '</select>';
    var top = '<section class="home-top">' +
      '<div class="ht-greet">' +
        '<span class="ht-hello">' + greet + '，<b>' + esc(act.name || '宝贝') + '</b></span>' +
        '<span class="ht-sub">今天也要开开心心学习哦</span>' +
      '</div>' +
      '<div class="ht-actions">' +
        '<span class="ht-lv">⭐ ' + (Store.state.stars || 0) + ' 星 · 连续打卡 ' + (d.streak || 0) + ' 天</span>' +
        '<button type="button" class="ht-icon" data-kid aria-label="宝贝切换" onclick="window.homeOpenKid()">' + kidAvatar(act) + '</button>' +
        '<span class="ht-mode mode-toggle">' + modeToggle + '</span>' +
      '</div>' +
      '</section>';

    // ===== 今日目标卡: 标题 + 激励语(单行) + 进度条与数据整合 + 继续按钮 =====
    var quote = d.today >= d.goal
      ? '🎉 今日目标已达成，继续保持！'
      : (remaining > 0 ? '再答 <b>' + remaining + '</b> 题就能突破今日目标，加油！' : '从第一题开始，答对题 + 攒星星，冲鸭！');
    // 最近获得勋章(按时序倒序取前 3)展示在今日目标: 前 2 枚(.hero)任何端都显示, 第 3 枚(.xtra)桌面显示/手机隐藏,
    // 手机端用「+N」指示剩余枚数
    var badList = Object.keys(Store.state.badges || {})
      .filter(function (k) { return Legacy && Legacy.BADGES && Legacy.BADGES[k]; })
      .map(function (k) { return { name: Legacy.BADGES[k].name, t: Number(Store.state.badges[k]) || 0 }; })
      .sort(function (a, b) { return b.t - a.t; });
    var badHtml = badList.slice(0, 3).map(function (b, i) {
      return '<span class="hg-badge' + (i < 2 ? ' hero' : ' xtra') + '">' + esc(b.name) + '</span>';
    }).join('');
    var badMore = badList.length > 3
      ? '<span class="hg-more" title="共 ' + badList.length + ' 枚勋章">+' + (badList.length - 3) + '</span>'
      : '';
    var goalStats = '<div class="hg-stats">' +
      (badList.length ? '<span class="hg-badges" title="已获得 ' + badList.length + ' 枚勋章">' + badHtml + badMore + '</span>' : '') +
      '</div>';
    var goal = '<section class="home-goal">' +
      '<div class="hg-head"><span class="hg-title">📊 今日学习目标</span>' +
      '<span class="hg-count"><b>' + done + '</b> / ' + d.goal + ' 题</span></div>' +
      '<div class="hg-quote">' + quote + '</div>' +
      '<div class="hg-track"><div class="hc-fill" style="width:' + barW + '%;"></div></div>' +
      goalStats +
      '</section>';

    // ===== 4 个学习入口卡: 2×2 网格, 等高不换行 =====
    var today = todayStr();
    function rKey(r) {
      if (r.date) return r.date;
      var dt = r.t ? new Date(r.t) : new Date();
      return dt.getFullYear() + '-' + ('0' + (dt.getMonth()+1)).slice(-2) + '-' + ('0'+dt.getDate()).slice(-2);
    }
    var recs = Store.state.records || [];
    var subjN = { zh: 0, math: 0, en: 0 };
    recs.forEach(function (r) { if (rKey(r) === today && subjN[r.subj] !== undefined) subjN[r.subj]++; });
    var lvMap = (Store.state.level || {});
    var courses = [
      { s: 'zh', type: 'zi', em: '📖', name: '语文识字', sub: '认识新汉字', locked: false },
      { s: 'math', type: 'calc', em: '🔢', name: '数学口算', sub: '加减乘除小能手', locked: false },
      { s: 'en', type: '', em: '🌍', name: '英语启蒙', sub: 'ABC 说起来', locked: false }
    ];
    function courseStatus(c) {
      if (c.locked) return { tag: '未解锁', cls: 'locked' };
      var lv0 = c.s === 'daily' ? Math.min(5, Math.max(1, Math.ceil((d.today / Math.max(1, d.goal)) * 5))) : (lvMap[c.s] || 0);
      if (lv0 >= 5) return { tag: '已通关', cls: 'done' };
      if (lv0 > 0) return { tag: '去学习', cls: 'go' };
      return { tag: '未开始', cls: 'todo' };
    }
    function courseGo(c) {
      if (c.s === 'daily') return 'window.eduNav(\'home\');window.Edu.Workbench.quickStart(\'daily\')';
      // 点击卡片默认进入该学科的独立全屏闯关地图
      return 'window.Edu.Course&&window.Edu.Course.openMapFull&&window.Edu.Course.openMapFull(\'' + c.s + '\')';
    }
    // 闯关模式: 打开该学科的独立全屏闯关地图(左右滑动选择已解锁小关), 由地图进入各小关
    function courseGuan(c) {
      if (c.s === 'daily') return courseGo(c);
      return 'window.Edu.Course&&window.Edu.Course.openMapFull&&window.Edu.Course.openMapFull(\'' + c.s + '\')';
    }
    function courseSu(c) {
      // 极速练习: 题型跟随课程地图当前关卡, 且按学科单位取有效题型(避免数学/英语误入识字)
      if (c.s === 'daily') return courseGo(c);
      var t = null;
      if (window.Edu && window.Edu.Course && window.Edu.Course.COURSES && window.Edu.Course.COURSES[c.s]) {
        var idx = (window.Edu.Course.curLevelIdx && window.Edu.Course.curLevelIdx(c.s)) || 0;
        var lv = window.Edu.Course.COURSES[c.s].levels[idx];
        if (lv && lv.t) {
          var lt = lv.t;
          if (c.s === 'zh') {
            t = (lt === 'pinyin' || lt === 'yun' || lt === 'read' || lt === 'tone') ? 'pinyin' : 'zi';
          } else if (c.s === 'math') {
            t = (lt === 'word') ? 'word' : 'calc';
          } else if (c.s === 'en') {
            t = 'word_en';
          }
        }
      }
      return 'window.homePractice(\'' + c.s + '\'' + (t ? ',\'' + t + '\'' : '') + ')';
    }
    // 课程地图当前所在关卡(大关·小关)
    function courseLevel(c) {
      if (c.s === 'daily') return null;
      if (!(window.Edu && window.Edu.Course)) return null;
      var pos = window.Edu.Course.curPos ? window.Edu.Course.curPos(c.s) : null;
      if (!pos) return null;
      var lv = (window.Edu.Course.COURSES[c.s] || {}).levels || [];
      if (!lv[pos.big]) return null;
      return { n: pos.big + 1, s: pos.stage + 1, name: lv[pos.big].name, em: lv[pos.big].em };
    }
    var courseCards = courses.map(function (c) {
      var st = courseStatus(c);
      var n = c.s === 'daily' ? d.today : subjN[c.s];
      var locked = st.cls === 'locked';
      var lv = courseLevel(c);
      var click = locked ? '' : ' onclick="' + courseGo(c) + '"';
      // 单行状态: 进行中显示当前关卡, 每日显示进度, 未开始显示简介
      var lvText = lv
        ? '第 ' + lv.n + ' 大关' + (lv.name ? ' · ' + lv.name : '')
        : (c.s === 'daily' ? '今日 ' + Math.min(d.today, d.goal) + '/' + d.goal + ' 题' : c.sub);
      // 两行展示: 第一行 emoji+学科名+关卡, 第二行 已练题数+闯关模式+极速练习
      var modes = '<span class="hc-modes"' + (locked ? '' : ' onclick="event.stopPropagation()"') + '>' +
        '<button type="button" class="hc-mode hc-guan" onclick="' + courseGuan(c) + '">🗺️ 闯关模式</button>' +
        '<button type="button" class="hc-mode hc-su" onclick="' + courseSu(c) + '">⚡ 极速练习</button>' +
        '</span>';
      return '<section class="home-course hc-subj-' + (c.s || '') + (locked ? ' locked' : '') + '"' + click + '>' +
        '<div class="hc-main">' +
        '<span class="hc-emo">' + c.em + '</span>' +
        '<span class="hc-nm">' + c.name + '</span>' +
        '<span class="hc-lv">' + esc(lvText) + '</span>' +
        '</div>' +
        '<div class="hc-foot">' +
        '<span class="hc-count">已练 ' + n + ' 题</span>' +
        modes +
        '</div>' +
        '</section>';
    }).join('');
    var list = '<section class="home-course-sec">' +
      '<div class="home-sec-head"><h3>📚 继续练</h3>' +
      '<span class="hc-hint"><i class="bi bi-chevron-double-right hh-a"></i>点卡片直接开练</span></div>' +
      '<div class="home-course-scroll">' + courseCards + '</div></section>';

    body.innerHTML = top + '<div class="ht-kiddrop" id="homeKidDrop"></div>' + goal + list;
    body.classList.add('home-compact');
    anim(body);
  }

  window.homePickKid = function (id) {
    if (window.eduKids) window.eduKids.setActive(id);
    Store.loadAllState();
    renderHome();
    renderKidBar();
  };
  window.homeStartLearn = function () {
    var act = window.eduKids ? window.eduKids.active() : null;
    if (act) kidEnter(act.id);
  };
  // 顶部条宝贝切换: 轻量下拉, 无独立顶栏时提供统一身份入口
  window.openKidDrop = function (dropId) {
    var drop = document.getElementById(dropId || 'homeKidDrop');
    if (!drop) return;
    var list = (window.eduKids ? window.eduKids.all() : []) || [];
    var act = window.eduKids ? window.eduKids.active() : null;
    if (drop.classList.contains('show')) { drop.classList.remove('show'); return; }
    var ht = '<div class="ht-kd-title">选择宝贝</div>' + list.map(function (k) {
      var on = act && k.id === act.id;
      return '<button type="button" class="ht-kd-item' + (on ? ' on' : '') + '" onclick="window.switchKid(\'' + k.id + '\')">' +
        '<span class="ht-kd-ava">' + kidAvatar(k) + '</span>' +
        '<span class="ht-kd-name">' + esc(k.name || '宝贝') + '</span>' +
        (on ? '<i class="bi bi-check2 ht-kd-ok"></i>' : '') + '</button>';
    }).join('') +
      '<button type="button" class="ht-kd-add" onclick="window.kidAdd()">➕ 添加宝贝</button>';
    drop.innerHTML = ht;
    drop.classList.add('show');
  };
  window.homeOpenKid = function (dropId) {
    window.openKidDrop(dropId || 'homeKidDrop');
  };
  window.homeCloseKid = function () {
    var drop = document.getElementById('homeKidDrop');
    if (drop) drop.classList.remove('show');
  };
  window.openDetail = function (which) {
    var kid = window.eduKids ? window.eduKids.active() : null;
    if (!kid) { Speech.toast('请先选择宝贝'); return; }
    Store.loadAllState();
    var stL = Store.state;
    var recs = stL.records || [];
    var title = document.getElementById('detailTitle');
    var sub = document.getElementById('detailSub');
    var body = document.getElementById('detailBody');
    var now = new Date();
    if (which === 'trend') {
      if (title) title.textContent = '📈 本周趋势';
      if (sub) sub.textContent = '最近 7 天答题数量';
      var days = [];
      for (var i = 6; i >= 0; i--) {
        var t = new Date(now.getTime() - i * 86400000);
        days.push({ label: (t.getMonth() + 1) + '月' + t.getDate() + '日', n: recs.filter(function (r) { return r.date === keyOf(t); }).length, cur: i === 0 });
      }
      var maxN = 1;
      days.forEach(function (x) { maxN = Math.max(maxN, x.n || 1); });
      if (body) body.innerHTML = '<div class="dt-line">' + days.map(function (x) {
        var hgt = Math.max(4, Math.round(x.n / maxN * 60));
        return '<div class="dt-col' + (x.cur ? ' cur' : '') + '"><i style="height:' + hgt + 'px;"></i><span>' + x.label + '</span><b>' + x.n + '</b></div>';
      }).join('') + '</div>' +
        '<div class="dt-total">本周共答 <b>' + days.reduce(function (a, x) { return a + (x.n || 0); }, 0) + '</b> 题</div>';
    } else if (which === 'wrong') {
      if (title) title.textContent = '📝 错题本';
      var due = dueWrongListFor(stL);
      if (sub) sub.textContent = '待复习 ' + due.length + ' 个错题';
      if (body) body.innerHTML = due.slice(0, 20).map(function (w) {
        var shown = String(w.correct).split('|').join(' → ');
        return '<div class="dt-row"><span class="si-emoji">📕</span><div><div class="dt-w">' + esc(w.prompt) + '</div><div class="dt-wm">' + (SUBJ_LABEL[w.subj] || w.subj) + ' · 正确答案 ' + esc(shown) + '</div></div></div>';
      }).join('') || '<p class="muted" style="text-align:center;">太棒了，没有待复习的错题 🎉</p>';
    } else if (which === 'zishi') {
      if (title) title.textContent = '📚 识字量';
      var totalZ = recs.filter(function (r) { return r.subj === 'zh' && r.type === 'zi'; }).length;
      var zishi = recs.filter(function (r) { return r.subj === 'zh' && r.type === 'zi' && r.ok; }).length;
      if (sub) sub.textContent = '累计认读 ' + zishi + ' / ' + totalZ + ' 个汉字';
      if (body) body.innerHTML = '<div class="dt-big">' + zishi + ' <small>字</small></div>' +
        '<p class="muted" style="text-align:center;margin:4px 0 12px;">坚持每日识字，向识字小达人进发</p>';
    } else if (which === 'honor') {
      if (title) title.textContent = '🏆 荣誉墙';
      var bad = stL.badges || {};
      if (sub) sub.textContent = '已获得 ' + Object.keys(bad).length + ' 枚徽章';
      if (body) body.innerHTML = '<div class="dt-badges"><p class="muted" style="text-align:center;">努力闯关，解锁第一枚徽章吧！</p></div>';
    } else if (which === 'wish') {
      if (title) title.textContent = '⭐ 星票';
      var wList = stL.wishes || [];
      if (sub) sub.textContent = '当前 ' + (stL.stars || 0) + ' 星 · 已兑换 ' + wList.filter(function (w) { return w.done; }).length + '/' + wList.length;
      if (body) body.innerHTML = '<div class="dt-big">⭐ ' + (stL.stars || 0) + ' <small>星</small></div>' +
        '<div class="dt-wl">' + (wList.map(function (w) {
          return '<div class="dt-row"><span class="si-emoji">🎁</span><div><div class="dt-w">' + esc(w.name) + '</div></div></div>';
        }).join('') || '<p class="muted" style="text-align:center;">还没有星票，可在「星愿」里设置</p>') + '</div>';
    }
    var mask = document.getElementById('eduMaskDetail');
    if (mask) mask.style.display = 'flex';
  };

  window.homeEditKid = function (id) {
    var k = window.eduKids ? window.eduKids.byId(id) : null;
    if (!k) return;
    Kids.populateYears();
    editKidId = id;
    editKidAva = kidAvatar(k);
    var ni = document.getElementById('editNameInput');
    if (ni) ni.value = k.name || '';
    var yi = document.getElementById('editYearInput');
    if (yi) yi.value = String(k.birthYear);
    var mask = document.getElementById('eduMaskKidEdit');
    if (mask) mask.style.display = 'flex';
  };

  window.openKidsMgr = function () {
    var list = document.getElementById('kidsMgrList');
    if (!list) return;
    var kids = window.eduKids ? window.eduKids.all() : [];
    list.innerHTML = kids.map(function (k) {
      return '<div class="mgr-row" data-id="' + k.id + '">' +
        '<span class="mgr-ava">' + kidAvatar(k) + '</span>' +
        '<span class="mgr-name">' + esc(k.name || '宝贝') + ' · ' + (window.eduKids ? window.eduKids.ageOf(k.birthYear) : 6) + '岁</span>' +
        '<span class="mgr-edit" onclick="homeEditKid(\'' + k.id + '\')" title="编辑">✎</span>' +
        '<button type="button" class="mgr-del" onclick="mgrDeleteKid(\'' + k.id + '\')">删除</button>' +
        '</div>';
    }).join('') || '<p class="muted" style="text-align:center;">还没有宝贝</p>';
    var mask = document.getElementById('eduMaskKidsMgr');
    if (mask) mask.style.display = 'flex';
  };
  window.mgrDeleteKid = function (id) {
    window.requireParent(function () {
      if (!(window.confirm && window.confirm('确定删除该宝贝？此操作不可恢复。'))) return;
      if (window.eduKids) window.eduKids.remove(id);
      try {
        localStorage.removeItem(C.LS_BASE + '_' + id);
        localStorage.removeItem(C.STR_BASE + '_' + id);
        localStorage.removeItem('edu_pref_v1_' + id);
      } catch (e) {}
      if (window.fetch) {
        window.fetch('/edu/api/kids', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ kids:[], removedIds:[id] }) })
          .then(function(r){ return r.json && r.json(); })
          .catch(function(){});
      }
      renderKidsMgrList();
      renderHome();
      renderKidBar();
    });
  };
  function renderKidsMgrList() {
    var list = document.getElementById('kidsMgrList');
    if (!list) return;
    var kids = window.eduKids ? window.eduKids.all() : [];
    list.innerHTML = kids.map(function (k) {
      return '<div class="mgr-row" data-id="' + k.id + '"><span class="mgr-ava">' + kidAvatar(k) + '</span><span class="mgr-name">' + esc(k.name || '宝贝') + '</span><span class="mgr-edit">✎</span></div>';
    }).join('') || '<p class="muted" style="text-align:center;">还没有宝贝</p>';
  }
  window.kidEnter = function (id) {
    if (window.eduKids) window.eduKids.setActive(id);
    Store.loadAllState();
    var p = Nav.getPref();
    if (p && p.mode === 'paradise') {
      Nav.setSubj('zh');
      Nav.setPar(p.par || null);
    } else {
      Nav.setSubj((p && p.subj) || 'zh');
      Nav.setPar(null);
    }
    window.eduNav('learn');
  };
  window.kidEditById = function (id) {
    window.homeEditKid(id);
  };
  window.addWishFor = function (id) {
    window.requireParent(function () {
      if (window.eduKids) window.eduKids.setActive(id);
      Store.loadAllState();
      window.eduNav('wish');
    });
  };

  // stub subjNow/parNow accessors bound to Nav

  var editKidId = null;
  var editKidAva = '🧒';

  window.renderHome = renderHome;
  window.Edu.Home = {
    renderHome: renderHome,
    homePickKid: window.homePickKid,
    homeStartLearn: window.homeStartLearn,
    homeEditKid: window.homeEditKid,
    openDetail: window.openDetail,
    openKidsMgr: window.openKidsMgr,
    mgrDeleteKid: window.mgrDeleteKid,
    switchKid: window.switchKid,
    toggleKidDrop: window.toggleKidDrop,
    kidEnter: window.kidEnter,
    kidEditById: window.kidEditById,
    openReport: window.openReport,
    renderStarBar: window.renderStarBar,
    renderKidBar: window.renderKidBar,
    kidAvatar: kidAvatar,
    kidLevel: kidLevel,
    homeKidData: homeDashData,
    loginStreak: loginStreak,
    todayAccuracy: todayAccuracy,
    dueWrongListFor: dueWrongListFor,
    minsUsedP: minsUsedP,
    miniLine: miniLine,
    todayQuote: todayQuote
  };

  // ===================== Workbench 桥接（由学习核心提供） =====================
  window.Edu.Workbench = {
    wbZhMode: ZhWorkbench.wbZhMode,
    wbPinyinMode: ZhWorkbench.wbPinyinMode,
    wbCiyuMode: ZhWorkbench.wbCiyuMode,
    wbMathMode: MathWorkbench.wbMathMode,
    wbWrongActive: MathWorkbench.wbWrongActive,
    wbEnMode: EnWorkbench.wbEnMode
  };
  window.Edu.Workbench.wbInit = function () {
    var pref = Nav.getPref();
    if (pref.wbZh) ZhWorkbench.wbZhMode = pref.wbZh;
    if (pref.wbPy) ZhWorkbench.wbPinyinMode = pref.wbPy;
    if (pref.wbCy) ZhWorkbench.wbCiyuMode = pref.wbCy;
    if (pref.wbMath) MathWorkbench.wbMathMode = pref.wbMath;
    if (pref.wbEn) EnWorkbench.wbEnMode = pref.wbEn;
    var s = pref.lastSubj || 'zh';
    if (s === 'daily') { window.startDaily(); return; }
    if (s === 'zh') window.wbZh(ZhWorkbench.wbZhMode);
    else if (s === 'math') window.wbMath(MathWorkbench.wbMathMode);
    else if (s === 'en') window.wbEn(EnWorkbench.wbEnMode);
    window.renderNav();
  };
  window.Edu.Workbench.wbSubject = function (s) {
    Nav.prefSet('subj', s);
    var pref = Nav.getPref(); pref.lastSubj = s; Nav.savePref(pref);
    if (s === 'zh') window.wbZh(ZhWorkbench.wbZhMode);
    else if (s === 'math') window.wbMath(MathWorkbench.wbMathMode);
    else if (s === 'en') window.wbEn(EnWorkbench.wbEnMode);
    window.renderNav();
  };
  // 首页一键直达答题：合并「选科/选题」到首页，1 步进入答题
  window.Edu.Workbench.quickStart = function (subj, type) {
    if (!(window.eduKids && window.eduKids.active())) { Speech.toast('请先选择宝贝'); return; }
    Store.loadAllState();
    Nav.prefSet('subj', subj);
    var p = Nav.getPref();
    p.lastSubj = subj; p.mode = 'workbench'; p.par = null;
    // 记录目标题型: wbInit 会依据 pref 打开对应面板, 避免"先默认开面板再二次打开"的重复初始化
    if (subj === 'daily') {
      p.wbZh = null; p.wbMath = null; p.wbEn = null;
    } else if (subj === 'math') { p.wbMath = type || p.wbMath || 'calc'; }
    else if (subj === 'zh') { p.wbZh = type || p.wbZh || 'zi'; }
    else if (subj === 'en') { p.wbEn = type || p.wbEn || 'word'; }
    Nav.savePref(p);
    eduNav('learn');
    if (window.renderNav) window.renderNav();
  };
  // 首页直达极速练习: 先切到工作台挂载对应学科面板, 再启动极速练习(避免空白页)
  window.homePractice = function (subj, type) {
    if (!(window.eduKids && window.eduKids.active())) { Speech.toast('请先选择宝贝'); return; }
    Store.loadAllState();
    Nav.prefSet('subj', subj);
    var p = Nav.getPref();
    p.lastSubj = subj; p.mode = 'workbench'; p.par = null;
    if (subj === 'math') p.wbMath = type || 'calc';
    else if (subj === 'en') p.wbEn = type || 'word';
    else p.wbZh = type || 'zi';
    Nav.savePref(p);
    eduNav('learn');
    if (window.renderNav) window.renderNav();
    var cid = (subj === 'daily') ? 'wb-daily' : (subj === 'math') ? 'wb-math-body' : (subj === 'en') ? 'wb-en-body' : 'wb-zh-body';
    var tries = 0;
    (function waitShell() {
      if (document.getElementById(cid)) { window.startPractice(subj, type); return; }
      if (++tries > 40) return;
      setTimeout(waitShell, 80);
    })();
  };
  window.Edu.Workbench.quickHome = function () { eduNav('home'); };
  // 切换外层学科面板(语文/数学/英语/每日挑战)的可见性
  window.Edu.Workbench.showSubjectSection = function (s) {
    var id = s === 'daily' ? 'wb-daily' : 'wb-' + s;
    ['wb-zh', 'wb-math', 'wb-en', 'wb-daily'].forEach(function (x) {
      var el = document.getElementById(x);
      if (el) el.style.display = (x === id) ? '' : 'none';
    });
  };

  // legacy getters for Nav-bound subj/par (kept for compatibility)
  window.Edu.Home.getSubj = function () { return Nav.subjNow; };
  window.Edu.Home.getPar = function () { return Nav.parNow; };
  window.Edu.Home.setSubj = function (s) { Nav.setSubj(s); };
  window.Edu.Home.setPar = function (p) { Nav.setPar(p); };

  // 点击下拉外部时收起 (惰性: 仅当首页存在宝贝下拉时挂载)
  if (typeof document !== 'undefined' && document.addEventListener && !window.__eduHomeOutClick) {
    window.__eduHomeOutClick = true;
    document.addEventListener('click', function (e) {
      var drop = document.getElementById('homeKidDrop');
      var btn = e.target && e.target.closest ? e.target.closest('.ht-icon[data-kid]') : null;
      if (drop && drop.classList.contains('show') && !drop.contains(e.target) && !btn) {
        drop.classList.remove('show');
      }
    });
  }
})();
