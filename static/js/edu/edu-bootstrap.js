(function () {
  'use strict';
  var Store = window.Edu.Store;
  var Speech = window.Edu.Speech;
  var Kids = window.Edu.Kids;
  var Nav = window.Edu.Nav;
  var QuizEngine = window.Edu.QuizEngine;

  // enter / lastNav are owned by edu-nav.js (single-page shell restore).
  window.enter = function () { Nav.enter(); };
  window.lastNav = Nav.lastNav;

  // Register eduSync callbacks
  if (window.eduSync) {
    window.eduSync.setOnState(function (kidId, dkey, data) {
      if (!data || typeof data !== 'object') return;
      var key = (dkey === 'workbench') ? Store.wbKeyFor(kidId) : Store.stateKeyFor(kidId);
      if (localStorage.getItem(key)) return;
      // 并入式加载: 只回填当前缺数据的本地键, 并保持 Store 对象引用不变,
      // 避免「整体替换 Store.state/wb」导致闭包 state 与导出对象分叉而丢数据
      localStorage.setItem(key, JSON.stringify(data));
      var target = (dkey === 'workbench') ? Store.wb : Store.state;
      Object.keys(target || {}).forEach(function (k) { delete target[k]; });
      Object.assign(target, data);
      var a = window.eduKids ? window.eduKids.active() : null;
      if (a && a.id === kidId && dkey === 'workbench' && Nav && Nav.eduNav) {
        Nav.eduNav('learn');
      }
    });
  }

  // Initial render
  Nav.renderNav();

  function boot() {
    if (window.eduKids && window.eduKids.hasAny()) {
      Nav.enter();
    } else {
      var cp = Nav.getCurrentPage();
      if (cp === 'home') {
        Nav.eduNav('home');
        if (Kids && Kids.openKidMask) Kids.openKidMask('👶 欢迎来到教育乐园', '首次使用请先登记孩子的出生年份与性别，之后自动进入对应年龄段内容');
      } else {
        Nav.eduNav(cp);
      }
    }
  }

  window.Edu.Bootstrap = {
    boot: boot,
    bootNow: function () {
      try { boot(); }
      catch (err) { if (window.console && window.console.error) window.console.error('[edu] boot error:', err); }
    }
  };

  // Loader dismiss: guaranteed independent of boot() so a module/boot failure
  // never leaves the spinner hanging forever ("一直转圈").
  (function () {
    var hide = null;
    function dismiss() {
      if (hide) return;
      var l = document.getElementById && document.getElementById('eduLoader');
      if (!l || !l.parentNode) { hide = 1; return; }
      hide = 1;
      l.style.opacity = '0';
      l.style.pointerEvents = 'none';
      setTimeout(function () { if (l.parentNode) l.parentNode.removeChild(l); }, 450);
    }
    if (document.readyState === 'loading' && typeof window.addEventListener === 'function') {
      window.addEventListener('load', dismiss);
    } else { dismiss(); }
    setTimeout(dismiss, 1300);
  })();

  // Run boot logic in a guarded fashion so failures surface in console but
  // never block the loader dismissal above.
  (function () {
    try { window.Edu.Bootstrap.bootNow(); }
    catch (err) { if (window.console && window.console.error) window.console.error('[edu] bootNow error:', err); }
  })();

  // Hydrate from backend
  if (window.eduSync) {
    window.eduSync.hydrate().then(function () {
      if (window.eduKids && window.eduKids.hasAny()) {
        var mask = document.getElementById('eduMask');
        if (mask && mask.style.display === 'flex') {
          mask.style.display = 'none';
          window.Edu.Bootstrap.bootNow();
        }
      }
    });
  }
})();
