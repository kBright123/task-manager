(function () {
  'use strict';
  var C = window.Edu.Constants;
  var M = window.Edu.MathUtils;
  var Store = window.Edu.Store;
  var Legacy = window.Edu.Legacy;
  var Speech = window.Edu.Speech;

  // =====================================================================
  // 游戏化课程地图与激励体系
  // 参考 Mimi 启蒙乐园的课程地图 / 星光识字岛的闯关 // 幼小衔接工作台
  // 每个学科是一条「旅程」, 每个关卡节点对映一个现有题型. 通关=答对>=80% 或 3星.
  // =====================================================================

  var SUBJ_LABEL = { zh: '语文', math: '数学', en: '英语', daily: '每日' };

  // 学科课程定义: t=现有题型(用于启动答题), name/em 用于地图节点展示
  var COURSES = {
    zh: {
      title: '语文识字之旅', emoji: '📖', journey: '小探险家登山', startEm: '🧗',
      levels: [
        { t: 'zi', name: '识字起航', em: '🔠' },
        { t: 'pinyin', name: '声母乐园', em: '🔤' },
        { t: 'yun', name: '韵母城堡', em: '🔡' },
        { t: 'read', name: '拼读加油站', em: '🗣️' },
        { t: 'tone', name: '四声小调', em: '🎵' },
        { t: 'ciyu', name: '词语列车', em: '🗂️' },
        { t: 'poem', name: '古诗山川', em: '📜' },
        { t: 'stroke', name: '笔顺工坊', em: '✍️' }
      ]
    },
    math: {
      title: '数学探险岛', emoji: '🔢', journey: '小火车前进', startEm: '🚂',
      levels: [
        { t: 'calc', name: '口算峡谷', em: '🧮' },
        { t: 'judge', name: '判断码头', em: '⚖️' },
        { t: 'order', name: '排序登山道', em: '↕️' },
        { t: 'word', name: '应用题营地', em: '📝' },
        { t: 'calc', name: '口算加速带', em: '🚀' },
        { t: 'calc', name: '口算巅峰', em: '🏔️' }
      ]
    },
    en: {
      title: '英语星光岛', emoji: '🔤', journey: '星星路线', startEm: '🚀',
      levels: [
        { t: 'word', name: '单词灯塔', em: '🔤' },
        { t: 'dialogue', name: '对话港口', em: '💬' },
        { t: 'match', name: '配对小径', em: '🤝' },
        { t: 'word', name: '单词加速带', em: '🚀' },
        { t: 'dialogue', name: '对话巅峰', em: '🏔️' }
      ]
    }
  };

  // 累计星星阈值触发特殊奖励(奖励星星, 星星是唯一可兑换星愿的货币)
  var STAR_REWARDS = [
    { at: 20, em: '🎖️', txt: '小勇士', bonus: 5 },
    { at: 50, em: '🏆', txt: '闯关先锋', bonus: 10 },
    { at: 100, em: '👑', txt: '学习星星国王', bonus: 15 }
  ];

  // ---- 工具 ----
  function esc(s) { return String(s === undefined || s === null ? '' : s).replace(/</g, '&lt;').replace(/&/g, '&amp;'); }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function keyOf(d) { return pad(d.getFullYear()) + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }

  function stateCourse() {
    Store.state.course = Store.state.course || {};
    return Store.state.course;
  }

  // node 索引: 课程里第 idx 关(0 起)对应到 COURSES[subj].levels[idx]
  function levelCount(subj) { return (COURSES[subj] && COURSES[subj].levels) ? COURSES[subj].levels.length : 0; }

  // 返回该学科某节点的进度对象(不存在则创建, 但 unlocked 不越过当前已解锁)
  function nodeProg(subj, idx) {
    var sc = stateCourse();
    sc[subj] = sc[subj] || { nodes: [], unlocked: 1, done: false };
    var nodes = sc[subj].nodes;
    while (nodes.length <= idx) nodes.push({ stars: 0, best: 0, passed: false, done: false, tries: 0 });
    return nodes[idx];
  }
  function courseProg(subj) {
    var sc = stateCourse();
    sc[subj] = sc[subj] || { nodes: [], unlocked: 1, done: false };
    return sc[subj];
  }

  // 已解锁节点数(1 起): 首关总是解锁; 每通关一关解锁下一关
  function unlockedCount(subj) {
    var p = courseProg(subj);
    return Math.max(1, Math.min(levelCount(subj), p.unlocked || 1));
  }
  function curLevelIdx(subj) {
    // 第一个未通关且已解锁的节点为「当前位置」
    var p = courseProg(subj);
    var un = p.unlocked || 1;
    for (var i = 0; i < un; i++) { if (!p.nodes[i] || !p.nodes[i].passed) return i; }
    return Math.min(un, levelCount(subj)) - 1;
  }

  // 通关某一关需要的题型启动: 复用各工作台
  function launchLevel(subj, idx) {
    var lv = COURSES[subj].levels[idx];
    if (!lv) return;
    var un = unlockedCount(subj);
    if (idx >= un) { if (Speech && Speech.toast) Speech.toast('先通关前面的关卡才能解锁这里哦 🔒'); return; }
    // 语文题型在导入面板中有子模式(声母/韵母/拼读/四声), 需落到真正的答题 type 以匹配结算
    var quizT = zhLevelQuizType(lv.t);
    // 记录「正在闯的第几关」, 供结算时回写 course 进度
    Store.state.courseIn = { subj: subj, idx: idx, t: quizT, startedAt: Date.now() };
    Store.state.courseInflight = 1;
    var type = lv.t;
    var NavP = window.Edu && window.Edu.Nav;
    var pref = (NavP && NavP.getPref) ? NavP.getPref() : null;
    var setPref = function (key) {
      // 记录当前学科进学习页, 供 eduNav→wbInit 按 lastSubj 打开对应面板(避免回退到上一学科/拼音)
      if (pref) { pref.lastSubj = subj; pref.mode = 'workbench'; pref.subj = subj; if (key) pref[key] = type; if (NavP && NavP.savePref) NavP.savePref(pref); }
    };
    if (subj === 'math') { if (window.wbMath) window.wbMath(type === 'did' ? 'calc' : type); setPref('wbMath'); }
    else if (subj === 'en') { if (window.wbEn) window.wbEn(type); setPref('wbEn'); }
    else if (subj === 'zh' && window.wbZh) {
      if (type === 'pinyin' || type === 'yun' || type === 'read' || type === 'tone') {
        window.wbZh('pinyin');
        if (pref) { pref.wbZh = 'pinyin'; pref.wbPy = type; }
        setPref();
        if ((type === 'yun' || type === 'read' || type === 'tone') && window.wbPinyin) window.wbPinyin(type);
      } else if (type === 'ciyu') {
        window.wbZh('ciyu');
        if (pref) { pref.wbZh = 'ciyu'; pref.wbCy = 'fan'; }
        setPref();
        if (window.wbCiyu) window.wbCiyu('fan');
      } else {
        window.wbZh(type);
        if (pref) { pref.wbZh = type; }
        setPref();
      }
    }
    // 进入学习页展示答题
    if (window.eduNav) window.eduNav('learn');
  }

  // 语文关卡题型 → 实际渲染/结算的答题 type
  function zhLevelQuizType(t) {
    if (t === 'ciyu') return 'fan';
    if (t === 'yun' || t === 'read' || t === 'tone' || t === 'pinyin' || t === 'zi' || t === 'poem' || t === 'stroke') return t;
    return t;
  }

  // ---- 激励: 星星(唯一货币, 可兑换星愿) ----
  // 星星主页里已积累(答题评星 addStarLog), 这里补充「通关/每日挑战/里程碑」的额外奖励星星
  function addStarBonus(n, label) {
    Store.state.stars = (Store.state.stars || 0) + (n || 0);
    if (Store.addStarLog) Store.addStarLog(n);
    return Store.state.stars;
  }

  // 星星里程碑: 达到阈值给一次性点数和徽章
  function checkStarMilestones() {
    var newly = [];
    var stars = Store.state.stars || 0;
    var sc = stateCourse();
    sc.rewards = sc.rewards || {};
    STAR_REWARDS.forEach(function (r) {
      if (stars >= r.at && !sc.rewards['star_' + r.at]) {
        sc.rewards['star_' + r.at] = Date.now();
        addStarBonus(r.bonus, '星星里程碑·' + r.txt);
        newly.push(r);
      }
    });
    return newly;
  }

  // 连续打卡天数: 依据使用/做题记录
  function streakDays() {
    var daySet = {};
    (Store.state.records || []).forEach(function (r) { if (r && r.date) daySet[r.date] = 1; });
    var d = new Date();
    var streak = 0;
    if (!daySet[keyOf(d)]) d = new Date(d.getTime() - 86400000);
    while (daySet[keyOf(d)]) { streak++; d = new Date(d.getTime() - 86400000); }
    return streak;
  }

  // 通关关卡奖励 + 解锁下一关 + 里程碑
  function applyPass(subj, idx, stars) {
    var p = courseProg(subj);
    var nodes = p.nodes;
    var st = nodes[idx] || (nodes[idx] = { stars: 0, best: 0, passed: false, done: false, tries: 0 });
    st.stars = Math.max(st.stars || 0, stars);
    st.best = Math.max(st.best || 0, stars);
    st.passed = true;
    st.passedAt = Date.now();
    // 通关 +3 星星
    addStarBonus(3, (SUBJ_LABEL[subj] || subj) + '通关·' + (COURSES[subj].levels[idx].name));
    // 解锁下一关
    var unlocked = Math.max(p.unlocked || 1, idx + 2);
    p.unlocked = Math.min(levelCount(subj), unlocked);
    // 整科通关
    var allPassed = true;
    for (var i = 0; i < levelCount(subj); i++) { if (!nodes[i] || !nodes[i].passed) { allPassed = false; break; } }
    if (allPassed) p.done = true;
    return { name: COURSES[subj].levels[idx].name, stars: stars, allPassed: allPassed };
  }

  // ---- 结算: 由答题引擎在交卷时调用 ----
  // 返回摘要对象, 供完成页展示「关卡进度/星数/解锁/奖励」
  function recordQuizResult(subj, type, stats) {
    stats = stats || {};
    var right = stats.right || 0;
    var total = stats.total || 1;
    var triesUsed = stats.triesUsed || 0;   // 首次答对 = 0
    var fast = stats.fast;                  // 是否用时短
    var pct = total ? Math.round((right / total) * 100) : 0;

    // 1-3 星: 正确 + 首次尝试 + 用时短
    var stars = 0;
    if (pct >= 60) stars = 1;
    if (pct >= 80) stars = Math.max(stars, 2);
    if (stars >= 2) {
      if (triesUsed === 0) stars = 3;
      else if (fast) stars = 3;
    }
    if (pct === 0) stars = 0;

    var passed = (pct >= 80) || (stars >= 3);
    var out = { subj: subj, type: type, right: right, total: total, pct: pct, stars: stars, passed: passed, levelIdx: -1 };

    // 是否正处在关卡闯关中(若直接答题启动, courseIn 缺失则尝试按题型匹配)
    var inflight = Store.state.courseIn || null;
    var idx = -1;
    if (inflight && inflight.subj === subj && inflight.t === type) { idx = inflight.idx; }
    else {
      // 尝试按题型对映到当前未通关关卡
      var un = (function(){ try { return unlockedCount(subj); } catch (e) { return 1; } })();
      var lv = COURSES[subj] ? COURSES[subj].levels : null;
      var p0 = courseProg(subj);
      for (var k = 0; k < un && lv; k++) {
        var lvT = (subj === 'zh') ? zhLevelQuizType(lv[k].t) : lv[k].t;
        if (lvT === type && (!p0.nodes[k] || !p0.nodes[k].passed)) { idx = k; break; }
      }
    }

    if (idx >= 0 && COURSES[subj] && COURSES[subj].levels[idx]) {
      out.levelIdx = idx;
      var opts = { fast: !!fast, triesUsed: triesUsed };
      cacheTriesForLevel(subj, idx, type, opts);
      if (passed) {
        var res = applyPass(subj, idx, stars);
        out.levelName = res.name;
        out.unlockedNext = (idx + 1 < levelCount(subj)) ? COURSES[subj].levels[idx + 1].name : null;
        out.allPassed = res.allPassed;
        out.passed = true;
        out.passedNow = true;
      } else {
        var pn = courseProg(subj).nodes[idx];
        if (pn) { pn.tries = (pn.tries || 0) + 1; }
        out.passed = false;
        out.tryAgain = true;
      }
    } else if (passed && type === 'daily') {
      // 每日挑战: 完成 +1 星星
      if (pct >= 60) addStarBonus(1, '完成每日挑战');
      out.dailyDone = true;
    } else {
      // 非关卡自由练习: 不推进课程进度, 高分仍计入星星里程碑
      out.freePractice = true;
    }

    // 星星里程碑
    var rewards = checkStarMilestones();
    out.milestones = rewards;

    // 错题进错题本已由答题引擎处理
    Store.saveState();
    return out;
  }

  // 记录某关卡的用时/是否首次(用于评星时参考; 简化: 直接用结算传参)
  var _lvlTries = {};
  function cacheTriesForLevel(subj, idx, type, opts) {
    _lvlTries[subj + ':' + idx] = { type: type, tries: opts.triesUsed, fast: opts.fast };
  }

  // ---- 页面渲染: 闯关 Tab 升级为「课程地图 + 激励 + 成就」 ----
  function starRow(stars) {
    var h = '';
    for (var i = 0; i < 3; i++) h += i < stars ? '⭐' : '<span class="cm-star-off">☆</span>';
    return h;
  }

  // 单学科旅程地图(横向滚动)
  function journeyHtml(subj) {
    var course = COURSES[subj];
    if (!course) return '';
    var un = unlockedCount(subj);
    var p = courseProg(subj);
    var cur = curLevelIdx(subj);
    var nodesHtml = course.levels.map(function (lv, i) {
      var st = p.nodes[i] || { stars: 0, passed: false, done: false, best: 0 };
      var cls;
      var badge = '';
      if (i >= un) { cls = 'cm-node locked'; }
      else if (st.passed) { cls = 'cm-node done'; badge = (st.best >= 3 ? '🥇' : (st.best >= 2 ? '🥈' : '⭐')); }
      else if (i === cur && !st.passed) { cls = 'cm-node current'; }
      else { cls = 'cm-node todo'; }
      var body = '<button type="button" class="' + cls + '"' +
        (i >= un ? ' disabled aria-disabled="true"' : ' onclick="window.Edu.Course.launchLevel(\'' + subj + '\',' + i + ')"') + '>' +
        '<span class="cm-node-em">' + lv.em + '</span>' +
        '<span class="cm-node-name">' + esc(lv.name) + '</span>' +
        '<span class="cm-node-stars">' + starRow(st.best || (st.passed ? 3 : 0)) + '</span>' +
        (st.passed ? '<span class="cm-node-state">' + badge + '</span>' : (i >= un ? '<span class="cm-node-state">🔒</span>' : (i === cur ? '<span class="cm-node-here">📍 当前位置</span>' : ''))) +
        '</button>';
      return '<div class="cm-step">' + body +
        (i < course.levels.length - 1 ? '<span class="cm-link"></span>' : '') + '</div>';
    }).join('');

    return '<div class="cm-course" data-subj="' + subj + '">' +
      '<div class="cm-head">' +
        '<span class="cm-course-emo">' + course.emoji + '</span>' +
        '<div class="cm-course-meta"><div class="cm-course-title">' + esc(course.title) + '</div>' +
        '<div class="cm-course-journey">' + course.journey + ' · <span class="cmi-prog">' +
          (p.done ? '🏁 已通关' : '已解锁 ' + un + ' / ' + course.levels.length) + '</span></div></div>' +
      '</div>' +
      '<div class="cm-track">' + nodesHtml + '</div>' +
      '</div>';
  }

  function streakCalendar() {
    var daySet = {};
    (Store.state.records || []).forEach(function (r) { if (r && r.date) daySet[r.date] = 1; });
    var days = [];
    var now = new Date();
    for (var d = 6; d >= 0; d--) {
      var t = new Date(now.getTime() - d * 86400000);
      days.push({ key: keyOf(t), on: !!daySet[keyOf(t)] });
    }
    return '<div class="cm-streak">' + days.map(function (x, i) {
      return '<div class="cm-day' + (x.on ? ' on' : '') + '" title="' + x.key + '">' +
        (x.on ? '🔥' : '<span class="cm-day-empty">' + (i === days.length - 1 ? '今日' : '·') + '</span>') + '</div>';
    }).join('') + '</div>';
  }

  function badgesHtml() {
    var keys = Object.keys(Legacy.BADGES || {});
    var unlocked = 0;
    keys.forEach(function (k) { if (Store.state.badges && Store.state.badges[k]) unlocked++; });
    return '<div class="cm-badges">' + keys.map(function (k) {
      var got = Store.state.badges && Store.state.badges[k];
      return '<button type="button" class="cm-badge' + (got ? ' on' : ' dim') + '" data-k="' + k + '" onclick="window.Edu.Course.badgePulse(\'' + k + '\')">' +
        '<span class="cm-badge-em">' + ((Legacy.BADGES[k] && Legacy.BADGES[k].name.split(' ')[0]) || '🏅') + '</span>' +
        '<span class="cm-badge-nm">' + ((Legacy.BADGES[k] && Legacy.BADGES[k].name) || k) + '</span></button>';
    }).join('') + '</div>';
  }

  function renderCoursePage() {
    var body = document.getElementById('eduBadgesBody');
    if (!body) return;
    var act = window.eduKids ? window.eduKids.active() : null;
    var name = act ? (act.name || '宝贝') : '宝贝';
    var stars = Store.state.stars || 0;
    var streak = streakDays();
    var mapHtml = (['zh', 'math', 'en'].map(journeyHtml)).join('');

    var milestonesHtml = STAR_REWARDS.map(function (r) {
      var sc = stateCourse();
      var got = sc.rewards && sc.rewards['star_' + r.at];
      var reached = stars >= r.at;
      return '<span class="cm-mil' + (reached ? ' reached' : '') + (got ? ' got' : '') + '" title="累计 ' + r.at + ' 星 · 奖励 +' + r.bonus + ' 星星">' +
        r.em + ' ' + r.at + ' 星</span>';
    }).join('');

    body.innerHTML =
      '<div class="cm-wrap">' +
        '<div class="cm-hero">' +
          '<div class="cm-hero-em">🗺️</div>' +
          '<div class="cm-hero-meta">' +
            '<div class="cm-hero-t">' + esc(name) + ' 的闯关地图</div>' +
            '<div class="cm-hero-sub">让学习像游戏一样有趣 · 通关解锁下一关，攒星星换徽章</div>' +
          '</div>' +
        '</div>' +

        '<div class="cm-stats">' +
          '<div class="cm-stat"><div class="v">⭐ ' + stars + '</div><div class="l">星星</div></div>' +
          '<div class="cm-stat"><div class="v">🔥 ' + streak + '</div><div class="l">连续打卡</div></div>' +
        '</div>' +

        '<section class="cm-card">' +
          '<div class="cm-card-h"><span>🗺️ 课程地图</span><span class="cm-hint">左右滑动可查看每科旅程</span></div>' +
          '<div class="cm-maps">' + mapHtml + '</div>' +
        '</section>' +

        '<section class="cm-card">' +
          '<div class="cm-card-h"><span>🎖️ 星星里程碑</span></div>' +
          '<div class="cm-milestones">' + milestonesHtml + '</div>' +
          '<div class="cm-cal-wrap"><div class="cm-cal-h">🔥 最近打卡日历</div>' + streakCalendar() + '</div>' +
        '</section>' +

        '<section class="cm-card">' +
          '<div class="cm-card-h"><span>🏅 我的成就徽章</span><span class="cm-hint">已解锁 ' + unlockedBadgeCount() + ' 枚</span></div>' +
          badgesHtml() +
        '</section>' +
      '</div>';
    anim(body);
  }

  function unlockedBadgeCount() {
    var n = 0;
    for (var k in (Legacy.BADGES || {})) { if (Store.state.badges && Store.state.badges[k]) n++; }
    return n;
  }

  function badgePulse(k) {
    var el = null;
    try { el = document.querySelector('.cm-badge[data-k="' + k + '"]'); } catch (e) {}
    if (el) { el.classList.add('pulse'); setTimeout(function () { el.classList.remove('pulse'); }, 600); }
    else if (Legacy && Legacy.badgePulse) Legacy.badgePulse(k);
  }

  function anim(el) {
    if (!el) return;
    el.classList.remove('page-enter');
    void el.offsetWidth;
    el.classList.add('page-enter');
  }

  window.Edu.Course = {
    COURSES: COURSES,
    SUBJ_LABEL: SUBJ_LABEL,
    STAR_REWARDS: STAR_REWARDS,
    renderCoursePage: renderCoursePage,
    recordQuizResult: recordQuizResult,
    launchLevel: launchLevel,
    zhLevelQuizType: zhLevelQuizType,
    journeyTeaser: journeyTeaser,
    addStarBonus: addStarBonus,
    streakDays: streakDays,
    unlockedCount: unlockedCount,
    curLevelIdx: curLevelIdx,
    nodeProg: nodeProg,
    levelCount: levelCount,
    applyPass: applyPass,
    checkStarMilestones: checkStarMilestones,
    badgePulse: badgePulse,
    courseProg: courseProg
  };

  function journeyTeaser() {
    if (!Store.state.course) return '';
    // 选进度最多的学科作为「当前旅程」展示
    var best = null, bestDone = -1;
    for (var s in COURSES) {
      var p = courseProg(s);
      var done = 0;
      (p.nodes || []).forEach(function (n) { if (n && n.passed) done++; });
      if (done > bestDone) { bestDone = done; best = s; }
    }
    if (!best) best = 'zh';
    var course = COURSES[best];
    var p = courseProg(best);
    var un = unlockedCount(best);
    var cur = curLevelIdx(best);
    var done = 0;
    (p.nodes || []).forEach(function (n) { if (n && n.passed) done++; });
    var steps = course.levels.map(function (lv, i) {
      var st = p.nodes[i] || {};
      var cls = i >= un ? 'done-no' : (st.passed ? 'done-yes' : (i === cur ? 'done-cur' : 'done-no'));
      return '<span class="cmt-dot ' + cls + '" title="' + esc(lv.name) + '"></span>';
    }).join('');
    return '<button type="button" class="home-cousrteaser" onclick="window.eduNav(\'badges\')">' +
      '<span class="cmt-emo">🗺️</span>' +
      '<span class="cmt-meta"><span class="cmt-t">' + esc(course.title) + '</span>' +
      '<span class="cmt-s">' + course.journey + ' · 已通关 ' + done + ' / ' + course.levels.length + ' 关</span>' +
      '<span class="cmt-track">' + steps + '</span></span>' +
      '<span class="cmt-go">闯关地图 <i class="bi bi-chevron-right"></i></span>' +
      '</button>';
  }

  // 覆写「闯关」Tab 渲染: 由课程地图页接管; Badges 模块若已加载则同步覆写其入口
  window.renderBadges = renderCoursePage;
  if (window.Edu.Badges) window.Edu.Badges.renderBadges = renderCoursePage;
})();
