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
    window.eduSync.setOnState(function (kidId, dkey, data, force) {
      if (!data || typeof data !== 'object') return;
      var key = (dkey === 'workbench') ? Store.wbKeyFor(kidId) : Store.stateKeyFor(kidId);
      // force(双向归并/收养后): 后端已是权威合并值(本端数据已被吸收), 直接以服务端为准;
      // 否则只回填当前缺数据的本地键(离线优先, 不覆盖本地未同步数据)
      if (!force && localStorage.getItem(key)) return;
      // 学习守护例外: 本地「当天已解锁次数」即便未同步到服务端也予以保留(取较大),
      // 避免「答对解锁后刷新, 服务端旧弹又拉回超时」反复弹窗。
      if (force && dkey === 'state') {
        var prevData = {};
        try { prevData = JSON.parse(localStorage.getItem(key) || '{}'); } catch (e) { prevData = {}; }
        var clue = {};
        try { clue = prevData.usageExtra || {}; } catch (e) { clue = {}; }
        var slue = (data && data.usageExtra) || {};
        var mergedLue = {};
        Object.keys(clue).forEach(function (k) { mergedLue[k] = Number(clue[k]) || 0; });
        Object.keys(slue).forEach(function (k) { mergedLue[k] = Math.max(mergedLue[k] || 0, Number(slue[k]) || 0); });
        data = JSON.parse(JSON.stringify(data));
        data.usageExtra = mergedLue;
        // 星星账本: 保留本地「服务端尚未确认」的加/扣星事件(离线期间积累), 覆盖后回放,
        // 避免 force 覆盖把离线挣的星星吞掉; 已入账的以服务端权威 total 展示, 不重复累加。
        var localAwards = (prevData && Array.isArray(prevData.starAwards)) ? prevData.starAwards : [];
        var serverKeys = {};
        (Array.isArray(data.starAwards) ? data.starAwards : []).forEach(function (ev) { if (ev && ev.key) serverKeys[ev.key] = 1; });
        var pendingAwards = localAwards.filter(function (ev) { return ev && ev.key && !serverKeys[ev.key]; });
        if (pendingAwards.length) {
          var pendingSum = 0;
          pendingAwards.forEach(function (ev) { pendingSum += Number(ev.amount) || 0; });
          data.starAwards = (Array.isArray(data.starAwards) ? data.starAwards : []).concat(pendingAwards);
          data.stars = (Number(data.stars) || 0) + pendingSum;
          if (window.eduSync && window.eduSync.pushStars) window.eduSync.pushStars(kidId, pendingAwards);
        }
      }
      // 并入式加载: 只回填当前缺数据的本地键, 并保持 Store 对象引用不变,
      // 避免「整体替换 Store.state/wb」导致闭包 state 与导出对象分叉而丢数据
      localStorage.setItem(key, JSON.stringify(data));
      var target = (dkey === 'workbench') ? Store.wb : Store.state;
      Object.keys(target || {}).forEach(function (k) { delete target[k]; });
      Object.assign(target, data);
      var a = window.eduKids ? window.eduKids.active() : null;
      // 仅当当前/恢复页是首页时自动进入学习页; 若用户在 勋章/星愿/我的 等页, 不打断其所在页
      if (a && a.id === kidId && dkey === 'workbench' && Nav && Nav.eduNav &&
          (!Nav.getCurrentPage || Nav.getCurrentPage() === 'home')) {
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

  // 学习守护: 每日使用时长到达上限后弹出验证弹框(扣星/繁体数学题解锁), 刷新页面也会再次拦截
  (function () {
    try {
      if (window.Edu && window.Edu.UsageGate && window.Edu.UsageGate.start) window.Edu.UsageGate.start();
    } catch (err) { if (window.console && window.console.error) window.console.error('[edu] usage gate error:', err); }
  })();

  // Hydrate from backend
  if (window.eduSync) {
    window.eduSync.hydrate().then(function (hres) {
      if (window.eduKids && window.eduKids.hasAny()) {
        var mask = document.getElementById('eduMask');
        if (mask && mask.style.display === 'flex') {
          mask.style.display = 'none';
          window.Edu.Bootstrap.bootNow();
        }
      }
      // 档案在另一台设备被改名的, hydration 已回填本地, 重绘姓名区让改动立即可见
      if (hres && hres.reconciled) {
        try {
          if (Nav && Nav.eduNav) Nav.eduNav(Nav.getCurrentPage());
        } catch (err) { /* 后台重绘失败不影响主流程 */ }
      }
    });
  }
})();
