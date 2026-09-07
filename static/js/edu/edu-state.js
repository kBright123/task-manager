(function () {
  'use strict';
  var C = window.Edu.Constants;

  function load(k) { try { return JSON.parse(localStorage.getItem(k)); } catch(e){ return null; } }
  function save(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch(e){} }
  function clone(o) { return JSON.parse(JSON.stringify(o)); }

  var state = { stars: 0, records: [], wrong: [], settings: {}, usage: {}, maxCombo: 0, badges: {}, submits: 0, wishes: [], wishLog: [], level: {}, starLog: [], starAwards: [], dailySecs: {}, giftPrices: {}, redeemed: [], usageExtra: {} };
  var wb = {};
  var recentExclude = [];

  function kidSyncKey() { var a = window.eduKids ? window.eduKids.active() : null; return a ? a.id : 'default'; }
  function stateKeyFor(kidId) { return C.LS_BASE + '_' + (kidId || kidSyncKey()); }
  function wbKeyFor(kidId) { return C.STR_BASE + '_' + (kidId || kidSyncKey()); }
  function stateKey() { return stateKeyFor(); }
  function wbKey() { return wbKeyFor(); }

  function dayKey(dt) {
    var t = dt || new Date();
    var mm = t.getMonth() + 1, dd = t.getDate();
    return String(t.getFullYear()) + '-' + (mm < 10 ? '0' : '') + mm + '-' + (dd < 10 ? '0' : '') + dd;
  }

  function loadAllState() {
    var s = load(stateKey());
    if (s && typeof s === 'object' && !Array.isArray(s)) {
      Object.keys(state).forEach(function(k){ delete state[k]; });
      Object.assign(state, s);
    }
    var w = load(wbKey());
    if (w && typeof w === 'object' && !Array.isArray(w)) {
      Object.keys(wb).forEach(function(k){ delete wb[k]; });
      Object.assign(wb, w);
    }
    // 补齐默认字段: 旧版 localStorage / 非法备份恢复可能导致缺字段
    mergeSet({});
    state.usage = (state.usage && typeof state.usage === 'object') ? state.usage : {};
    state.badges = (state.badges && typeof state.badges === 'object') ? state.badges : {};
    state.level = (state.level && typeof state.level === 'object') ? state.level : {};
    state.adv = (state.adv && typeof state.adv === 'object') ? state.adv : {};
    state.dailySecs = (state.dailySecs && typeof state.dailySecs === 'object') ? state.dailySecs : {};
    state.usageExtra = (state.usageExtra && typeof state.usageExtra === 'object') ? state.usageExtra : {};
    state.records = Array.isArray(state.records) ? state.records : [];
    state.wrong = Array.isArray(state.wrong) ? state.wrong : [];
    state.wishes = Array.isArray(state.wishes) ? state.wishes : [];
    state.wishLog = Array.isArray(state.wishLog) ? state.wishLog : [];
    state.starLog = Array.isArray(state.starLog) ? state.starLog : [];
    state.starAwards = Array.isArray(state.starAwards) ? state.starAwards : [];
    state.giftPrices = (state.giftPrices && typeof state.giftPrices === 'object') ? state.giftPrices : {};
    state.redeemed = Array.isArray(state.redeemed) ? state.redeemed : [];
    if (!state.stars) state.stars = 0;
    if (!state.maxCombo) state.maxCombo = 0;
    if (!state.submits) state.submits = 0;
  }

  function mergeSet(s) {
    state.settings = Object.assign({}, C.DEFAULT_SET, (state.settings && typeof state.settings === 'object') ? state.settings : {}, s || {});
    return state.settings;
  }

  function curSettings() { return state.settings; }

  function saveState() {
    save(stateKey(), state);
    var kid = window.eduKids ? window.eduKids.active() : null;
    if (kid && kid.id && window.eduSync && window.eduSync.pushState) window.eduSync.pushState(kid.id, 'state', state);
  }
  function saveWb() {
    save(wbKey(), wb);
    var kid = window.eduKids ? window.eduKids.active() : null;
    if (kid && kid.id && window.eduSync && window.eduSync.pushState) window.eduSync.pushState(kid.id, 'workbench', wb);
  }

  // 今日用量: 按「本地日期」建键(与 addDailySecs/addStarLog 一致), 可直接自增并自动回写
  function usageForToday() {
    var t = dayKey();
    if (!state.usage || typeof state.usage !== 'object') state.usage = {};
    var u = state.usage[t];
    if (!u || typeof u !== 'object') u = state.usage[t] = { secs: 0, count: 0, n: 0 };
    if (typeof u.n !== 'number') u.n = 0;
    if (typeof u.count !== 'number') u.count = 0;
    if (typeof u.secs !== 'number') u.secs = 0;
    return u;
  }

  function minsUsed() { return Math.ceil((usageForToday().secs || 0) / 60); }

  // ---- 学习守护(每日使用时长达标后拦截) ----
  // 今日已解锁次数(每次 +USAGE_UNLOCK_MIN 分钟)
  function usageExtraToday() {
    var k = dayKey();
    state.usageExtra = (state.usageExtra && typeof state.usageExtra === 'object') ? state.usageExtra : {};
    return state.usageExtra[k] || 0;
  }
  // 每日允许的分钟数: 家长设置 >0 用家长设置, 否则用默认 30 分钟
  function usageLimitMin() {
    var s = curSettings();
    return (s && s.dailyMin > 0) ? s.dailyMin : C.USAGE_DEFAULT_MIN;
  }
  function usageLimitSec() {
    return (usageLimitMin() + usageExtraToday() * C.USAGE_UNLOCK_MIN) * 60;
  }
  function usageUsedSec() { return usageForToday().secs || 0; }
  function usageOver() { return usageUsedSec() >= usageLimitSec(); }
  // 页面计时器累计学习秒数(同时写入 dailySecs 供家长看板用时分析)
  function addUsageSecs(secs) {
    if (!(secs > 0)) return;
    var u = usageForToday();
    u.secs = (u.secs || 0) + Math.round(secs);
    addDailySecs(secs);
    saveState();
  }
  // 记录一次解锁(扣星或答对题): 当日额度增加 USAGE_UNLOCK_MIN 分钟.
  // 若今天已用时长远超新额度(解锁次数因刷新/合并丢失, 或历史版本在弹框期间也计入时长),
  // 单次 +30 分钟仍是超限状态, 弹框会立刻再次弹出. 这里按已用时长把额度补足到
  // 「至少还能再学 USAGE_UNLOCK_MIN 分钟」, 让本次解锁真正可用.
  function addUsageUnlock() {
    var k = dayKey();
    state.usageExtra = (state.usageExtra && typeof state.usageExtra === 'object') ? state.usageExtra : {};
    state.usageExtra[k] = (state.usageExtra[k] || 0) + 1;
    var guard = 0;
    while (usageUsedSec() + C.USAGE_UNLOCK_MIN * 60 > usageLimitSec() && guard < 1000) {
      state.usageExtra[k] = state.usageExtra[k] + 1;
      guard++;
    }
    saveState();
  }

  function checkLimit() {
    var u = usageForToday();
    var s = curSettings();
    if (s.dailyQ && u.count >= s.dailyQ) return '今日题数已达上限';
    if (s.dailyMin && minsUsed() >= s.dailyMin) return '今日用时已达上限';
    return null;
  }

  function stateLevel(subj) {
    var lv = (state.level || {})[subj];
    return lv || 3;
  }

  function setLevel(subj, v) {
    state.level = state.level || {};
    state.level[subj] = Math.max(1, Math.min(5, v));
    saveState();
  }

  // 用时分析: 按天累计学习秒数(供家长看板「用时分析」折线/柱状图)
  function addDailySecs(secs) {
    if (!(secs > 0)) return;
    state.dailySecs = state.dailySecs || {};
    var k = dayKey();
    state.dailySecs[k] = (state.dailySecs[k] || 0) + Math.round(secs);
    saveState();
  }

  // 星星获取流水: 每次闯关交卷追加一条(供星星曲线)
  function addStarLog(stars) {
    if (!(stars > 0)) return;
    state.starLog = state.starLog || [];
    var k = dayKey();
    state.starLog.push({ date: k, s: stars });
    if (state.starLog.length > 400) state.starLog.shift();
  }

  // 星星事件自动去重键: 页面未显式传 key 时(答题临时加星), 用时间+序号保证唯一
  var _awardSeq = 0;
  function starEventKey() {
    _awardSeq = (_awardSeq + 1) % 1000000;
    return 'auto_' + Date.now() + '_' + _awardSeq;
  }

  // 所有「加/扣星星」的唯一入口: 本地乐观更新 + 记流水 + 同步服务端权威账本(按 key 幂等).
  // amount>0 加星(答题/通关/里程碑/每日), amount<0 扣星(解锁/兑换);
  // 通关/里程碑/每日等请传稳定可重现的 key, 网络重试/多设备回放不会重复累加.
  function awardStars(amount, reason, key) {
    amount = Number(amount) || 0;
    if (amount === 0) return state.stars;
    key = key || starEventKey();
    state.starAwards = state.starAwards || [];
    for (var i = 0; i < state.starAwards.length; i++) {
      if (state.starAwards[i] && state.starAwards[i].key === key) return state.stars;
    }
    var ev = { key: key, amount: amount, reason: (reason || '').slice(0, 60), ts: Date.now() };
    state.starAwards.push(ev);
    if (state.starAwards.length > 2000) state.starAwards.splice(0, state.starAwards.length - 2000);
    state.stars = (Number(state.stars) || 0) + amount;
    if (amount > 0) addStarLog(amount);
    save(stateKey(), state);
    try {
      if (window.eduSync && window.eduSync.pushStars) {
        var kid = window.eduKids ? window.eduKids.active() : null;
        if (kid && kid.id) window.eduSync.pushStars(kid.id, [ev]);
      }
    } catch (e) {}
    return state.stars;
  }

  window.Edu.Store = {
    state: state,
    wb: wb,
    recentExclude: recentExclude,
    loadAllState: loadAllState,
    mergeSet: mergeSet,
    curSettings: curSettings,
    saveState: saveState,
    saveWb: saveWb,
    usageForToday: usageForToday,
    minsUsed: minsUsed,
    checkLimit: checkLimit,
    stateLevel: stateLevel,
    setLevel: setLevel,
    addDailySecs: addDailySecs,
    addStarLog: addStarLog,
    awardStars: awardStars,
    usageExtraToday: usageExtraToday,
    usageLimitMin: usageLimitMin,
    usageLimitSec: usageLimitSec,
    usageUsedSec: usageUsedSec,
    usageOver: usageOver,
    addUsageSecs: addUsageSecs,
    addUsageUnlock: addUsageUnlock,
    stateKeyFor: stateKeyFor,
    wbKeyFor: wbKeyFor,
    kidSyncKey: kidSyncKey
  };

  window.state = state;
  window.wb = wb;
  window.loadAllState = loadAllState;
  window.curSettings = curSettings;
  window.saveState = saveState;
  window.saveWb = saveWb;
  window.usageForToday = usageForToday;
  window.minsUsed = minsUsed;
  window.checkLimit = checkLimit;
  window.stateLevel = stateLevel;
  window.setLevel = setLevel;
})();