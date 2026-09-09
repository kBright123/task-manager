(function () {
  'use strict';
  var C = window.Edu.Constants;
  var Store = window.Edu.Store;
  var Speech = window.Edu.Speech;
  var Kids = window.Edu.Kids;
  var Nav = window.Edu.Nav;

  // =====================================================================
  // 设置中心(第四批升级):
  //   · 学习设置(难度)                     · 音效开关(Speech)
  //   · 重置进度: 勾选「我已知晓」二次确认(eduMaskReset)
  //   · 危险操作: 输入指定文字确认(eduMaskConfirm, 如删除宝贝)
  // =====================================================================

  var confirmExpect = '';
  var confirmCb = null;

  window.Edu.Settings = window.Edu.Settings || {};

  var SCREENS = {
    sound:  { title: '🔊 朗读与音效', sub: '控制朗读与音效的开关' }
  };
  var CURRENT_SCREEN = 'sound';

  function qsa(sel) {
    return (typeof document.querySelectorAll === 'function') ? document.querySelectorAll(sel) : [];
  }

  function showScreen(screen) {
    var name = SCREENS[screen] ? screen : 'sound';
    CURRENT_SCREEN = name;
    var screens = qsa('.set-screen');
    for (var i = 0; i < screens.length; i++) {
      screens[i].style.display = (screens[i].getAttribute && screens[i].getAttribute('data-screen') === name) ? '' : 'none';
    }
    var t = document.getElementById('setTitle');
    if (t) t.textContent = SCREENS[name].title;
    var sub = document.getElementById('setSub');
    if (sub) sub.textContent = SCREENS[name].sub;
  }

  // ---- 弹出设置(回填当前值, 仅显示对应屏幕) ----
  window.openSettings = function (screen) {
    var mask = document.getElementById('eduMaskSet');
    if (!mask) return;
    showScreen(screen);
    var s = Store.curSettings();
    var el;
    if ((el = document.getElementById('setSound'))) el.checked = s.sound !== false;
    mask.style.display = 'flex';
  };

  window.setSave = function () {
    var s = Store.curSettings();
    var screen = CURRENT_SCREEN;
    var el;
    // 朗读与音效屏幕
    if (screen === 'sound') {
      if ((el = document.getElementById('setSound'))) {
        s.sound = el.checked;
        try { localStorage.setItem(C.SPEAK_ON_KEY, el.checked ? 'true' : 'false'); } catch (e) {}
        if (window.Edu.Speech && window.Edu.Speech.setSpeakIcon) window.Edu.Speech.setSpeakIcon();
      }
    }
    Store.mergeSet(s);
    Store.saveState();
    document.getElementById('eduMaskSet').style.display = 'none';
    if (window.renderMine) window.renderMine();
    Speech.toast('设置已保存');
  };

  window.toggleSoundInline = function (on) {
    var s = Store.curSettings();
    s.sound = !!on;
    if (on !== undefined && typeof on === 'boolean') {
      try { localStorage.setItem(C.SPEAK_ON_KEY, on ? 'true' : 'false'); } catch (e) {}
    }
    Store.mergeSet(s);
    Store.saveState();
    if (window.Edu.Speech && window.Edu.Speech.setSpeakIcon) window.Edu.Speech.setSpeakIcon();
    if (window.renderMine) window.renderMine();
    Speech.toast(on ? '已开启朗读与音效' : '已关闭朗读与音效');
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

  // ---- 分学科重置: 仅清所选学科(记录/错题/闯关/档位/掌握度/该学科徽章), 星星保留 ----
  window.resetSubjectGo = function () {
    var boxes = document.querySelectorAll('.rs-cb');
    var subjects = [];
    boxes.forEach(function (b) { if (b.checked) subjects.push(b.dataset.s); });
    if (!subjects.length) { Speech.toast('请先勾选要重置的学科'); return; }
    var ack = document.getElementById('resetSubjAck');
    if (ack && !ack.checked) { Speech.toast('请先勾选「我已知晓」'); return; }
    var mask = document.getElementById('eduMaskReset');
    if (mask) mask.style.display = 'none';
    window.requireParent(function () {
      var kid = (window.eduKids && window.eduKids.active()) || null;
      if (!kid) { Speech.toast('请先选择宝贝'); return; }
      var pid = kid.dbId || kid.id.replace(/^db/, '');
      // 未同步的新宝贝先同步建档拿 dbId
      var doReset = function () {
        var badgeKeys = [];
        var Legacy = window.Edu && window.Edu.Legacy;
        if (Legacy && typeof Legacy.catBadges === 'function') {
          subjects.forEach(function (s) {
            (Legacy.catBadges(s) || []).forEach(function (k) {
              var key = String(k);
              if (badgeKeys.indexOf(key) < 0) badgeKeys.push(key);
            });
          });
        }
        fetch('/edu/api/reset_subject', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pid: Number(pid) || 0, subjects: subjects, badgeKeys: badgeKeys })
        }).then(function (r) { return r.json(); }).then(function (res) {
          if (res.ok) location.reload();
          else Speech.toast(res.error || '重置失败');
        }).catch(function () { Speech.toast('网络异常，重置失败'); });
      };
      if (pid && /^\d+$/.test(pid)) { doReset(); return; }
      if (window.eduSync && window.eduSync.pushKids) {
        window.eduSync.pushKids().then(function () {
          var k2 = (window.eduKids && window.eduKids.active()) || null;
          var p2 = k2 && (k2.dbId || String(k2.id).replace(/^db/, ''));
          if (p2 && /^\d+$/.test(p2)) doReset();
          else Speech.toast('宝贝尚未同步，请稍后重试');
        }).catch(function () { Speech.toast('网络异常，重置失败'); });
      } else { Speech.toast('宝贝尚未同步，请稍后重试'); }
    });
  };

  window.Edu.Settings.openSettings = window.openSettings;
  window.Edu.Settings.setSave = window.setSave;
  window.Edu.Settings.openConfirm = window.openConfirm;
  window.Edu.Settings.confirmOk = window.confirmOk;
  window.Edu.Settings.confirmCancel = window.confirmCancel;
  window.Edu.Settings.openReset = window.openReset;
  window.openResetConfirm = window.openReset; // 兼容 mine 页调用
  window.Edu.Settings.openResetConfirm = window.openReset;
  window.Edu.Settings.resetGo = window.resetGo;
  window.Edu.Settings.resetCancel = window.resetCancel;
  window.Edu.Settings.resetSubjectGo = window.resetSubjectGo;

  // 兼容旧调用(第三批测试仍指向 resetAll)
  window.Edu.Settings.resetAll = window.resetGo;
})();