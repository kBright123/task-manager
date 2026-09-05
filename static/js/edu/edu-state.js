(function () {
  'use strict';
  var C = window.Edu.Constants;

  function load(k) { try { return JSON.parse(localStorage.getItem(k)); } catch(e){ return null; } }
  function save(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch(e){} }
  function clone(o) { return JSON.parse(JSON.stringify(o)); }

  var state = { stars: 0, records: [], wrong: [], settings: {}, usage: {}, maxCombo: 0, badges: {}, submits: 0, wishes: [], wishLog: [], level: {}, starLog: [], dailySecs: {}, giftPrices: {}, redeemed: [] };
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
    state.records = Array.isArray(state.records) ? state.records : [];
    state.wrong = Array.isArray(state.wrong) ? state.wrong : [];
    state.wishes = Array.isArray(state.wishes) ? state.wishes : [];
    state.wishLog = Array.isArray(state.wishLog) ? state.wishLog : [];
    state.starLog = Array.isArray(state.starLog) ? state.starLog : [];
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