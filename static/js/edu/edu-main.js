// ===========================================
// Edu 乐园 - 模块入口文件
// 所有模块按依赖顺序加载，最后由 edu-bootstrap.js 启动应用
// ===========================================

(function() {
  'use strict';

  // Cache-bust version: sourced from the <script src="...edu-main.js?v=..."> tag.
  // Appended to every dynamically loaded module so the service worker / HTTP
  // cache can never serve a stale or mismatched module set (which previously
  // caused "page keeps loading" and "no questions rendered" on repeat visits).
  var srcVer = '';
  try {
    if (document.currentScript && document.currentScript.src) {
      var _m = document.currentScript.src.match(/[?&]v=([^&]+)/);
      if (_m) srcVer = _m[1];
    }
  } catch (e) {}
  var verQ = srcVer ? ('?v=' + encodeURIComponent(srcVer)) : '';

  var scripts = [
    '/static/js/edu/edu-constants.js',
    '/static/js/edu/edu-math-utils.js',
    '/static/js/edu/edu-core.js',
    '/static/js/edu/edu-speech.js',
    '/static/js/edu/edu-state.js',
    '/static/js/edu/edu-parent.js',
    '/static/js/edu/edu-quiz-engine.js',
    '/static/js/edu/edu-engine.js',
    '/static/js/edu/edu-legacy.js',
    '/static/js/edu/edu-zh.js',
    '/static/js/edu/edu-math.js',
    '/static/js/edu/edu-en.js',
    '/static/js/edu/edu-paradise.js',
    '/static/js/edu/edu-daily.js',
    '/static/js/edu/edu-practice.js',
    '/static/js/edu/edu-header.js',
    '/static/js/edu/edu-fab.js',
    '/static/js/edu/edu-nav.js',
    '/static/js/edu/edu-kids.js',
    '/static/js/edu/edu-home.js',
    '/static/js/edu/edu-mine.js',
    '/static/js/edu/edu-edit.js',
    '/static/js/edu/edu-report.js',
    '/static/js/edu/edu-mask.js',
    '/static/js/edu/edu-wish.js',
    '/static/js/edu/edu-badges.js',
    '/static/js/edu/edu-course.js',
    '/static/js/edu/edu-stats.js',
    '/static/js/edu/edu-dash.js',
    '/static/js/edu/edu-backup.js',
    '/static/js/edu/edu-settings.js',
    '/static/js/edu/edu-bootstrap.js'
  ];

  function loadScript(src) {
    return new Promise(function(resolve, reject) {
      var script = document.createElement('script');
      script.src = src + verQ;
      script.onload = resolve;
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }

  function loadAll() {
    var promise = Promise.resolve();
    scripts.forEach(function(src) {
      promise = promise.then(function() { return loadScript(src); });
    });
    return promise;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadAll);
  } else {
    loadAll();
  }
})();