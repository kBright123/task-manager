(function () {
  'use strict';
  var Store = window.Edu.Store;

  var toastT = null;

  function toast(msg) {
    var el = document.getElementById('eduToast');
    if (!el) return;
    clearTimeout(toastT);
    el.textContent = msg;
    el.style.display = 'block';
    el.style.opacity = '1';
    toastT = setTimeout(function(){ el.style.opacity = '0'; setTimeout(function(){ el.style.display='none'; },300); }, 1800);
  }

  function renderStars() {
    var bar = document.getElementById('kbStarBar');
    if (!bar) return;
    var s = Store.state.stars || 0;
    var html = '';
    for (var i=0;i<5;i++) html += '<i class="bi bi-star-fill" style="color:'+(i<s?'#ffd93d':'var(--edu-border-2)')+';font-size:.85rem;margin-right:2px;"></i>';
    bar.innerHTML = html;
  }

  window.Edu.Parent = {
    toast: toast,
    renderStars: renderStars
  };

  window.requireParent = function (cb) {
    if (window.Edu.Core && window.Edu.Core.requireParent) return window.Edu.Core.requireParent(cb);
    // 已去除家长口令限制: 直接放行
    if (cb) cb();
    return true;
  };

  window.openParentMode = function (tab) {
    window.requireParent(function(){
      if (window.Edu.Settings && window.Edu.Settings.openSettings) {
        window.Edu.Settings.openSettings(tab || 'course');
        if (tab) {
          setTimeout(function(){
            var map = { eye: 'setEyeMin', course: 'setRange', sound: 'setSound' };
            var el = map[tab] ? document.getElementById(map[tab]) : null;
            if (el) el.scrollIntoView({behavior:'smooth', block:'center'});
          }, 100);
        }
      }
    });
  };
})();