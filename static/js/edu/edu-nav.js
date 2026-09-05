(function () {
  'use strict';
  var C = window.Edu.Constants;
  var Store = window.Edu.Store;
  var Speech = window.Edu.Speech;
  var Kids = window.Edu.Kids;
  var QuizEngine = window.Edu.QuizEngine;

  var eduPages = { home: 'eduHomePage', learn: 'eduLearnPage', wish: 'eduWishPage', badges: 'eduBadgesPage', stats: 'eduStatsPage', mine: 'eduMinePage' };
  var navNow = 'home';
  var subjNow = 'zh';
  var parNow = null;

  function activeKidId() { var k = window.eduKids ? window.eduKids.active() : null; return k ? String(k.id) : null; }
  function navKey() { var id = activeKidId() || 'kk'; return 'edu_nav_v1_' + id; }

  function saveNav() { try { localStorage.setItem(navKey(), navNow); } catch (e) {} }
  function lastNav() { try { return localStorage.getItem(navKey()) || 'home'; } catch (e) { return 'home'; } }

  var EDU_PREF_PREFIX = 'edu_pref_v1_';
  function getPref() {
    var id = activeKidId();
    if (!id) return {};
    try { return JSON.parse(localStorage.getItem(EDU_PREF_PREFIX + id)) || {}; } catch (e) { return {}; }
  }
  function savePref(p) {
    var id = activeKidId();
    if (id) { try { localStorage.setItem(EDU_PREF_PREFIX + id, JSON.stringify(p)); } catch (e) {} }
  }
  function prefSet(k, v) { var p = getPref() || {}; p[k] = v; savePref(p); }

  function defaultModeFor() {
    var kid = window.eduKids ? window.eduKids.active() : null;
    var age = kid ? (new Date().getFullYear() - (kid.birthYear || new Date().getFullYear())) : 6;
    return age <= 5 ? 'paradise' : 'workbench';
  }
  function currentMode() {
    var p = getPref();
    var m = p.mode;
    if (m !== 'workbench' && m !== 'paradise') m = defaultModeFor();
    var s = Store.curSettings();
    if (m === 'paradise' && s && s.show && s.show.par === false) m = 'workbench';
    return m;
  }
  function setModeUI(m) {
    var wb = document.getElementById('eduWorkbench');
    var pa = document.getElementById('eduParadise');
    if (wb) wb.style.display = (m === 'workbench') ? '' : 'none';
    if (pa) pa.style.display = (m === 'paradise') ? '' : 'none';
    var sel = document.getElementById('modeSelect');
    if (sel && sel.value !== m) sel.value = m;
  }
  window.switchMode = function (m) {
    if (m !== 'workbench' && m !== 'paradise') return;
    var p = getPref() || {};
    p.mode = m;
    savePref(p);
    if (m === 'workbench') { subjNow = p.subj || 'zh'; parNow = null; }
    else { parNow = p.par || null; }
    renderLearn();
    renderNav();
    Speech.toast(m === 'workbench' ? '🏫 已切换为幼小衔接' : '🌈 已切换为快乐乐园');
  };

  function applyContentToggles() {
    var s = Store.curSettings();
    var show = s && s.show;
    var tr = document.getElementById('wbTabTrace');
    if (tr) tr.style.display = (show && show.trace === false) ? 'none' : '';
    var sel = document.getElementById('modeSelect');
    if (sel) {
      var optPar = sel.querySelector ? sel.querySelector('option[value="paradise"]') : null;
      if (optPar) {
        var on = !(show && show.par === false);
        optPar.disabled = !on;
        optPar.style.display = on ? '' : 'none';
        if (!on && sel.value === 'paradise') window.switchMode('workbench');
      }
    }
  }

  function navBusy() {
    if (window.PRACTICE && window.PRACTICE.active) return true;
    var quiz = QuizEngine && QuizEngine.quiz;
    return !!(quiz && !quiz.submitted && navNow === 'learn');
  }

  function anim(el) {
    if (!el) return;
    el.classList.remove('page-enter');
    void el.offsetWidth;
    el.classList.add('page-enter');
  }

  function renderKidBar() {
    if (Kids && Kids.renderKidBar) return Kids.renderKidBar();
  }
  function renderStars() { var fn = window.renderStars; if (fn) fn(); }
  function renderStarBar() {
    if (Kids && Kids.renderStarBar) return Kids.renderStarBar();
  }
  function renderHome() { var fn = (window.Edu.Home && window.Edu.Home.renderHome); if (fn) fn(); }
  function renderWish() { var fn = (window.Edu.Wish && window.Edu.Wish.renderWish); if (fn) fn(); }
  function renderBadges() { var fn = (window.Edu.Badges && window.Edu.Badges.renderBadges); if (fn) fn(); }
  function renderStats() { var fn = (window.Edu.Stats && window.Edu.Stats.renderStats) || window.renderStats; if (fn) fn(); }
  function renderMine() { var fn = (window.Edu.Mine && window.Edu.Mine.renderMine) || window.renderMine; if (fn) fn(); }

  var PAGE_TITLES = { home: '', learn: '学习', stats: '学习报告', badges: '闯关赢星星', mine: '我的宝贝', wish: '星愿' };

  window.setPageTitle = function (t) {
    var el = document.getElementById('kbTitle');
    if (!el) return;
    el.textContent = t || '';
    el.style.display = t ? '' : 'none';
  };

  window.eduNav = function (p) {
    if (window.Edu.FAB) window.Edu.FAB.quickFabSet(true);
    // 离开答题相关页面时，清理 quiz-live/quiz-complete 类，避免底部 dock 被隐藏
    if (navNow === 'learn' && p !== 'learn') {
      if (window.Edu.QuizEngine && window.Edu.QuizEngine.clearQuizBodyClass) {
        window.Edu.QuizEngine.clearQuizBodyClass();
      }
    }
    navNow = p;
    saveNav();
    for (var k in eduPages) {
      var el = document.getElementById(eduPages[k]);
      if (el) el.style.display = (k === p) ? '' : 'none';
    }
    anim(document.getElementById(eduPages[p]));
    if (p === 'home') { Store.loadAllState(); renderHome(); applyContentToggles(); }
    if (p === 'wish') { Store.loadAllState(); renderStars(); renderStarBar(); renderWish(); }
    if (p === 'badges') { Store.loadAllState(); renderBadges(); }
    if (p === 'stats') { Store.loadAllState(); renderStars(); renderStarBar(); renderStats(); }
    if (p === 'mine') { Store.loadAllState(); renderStars(); renderStarBar(); renderMine(); }
    if (p === 'learn') {
      renderKidBar();
      Store.loadAllState();
      renderStars();
      renderLearn();
    }
    renderNav();
  };

  function renderLearn() {
    var m = currentMode();
    setModeUI(m);
    if (m === 'workbench') {
      if (window.Edu.Workbench && window.Edu.Workbench.wbInit) window.Edu.Workbench.wbInit();
    } else if (window.Edu.Paradise && window.Edu.Paradise.parInit) {
      window.Edu.Paradise.parInit();
    }
  }
  window.renderLearn = renderLearn;

  function renderNav() {
    var nav = document.getElementById('eduBottomNav');
    if (!nav) return;
    var isLearn = (navNow === 'home' || navNow === 'learn');
    var isWish = (navNow === 'wish');
    var items = [
      { act: isLearn, oc: "eduNav('home')", icon: '<i class="bi bi-house-heart"></i>', label: '学习' },
      { act: navNow === 'badges', oc: "eduNav('badges')", icon: '<i class="bi bi-award"></i>', label: '勋章' },
      { act: isWish, oc: "eduNav('wish')", icon: '<i class="bi bi-star"></i>', label: '星愿' },
      { act: navNow === 'mine', oc: "eduNav('mine')", icon: '<i class="bi bi-person"></i>', label: '我的' }
    ];
    nav.innerHTML = items.map(function (it) {
      var cls = 'edu-nav-btn' + (it.act ? ' active' : '');
      return '<button type="button" class="' + cls + '" onclick="' + it.oc + '">' +
        it.icon + '<span>' + it.label + '</span></button>';
    }).join('');
  }
  window.renderNav = renderNav;

  window.navCourse = function (s) {
    var p = getPref() || {};
    p.mode = 'workbench';
    p.subj = s;
    p.lastSubj = s;
    p.par = null;
    savePref(p);
    subjNow = s;
    parNow = null;
    // 只设 pref 再进 learn: wbInit 会按 lastSubj 打开一次面板,
    // 避免「eduNav→wbInit 启动 + wbSubject 再启动」双触发导致刚保存的快照被误判为可续学
    eduNav('learn');
  };
  window.navDaily = function () {
    var p = getPref() || {};
    p.mode = 'workbench';
    p.subj = 'daily';
    p.lastSubj = 'daily';
    p.wbZh = null; p.wbMath = null; p.wbEn = null;
    savePref(p);
    parNow = null;
    subjNow = 'daily';
    // wbInit 检测 lastSubj==='daily' 会调用 startDaily()(仅一次)
    eduNav('learn');
  };
  window.navParPlay = function (key) {
    var p = getPref() || {};
    p.mode = 'paradise';
    p.par = key;
    savePref(p);
    parNow = key;
    eduNav('learn');
    if (window.Edu.Paradise && window.Edu.Paradise.parPlay) window.Edu.Paradise.parPlay(key);
  };

  window.switchKid = function (id) {
    if (!id || (window.eduKids && window.eduKids.active() && window.eduKids.active().id === id)) { return; }
    Store.saveState(); Store.saveWb();
    if (window.eduKids) window.eduKids.setActive(id);
    var drop = document.getElementById('kidPickDrop');
    if (drop) drop.classList.remove('show');
    // 停留在当前页切换宝贝, 不跳回首页
    window.eduNav(navNow);
  };
  window.toggleKidDrop = function () {
    var drop = document.getElementById('kidPickDrop');
    if (drop) drop.classList.toggle('show');
  };
  window.renderKidBar = renderKidBar;
  window.renderStarBar = renderStarBar;

  // 顶部条: 返回/Dock 守卫
  window.quitAsk = function () {
    if (!navBusy()) { window.eduNav('home'); return; }
    var mask = document.getElementById('eduMaskQuit');
    if (mask) mask.style.display = 'flex';
  };
  window.quitCancel = function () {
    var mask = document.getElementById('eduMaskQuit');
    if (mask) mask.style.display = 'none';
  };
  window.quitConfirm = function () {
    window.quitCancel();
    if (window.PRACTICE && window.PRACTICE.active) {
      if (window.stopPractice) window.stopPractice();
    } else if (QuizEngine && QuizEngine.quiz && !QuizEngine.quiz.submitted) {
      // 先落盘本局进度(保存已作答), 再清状态 — 避免退出即丢本局数据
      Store.saveState();
      if (QuizEngine.clearQuizState) QuizEngine.clearQuizState();
    }
    if (QuizEngine && QuizEngine.clearQuizBodyClass) QuizEngine.clearQuizBodyClass();
    window.eduNav('home');
    renderNav();
  };

  function getCurrentPage() {
    var saved = (function () { try { return localStorage.getItem(navKey()) || 'home'; } catch (e) { return 'home'; } })();
    return (saved === 'learn' || saved === 'wish' || saved === 'badges' || saved === 'mine') ? saved : 'home';
  }

  function enter() {
    renderKidBar();
    Store.loadAllState();
    renderStars();
    applyContentToggles();
    var saved = lastNav();
    var page = (saved === 'learn' || saved === 'wish' || saved === 'badges' || saved === 'mine') ? saved : 'home';
    window.eduNav(page);
  }
  window.lastNav = lastNav;
  window.enter = enter;

  function setSubj(s) { subjNow = s; }
  function setPar(p) { parNow = p; }
  function getSubj() { return subjNow; }
  function getPar() { return parNow; }

  window.Edu.Nav = {
    navNow: navNow,
    subjNow: subjNow,
    parNow: parNow,
    get subjNow() { return subjNow; },
    get parNow() { return parNow; },
    setSubj: setSubj,
    setPar: setPar,
    getSubj: getSubj,
    getPar: getPar,
    saveNav: saveNav,
    lastNav: lastNav,
    getPref: getPref,
    savePref: savePref,
    prefSet: prefSet,
    defaultModeFor: defaultModeFor,
    currentMode: currentMode,
    setModeUI: setModeUI,
    applyContentToggles: applyContentToggles,
    renderNav: renderNav,
    renderLearn: renderLearn,
    eduNav: window.eduNav,
    navCourse: window.navCourse,
    navDaily: window.navDaily,
    navParPlay: window.navParPlay,
    anim: anim,
    getCurrentPage: getCurrentPage,
    quitAsk: window.quitAsk,
    quitCancel: window.quitCancel,
    quitConfirm: window.quitConfirm,
    enter: enter
  };
})();
