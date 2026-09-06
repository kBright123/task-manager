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

  var SUBJ_LABEL = { zh: '语文', math: '数学', en: '英语', go: '围棋', daily: '每日' };

  // 每个大关卡分成的小关卡数, 以及逐小关的基础正确率门槛(小关难度递增)
  var STAGES_PER_BIG = 5;
  var STAGE_THRESH = [50, 60, 70, 80, 85];

  // 学科课程定义: t=现有题型(用于启动答题), name/em 用于地图节点展示
  //   cfg(数学): 关卡主题难度配置 {max: 最大数值, ops: 允许运算, nocarry: 是否禁进位退位}
  //   每个大关内 5 个小关难度自动递增(范围按小关进度逐步放开), 无需家长手动设置
  var COURSES = {
    zh: {
      title: '语文识字之旅', emoji: '📖', journey: '小探险家登山', startEm: '🧗',
      levels: [
        { t: 'zi', name: '识字起航', em: '🔠' },
        { t: 'pinyin', name: '声母乐园', em: '🔤' },
        { t: 'yun', name: '韵母城堡', em: '🔡' },
        { t: 'read', name: '拼读加油站', em: '🗣️' },
        { t: 'tone', name: '四声小调', em: '🎵' },
        { t: 'ciyu', name: '反义词列车', em: '🔄' },
        { t: 'liang', name: '量词小站', em: '📦' },
        { t: 'poem', name: '古诗山川', em: '📜' },
        { t: 'stroke', name: '笔顺工坊', em: '✍️' },
        { t: 'zi', name: '常用字星球', em: '🌍' }
      ]
    },
    math: {
      title: '数学探险岛', emoji: '🔢', journey: '小火车前进', startEm: '🚂',
      levels: [
        { t: 'calc', name: '糖果加减乐园', em: '🍬', cfg: { max: 10, ops: ['+', '-'], nocarry: true } },
        { t: 'calc', name: '小桥加减镇', em: '🌉', cfg: { max: 20, ops: ['+', '-'], nocarry: true } },
        { t: 'calc', name: '进位闯关岛', em: '🏝️', cfg: { max: 20, ops: ['+', '-'] } },
        { t: 'calc', name: '山丘加减路', em: '⛰️', cfg: { max: 50, ops: ['+', '-'] } },
        { t: 'judge', name: '聪明判断站', em: '🧠', cfg: { max: 50, ops: ['+', '-'] } },
        { t: 'order', name: '排队小火车', em: '🚃' },
        { t: 'calc', name: '口诀乘法森林', em: '🌲', cfg: { max: 9, ops: ['×'] } },
        { t: 'calc', name: '除法宝藏洞', em: '💎', cfg: { max: 9, ops: ['÷'] } },
        { t: 'word', name: '生活应用山谷', em: '🏞️' },
        { t: 'calc', name: '数学巅峰城堡', em: '🏰', cfg: { max: 100, ops: ['+', '-', '×', '÷'] } }
      ]
    },
    en: {
      title: '英语星光岛', emoji: '🔤', journey: '星星路线', startEm: '🚀',
      levels: [
        { t: 'word', name: '单词灯塔', em: '🔤' },
        { t: 'dialogue', name: '对话港口', em: '💬' },
        { t: 'match', name: '配对小径', em: '🤝' },
        { t: 'listen', name: '单词回声谷', em: '🎧' },
        { t: 'dialogue', name: '问候接力', em: '🙋' },
        { t: 'word', name: '美食单词街', em: '🍔' },
        { t: 'dialogue', name: '礼貌用语站', em: '😊' },
        { t: 'match', name: '配对彩虹桥', em: '🌈' },
        { t: 'word', name: '单词冲刺', em: '🚀' },
        { t: 'dialogue', name: '对话巅峰', em: '🏔️' }
      ]
    },
    go: {
      title: '围棋少年行', emoji: '⚫', journey: '棋圣之路', startEm: '🎴',
      levels: [
        { t: 'go_atari', name: '基本气与吃子', em: '💨' },
        { t: 'go_liberty', name: '找气与逃跑', em: '🏃' },
        { t: 'go_capture', name: '打吃与提子', em: '🎯' },
        { t: 'go_connect', name: '连接与分断', em: '🔗' },
        { t: 'go_life_death', name: '死活与二眼', em: '👁️' },
        { t: 'go_ko', name: '打劫与劫材', em: '♻️' },
        { t: 'go_semeai', name: '共活与双活', em: '⚖️' },
        { t: 'go_opening', name: '布局与定式', em: '📐' },
        { t: 'go_endgame', name: '官子与收官', em: '🏁' },
        { t: 'go_quiz', name: '围棋大闯关', em: '🏆' }
      ]
    }
  };

  // 关卡难度自动配置: 由「大关主题 cfg + 当前小关进度」决定, 无需家长手动设置
  // 返回 {max, ops, nocarry}|null(仅数学/calc 类关卡有意义)
  function autoMathCfg(subj, idx, stage) {
    var lv = COURSES[subj] && COURSES[subj].levels[idx];
    if (!lv || !lv.cfg) return null;
    var c = lv.cfg;
    var max = c.max || 20;
    // 小关难度递增: 范围随小关 0..4 逐步放宽(0.5→1.0), 但不超过该大关上限
    var base = Math.max(6, Math.round(max * (0.5 + 0.1 * (stage || 0))));
    var eff = Math.min(max, base);
    return { max: eff, ops: c.ops || ['+', '-'], nocarry: !!c.nocarry };
  }

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

  // openMap 聚焦的学科(地图渲染后高亮并横向滚动到该学科卡片)
  var focusSubj = null;

  // 大关卡节点(兼容旧扁平结构迁移): 每个大关含 STAGES_PER_BIG 个小关
  //   nd.passStage : 该大关内已通关到第几小关(0..4, -1=未通过任何小关)
  //   nd.stars     : 每小关最佳星数(arr[stage])
  //   nd.done      : 5 个小关全部通关(下一大关解锁条件)
  function normalizeNode(old) {
    if (!old || typeof old.passStage === 'number') return old || makeNode(-1);
    // 旧结构 {stars,best,passed,done}: passed 视为整大关已通关
    var nd = makeNode(old.passed ? (STAGES_PER_BIG - 1) : -1);
    if (old.passed) nd.done = true;
    if (typeof old.best === 'number') { for (var s = 0; s < STAGES_PER_BIG; s++) nd.stars[s] = Math.max(nd.stars[s], old.best); }
    return nd;
  }
  function makeNode(passStage) {
    var stars = [];
    for (var s = 0; s < STAGES_PER_BIG; s++) stars.push(0);
    return { passStage: (passStage === undefined ? -1 : passStage), stars: stars, done: false, passedAt: 0, tries: 0 };
  }
  function nodeProg(subj, big) {
    var sc = stateCourse();
    sc[subj] = sc[subj] || { nodes: [], unlocked: 1, done: false };
    var nodes = sc[subj].nodes;
    while (nodes.length <= big) nodes.push(null);
    if (!nodes[big]) nodes[big] = makeNode(-1);
    else nodes[big] = normalizeNode(nodes[big]);
    return nodes[big];
  }
  function courseProg(subj) {
    var sc = stateCourse();
    sc[subj] = sc[subj] || { nodes: [], unlocked: 1, done: false };
    return sc[subj];
  }

  // 大关卡总数
  function levelCount(subj) { return (COURSES[subj] && COURSES[subj].levels) ? COURSES[subj].levels.length : 0; }

  // 大关卡是否已解锁: 第 0 大关总是解锁, 前一大大关 5 小关全通后解锁下一大大关
  function bigUnlocked(subj, big) {
    if (big <= 0) return true;
    return !!(nodeProg(subj, big - 1).done);
  }
  // 大关内第 stage 小关是否解锁: 大关本身解锁, 且上一小关已通关
  function stageUnlocked(subj, big, stage) {
    if (!bigUnlocked(subj, big)) return false;
    if (stage <= 0) return true;
    return nodeProg(subj, big).passStage + 1 >= stage;
  }
  // 某大关内已解锁小关数(0..5)
  function stageUnlockedCount(subj, big) {
    if (!bigUnlocked(subj, big)) return 0;
    var p = nodeProg(subj, big).passStage;
    return Math.min(STAGES_PER_BIG, Math.max(1, p + 2));
  }
  // 已解锁大关数(1 起)
  function unlockedCount(subj) {
    var n = 0;
    for (var i = 0; i < levelCount(subj); i++) if (bigUnlocked(subj, i)) n++;
    return Math.max(1, n);
  }
  // 当前位置: 第一个「已解锁且未通关」的小关 → {big, stage}; 全通则指向最后一小关
  function curPos(subj) {
    for (var big = 0; big < levelCount(subj); big++) {
      if (!bigUnlocked(subj, big)) break;
      var nd = nodeProg(subj, big);
      if (nd.passStage < STAGES_PER_BIG - 1) return { big: big, stage: nd.passStage + 1 };
    }
    return { big: Math.max(0, levelCount(subj) - 1), stage: STAGES_PER_BIG - 1 };
  }
  function curLevelIdx(subj) { return curPos(subj).big; }
  // 通关第 (big,stage) 后, 下一个要进入的关卡
  function nextPos(subj, big, stage) {
    if (stage + 1 < STAGES_PER_BIG && bigUnlocked(subj, big)) return { big: big, stage: stage + 1 };
    if (big + 1 < levelCount(subj) && bigUnlocked(subj, big + 1)) return { big: big + 1, stage: 0 };
    return null;
  }

  // 通关某一关需要的题型启动: 复用各工作台
  // idx=大关卡, stage=该大关内的小关卡(0..4). 未解锁(大关未解锁或小关前序未通)则提示.
  function launchLevel(subj, idx, stage) {
    var lv = COURSES[subj].levels[idx];
    if (!lv) return;
    if (!bigUnlocked(subj, idx)) { if (Speech && Speech.toast) Speech.toast('先通关前面的关卡才能解锁这里哦 🔒'); return; }
    stage = (typeof stage === 'number' && stage >= 0 && stage < STAGES_PER_BIG) ? stage : 0;
    if (!stageUnlocked(subj, idx, stage)) { if (Speech && Speech.toast) Speech.toast('先通过前面的小关才能解锁这里哦 🔒'); return; }
    // 语文题型在导入面板中有子模式(声母/韵母/拼读/四声), 需落到真正的答题 type 以匹配结算
    var quizT = (subj === 'zh') ? zhLevelQuizType(lv.t) : (subj === 'go') ? goLevelQuizType(lv.t) : lv.t;
    var type = lv.t;
    var NavP = window.Edu && window.Edu.Nav;
    var pref = (NavP && NavP.getPref) ? NavP.getPref() : null;
    // 记录当前学科进学习页, 供 eduNav→wbInit 按 lastSubj 打开对应面板(避免回退到上一学科/拼音)
    var setPref = (function (origPref) {
      return function (key) {
        if (origPref) { origPref.lastSubj = subj; origPref.mode = 'workbench'; origPref.subj = subj; if (key) origPref[key] = type; if (NavP && NavP.savePref) NavP.savePref(origPref); }
      };
    })(pref);
    var prefKey = subj === 'math' ? 'wbMath' : (subj === 'en' ? 'wbEn' : (subj === 'go' ? 'wbGo' : (type === 'pinyin' || type === 'yun' || type === 'read' || type === 'tone' ? null : (type === 'ciyu' || type === 'liang' ? null : 'wbZh'))));
    setPref(prefKey);
    if (type === 'pinyin' || type === 'yun' || type === 'read' || type === 'tone') { if (pref) { pref.wbZh = 'pinyin'; pref.wbPy = type; } setPref(); }
    else if (type === 'ciyu' || type === 'liang') { if (pref) { pref.wbZh = 'ciyu'; pref.wbCy = type === 'liang' ? 'liang' : 'fan'; } setPref(); }
    else if (subj === 'go') { if (pref) { pref.wbGo = type; } setPref(); }

    // 进入学习页展示答题(若从全屏闯关地图进入, 先关闭覆盖层, 否则遮挡答题页)。
    // 注意: eduNav('learn') 内部会 Store.loadAllState() 重读持久化状态, 从而清空内存里
    // 的 courseIn. 因此闯关上下文(含关卡难度 cfg)必须在 eduNav 之后再写入并启动题型,
    // 否则 wbInit 重渲染时会读取已被清空的 courseIn 而回落默认难度.
    if (closeMapFull) closeMapFull();
    if (window.eduNav) window.eduNav('learn');

    // 记录「正在闯的第几大关/第几小关」, 供结算时回写 course 进度
    Store.state.courseIn = { subj: subj, idx: idx, stage: stage, t: quizT, startedAt: Date.now() };
    // 关卡难度自动递增: 由大关主题 + 小关进度算出, 答题器据此生成对应难度题目
    var mcfg = autoMathCfg(subj, idx, stage);
    if (mcfg) Store.state.courseIn.cfg = mcfg;
    Store.state.courseInflight = 1;

    if (subj === 'math') { if (window.wbMath) window.wbMath(type === 'did' ? 'calc' : type); }
    else if (subj === 'en') { if (window.wbEn) window.wbEn(type); }
    else if (subj === 'zh' && window.wbZh) {
      if (type === 'pinyin' || type === 'yun' || type === 'read' || type === 'tone') {
        window.wbZh('pinyin');
        if ((type === 'yun' || type === 'read' || type === 'tone') && window.wbPinyin) window.wbPinyin(type);
      } else if (type === 'ciyu' || type === 'liang') {
        window.wbZh('ciyu');
        if (window.wbCiyu) window.wbCiyu(type === 'liang' ? 'liang' : 'fan');
      } else {
        window.wbZh(type);
      }
    }
    else if (subj === 'go' && window.wbGo) {
      window.wbGo(type);
    }
  }

  // 语文关卡题型 → 实际渲染/结算的答题 type
  function zhLevelQuizType(t) {
    if (t === 'ciyu') return 'fan';
    if (t === 'yun' || t === 'read' || t === 'tone' || t === 'pinyin' || t === 'zi' || t === 'poem' || t === 'stroke') return t;
    return t;
  }
  // 围棋关卡题型 → 实际渲染/结算的答题 type
  function goLevelQuizType(t) {
    // 围棋关卡 go_xxx → 归一化为工作台题型 xxx, 与 quiz.type/结算匹配
    return String(t || '').replace(/^go_/, '') || t;
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

  // 通关某个大关的小关: 记录星级/清除推进; 每小关首次通关 +3 星星; 大关 5 小关全通则 done + 解锁下一大关
  // 返回 { name(大关名), stageName, stars, allPassed, bigDone, next }
  function applyPass(subj, idx, stage, stars) {
    var p = courseProg(subj);
    var st = nodeProg(subj, idx);
    var bigName = COURSES[subj].levels[idx].name;
    var isNew = st.passStage < stage;
    st.stars[stage] = Math.max(st.stars[stage] || 0, stars);
    st.passStage = Math.max(st.passStage || -1, stage);
    if (stage + 1 >= STAGES_PER_BIG) {
      st.done = true;
      st.passedAt = Date.now();
    }
    // 首次通关该小关才 +3 星星(重打同一小关不重复奖励)
    if (isNew) addStarBonus(3, (SUBJ_LABEL[subj] || subj) + '通关·' + bigName);
    var bigDone = st.done;
    // 整科通关
    var allPassed = true;
    for (var i = 0; i < levelCount(subj); i++) { if (!nodeProg(subj, i).done) { allPassed = false; break; } }
    if (allPassed) p.done = true;
    var next = nextPos(subj, idx, stage);
    return { name: bigName, stageName: '第' + (idx + 1) + '大关·第' + (stage + 1) + '小关', stage: stage, stars: stars, allPassed: allPassed, bigDone: bigDone, next: next };
  }

  // 当前正在闯的关是否「此前已通关」(重打) → 答对获得的星星减半
  function isLevelCleared(ci) {
    if (!ci || !ci.subj) return false;
    try {
      return nodeProg(ci.subj, ci.idx).passStage >= ci.stage;
    } catch (e) { return false; }
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

    var out = { subj: subj, type: type, right: right, total: total, pct: pct, stars: stars, passed: false, levelIdx: -1, stage: -1 };

    // 是否正处在关卡闯关中(若直接答题启动, courseIn 缺失则尝试按当前位置匹配)
    var inflight = Store.state.courseIn || null;
    var idx = -1, stage = 0;
    if (inflight && inflight.subj === subj && inflight.t === type) {
      idx = inflight.idx;
      stage = (typeof inflight.stage === 'number') ? inflight.stage : 0;
    } else {
      // 尝试按题型对映到当前未通关大关的第一未通小关
      var cp = (function(){ try { return curPos(subj); } catch (e) { return { big: 0, stage: 0 }; } })();
      var lvT = (subj === 'zh') ? zhLevelQuizType(COURSES[subj].levels[cp.big].t) : (subj === 'go') ? goLevelQuizType(COURSES[subj].levels[cp.big].t) : COURSES[subj].levels[cp.big].t;
      if (lvT === type && stageUnlocked(subj, cp.big, cp.stage) && !nodeProg(subj, cp.big).done) { idx = cp.big; stage = cp.stage; }
    }

    if (idx >= 0 && COURSES[subj] && COURSES[subj].levels[idx]) {
      out.levelIdx = idx;
      out.stage = stage;
      // 逐小关难度递增: 通关所需正确率逐小关抬高
      var th = STAGE_THRESH[Math.min(stage, STAGES_PER_BIG - 1)] | 0;
      var passed = (pct >= th) || (stars >= 3);
      out.passed = passed;
      var opts = { fast: !!fast, triesUsed: triesUsed };
      cacheTriesForLevel(subj, idx, type, opts);
      if (passed) {
        var res = applyPass(subj, idx, stage, stars);
        out.levelName = res.name;
        out.stageName = res.stageName;
        out.stageNow = stage;
        out.stageCur = Math.max(stage, nodeProg(subj, idx).passStage);
        out.gotStars = stars;
        out.bigDone = res.bigDone;
        var nxt = res.next;
        out.next = nxt || null;
        out.unlockedNext = nxt
          ? ((nxt.big > idx)
              ? COURSES[subj].levels[nxt.big].name                     // 解锁下一大关
              : '第' + (nxt.stage + 1) + '小关')                         // 同大关下一小关
          : null;
        out.allPassed = res.allPassed;
        out.passedNow = true;
      } else {
        var pn = nodeProg(subj, idx);
        pn.tries = (pn.tries || 0) + 1;
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
  // ---- 闯关地图: 蛇形路径视觉化 ----
  var SNAKE_W = 2340;   // 地图逻辑宽度(px), 含最后一关的延长路段, 窄屏横向滑动
  var SNAKE_H = 560;    // 地图逻辑高度, 更高撑满全屏视口
  var NODE_D = 80;      // 节点直径(小圆更贴路面, 视觉上落在路中间)
  var SNAKE_X0 = 150;   // 首节点中心 x(第一大关即起点)
  var SNAKE_DX = 215;   // 节点中心 x 间距(加宽让蜿蜒山路与小关点更舒展)
  var SNAKE_Y_A = 210;  // 第一行节点中心 y
  var SNAKE_Y_B = 372;  // 第二行节点中心 y(蛇形)
  var SUBJ_THEME = {    // 三学科各一固定主题(识别度高、场景各自不同)
    zh: 'cm-theme-zh',
    math: 'cm-theme-math',
    en: 'cm-theme-en',
    go: 'cm-theme-go'
  };
  function subjTheme(subj) {
    return SUBJ_THEME[subj] || 'cm-theme-zh';
  }

  // 每学科的背景装饰层(铺满画布的 emoji 场景, 位于道路/节点之下)
  function subjScenery(subj) {
    var els = {
      zh: [
        ['c-sun','☀️'],['c-sky','☁️'],['c-sky2','☁️'],['c-bird','🦅'],
        ['c-hill','⛰️'],['c-hill2','🏔️'],
        ['c-tree1','🌳'],['c-tree2','🌲'],['c-tree3','🌳'],['c-tree4','🌲'],['c-tree5','🌵'],
        ['c-bush','🌿'],['c-bush2','🎋'],
        ['c-flower','🌼'],['c-flower2','🌸'],['c-flower3','🌻'],
        ['c-fish','🐟'],['c-fish2','🐡']
      ],
      math: [
        ['c-sky','🌙'],['c-sky2','✨'],['c-sky3','🌟'],['c-sat','🛰️'],['c-rocket','🚀'],
        ['c-planet','🪐'],['c-planet2','🌍'],
        ['c-geo','🔷'],['c-geo2','🔺'],['c-geo3','🔶'],['c-geo4','▪️'],
        ['c-star','⭐'],['c-meteor','☄️']
      ],
      en: [
        ['c-sun','🌞'],['c-sky','☁️'],['c-sky2','☁️'],['c-bird','🦩'],
        ['c-island','🏝️'],['c-island2','🏝️'],['c-sail','⛵'],['c-sail2','🚤'],
        ['c-dolphin','🐬'],['c-wave','🌊'],['c-wave2','🌊'],
        ['c-crab','🦀'],['c-shell','🐚'],['c-anchor','⚓'],['c-fish','🐠']
      ],
      go: [
        ['c-sky','🌅'],['c-sky2','☁️'],['c-mountain','🏔️'],['c-tree','🌲'],
        ['c-pavilion','🏯'],['c-stone','⚫'],['c-stone2','⚪'],
        ['c-bamboo','🎋'],['c-bamboo2','🎍'],['c-koi','🐟'],['c-dragon','🐉'],
        ['c-sakura','🌸'],['c-sakura2','🌸'],['c-lantern','🏮'],['c-fan','🪭']
      ]
    }[subj] || [];
    return '<div class="cm-campus" aria-hidden="true">' +
      els.map(function (e) { return '<span class="' + e[0] + '">' + e[1] + '</span>'; }).join('') +
      '</div>';
  }
  // 节点中心坐标: 蛇形交替两行
  function snakeXY(i) {
    var x = SNAKE_X0 + i * SNAKE_DX;
    var y = (i % 2 === 0) ? SNAKE_Y_A : SNAKE_Y_B;
    return { x: x, y: y };
  }
  // 三次贝塞尔插值: 与 snakePath 的 S 形路径一致 (0≤t≤1)
  function bezPt(a, b, mid, t) {
    var u = 1 - t;
    var w0 = u * u * u, w1 = 3 * u * u * t, w2 = 3 * u * t * t, w3 = t * t * t;
    return {
      x: w0 * a.x + w1 * a.x + w2 * b.x + w3 * b.x,
      y: w0 * a.y + w1 * mid + w2 * mid + w3 * b.y
    };
  }
// 大关 i 的第 s 个小关在路径上的坐标(沿「离开本大关城堡、通往下一大关」的路段排布,
  // 最后一关沿用向前延伸的直路; 起点即第一大关, 小关从城堡圆之后开始展开)
  function stageXY(subj, i, s) {
    var n = levelCount(subj);
    var a = snakeXY(i);
    var b = (i + 1 < n) ? snakeXY(i + 1) : { x: a.x + SNAKE_DX, y: a.y };   // 最后的城堡向右侧延长一段直路承载收官小关
    var mid = (a.y + b.y) / 2;
    var t = 0.10 + 0.15 * s;                         // 0.10..0.70, 紧贴本大关圆之后、沿路通往下一大关
    return bezPt(a, b, mid, t);
  }
  // 小人在地图上的位置: 始终落在「即将要去的那一关」关卡点上, 通关后沿道路向前移动
  // 大关通关 → 站在城堡上; 大关内未通 → 站在该大关待闯的小关点(石头)上
  function mascotXY(subj) {
    var n = levelCount(subj);
    if (n === 0) return { x: SNAKE_X0, y: SNAKE_Y_A };
    var p = curPos(subj);
    var big = Math.min(p.big, n - 1);
    var node_done = nodeProg(subj, big).done;
    if (node_done) return snakeXY(big);
    return stageXY(subj, big, Math.min(p.stage, STAGES_PER_BIG - 1));
  }
  // 大关 i 的 5 个小关, 作为山路上的小石头, 沿「离开本大关、前往下一大关」的路段依次排布
  function stageDots(subj, i) {
    var nd = nodeProg(subj, i);
    var bigLk = !bigUnlocked(subj, i);
    var cur = curPos(subj);
    // 石头 emoji 池: 每大关不同石头, 增加视觉辨识度
    var stones = ['🪨','🗿','🏔️','🪵','🌰','🍂','🍄','🌻','🌲','🌳','🌴','🌵','🪸','🐚','🪷','🪻'];
    var base = (i * 7) % stones.length;
    var dots = [];
    for (var s = 0; s < STAGES_PER_BIG; s++) {
      var p = stageXY(subj, i, s);
      var lk = bigLk || !stageUnlocked(subj, i, s);
      var done = !lk && (nd.passStage >= s);
      var isCur = !lk && !done && cur.big === i && cur.stage === s;
      var cls = 'cm-dot' + (done ? ' done' : (isCur ? ' current' : (lk ? ' locked' : ' todo')));
      var oc = lk ? '' : 'window.Edu.Course.launchLevel(\'' + subj + '\',' + i + ',' + s + ')';
      var stone = stones[(base + s) % stones.length];
      dots.push('<button type="button" class="' + cls + '" style="left:' + Math.round(p.x) + 'px;top:' + Math.round(p.y) + 'px;"' +
        (lk ? ' disabled aria-disabled="true"' : ' onclick="' + oc + '"') +
        ' title="第' + (i + 1) + '大关 · 第' + (s + 1) + '小关">' + stone + '</button>');
    }
    return dots.join('');
  }
  // 蛇形连接路径(SVG): 相邻节点用 S 形贝塞尔相连, 最后一关尾接一段向前延伸的直路
  function snakePath(subj, curBig) {
    var n = levelCount(subj);
    if (n === 0) return { segs: [] };
    var segs = [];
    for (var i = 0; i < n - 1; i++) {
      segs.push({ a: snakeXY(i), b: snakeXY(i + 1), used: curBig > i ? 'used' : 'todo' });
    }
    var last = snakeXY(n - 1);
    segs.push({ a: last, b: { x: last.x + SNAKE_DX, y: last.y }, used: curBig >= n ? 'used' : 'todo' });
    return { segs: segs };
  }
  // 单个大关卡节点圆
  function snakeNode(subj, i, lv, curBig) {
    var bigLk = !bigUnlocked(subj, i);
    var nd = nodeProg(subj, i);
    var bigDone = nd.done;
    var intro = snakeXY(i);
    var cls = 'cm-big' + (bigLk ? ' locked' : (bigDone ? ' done' : (curBig === i ? ' current' : ' open')));
    // 节点状态标识: 已通=⭐, 当前=🌟(呼吸发光), 未解锁=🔒, 其余可达无图标
    var badge;
    if (bigLk) badge = '<span class="cm-node-badge lock">🔒</span>';
    else if (curBig === i) badge = '<span class="cm-node-badge cur">🌟</span>';
    else if (bigDone) badge = '<span class="cm-node-badge ok">⭐</span>';
    else badge = '';
    var short = String(lv.name || '').slice(0, 2);
    var oc = bigLk ? '' : 'window.Edu.Course.launchLevel(\'' + subj + '\',' + i + ',' + (curBig === i ? curPosStg(subj, i) : 0) + ')';
    var isCur = (curBig === i && !bigLk);
    return '<div class="cm-zone' + (isCur ? ' is-cur' : '') + '" style="left:' + intro.x + 'px;top:' + intro.y + 'px;">' +
      '<button type="button" class="' + cls + '"' + (bigLk ? ' disabled aria-disabled="true"' : ' onclick="' + oc + '"') + ' title="' + esc(lv.name) + '">' +
        '<span class="cm-node-num">' + (i + 1) + '</span>' +
        '<span class="cm-node-short">' + esc(short) + '</span>' +
        badge +
      '</button>' +
      '<div class="cm-node-label">' + esc(lv.name) + '</div>' +
    '</div>';
  }
  // 当前大关内应继续的小关
  function curPosStg(subj, big) {
    var p = curPos(subj);
    return (p.big === big) ? Math.min(STAGES_PER_BIG - 1, p.stage) : 0;
  }

  // 旅程 + 进度说明(用于地图头部/全屏顶栏): 如「小探险家登山 · 已解锁 1 / 8 大关」
  function journeyLine(subj) {
    var course = COURSES[subj];
    if (!course) return '';
    var n = levelCount(subj);
    var done = courseProg(subj).done;
    return course.journey + ' · ' + (done ? '🏁 已通关' : '已解锁 ' + unlockedCount(subj) + ' / ' + n + ' 大关');
  }

  // 下一步指引提示(与旅程合并为一行, 避免重复描述): 如「⭐ 下一步：去「识字起航」」
  function nextHint(subj) {
    var course = COURSES[subj];
    if (!course) return '';
    var n = levelCount(subj);
    var doneAll = courseProg(subj).done;
    if (doneAll) return '🏁 已完成全部大关！';
    var curBig = Math.min(curPos(subj).big, n - 1);
    return '⭐ 下一步：去「' + esc(course.levels[curBig].name) + '」';
  }

  // 顶部进度条: 每大关一格, 已通过=金色✓, 当前任务=⭐(呼吸, 明示「下一步去哪座城堡」), 未解锁=灰锁
  function progressBarHtml(subj) {
    var course = COURSES[subj];
    if (!course) return '';
    var n = levelCount(subj);
    var doneAll = courseProg(subj).done;
    var curBig = Math.min(curPos(subj).big, n - 1);
    // 按需求去掉大关点阵进度条, 仅保留「下一步」指引一行
    var hint = doneAll
      ? '🏁 已完成全部大关！'
      : '⭐ 下一步：去「' + esc(course.levels[curBig].name) + '」';
    return '<div class="cm-progress">' +
      '<div class="cm-progress-hint">' + hint + '</div>' +
      '</div>';
  }

  function journeyHtml(subj, focus) {
    var course = COURSES[subj];
    if (!course) return '';
    var n = levelCount(subj);
    var curBig = Math.min(curPos(subj).big, n - 1);
    var curLv = course.levels[curBig];
    var sp = snakePath(subj, curBig);

    // 蛇形节点 + 路径 + 角色指示器
    var nodes = course.levels.map(function (lv, i) { return snakeNode(subj, i, lv, curBig); }).join('');
    // 小关 = 山路上的小圆点: 每大关 5 个, 沿通往该城堡的路段排布(位于道路层之上、城堡圆之下)
    var dots = '<div class="cm-dots">' + course.levels.map(function (lv, i) { return stageDots(subj, i); }).join('') + '</div>';
    // 蜿蜒山路: 每段 = 路面(Road 底色) + 中心虚线(路标) + 已走过的金色覆盖
    var segs = '';
    for (var i = 0; i < sp.segs.length; i++) {
      var a = sp.segs[i].a, b = sp.segs[i].b;
      var mid = (a.y + b.y) / 2;
      var d = 'M' + a.x + ' ' + a.y + ' C' + a.x + ' ' + mid + ',' + b.x + ' ' + mid + ',' + b.x + ' ' + b.y;
      var st = sp.segs[i].used;
      segs += '<g class="cm-seg-g ' + st + '">' +
        '<path class="cm-road" d="' + d + '"/>' +
        '<path class="cm-center" d="' + d + '"/>' +
        '</g>';
    }
    var mascot = '';
    if (levelCount(subj) > 0) {
      var m = mascotXY(subj);
      mascot = '<div class="cm-mascot" style="left:' + Math.round(m.x - 18) + 'px;top:' + Math.round(m.y - 20) + 'px;">🧒</div>';
    }

    return '<div class="cm-course' + (focus ? ' focus' : '') + '" data-subj="' + subj + '" id="cmCourse' + subj + '">' +
      '<div class="cm-head">' +
        '<span class="cm-course-emo">' + course.emoji + '</span>' +
        '<div class="cm-course-meta"><div class="cm-course-title">' + esc(course.title) + '</div>' +
        '<div class="cm-course-journey ' + subjTheme(subj) + '">' + journeyLine(subj) + '</div></div>' +
      '</div>' +
      progressBarHtml(subj) +
      '<div class="cm-snake-wrap ' + subjTheme(subj) + '">' +
        '<div class="cm-snake" aria-label="闯关地图，可左右滑动">' +
        '<div class="cm-snake-inner" style="width:' + SNAKE_W + 'px;height:' + SNAKE_H + 'px;">' +
          subjScenery(subj) +
          '<svg class="cm-path" viewBox="0 0 ' + SNAKE_W + ' ' + SNAKE_H + '" preserveAspectRatio="none" aria-hidden="true">' + segs + '</svg>' +
          dots + nodes + mascot +
        '</div>' +
      '</div>' +
        '<div class="cm-snake-foot">' +
          '<span class="cm-swipe-hint">◀ 左右滑动查看关卡 ▶</span>' +
        '</div>' +
      '</div>' +
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

  var activeMapSubject = 'zh';

  // 地图卡片内的「学科切换」标签(语文/数学/英语)。slotId: 标签点击后要重绘的地图容器 id
  function mapTabsHtml(slotId) {
    slotId = slotId || 'cmMapSlot';
    return '<div class="cm-tabs">' + (['zh', 'math', 'en'].map(function (s) {
      var c = COURSES[s];
      var un = unlockedCount(s);
      var done = courseProg(s).done;
      var act = s === activeMapSubject;
      return '<button type="button" class="cm-tab' + (act ? ' active' : '') + '" data-subj="' + s + '" onclick="window.Edu.Course.switchMapSubject(\'' + s + '\',\'' + slotId + '\')" aria-pressed="' + act + '">' +
        '<span class="cm-tab-em">' + c.emoji + '</span>' +
        '<span class="cm-tab-meta"><span class="cm-tab-name">' + SUBJ_LABEL[s] + ' · ' + esc(c.title.slice(0, 4)) + '</span>' +
        '<span class="cm-tab-prog">' + (done ? '🏁 已通关' : '已解锁 ' + un + ' / ' + c.levels.length + ' 大关') + '</span></span>' +
        '</button>';
    })).join('') + '</div>';
  }

  // 渲染当前学科的地图(仅一张蛇形地图, 不再三科堆叠)。slotId: 地图容器 id(全屏视图用独立 id 避免与卡片冲突)
  function mapSlotHtml(slotId) {
    return '<div class="cm-maps" id="' + (slotId || 'cmMapSlot') + '">' + journeyHtml(activeMapSubject, true) + '</div>';
  }

  // 切换到某学科地图(仅重绘地图卡片/全屏地图内部, 不重绘整页)
  // 切换学科地图。slotId: 地图容器 id; tabScope: 仅重绘哪个视图内的标签(class 前缀), null=全部
  function switchMapSubject(s, slotId) {
    if (!(s in COURSES) || s === activeMapSubject) return;
    activeMapSubject = s;
    slotId = slotId || 'cmMapSlot';
    var slot = document.getElementById(slotId);
    var scope = slot ? slot.closest('.edu-map-full, .cm-card') : null;
    var tabsScope = scope ? scope.querySelectorAll('.cm-tab') : [];
    var tabs = tabsScope.length ? tabsScope : document.querySelectorAll('.cm-tab');
    for (var i = 0; i < tabs.length; i++) {
      var on = tabs[i].getAttribute('data-subj') === s;
      tabs[i].classList.toggle('active', on);
      if (tabs[i].setAttribute) tabs[i].setAttribute('aria-pressed', on ? 'true' : 'false');
    }
    if (slot) {
      slot.innerHTML = mapSlotHtml();
      anim(slot);
      var fCourse = document.getElementById('cmCourse' + s);
      if (fCourse) {
        setTimeout(function () {
          try { if (fCourse.scrollIntoView) fCourse.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'start' }); } catch (e) {}
        }, 100);
      }
    }
  };

  function renderCoursePage() {
    var body = document.getElementById('eduBadgesBody');
    if (!body) return;
    if (typeof window.renderWelcomeInto === 'function') window.renderWelcomeInto('badgesWelcome', '闯关赢星星，集齐你的勋章');
    var stars = Store.state.stars || 0;

    // 进入时的学科: 优先来自首页某科的「闯关模式」入口(focusSubj)
    if (focusSubj in COURSES) activeMapSubject = focusSubj;

    var milestonesHtml = STAR_REWARDS.map(function (r) {
      var sc = stateCourse();
      var got = sc.rewards && sc.rewards['star_' + r.at];
      var reached = stars >= r.at;
      return '<span class="cm-mil' + (reached ? ' reached' : '') + (got ? ' got' : '') + '" title="累计 ' + r.at + ' 星 · 奖励 +' + r.bonus + ' 星星">' +
        r.em + ' ' + r.at + ' 星</span>';
    }).join('');

    body.innerHTML =
      '<div class="cm-wrap">' +
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
    // 聚焦学科: 滚动到该学科地图卡片并高亮
    if (focusSubj) {
      var fCourse = document.getElementById('cmCourse' + focusSubj);
      if (fCourse) {
        setTimeout(function () {
          try { if (fCourse.scrollIntoView) fCourse.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'start' }); } catch (e) {}
        }, 120);
      }
      focusSubj = null;
    }
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
    STAGES_PER_BIG: STAGES_PER_BIG,
    renderCoursePage: renderCoursePage,
    recordQuizResult: recordQuizResult,
    launchLevel: launchLevel,
    zhLevelQuizType: zhLevelQuizType,
    journeyTeaser: journeyTeaser,
    addStarBonus: addStarBonus,
    streakDays: streakDays,
    journeyLine: journeyLine,
    nextHint: nextHint,
    unlockedCount: unlockedCount,
    curLevelIdx: curLevelIdx,
    curPos: curPos,
    nextPos: nextPos,
    nodeProg: nodeProg,
    levelCount: levelCount,
    applyPass: applyPass,
    isLevelCleared: isLevelCleared,
    checkStarMilestones: checkStarMilestones,
    badgePulse: badgePulse,
    courseProg: courseProg,
    bigUnlocked: bigUnlocked,
    stageUnlocked: stageUnlocked,
    stageUnlockedCount: stageUnlockedCount,
    switchMapSubject: switchMapSubject,
    openMap: openMap,
    openMapFull: openMapFull,
    closeMapFull: closeMapFull
  };

  // 「闯关模式」按钮: 打开该学科的课程地图(全关卡, 可左右滑动选择已解锁小关), 并聚焦该学科
  function openMap(subj) {
    if (!(subj in COURSES)) subj = 'zh';
    focusSubj = subj;
    var NavP = window.Edu && window.Edu.Nav;
    if (NavP && NavP.getPref) {
      var pref = NavP.getPref();
      if (pref) { pref.lastSubj = subj; pref.mode = 'workbench'; pref.subj = subj; if (NavP.savePref) NavP.savePref(pref); }
    }
    if (window.eduNav) window.eduNav('badges');
  }

  // 首页点击「闯关模式」: 打开独立全屏闯关地图页(不跳到闯关 Tab), 展示该学科的蛇形地图
  function openMapFull(subj) {
    if (!(subj in COURSES)) subj = 'zh';
    activeMapSubject = subj;
    var NavP = window.Edu && window.Edu.Nav;
    if (NavP && NavP.getPref) {
      var pref = NavP.getPref();
      if (pref) { pref.lastSubj = subj; pref.mode = 'workbench'; pref.subj = subj; if (NavP.savePref) NavP.savePref(pref); }
    }
    var full = document.getElementById('eduMapFull');
    if (!full) { openMap(subj); return; }
    var tabs = document.getElementById('emfTabs');
    var body = document.getElementById('eduMapFullBody');
    var journey = document.getElementById('emfJourney');
    // 全屏地图只展示当前学科, 不需要学科切换, 故不渲染学科标签
    if (tabs) tabs.innerHTML = '';
    if (tabs) tabs.style.display = 'none';
    // 旅程 + 下一步指引合并为一行, 去除「小探险家 ·」重复描述(内联 ⭐ 提示由 CSS 隐藏)
    if (journey) journey.textContent = journeyLine(subj) + '　' + nextHint(subj);
    if (body) body.innerHTML = mapSlotHtml('cmMapSlotFull');
    // 学科主题背景铺满整个全屏地图(含顶栏/进度提示), 而非仅地图盒子
    full.className = 'edu-map-full ' + subjTheme(subj);
    full.style.display = 'flex';
    // 立即(同步)按视口缩放蛇形画布: 避免先以 1680×560 原尺寸渲染再缩小造成闪烁.
    // 用 window 视口尺寸而非 clientHeight, 避免触发一次性同步 reflow(点击更快);
    // 全屏遮罩为 position:fixed 铺满视口, 故视口尺寸即可代表可用尺寸.
    var inner = body.querySelector('.cm-snake-inner');
    var wrap = body.querySelector('.cm-snake');
    var availW = window.innerWidth;
    var availH = window.innerHeight - 60;
    // 仅宽屏桌面才整体缩放铺满; 窄屏与平板(含 iPad 竖/横屏)保持画布原生宽度, 靠 .cm-snake 横向滚动,
    // 避免 iPad(竖屏 ~768px) 被缩到最小且 overflow:hidden 导致无法左右滚动.
    if (inner && wrap && availW >= 1100) {
      var k = Math.min(availW / SNAKE_W, availH / SNAKE_H);
      k = Math.max(0.25, Math.min(1.6, k));
      inner.style.width = SNAKE_W + 'px';
      inner.style.height = SNAKE_H + 'px';
      inner.style.transform = 'scale(' + k + ')';
      inner.style.transformOrigin = 'top left';
      inner.style.marginBottom = (-(SNAKE_H * (1 - k))) + 'px';
      wrap.style.width = Math.round(SNAKE_W * k) + 'px';
      wrap.style.height = Math.round(SNAKE_H * k) + 'px';
      wrap.style.margin = '0 auto';
      wrap.style.overflow = 'hidden';
      if (body) { body.style.display = 'flex'; body.style.alignItems = 'center'; }
    } else if (inner && wrap) {
      // 手机窄屏: 保持原横向滑动 + 高度撑满
      var rectW = wrap.getBoundingClientRect();
      if (rectW.height > 40) inner.style.height = rectW.height + 'px';
    }
    var dock = document.getElementById('eduBottomNav');
    if (dock) dock.style.display = 'none';
    document.documentElement.style.overflow = 'hidden';
    document.documentElement.style.height = '100%';
  }

  // 关闭独立全屏闯关地图页, 回到来源页
  function closeMapFull() {
    var full = document.getElementById('eduMapFull');
    if (full) full.style.display = 'none';
    var body = document.getElementById('eduMapFullBody');
    if (body) body.innerHTML = '';
    var tabs = document.getElementById('emfTabs');
    if (tabs) tabs.innerHTML = '';
    if (tabs) tabs.style.display = '';
    var dock = document.getElementById('eduBottomNav');
    if (dock) dock.style.display = '';
    document.documentElement.style.overflow = '';
    document.documentElement.style.height = '';
  }

  function journeyTeaser() {
    if (!Store.state.course) return '';
    // 选进度最多的学科作为「当前旅程」展示
    var best = null, bestDone = -1;
    for (var s in COURSES) {
      var p = courseProg(s);
      var done = 0;
      (p.nodes || []).forEach(function (n) { if (n && n.done) done++; });
      if (done > bestDone) { bestDone = done; best = s; }
    }
    if (!best) best = 'zh';
    var course = COURSES[best];
    var un = unlockedCount(best);
    var cur = curLevelIdx(best);
    var done = 0;
    courseProg(best).nodes.forEach(function (n) { if (n && n.done) done++; });
    var steps = course.levels.map(function (lv, i) {
      var st = nodeProg(best, i);
      var cls = i >= un ? 'done-no' : (st.done ? 'done-yes' : (i === cur ? 'done-cur' : 'done-no'));
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
