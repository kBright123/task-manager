(function () {
  'use strict';
  var C = window.Edu.Constants;
  var Store = window.Edu.Store;

  var PWD_KEY = C.PWD_KEY;
  var parentUnlocked = false;
  var pwdPending = null;
  var toastT = null;

  function parentPwd() {
    var v = localStorage.getItem(PWD_KEY);
    return (v && /^\d{4}$/.test(v)) ? v : '0000';
  }

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
    parentPwd: parentPwd,
    parentUnlocked: parentUnlocked,
    pwdPending: pwdPending,
    toast: toast,
    renderStars: renderStars,
    PWD_KEY: PWD_KEY
  };

  window.requireParent = function (cb) {
    if (window.Edu.Core && window.Edu.Core.requireParent) return window.Edu.Core.requireParent(cb);
    var p = parentPwd();
    var input = prompt('请输入4位家长口令（默认 0000）');
    if (input === p) { cb(); return; }
    toast('口令错误');
  };

  window.pwdConfirm = function () {
    if (window.Edu.Core && window.Edu.Core.pwdConfirm) return window.Edu.Core.pwdConfirm();
    var inp = document.getElementById('pwdInput');
    if (!inp) return;
    if (inp.value === parentPwd()) {
      window.Edu.Parent.parentUnlocked = true;
      if (window.Edu.Parent.pwdPending) { window.Edu.Parent.pwdPending(); window.Edu.Parent.pwdPending = null; }
      var mask = document.getElementById('eduMaskPwd');
      if (mask) mask.style.display = 'none';
    } else {
      toast('口令错误');
    }
  };

  window.pwdCancel = function () {
    if (window.Edu.Core && window.Edu.Core.pwdCancel) return window.Edu.Core.pwdCancel();
    var mask = document.getElementById('eduMaskPwd');
    if (mask) mask.style.display = 'none';
    window.Edu.Parent.pwdPending = null;
  };

  window.openParentMode = function () {
    window.Edu.Parent.pwdPending = function(){
      if (window.Edu.Settings && window.Edu.Settings.openSettings) window.Edu.Settings.openSettings();
    };
    window.requireParent(function(){});
  };
})();