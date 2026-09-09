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
    var stars = Store.state.stars || 0;
    var bar = document.getElementById('kbStarBar');
    if (bar) {
      var html = '';
      for (var i=0;i<5;i++) html += '<i class="bi bi-star-fill" style="color:'+(i<stars?'#ffd93d':'var(--edu-border-2)')+';font-size:.85rem;margin-right:2px;"></i>';
      bar.innerHTML = html;
    }
    // 同步刷新各页顶部「⭐ 已获得 N 颗星星 + 🔥 打卡第 N 天」文本(welcomeBarHtml 生成的只读节点)
    var recs = Store.state.records || [];
    var streak = Store.checkin ? Store.checkin() : 0;
    var starChip = stars > 0 ? ('⭐ 已获得 ' + stars + ' 颗星星') : '继续闯关赢星星✨';
    var fireChip = '🔥 打卡第 ' + streak + ' 天';
    var nodes = document.querySelectorAll('.ht-star');
    for (var j = 0; j < nodes.length; j++) nodes[j].textContent = starChip;
    var fires = document.querySelectorAll('.ht-fire');
    for (var k = 0; k < fires.length; k++) fires[k].textContent = fireChip;
  }

  window.Edu.Parent = {
    toast: toast,
    renderStars: renderStars
  };

  // 家长手动设置打卡天数: 把所有宝贝的打卡数补到至少指定值(取大, 不回退)
  window.parentSetCheckin = function () {
    var m = document.getElementById('eduMaskSetCheckin');
    if (!m) return;
    var input = document.getElementById('pscDays');
    if (input) input.value = '';
    m.style.display = 'flex';
    setTimeout(function () { if (input) input.focus(); }, 100);
  };
  window.parentSetCheckinCancel = function () {
    var m = document.getElementById('eduMaskSetCheckin');
    if (m) m.style.display = 'none';
  };
  window.parentSetCheckinConfirm = function () {
    var input = document.getElementById('pscDays');
    var days = input ? parseInt(input.value, 10) : 0;
    if (!days || days < 1 || days > 3650) { toast('请输入有效的打卡天数(1-3650)'); if (input) input.focus(); return; }
    window.requireParent(function () {
      if (Store.setAllCheckin) Store.setAllCheckin(days);
      Store.saveState();
      if (window.Edu.Home && window.Edu.Home.fireChipHtml) {
        var streak = Store.checkin ? Store.checkin() : days;
        var fires = document.querySelectorAll('.ht-fire');
        for (var k = 0; k < fires.length; k++) fires[k].textContent = '🔥 打卡第 ' + streak + ' 天';
      }
      parentSetCheckinCancel();
      toast('已将宝贝打卡数设为至少 ' + days + ' 天');
      if (window.renderWish) { try { window.renderWish(); } catch (e) {} }
    });
  };
  window.Edu.Parent.setCheckin = window.parentSetCheckin;

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
            var map = { course: 'setRange', sound: 'setSound' };
            var el = map[tab] ? document.getElementById(map[tab]) : null;
            if (el) el.scrollIntoView({behavior:'smooth', block:'center'});
          }, 100);
        }
      }
    });
  };
})();