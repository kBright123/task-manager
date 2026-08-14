/*
  This file is part of 知行合一 · 任务与知识管理系统 (TaskManager).
  Copyright (C) 2026 TaskManager contributors
  
  This program is free software: you can redistribute it and/or modify
  it under the terms of the GNU General Public License as published by
  the Free Software Foundation, either version 3 of the License, or
  (at your option) any later version.
  
  This program is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  GNU General Public License for more details.
  
  You should have received a copy of the GNU General Public License
  along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

    // Auto-dismiss flash
    setTimeout(function() {
      document.querySelectorAll('.flash-item').forEach(function(el) { el.remove(); });
    }, 5000);

    // Ripple effect on buttons
    document.addEventListener('click', function(e) {
      var btn = e.target.closest('.btn');
      if (!btn) return;
      var rect = btn.getBoundingClientRect();
      var ripple = document.createElement('span');
      ripple.className = 'ripple';
      var size = Math.max(rect.width, rect.height);
      ripple.style.width = ripple.style.height = size + 'px';
      ripple.style.left = (e.clientX - rect.left - size/2) + 'px';
      ripple.style.top = (e.clientY - rect.top - size/2) + 'px';
      btn.appendChild(ripple);
      setTimeout(function() { ripple.remove(); }, 500);
    });

    // Close dropdown on outside click
    document.addEventListener('click', function(e) {
      if (!e.target.closest('.user-badge')) {
        document.querySelectorAll('.user-dropdown').forEach(function(el) {
          el.classList.add('d-none');
        });
      }
      if (!e.target.closest('.nav-notification')) {
        document.getElementById('notificationDropdown')?.classList.add('d-none');
      }
    });
    function toggleNotificationDropdown() {
      var dd = document.getElementById('notificationDropdown');
      dd.classList.toggle('d-none');
    }

    // 浏览器通知: 点击铃铛请求权限; 授权后轮询新通知并弹出系统通知
    (function () {
      if (!('Notification' in window)) return;
      var lastId = parseInt(window.NOTIFY_LAST_ID || 0, 10);
      function notify(t) {
        try {
          var n = new Notification('知行合一 · 新通知', {
            body: t.message, icon: '/static/favicon.svg', tag: 'tm-notify'
          });
          n.onclick = function () { window.focus(); this.close(); };
          setTimeout(function () { n.close(); }, 12000);
        } catch (e) { /* 部分浏览器构造通知可能抛错 */ }
      }
      function poll() {
        fetch('/api/notifications/unread')
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (!d || !d.ok) return;
            var items = d.items || [];
            var maxId = lastId;
            for (var i = 0; i < items.length; i++) {
              var it = items[i];
              if (it.id > maxId) maxId = it.id;
              if (it.id > lastId && it.message) notify(it);
            }
            lastId = Math.max(lastId, maxId);
            // 未读数变化时更新铃铛红点
            var dot = document.querySelector('#notificationBell .dot');
            var count = (d.unread || 0);
            if (count > 0 && !dot) {
              var bell = document.getElementById('notificationBell');
              if (bell) {
                var d2 = document.createElement('span');
                d2.className = 'dot';
                d2.style.cssText = 'position:absolute;top:4px;right:4px;width:9px;height:9px;background:var(--danger);border:2px solid #fff;border-radius:50%;';
                bell.appendChild(d2);
              }
            } else if (count === 0 && dot) { dot.remove(); }
          })
          .catch(function () { /* 静默 */ });
      }
      function start() {
        if (Notification.permission === 'granted') poll();
      }
      var bell = document.getElementById('notificationBell');
      if (bell) bell.addEventListener('click', function () {
        if (Notification.permission === 'default') {
          Notification.requestPermission().then(function (p) {
            if (p === 'granted') poll();
          });
        }
      });
      window.addEventListener('load', function () { start(); setInterval(start, 30000); });
    })();

    // 快捷悬浮球: 展开/收起 + 动作分发(有弹窗则内联打开, 否则跳转)
    var _fab = document.getElementById('quickFab');
    var _fabBtn = document.getElementById('quickFabToggle');
    function closeFab() { if (_fab) _fab.classList.remove('open'); if (_fabBtn) _fabBtn.setAttribute('aria-expanded', 'false'); }
    function fabOpen(btn) {
      closeFab();
      var m = document.getElementById(btn.getAttribute('data-modal'));
      if (m) { bootstrap.Modal.getOrCreateInstance(m).show(); return; }
      window.location.href = btn.getAttribute('data-url');
    }
    function fabKb(btn) {
      closeFab();
      if (typeof kbUploadOpen === 'function') { kbUploadOpen(); return; }
      window.location.href = btn.getAttribute('data-url');
    }
    if (_fab && _fabBtn) {
      (function () {
        var fab = _fab, btn = _fabBtn;
        function openFab() { fab.classList.add('open'); btn.setAttribute('aria-expanded', 'true'); }
        btn.addEventListener('click', function (e) { e.stopPropagation(); if (fab.classList.contains('open')) closeFab(); else openFab(); });
        btn.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); if (fab.classList.contains('open')) closeFab(); else openFab(); } });
        fab.addEventListener('focusout', function (e) { if (!fab.contains(e.relatedTarget)) closeFab(); });
        document.addEventListener('click', function (e) { if (!fab.contains(e.target)) closeFab(); });
        document.addEventListener('shown.bs.modal', function () { fab.classList.add('d-none'); });
        document.addEventListener('hidden.bs.modal', function () { fab.classList.remove('d-none'); });
      })();
    }

    // 全局提交按钮 Loading（防重复提交）: POST/PUT 表单提交后禁用并显示"处理中..."
    document.addEventListener('submit', function (e) {
      var form = e.target;
      if (form.method && form.method.toLowerCase() === 'get') return;
      var btns = form.querySelectorAll('button[type="submit"], button.submit-able, input[type="submit"]');
      for (var i = 0; i < btns.length; i++) {
        var b = btns[i];
        if (b.disabled) continue;
        b.disabled = true;
        var hasText = (b.textContent || '').replace(/\s+/g, ' ').trim().length > 0;
        if (hasText && !(b.dataset && b.dataset.noLoading)) {
          b.dataset.origLabel = b.innerHTML;
          b.innerHTML = '<span class="spinner-border spinner-border-sm" style="width:.75rem;height:.75rem;"></span> 处理中...';
        }
      }
    }, true);

    // 全局 Toast 提示
    window.toast = function (message, type) {
      type = type || 'info';
      var c = document.getElementById('globalToast');
      if (!c) {
        c = document.createElement('div');
        c.id = 'globalToast';
        c.style.cssText = 'position:fixed;right:18px;bottom:76px;z-index:2000;display:flex;flex-direction:column;gap:8px;max-width:320px;';
        document.body.appendChild(c);
      }
      var colors = { success: 'var(--success)', warning: 'var(--warning)', danger: 'var(--danger)', info: 'var(--primary)' };
      var color = colors[type] || colors.info;
      var el = document.createElement('div');
      el.style.cssText = 'background:#fff;border:1px solid var(--gray-200);border-left:4px solid ' + color + ';border-radius:10px;box-shadow:var(--shadow-lg);padding:10px 14px;font-size:.83rem;color:var(--gray-700);animation:tmFadeIn .18s ease-out;';
      el.textContent = message;
      c.appendChild(el);
      setTimeout(function () { el.style.opacity = '0'; el.style.transition = 'opacity .3s'; setTimeout(function () { el.remove(); }, 320); }, 3000);
    };
    // 移动端下拉刷新(webview 内原生下拉刷新不可用时的兜底)
    (function () {
      if (!('ontouchstart' in window)) return;
      if (window.innerWidth > 767) return;
      var THRESHOLD = 70;
      var startY = 0, pulling = false, dist = 0, indicator = null;
      var navTop = document.body.classList.contains('authed') ? 64 : 0;
      function createIndicator() {
        var el = document.createElement('div');
        el.className = 'ptr-indicator';
        el.style.top = navTop + 'px';
        el.innerHTML = '<div class="ptr-arc"><i class="bi bi-arrow-down"></i></div><span class="ptr-txt">下拉刷新</span>';
        document.body.appendChild(el);
        return el;
      }
      function isFormTarget(t) {
        return !!(t && t.closest && t.closest('select, input, textarea, button, .table-responsive, .modal, [data-bs-toggle]'));
      }
      function atTop() { return (window.pageYOffset || document.documentElement.scrollTop) <= 0; }
      function resetIndicator() {
        if (!indicator) return;
        indicator.classList.remove('pull-ready');
        var icon = indicator.querySelector('.ptr-arc i');
        if (icon) { icon.className = 'bi bi-arrow-down'; icon.style.transform = ''; }
        indicator.querySelector('.ptr-txt').textContent = '下拉刷新';
      }
      function hideIndicator() {
        if (!indicator) return;
        indicator.style.transform = 'translate(-50%, -140%)';
        resetIndicator();
        var el = indicator;
        setTimeout(function () { el.remove(); }, 200);
        indicator = null;
      }
      document.addEventListener('touchstart', function (e) {
        if (e.touches.length !== 1) return;
        if (!atTop() || isFormTarget(e.target)) { pulling = false; return; }
        startY = e.touches[0].clientY;
        pulling = true; dist = 0;
      }, { passive: true });
      document.addEventListener('touchmove', function (e) {
        if (!pulling) return;
        if (!atTop()) { pulling = false; return; }
        var dy = e.touches[0].clientY - startY;
        if (dy <= 0) {
          dist = 0;
          if (indicator) {
            indicator.style.transform = 'translate(-50%, -140%)';
            resetIndicator();
          }
          return;
        }
        dist = Math.min(dy * 0.5, 90);
        if (!indicator) indicator = createIndicator();
        indicator.style.transform = 'translate(-50%, ' + (dist - 54) + 'px)';
        var ready = dist >= THRESHOLD;
        var ratio = Math.min(dist / THRESHOLD, 1);
        var icon = indicator.querySelector('.ptr-arc i');
        if (icon) {
          if (ready) { icon.className = 'bi bi-arrow-repeat'; icon.style.transform = ''; }
          else { icon.className = 'bi bi-arrow-down'; icon.style.transform = 'rotate(' + Math.round(ratio * 180) + 'deg)'; }
        }
        indicator.querySelector('.ptr-txt').textContent = ready ? '释放刷新' : '下拉刷新';
        indicator.classList.toggle('pull-ready', ready);
      }, { passive: true });
      function endPull() {
        if (!pulling) return;
        pulling = false;
        var doReload = dist >= THRESHOLD;
        hideIndicator();
        dist = 0;
        if (doReload) window.location.reload();
      }
      document.addEventListener('touchend', endPull);
      document.addEventListener('touchcancel', endPull);
    })();
