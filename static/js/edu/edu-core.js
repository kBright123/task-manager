// ============================================================
// Edu 乐园 - 共享运行时核心
// 迁移自原单页 education.js 中"跨模块共享"的可变状态与工具函数。
// 所有 feature 模块经由 window.Edu.Core 访问同一份实时引用，
// 从而在拆分模块(每个 IIFE)下保持与原单页闭包一致的行为。
// ============================================================
(function () {
  'use strict';

  var QUIZ_LEN = 10;
  var LS_BASE = 'edu_record_v1';
  var STR_BASE = 'edu_workbench_v1';
  var DEFAULT_SET = { range: 0, nocarry: false, mult: false, dailyQ: 20, dailyMin: 0, show: { trace: true, par: true } };

  function load(k) { try { return JSON.parse(localStorage.getItem(k)); } catch(e){ return null; } }
  function save(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch(e){} }
  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function esc(s) { return String(s === undefined || s === null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'); }

  // ---- 共享可变状态(实时引用, 模块间共享) ----
  var state = { stars: 0, records: [], wrong: [], settings: {}, usage: {}, maxCombo: 0, badges: {}, submits: 0, wishes: [], wishLog: [] };
  var wb = {};
  var recentExclude = [];

  // 关卡/练习进行态
  var quiz = null;
  var quizContainerId = null;
  var quizSubject = null;
  var quizOrder = {};
  var quizView = 0;

  // 家长态 / 偏好
  var PWD_KEY = 'edu_parent_pwd_v1';
  var parentUnlocked = false;
  var pwdPending = null;

  // 当前科目/页面/模式
  var navNow = 'home';
  var subjNow = 'zh';
  var parNow = null;
  var wbZhMode = 'zi';
  var wbPinyinMode = 'sm';
  var wbCiyuMode = 'fan';

  var EDU_PREF_PREFIX = 'edu_pref_v1_';
  var NAV_KEY = 'edu_nav_v1_';

  function childId() { var a = window.eduKids ? window.eduKids.active() : null; return a ? String(a.id) : 'default'; }
  function eduPages() {
    return { home: 'eduHomePage', learn: 'eduLearnPage', wish: 'eduWishPage', badges: 'eduBadgesPage', stats: 'eduStatsPage' };
  }

  function stateKeyFor(kidId) { return LS_BASE + '_' + (kidId || childId()); }
  function wbKeyFor(kidId) { return STR_BASE + '_' + (kidId || childId()); }

  // ---- 存储/状态 ----
  function loadAllState() {
    var raw = load(stateKeyFor());
    state = raw || { stars: 0, records: [], wrong: [], settings: {}, usage: {}, maxCombo: 0, badges: {}, submits: 0, wishes: [], wishLog: [], level: {}, adv: {} };
    state.settings = mergeSet(state.settings);
    state.usage = state.usage || { date: '', n: 0, secs: 0 };
    state.badges = state.badges || {};
    state.level = state.level || {};
    state.adv = state.adv || {};
    if (!Array.isArray(state.records)) state.records = [];
    if (!Array.isArray(state.wrong)) state.wrong = [];
    if (!Array.isArray(state.wishes)) state.wishes = [];
    if (!Array.isArray(state.wishLog)) state.wishLog = [];
    if (!state.maxCombo) state.maxCombo = 0;
    if (!state.submits) state.submits = 0;
    wb = load(wbKeyFor()) || {};
  }
  function mergeSet(s) {
    var out = {};
    for (var k in DEFAULT_SET) {
      if (k === 'show') {
        var sh = (s && s.show) ? s.show : {};
        var o = {};
        for (var sk in DEFAULT_SET.show) o[sk] = (sh[sk] !== undefined) ? !!sh[sk] : DEFAULT_SET.show[sk];
        out.show = o;
      } else {
        out[k] = (s && s[k] !== undefined && s[k] !== null) ? s[k] : DEFAULT_SET[k];
      }
    }
    return out;
  }
  function curSettings() { return state.settings; }
  function saveState() {
    save(stateKeyFor(), state);
    var kid = window.eduKids ? window.eduKids.active() : null;
    if (kid && window.eduSync) window.eduSync.pushState(kid.id, 'state', state);
  }
  function saveWb() {
    save(wbKeyFor(), wb);
    var kid = window.eduKids ? window.eduKids.active() : null;
    if (kid && window.eduSync) window.eduSync.pushState(kid.id, 'workbench', wb);
  }

  function todayStr() {
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }
  function yesterdayStr() {
    var y = new Date(Date.now() - 86400000);
    return y.getFullYear() + '-' + String(y.getMonth() + 1).padStart(2, '0') + '-' + String(y.getDate()).padStart(2, '0');
  }

  // ---- 每日用量(原单页语义: 单一 {date,n,secs}) ----
  function usageForToday() {
    var t = todayStr();
    if (!state.usage || state.usage.date !== t) { state.usage = { date: t, n: 0, secs: 0 }; }
    return state.usage;
  }
  function minsUsed() { return Math.ceil((usageForToday().secs || 0) / 60); }
  function checkLimit() {
    var s = curSettings();
    var u = usageForToday();
    if (s && s.dailyQ > 0 && u.n >= s.dailyQ) return '今日题量已达上限（' + s.dailyQ + ' 题）';
    if (s && s.dailyMin > 0 && minsUsed() >= s.dailyMin) return '今日用时已达上限（' + s.dailyMin + ' 分钟）';
    return null;
  }

  // ---- 家长口令 ----
  function parentPwd() { var v = load(PWD_KEY); return (v && /^\d{4}$/.test(v)) ? v : '0000'; }
  function requireParent(cb) {
    // 已去除家长口令限制: 不再弹口令验证, 直接放行
    if (cb) cb();
    return true;
  }
  function pwdConfirm() {
    var inp = document.getElementById('pwdInput');
    var val = (inp ? inp.value : '').replace(/\s+/g, '');
    if (val === parentPwd()) {
      parentUnlocked = true;
      var m = document.getElementById('eduMaskPwd');
      if (m) m.style.display = 'none';
      if (inp) inp.value = '';
      var cb = pwdPending; pwdPending = null;
      if (cb) cb();
      toast('家长确认通过');
    } else {
      if (inp) inp.value = '';
      toast('口令不正确');
    }
  }
  function pwdCancel() {
    pwdPending = null;
    var m = document.getElementById('eduMaskPwd');
    if (m) m.style.display = 'none';
  }
  window.requireParent = requireParent;
  window.pwdConfirm = pwdConfirm;
  window.pwdCancel = pwdCancel;
  window.parentPwd = parentPwd;

  // ---- toast / 星星 ----
  var toastT = null;
  function toast(msg) {
    var el = document.getElementById('eduToast');
    if (!el) return;
    el.textContent = msg;
    el.classList.add('show');
    if (toastT) clearTimeout(toastT);
    toastT = setTimeout(function () { el.classList.remove('show'); }, 1800);
  }
  window.toast = toast;

  // ---- 每日打卡 ----
  function ensureDay() {
    var t = todayStr();
    if (!wb.last) wb.last = '';
    if (wb.last !== t) {
      wb.streak = (wb.last === yesterdayStr()) ? (wb.streak || 0) + 1 : 1;
      wb.last = t;
      wb.done = [];
    }
    saveWb();
    return t;
  }

  // ---- 发音/朗读(摘自原单页 speech 段) ----
  var SPEAK_ON_KEY = 'edu_speak_v1';
  var zhVoice = null;
  var netAudio = null, netAudioUrl = '';
  var speakFBTimer = null;
  var lastSpeakText = '', lastSpeakAt = 0;
  var CN0 = '零一二三四五六七八九';
  function numCn(n) {
    n = Math.floor(Math.abs(n));
    if (n === 0) return '零';
    if (n < 10) return CN0[n];
    if (n < 20) return '十' + (n % 10 ? CN0[n % 10] : '');
    if (n < 100) return CN0[Math.floor(n / 10)] + '十' + (n % 10 ? CN0[n % 10] : '');
    if (n < 1000) { var b = Math.floor(n / 100), r = n % 100; return CN0[b] + '百' + (r ? (r < 10 ? '零' + CN0[r] : numCn(r)) : ''); }
    var q = Math.floor(n / 1000), r2 = n % 1000; return CN0[q] + '千' + (r2 ? (r2 < 100 ? '零' + numCn(r2) : numCn(r2)) : '');
  }
  function mathToSpeak(text) {
    if (!text) return '';
    var s = String(text);
    if (!/[+\-×÷＝=]/.test(s)) return s;
    s = s.replace(/×/g, ' 乘 ').replace(/÷/g, ' 除以 ')
      .replace(/\s*-\s*/g, ' 减 ').replace(/\s*\+\s*/g, ' 加 ')
      .replace(/[＝=]\s*\?+(\s*,?\s*对吗)?/g, ' 等于多少')
      .replace(/[＝=]/g, ' 等于 ')
      .replace(/\?+/g, '多少')
      .replace(/\s+/g, ' ');
    return s.replace(/(\d+)/g, function (m) { return numCn(parseInt(m, 10)); });
  }
  function ttLang(t) {
    var s = String(t || '');
    var han = (s.match(/[\u4e00-\u9fff]/g) || []).length;
    var lat = (s.replace(/\s/g, '').match(/[a-zA-Z]/g) || []).length;
    return han >= lat ? 'zh' : 'en';
  }
  function stopNetAudio() { if (netAudio) { try { netAudio.pause(); } catch (e) {} netAudio = null; netAudioUrl = ''; } }
  function playAudio(urls) {
    if (!urls || !urls.length || typeof Audio !== 'function') return;
    var next = urls.slice(1);
    try {
      if (!netAudio) netAudio = new Audio();
      netAudio.src = urls[0];
      netAudioUrl = urls[0];
      netAudio.onended = function () { stopNetAudio(); };
      netAudio.onerror = function () { if (netAudioUrl !== urls[0]) return; netAudio.onerror = null; stopNetAudio(); playAudio(next); };
      var p = netAudio.play();
      if (p && p.catch) p.catch(function () { if (netAudioUrl === urls[0]) { stopNetAudio(); playAudio(next); } });
    } catch (e) { playAudio(next); }
  }
  function playNetTTS(text) {
    if (!text) return;
    var t = String(text).slice(0, 180);
    var lang = ttLang(text);
    playAudio([
      '/edu/api/tts?le=' + lang + '&text=' + encodeURIComponent(t),
      'https://dict.youdao.com/dictvoice?le=' + lang + '&audio=' + encodeURIComponent(t),
      'https://translate.googleapis.com/translate_tts?ie=UTF-8&client=tw-ob&tl=' + (lang === 'zh' ? 'zh-CN' : 'en') + '&q=' + encodeURIComponent(t)
    ]);
  }
  function speakOn() { try { var v = load(SPEAK_ON_KEY); return v !== false; } catch (e) { return true; } }
  function speak(text) {
    if (!text || !speakOn()) return;
    var t = mathToSpeak(String(text));
    var now = Date.now();
    if (t === lastSpeakText && now - lastSpeakAt < 1200) return;
    lastSpeakText = t; lastSpeakAt = now;
    if (speakFBTimer) clearTimeout(speakFBTimer);
    try {
      if (!window.speechSynthesis) { playNetTTS(t); return; }
      window.speechSynthesis.cancel();
      stopNetAudio();
      var u = new SpeechSynthesisUtterance(t);
      if (zhVoice) { u.voice = zhVoice; u.lang = zhVoice.lang; } else { u.lang = 'zh-CN'; }
      u.rate = 0.85; u.pitch = 1.1;
      var started = false;
      speakFBTimer = setTimeout(function () { if (!started) playNetTTS(t); }, 900);
      try { u.onstart = function () { started = true; if (speakFBTimer) clearTimeout(speakFBTimer); stopNetAudio(); }; } catch (e) {}
      try { u.onerror = function () { if (speakFBTimer) clearTimeout(speakFBTimer); playNetTTS(t); }; } catch (e) {}
      window.speechSynthesis.speak(u);
    } catch (e) { playNetTTS(t); }
  }
  function setSpeakIcon() {
    var btn = document.getElementById('soundToggle');
    if (btn) btn.textContent = speakOn() ? '🔊' : '🔇';
  }
  window.toggleSpeak = function () {
    var on = !speakOn();
    try { save(SPEAK_ON_KEY, on); } catch (e) {}
    setSpeakIcon();
    window.Edu.Speech.speak('声音已开启');
    return on;
  };
  window.playSpeak = function (text) {
    if (!text) return;
    if (!speakOn()) { try { save(SPEAK_ON_KEY, true); } catch (e) {} setSpeakIcon(); }
    // 统一走 Edu.Speech 的高质量低延时实现(本地合成优先), 避免多条发音路径语义不一致
    if (window.Edu.Speech && window.Edu.Speech.playSpeak) { window.Edu.Speech.playSpeak(text); return; }
    speak(text);
  };
  window.speak = function (t) { speak(t); };
  function spkBtn(text, cls) {
    if (!text) return '';
    return '<button type="button" class="spk ' + (cls || '') + '" aria-label="朗读" onclick="playSpeak(\'' +
      String(text).replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\n/g, ' ').replace(/"/g, '&quot;') +
      '\')">🔊</button>';
  }
  function stripBlank(s) { return String(s || '').replace(/[_＿\s]*\_+[_＿\s]*/g, ' ').replace(/\s*=\s*\?+\s*$/, '').replace(/\s+/g, ' ').trim(); }

  // ---- 难度档 / 单调辅助 ----
  function stateLevel(subj) {
    var lv = (state.level || {})[subj];
    return (lv && lv >= 1 && lv <= 5) ? lv : 3;
  }
  function setLevel(subj, v) {
    state.level = state.level || {};
    state.level[subj] = Math.max(1, Math.min(5, v));
    saveState();
  }

  // ---- 闪卡式布局辅助 ----
  function anim(el) { if (!el) return; el.style.animation = 'none'; if (el.offsetHeight !== undefined) el.offsetHeight; el.style.animation = ''; }

  // 提供给 feature 模块的共享对象
  window.Edu.Core = {
    QUIZ_LEN: QUIZ_LEN,
    LS_BASE: LS_BASE,
    STR_BASE: STR_BASE,
    DEFAULT_SET: DEFAULT_SET,
    load: load,
    save: save,
    clone: clone,
    esc: esc,
    loadAllState: loadAllState,
    mergeSet: mergeSet,
    curSettings: curSettings,
    saveState: saveState,
    saveWb: saveWb,
    todayStr: todayStr,
    yesterdayStr: yesterdayStr,
    usageForToday: usageForToday,
    minsUsed: minsUsed,
    checkLimit: checkLimit,
    parentPwd: parentPwd,
    requireParent: requireParent,
    pwdConfirm: pwdConfirm,
    pwdCancel: pwdCancel,
    toast: toast,
    ensureDay: ensureDay,
    speaking: { speak: speak, speakOn: speakOn, mathToSpeak: mathToSpeak, numCn: numCn, spkBtn: spkBtn, stripBlank: stripBlank, setSpeakIcon: setSpeakIcon },
    stateLevel: stateLevel,
    setLevel: setLevel,
    anim: anim,
    state: state,
    wb: wb,
    recentExclude: recentExclude,
    quiz: quiz,
    quizOrder: quizOrder,
    childId: childId,
    stateKeyFor: stateKeyFor,
    wbKeyFor: wbKeyFor,
    parentUnlocked: parentUnlocked
  };

  window.state = state;
  window.wb = wb;
  window.Edu.state = state;
  window.loadAllState = loadAllState;
  window.curSettings = curSettings;
  window.saveState = saveState;
  window.saveWb = saveWb;
  window.usageForToday = usageForToday;
  window.minsUsed = minsUsed;
  window.checkLimit = checkLimit;
  window.todayStr = todayStr;
  window.esc = esc;
  window.parentPwd = parentPwd;
  window.anim = anim;
  window.stateLevel = stateLevel;
  window.setLevel = setLevel;
})();
