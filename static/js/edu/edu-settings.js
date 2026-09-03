(function () {
  'use strict';
  var C = window.Edu.Constants;
  var Store = window.Edu.Store;
  var Speech = window.Edu.Speech;
  var Kids = window.Edu.Kids;
  var Nav = window.Edu.Nav;

  // =====================================================================
  // 设置中心(第四批升级):
  //   · 学习设置(难度/每日限额)        · 护眼时长(默认20分钟)
  //   · 音效开关(Speech)              · 字体大小(小/中/大)
  //   · 家长口令修改                   · 数据导出/导入备份(匿名)
  //   · 重置进度: 勾选「我已知晓」二次确认(eduMaskReset)
  //   · 危险操作: 输入指定文字确认(eduMaskConfirm, 如删除宝贝)
  // =====================================================================

  var confirmExpect = '';
  var confirmCb = null;

  function applyFont(f) {
    var root = document.documentElement;
    if (!root) return;
    var cls = 'edu-font-s';
    if (f === 'l') cls = 'edu-font-l';
    else if (!f || f === 'm') cls = 'edu-font-m';
    root.className = root.className.replace(/\bedu-font-[sml]\b/g, '').trim();
    root.classList.add(cls);
  }
  window.Edu.Settings = window.Edu.Settings || {};
  window.Edu.Settings.applyFont = applyFont;

  // ---- 弹出设置(回填当前值) ----
  window.openSettings = function () {
    var mask = document.getElementById('eduMaskSet');
    if (!mask) return;
    var s = Store.curSettings();
    document.getElementById('setRange').value = s.range || 0;
    document.getElementById('setNoCarry').checked = !!s.nocarry;
    document.getElementById('setMult').checked = !!s.mult;
    document.getElementById('setDailyQ').value = s.dailyQ || 0;
    document.getElementById('setDailyMin').value = s.dailyMin || 0;
    document.getElementById('setPwd').value = '';
    document.getElementById('setTrace').checked = (s.show && s.show.trace) !== false;
    document.getElementById('setPar').checked = (s.show && s.show.par) !== false;
    // 新增: 护眼/音效/字体
    var eye = document.getElementById('setEyeMin');
    if (eye) eye.value = s.eyeMin || C.REST_DEFAULT;
    var snd = document.getElementById('setSound');
    if (snd) snd.checked = s.sound !== false;
    var ft = document.getElementById('setFont');
    if (ft) ft.value = s.font || 'm';
    mask.style.display = 'flex';
  };

  window.setSave = function () {
    var s = Store.curSettings();
    s.range = parseInt(document.getElementById('setRange').value, 10) || 0;
    s.nocarry = document.getElementById('setNoCarry').checked;
    s.mult = document.getElementById('setMult').checked;
    s.dailyQ = parseInt(document.getElementById('setDailyQ').value, 10) || 0;
    s.dailyMin = parseInt(document.getElementById('setDailyMin').value, 10) || 0;
    s.show = s.show || {};
    s.show.trace = document.getElementById('setTrace').checked;
    s.show.par = document.getElementById('setPar').checked;
    // 护眼/音效/字体
    var eye = document.getElementById('setEyeMin');
    if (eye) s.eyeMin = Math.min(60, Math.max(5, parseInt(eye.value, 10) || C.REST_DEFAULT));
    var snd = document.getElementById('setSound');
    if (snd) {
      s.sound = snd.checked;
      try { localStorage.setItem(C.SPEAK_ON_KEY, snd.checked ? 'true' : 'false'); } catch (e) {}
      if (window.Edu.Speech && window.Edu.Speech.setSpeakIcon) window.Edu.Speech.setSpeakIcon();
    }
    var ft = document.getElementById('setFont');
    if (ft) { s.font = ft.value || 'm'; applyFont(s.font); }
    var pwd = document.getElementById('setPwd').value;
    if (pwd && /^\d{4}$/.test(pwd)) localStorage.setItem(C.PWD_KEY, pwd);
    else if (pwd) { Speech.toast('口令需为4位数字'); return; }
    Store.mergeSet(s);
    Store.saveState();
    document.getElementById('eduMaskSet').style.display = 'none';
    Speech.toast('设置已保存');
  };

  // ---- 危险操作: 输入指定文字确认 ----
  window.openConfirm = function (opts) {
    if (!opts) return;
    var mask = document.getElementById('eduMaskConfirm');
    if (!mask) return;
    confirmExpect = String(opts.expect === undefined || opts.expect === null || opts.expect === '' ? '删除' : opts.expect);
    confirmCb = opts.cb || null;
    var title = document.getElementById('cTitle');
    var sub = document.getElementById('cSub');
    var expect = document.getElementById('cExpect');
    var input = document.getElementById('cInput');
    if (title) title.textContent = opts.title || '确认操作';
    if (sub) sub.textContent = opts.sub || '';
    if (expect) expect.textContent = confirmExpect;
    var okBtn = document.getElementById('cOkBtn');
    if (okBtn) okBtn.textContent = opts.okText || '确认';
    if (input) input.value = '';
    mask.style.display = 'flex';
  };

  window.confirmOk = function () {
    var input = document.getElementById('cInput');
    if (input && input.value.trim() !== confirmExpect) {
      Speech.toast('输入内容不匹配，请重新输入');
      input.focus && input.focus();
      return;
    }
    var mask = document.getElementById('eduMaskConfirm');
    if (mask) mask.style.display = 'none';
    var cb = confirmCb;
    confirmCb = null;
    confirmExpect = '';
    if (cb) cb();
  };
  window.confirmCancel = function () {
    var mask = document.getElementById('eduMaskConfirm');
    if (mask) mask.style.display = 'none';
    confirmCb = null;
    confirmExpect = '';
  };

  // ---- 重置进度: 勾选「我已知晓」二次确认 ----
  window.openReset = function () {
    var mask = document.getElementById('eduMaskReset');
    if (!mask) return;
    var ack = document.getElementById('resetAck');
    if (ack) ack.checked = false;
    mask.style.display = 'flex';
  };

  window.resetGo = function () {
    var ack = document.getElementById('resetAck');
    if (ack && !ack.checked) { Speech.toast('请先勾选「我已知晓」'); return; }
    var mask = document.getElementById('eduMaskReset');
    if (mask) mask.style.display = 'none';
    window.requireParent(function () {
      var btn = document.getElementById('resetGoBtn');
      if (btn) { btn.disabled = true; }
      fetch('/edu/api/reset', { method: 'POST' }).then(function (r) { return r.json(); }).then(function (res) {
        if (btn) { btn.disabled = false; }
        if (res.ok) { try { localStorage.clear(); } catch (e) {} location.reload(); }
        else { Speech.toast(res.error || '重置失败'); }
      }).catch(function(){ if (btn) { btn.disabled = false; } Speech.toast('重置失败'); });
    });
  };
  window.resetCancel = function () {
    var mask = document.getElementById('eduMaskReset');
    if (mask) mask.style.display = 'none';
  };

  // ---- 家长模式保险(锁定) ----
  window.lockParentMode = function () {
    window.Edu.Parent.parentUnlocked = false;
    window.Edu.Parent.pwdPending = null;
    var b = document.getElementById('parentLocked');
    if (b) b.textContent = '已锁定';
    Speech.toast('家长模式已锁定');
  };

  window.Edu.Settings.openSettings = window.openSettings;
  window.Edu.Settings.setSave = window.setSave;
  window.Edu.Settings.openConfirm = window.openConfirm;
  window.Edu.Settings.confirmOk = window.confirmOk;
  window.Edu.Settings.confirmCancel = window.confirmCancel;
  window.Edu.Settings.openReset = window.openReset;
  window.Edu.Settings.openResetConfirm = window.openReset; // 兼容 mine 页调用
  window.Edu.Settings.resetGo = window.resetGo;
  window.Edu.Settings.resetCancel = window.resetCancel;
  window.Edu.Settings.lockParentMode = window.lockParentMode;

  // 兼容旧调用(第三批测试仍指向 resetAll)
  window.Edu.Settings.resetAll = window.resetGo;
})();