// ===========================================
// Edu 乐园 - 模块入口文件
// 所有模块按依赖顺序加载，最后由 edu-bootstrap.js 启动应用
// ===========================================

(function() {
  'use strict';

  // Cache-bust version: sourced from the <script src="...edu-main.js?v=..."> tag.
  // Appended to the JS bundle so the service worker / HTTP cache never serves a
  // stale or mismatched module set (which previously caused "page keeps loading"
  // and "no questions rendered" on repeat visits).
  var srcVer = '';
  try {
    if (document.currentScript && document.currentScript.src) {
      var _m = document.currentScript.src.match(/[?&]v=([^&]+)/);
      if (_m) srcVer = _m[1];
    }
  } catch (e) {}
  var verQ = srcVer ? ('?v=' + encodeURIComponent(srcVer)) : '';

  // 首屏提速: 28 个模块已按依赖顺序由服务端合并成一个 /edu/bundle.js(单次请求),
  // 手机端不再逐文件串行拉取(移动 RTT 下可省下数秒), 且服务端 gzip + 不可变长缓存。
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
    return loadScript('/edu/bundle.js');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadAll);
  } else {
    loadAll();
  }
})();