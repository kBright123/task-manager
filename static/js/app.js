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
    function closeFab() {
      if (_fab) {
        var s = document.getElementById('fabSheet');
        if (s) {
          s.classList.remove('max');
          var b = s.querySelector('.fab-sheet-max');
          if (b) {
            var ic = b.querySelector('i');
            if (ic) ic.className = 'bi bi-arrows-angle-expand';
            b.setAttribute('aria-label', '最大化');
          }
        }
        _fab.classList.remove('open');
        if (_fabBtn) _fabBtn.setAttribute('aria-expanded', 'false');
      }
    }
    function fabToggleMax() {
      var s = document.getElementById('fabSheet');
      if (!s) return;
      var on = s.classList.toggle('max');
      var b = s.querySelector('.fab-sheet-max');
      if (b) {
        var ic = b.querySelector('i');
        if (ic) ic.className = on ? 'bi bi-arrows-angle-contract' : 'bi bi-arrows-angle-expand';
        b.setAttribute('aria-label', on ? '还原' : '最大化');
      }
      if (!on) positionFabSheet();
    }
    function positionFabSheet() {
      var s = document.getElementById('fabSheet');
      if (!s || !_fabBtn) return;
      var r = _fabBtn.getBoundingClientRect();
      var vw = window.innerWidth, vh = window.innerHeight;
      var gap = 10;
      var w = Math.min(560, Math.max(280, vw - 28));
      var maxH = Math.min(640, vh - 120);
      var above = r.top - gap - 4;
      var below = vh - r.bottom - gap - 4;
      var height = Math.max(160, Math.min(maxH, Math.max(above, below)));
      var top;
      if (above >= below) top = Math.max(4, r.top - height - gap);
      else top = Math.min(r.bottom + gap, Math.max(4, vh - height - 4));
      var left = Math.max(4, Math.min(r.right - w, vw - w - 4));
      s.style.setProperty('--fab-w', w + 'px');
      s.style.setProperty('--fab-h', height + 'px');
      s.style.setProperty('--fab-top', top + 'px');
      s.style.setProperty('--fab-left', left + 'px');
    }
    var _FAB_CHAT_MAX_TURNS = 5;
    function _fabChatKey() { var uid = (window.CURRENT_USER && window.CURRENT_USER.id) || 'anon'; return 'fabChatHistory:' + uid; }
    function fabChatTrim() { var box = document.getElementById('fabChatBox'); if (!box) return; var turns = box.querySelectorAll('.fab-turn'); for (var i = 0; i < turns.length - _FAB_CHAT_MAX_TURNS; i++) turns[i].remove(); }
    function fabChatPersist() { var box = document.getElementById('fabChatBox'); if (!box) return; try { var turns = box.querySelectorAll('.fab-turn'); var arr = []; for (var i = Math.max(0, turns.length - _FAB_CHAT_MAX_TURNS); i < turns.length; i++) arr.push(turns[i].innerHTML); localStorage.setItem(_fabChatKey(), JSON.stringify(arr)); } catch (e) { /* ignore storage errors */ } }
    function fabChatCommit() { fabChatTrim(); fabChatPersist(); }
    function fabChatClear() {
      // 只清小知对话内容(展示 + 本地历史), 不动联系人/会话列表
      if (!confirm('清除小知对话内容？联系人会话不受影响。')) return;
      var box = document.getElementById('fabChatBox');
      var empty = document.getElementById('fabChatEmpty');
      if (box) box.innerHTML = '';
      if (box && empty) box.appendChild(empty);
      if (empty) empty.style.display = '';
      try { localStorage.removeItem(_fabChatKey()); } catch (e) { /* ignore */ }
      fabChatUnreadRefresh();
    }
    function fabChatRestore() {
      var box = document.getElementById('fabChatBox');
      if (!box) return;
      var arr = [];
      try { arr = JSON.parse(localStorage.getItem(_fabChatKey()) || '[]'); } catch (e) { arr = []; }
      if (!Array.isArray(arr) || !arr.length) return;
      arr.slice(-_FAB_CHAT_MAX_TURNS).forEach(function (html) { var t = document.createElement('div'); t.className = 'fab-turn'; t.innerHTML = html; box.appendChild(t); });
      var empty = document.getElementById('fabChatEmpty');
      if (empty) empty.style.display = 'none';
      setTimeout(function () { box.scrollTop = box.scrollHeight; }, 0);
    }
    fabChatRestoreDeferred();
    window.addEventListener('pagehide', fabChatPersist);
    function fabChatRestoreDeferred() {
      // app.js 在 base.html 中先于 window.CURRENT_USER 定义(551行)执行;
      // 必须等解析完成、CURRENT_USER 就绪后再按用户键恢复历史
      if (document.readyState === 'loading') {
        window.addEventListener('DOMContentLoaded', fabChatRestore);
      } else {
        fabChatRestore();
      }
    }
    function showQuickTaskModal() {
      var m = document.getElementById('quickTaskModal');
      if (m) { bootstrap.Modal.getOrCreateInstance(m).show(); return; }
      var selfId = parseInt(window.CURRENT_USER && window.CURRENT_USER.id, 10) || 0;
      var selfName = (window.CURRENT_USER && (window.CURRENT_USER.name || window.CURRENT_USER.username)) || '我';
      if (!document.getElementById('quickTaskModal')) {
        var html = '' +
          '<div id="quickTaskModal" class="modal fade" tabindex="-1">' +
            '<div class="modal-dialog modal-dialog-centered">' +
              '<div class="modal-content">' +
                '<div class="modal-header py-2"><span style="font-weight:600;"><i class="bi bi-list-task" style="color:var(--primary);"></i> 快速创建待办</span><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>' +
                '<div id="qtStepInput">' +
                  '<div class="modal-body">' +
                    '<div style="position:relative;">' +
                      '<textarea id="qtText" class="form-control" rows="4" placeholder="输入待办，@选择人员 · 自动解析标题/时间/分配，支持每周/每月/每年重复\n例：开发登录功能 明天9点到下周五18点 @张三 @李四" style="font-size:.84rem;resize:none;"></textarea>' +
                    '</div>' +
                    '<div class="mt-2"><small style="color:var(--gray-500);font-size:.72rem;"><i class="bi bi-info-circle"></i> 输入 @ 选择人员，自动解析标题、时间、分配</small></div>' +
                  '</div>' +
                  '<div class="modal-footer py-2"><span class="text-muted" id="qtErr" style="font-size:.75rem;"></span><button class="btn btn-sm btn-primary" onclick="quickTaskParse()"><i class="bi bi-send"></i> 发布</button></div>' +
                '</div>' +
                '<div id="qtStepReview" style="display:none;">' +
                  '<div class="modal-body" style="font-size:.85rem;max-height:68vh;overflow-y:auto;">' +
                    '<div id="qtDupWarn" class="mb-2"></div>' +
                    '<div class="mb-2"><label class="form-label" style="font-size:.8rem;">标题</label><input type="text" id="qtTitle" class="form-control form-control-sm" maxlength="200" style="font-size:.85rem;"></div>' +
                    '<div class="mb-2"><label class="form-label" style="font-size:.8rem;">分类</label><select id="qtCategory" class="form-select form-control-sm" style="max-width:200px;font-size:.85rem;"><option value="工作">工作</option><option value="个人">个人</option><option value="会议">会议</option><option value="培训">培训</option><option value="考试">考试</option></select></div>' +
                    '<div class="row g-2 mb-2">' +
                      '<div class="col-6"><label class="form-label" style="font-size:.8rem;">开始时间</label><input type="datetime-local" id="qtStart" class="form-control form-control-sm"></div>' +
                      '<div class="col-6"><label class="form-label" style="font-size:.8rem;">截止时间</label><input type="datetime-local" id="qtEnd" class="form-control form-control-sm"></div>' +
                    '</div>' +
                    '<div class="mb-2">' +
                      '<label class="form-label" style="font-size:.8rem;">周期</label>' +
                      '<select id="qtRecurrenceSelect" class="form-select form-control-sm" style="max-width:200px;font-size:.82rem;" onchange="qtUpdateRecurrence()">' +
                        '<option value="" data-count="0" data-interval="0">不重复</option>' +
                        '<option value="weekly" data-count="4" data-interval="7">每周（4期）</option>' +
                        '<option value="monthly" data-count="3" data-interval="30">每月（3期）</option>' +
                        '<option value="yearly" data-count="2" data-interval="365">每年（2期）</option>' +
                        '<option value="custom" data-count="0" data-interval="0">自定义</option>' +
                      '</select>' +
                      '<span id="qtRecurrenceCustom" class="d-none" style="display:none;font-size:.78rem;color:var(--gray-600);">' +
                        '每隔 <input type="number" id="qtCustomInterval" class="form-control form-control-sm" style="width:48px;text-align:center;" min="1" value="7"> 天，共 <input type="number" id="qtCustomCount" class="form-control form-control-sm" style="width:44px;text-align:center;" min="1" value="3"> 期' +
                        '<button type="button" class="btn btn-sm btn-outline-primary ms-1" onclick="qtApplyCustomRecurrence()">应用</button>' +
                      '</span>' +
                      '<span id="qtRecurrenceHint" class="text-info" style="font-size:.75rem;"></span>' +
                    '</div>' +
                    '<div class="mb-2">' +
                      '<label class="form-label" style="font-size:.8rem;">分配人员</label>' +
                      '<div id="qtAssignBox" class="d-flex flex-wrap gap-1" style="border:1px solid var(--gray-200);border-radius:8px;padding:6px;background:var(--gray-50);"></div>' +
                    '</div>' +
                    '<div class="mb-1"><label class="form-label" style="font-size:.8rem;">待办描述</label><textarea id="qtDesc" class="form-control form-control-sm" rows="2" style="font-size:.8rem;resize:none;"></textarea></div>' +
                  '</div>' +
                  '<div class="modal-footer py-2 px-3"><span class="text-muted" id="qtErr2" style="font-size:.75rem;"></span><button class="btn btn-sm btn-outline-secondary" onclick="quickTaskBack()"><i class="bi bi-arrow-left"></i> 返回</button><button class="btn btn-sm btn-primary" onclick="quickTask()"><i class="bi bi-check"></i> 确认发布</button></div>' +
                '</div>' +
              '</div>' +
            '</div>' +
          '</div>';
        document.body.insertAdjacentHTML('beforeEnd', html);
      }
      if (typeof window.qtUsers === 'undefined') {
        window.qtUsers = [
          { id: 0, name: '所有人', keyword: '@所有人' },
          { id: selfId, name: selfName, keyword: selfName }
        ];
        window.qtSelfId = selfId;
      }
      if (typeof window.quickTaskParse !== 'function') {
        window.quickTaskParse = function () {
          var text = document.getElementById('qtText').value.trim();
          var errEl = document.getElementById('qtErr');
          if (text.length < 2) { errEl.textContent = '请至少输入2个字'; return; }
          errEl.textContent = '发布中...';
          fetch('/api/quick-task/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: text }) })
            .then(function (r) { return r.json(); }).then(function (d) {
              if (!d.ok) { errEl.textContent = (d.not_ready ? '⏳ ' : '') + (d.error || '解析失败'); return; }
              document.getElementById('qtTitle').value = d.title;
              document.getElementById('qtStart').value = d.start_time;
              document.getElementById('qtEnd').value = d.end_time;
              document.getElementById('qtCategory').value = d.category;
              document.getElementById('qtDesc').value = d.description;
              window.qtRec = { mode: '', interval: d.recurrence_interval_days || 0, count: d.recurrence_count || 0 };
              var sel = document.getElementById('qtRecurrenceSelect');
              var hint = document.getElementById('qtRecurrenceHint');
              var matched = false;
              if (sel && hint && sel.options) {
                for (var i = 0; i < sel.options.length; i++) {
                  var o = sel.options[i];
                  if (o.value && parseInt(o.dataset.interval) === window.qtRec.interval && parseInt(o.dataset.count) === window.qtRec.count) {
                    sel.selectedIndex = i; hint.innerHTML = '<i class="bi bi-arrow-repeat"></i> ' + o.text; matched = true; break;
                  }
                }
                if (!matched) {
                  if (window.qtRec.interval && window.qtRec.count > 0) {
                    sel.value = 'custom';
                    var cint = document.getElementById('qtCustomInterval'), ccnt = document.getElementById('qtCustomCount');
                    var cwrap = document.getElementById('qtRecurrenceCustom');
                    if (cint) cint.value = window.qtRec.interval;
                    if (ccnt) ccnt.value = window.qtRec.count;
                    if (cwrap) cwrap.style.display = 'flex';
                    hint.innerHTML = '<i class="bi bi-arrow-repeat"></i> 每' + window.qtRec.interval + '天，共' + window.qtRec.count + '期';
                  } else { sel.value = ''; hint.textContent = ''; }
                }
              }
              document.getElementById('qtDupWarn').innerHTML = (d.duplicate_tasks && d.duplicate_tasks.length) ? '<div class="alert alert-warning py-1 px-2" style="font-size:.75rem;">⚠️ 存在相似待办：' + d.duplicate_tasks.map(function (t) { return window.esc ? window.esc(t.title) : String(t.title).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }).slice(0, 3).join('、') + '</div>' : '';
              qtBuildAssignees(d.assignee_ids, d.assignee_names);
              errEl.textContent = '';
              document.getElementById('qtStepInput').style.display = 'none';
              document.getElementById('qtStepReview').style.display = '';
            }).catch(function () { errEl.textContent = '解析失败，请重试'; });
        };
      }
      if (typeof window.quickTaskBack !== 'function') {
        window.quickTaskBack = function () {
          document.getElementById('qtStepReview').style.display = 'none';
          document.getElementById('qtStepInput').style.display = '';
          document.getElementById('qtErr').textContent = '';
        };
      }
      if (typeof window.qtBuildAssignees !== 'function') {
        window.qtBuildAssignees = function (ids, names) {
          ids = ids || []; names = names || [];
          var box = document.getElementById('qtAssignBox');
          if (!box) return;
          function qesc(s) { return window.esc ? window.esc(s) : String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }
          var html = '';
          for (var i = 0; i < ids.length; i++) {
            var checked = ids[i] === selfId ? 'checked' : '';
            html += '<label class="form-check form-check-inline" style="font-size:.78rem;cursor:pointer;margin-right:6px;"><input type="checkbox" class="form-check-input qt-assignee" value="' + qesc(ids[i]) + '" ' + checked + '> ' + (qesc(names[i]) || ('用户' + qesc(ids[i]))) + '</label>';
          }
          box.innerHTML = html;
        };
      }
      if (typeof window.qtUpdateRecurrence !== 'function') {
        window.qtUpdateRecurrence = function () {
          var sel = document.getElementById('qtRecurrenceSelect');
          var opt = sel.options[sel.selectedIndex];
          var custom = document.getElementById('qtRecurrenceCustom');
          var hint = document.getElementById('qtRecurrenceHint');
          var rec = window.qtRec;
          if (opt.value === 'custom') {
            custom.style.display = 'flex';
            if (rec) { rec.mode = ''; rec.interval = 0; rec.count = 0; hint.textContent = ''; }
            return;
          }
          custom.style.display = 'none';
          if (!rec) rec = window.qtRec = {};
          rec.mode = opt.value;
          rec.interval = parseInt(opt.dataset.interval) || 0;
          rec.count = parseInt(opt.dataset.count) || 0;
          hint.innerHTML = opt.value ? ('<i class="bi bi-arrow-repeat"></i> ' + opt.text) : '';
        };
      }
      if (typeof window.qtApplyCustomRecurrence !== 'function') {
        window.qtApplyCustomRecurrence = function () {
          var interval = parseInt(document.getElementById('qtCustomInterval').value) || 7;
          var count = parseInt(document.getElementById('qtCustomCount').value) || 3;
          if (count < 1) count = 1;
          window.qtRec.mode = 'custom'; window.qtRec.interval = interval; window.qtRec.count = count;
          document.getElementById('qtRecurrenceHint').innerHTML = '<i class="bi bi-arrow-repeat"></i> 每' + interval + '天，共' + count + '期';
        };
      }
      if (typeof window.quickTask !== 'function') {
        window.quickTask = function () {
          var title = document.getElementById('qtTitle').value.trim();
          var err2 = document.getElementById('qtErr2');
          if (title.length < 2) { err2.textContent = '待办标题至少2个字'; return; }
          if (!document.getElementById('qtStart').value) { err2.textContent = '请填写开始时间'; return; }
          if (!document.getElementById('qtEnd').value) { err2.textContent = '请填写结束时间'; return; }
          var ids = [];
          document.querySelectorAll('.qt-assignee:checked').forEach(function (c) { ids.push(parseInt(c.value)); });
          if (ids.length === 0) { err2.textContent = '请至少选择一位负责人(可勾选自己)'; return; }
          var re = (window.qtRec && window.qtRec.interval) || 0;
          var rc = (window.qtRec && window.qtRec.count) || 0;
          var body = {
            title: title,
            start_time: document.getElementById('qtStart').value,
            end_time: document.getElementById('qtEnd').value,
            category: document.getElementById('qtCategory').value,
            description: document.getElementById('qtDesc').value,
            assignee_ids: ids,
            group_ids: [],
            is_all: false,
            assign_self: true,
            recurrence_interval_days: re,
            recurrence_count: rc
          };
          var btn = event && event.target ? event.target.closest('button') : null;
          if (btn) btn.disabled = true;
          fetch('/api/quick-task', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
            .then(function (r) { return r.json(); }).then(function (d) {
              if (d.ok) { window.location.href = '/user/tasks?new=' + d.task_id; } else if (d.not_ready) { err2.textContent = '⏳ ' + (d.error || '智能解析准备中，请稍候再试'); } else { err2.textContent = d.error || '创建失败'; }
            }).catch(function () { err2.textContent = '创建失败，请重试'; }).finally(function () { if (btn) btn.disabled = false; });
        };
      }
      bootstrap.Modal.getOrCreateInstance(document.getElementById('quickTaskModal')).show();
    }
    function fabKb(btn) {
      closeFab();
      if (typeof kbUploadOpen === 'function') { kbUploadOpen(); return; }
      var dynamicKbModal = document.getElementById('kbUploadModal');
      if (!dynamicKbModal) {
        var kbModalHtml = '<div id="kbUploadModal" class="modal fade" tabindex="-1"><div class="modal-dialog modal-dialog-centered"><div class="modal-content"><div class="modal-header py-2"><span style="font-weight:600;"><i class="bi bi-cloud-arrow-up" style="color:var(--warning);"></i> 上传知识</span><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div><div class="modal-body">上传知识功能</div><div class="modal-footer py-2"><button class="btn btn-sm btn-primary">开始上传</button></div></div></div></div>';
        document.body.insertAdjacentHTML('beforeEnd', kbModalHtml);
      }
      bootstrap.Modal.getOrCreateInstance(document.getElementById('kbUploadModal')).show();
    }
    function fabOpen(btn) {
      closeFab();
      var modalId = btn.getAttribute('data-modal');
      var url = btn.getAttribute('data-url');
      if (modalId) {
        var m = document.getElementById(modalId);
        if (m) { bootstrap.Modal.getOrCreateInstance(m).show(); return; }
        if (modalId === 'quickTaskModal' && typeof showQuickTaskModal === 'function') { showQuickTaskModal(); return; }
        if (modalId === 'quickNoteModal' && typeof showQuickNoteModal === 'function') { showQuickNoteModal(); return; }
      }
      if (url) { window.location.href = url; }
    }
    function fabMode() {
      closeFab();
      if (typeof toggleEduMode === 'function') toggleEduMode();
    }
    function fabDialogHide() {
      closeFab();
    }
    function fabDialogAction(fn) {
      closeFab();
      setTimeout(function () { if (typeof fn === 'function') fn(); }, 160);
    }
    function fabChatBubble(container, who, html) {
      var d = document.createElement('div');
      d.className = 'fab-chat-' + who;
      d.innerHTML = html;
      container.appendChild(d);
      var box = (container.closest && container.closest('.fab-chat-box')) || container;
      box.scrollTop = box.scrollHeight;
      return d;
    }
    function fabChatRefLinks(answer, hrefs, cls) {
      var esc = window.esc || function (s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'); };
      var safe = esc(answer);
      var out = safe.replace(/\[资料\s*(\d+)\]/g, function (m, n) {
        var h = hrefs[parseInt(n, 10) - 1];
        return h ? '<a class="fab-chat-ref" target="_blank" rel="noopener" href="' + esc(h) + '">' + m + '</a>' : m;
      });
      return '<div style="white-space:pre-wrap;" class="' + (cls || '') + '">' + out + '</div>';
    }
    /* ---- 微信式会话: 左侧会话列表(小知置顶 + 同组联系人) + 右侧对话窗 + @联想 ---- */
    var _fabPeerUid = 0;
    var _fabPeerUser = null;
    var _fabContacts = [];
    var _fabQuoteMsg = null;
    var _fabBotPending = false;
    var _fabMsgsById = {};
    function _fabEsc(s) {
      return window.esc ? window.esc(s) : String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    function _fabAva(name) { return (name || '?').trim().charAt(0).toUpperCase(); }
    function _fabNowHm() { var d = new Date(); function p(n) { return (n < 10 ? '0' : '') + n; } return p(d.getHours()) + ':' + p(d.getMinutes()); }
    function _fabScroll() { var b = document.getElementById('fabPeerMsgs'); if (b) b.scrollTop = b.scrollHeight; }
    function fabSheetScrollBottom() {
      // 展开悬浮球时把聊天区域对齐到最后一条(小知/对侧都滚), 避免停在旧位置
      var cb = document.getElementById('fabChatBox');
      if (cb) cb.scrollTop = cb.scrollHeight;
      var pb = document.getElementById('fabPeerMsgs');
      if (pb) pb.scrollTop = pb.scrollHeight;
    }
    function _fabInput() {
      return document.getElementById(_fabPeerUid ? 'fabPeerInput' : 'fabChatInput');
    }
    function _fabMentionBox() {
      return document.getElementById(_fabPeerUid ? 'fabPeerMention' : 'fabMention');
    }
    function fabContactsLoad(cb) {
      fetch('/api/chat/contacts').then(function (r) { return r.json(); }).then(function (d) {
        _fabContacts = (d && d.contacts) || [];
        fabSideBuild();
        _fabRefreshPeerStatus();
        fabChatUnreadRefresh();
        if (cb) cb(_fabContacts);
      }).catch(function () {
        if (!_fabContacts.length) {
          var list = document.getElementById('fabSideList');
          if (list && !list.querySelector('.fab-side-err')) {
            list.insertAdjacentHTML('afterbegin',
              '<div class="fab-side-err" style="font-size:.66rem;color:var(--gray-400);padding:10px 8px;">会话加载失败 <a href="javascript:fabContactsLoad(null)" style="color:var(--primary)">重试</a></div>');
          }
        }
        if (cb) cb(_fabContacts);
      });
    }
    function _fabFindContact(fragment) {
      var fx = String(fragment || '').trim().toLowerCase();
      if (!fx) return null;
      var hits = _fabContacts.filter(function (c) { return (c.name || '').toLowerCase().indexOf(fx) === 0 || (c.username || '').toLowerCase().indexOf(fx) === 0; });
      if (hits.length) return hits[0];
      return _fabContacts.filter(function (c) { return (c.name || '').indexOf(fragment) >= 0 || (c.username || '').toLowerCase().indexOf(fx) >= 0; })[0] || null;
    }
    function _fabRefreshInput() {
      var bi = document.getElementById('fabChatInput');
      if (bi) bi.placeholder = '输入消息';
      var pi = document.getElementById('fabPeerInput');
      if (pi) pi.placeholder = _fabPeerUser ? ('回复 ' + _fabPeerUser.name) : '输入消息';
    }
    /* 左侧会话列表: 搜索框(姓名/用户名搜本系统用户) + 小知置顶 + 联系人 */
    var _fabSideQuery = '';
    var _fabSearchTimer = null;
    var _fabSearchSeq = 0;
    var _fabSearching = false;
    var _fabSearchResults = null;
    function fabSideSearch(ev) {
      _fabSideQuery = (ev.target.value || '').trim().toLowerCase();
      clearTimeout(_fabSearchTimer);
      if (_fabSideQuery) {
        _fabSearchResults = null;
        _fabSearching = true;
        fabSideBuild();
        _fabSearchTimer = setTimeout(function () { fabSearchFetch(_fabSideQuery); }, 250);
      } else {
        _fabSearchResults = null;
        _fabSearching = false;
        _fabSearchSeq++;
        fabSideBuild();
      }
    }
    function _fabSideReset() {
      _fabSideQuery = '';
      _fabSearchResults = null;
      _fabSearching = false;
      clearTimeout(_fabSearchTimer);
      var si = document.getElementById('fabSideSearch');
      if (si) si.value = '';
      fabSideBuild();
    }
    function fabSearchFetch(q) {
      var seq = ++_fabSearchSeq;
      fetch('/api/chat/search?q=' + encodeURIComponent(q))
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (seq !== _fabSearchSeq || q !== _fabSideQuery) return;
          _fabSearchResults = (d && d.users) || [];
          _fabSearching = false;
          fabSideBuild();
        }).catch(function () {
          if (seq !== _fabSearchSeq) return;
          _fabSearchResults = _fabContacts.filter(function (c) {
            return (c.name || '').toLowerCase().indexOf(q) >= 0 || (c.username || '').toLowerCase().indexOf(q) >= 0;
          });
          _fabSearching = false;
          fabSideBuild();
        });
    }
    function fabSideBuild() {
      var list = document.getElementById('fabSideList');
      if (!list) return;
      var activeUid = _fabPeerUid || 0;
      var q = _fabSideQuery;
      var rows = '';
      if (!q) {
        rows += '<div class="fab-side-item' + (activeUid === 0 ? ' active' : '') + '" data-sid="0" onclick="fabSelectAssist()">' +
          '<div class="fab-pc-avatar fab-side-bear">🐻</div>' +
          '<div class="fab-pc-main"><div class="fab-pc-name">小知</div></div>' +
          (activeUid === 0 ? '<span class="fab-side-dot"></span>' : '') +
          '</div>';
      }
      var contacts = [];
      var searching = false;
      if (q) {
        if (_fabSearching) {
          searching = true;
          rows += '<div style="font-size:.66rem;color:var(--gray-400);padding:10px 8px;">搜索中…</div>';
        } else if (_fabSearchResults) {
          contacts = _fabSearchResults.map(function (u) {
            var cx = _fabContacts.filter(function (c) { return c.id === u.id; })[0];
            return cx || u;
          });
        } else {
          contacts = _fabContacts.filter(function (c) {
            return (c.name || '').toLowerCase().indexOf(q) >= 0 || (c.username || '').toLowerCase().indexOf(q) >= 0;
          });
        }
      } else {
        contacts = _fabContacts.filter(function (c) { return !!c.last_ts; });
        if (activeUid) {
          var existsAct = contacts.some(function (c) { return c.id === activeUid; });
          if (!existsAct) {
            var act = _fabContacts.filter(function (c) { return c.id === activeUid; })[0];
            if (act) contacts.unshift(act);
          }
        }
      }
      rows += (contacts || []).map(function (c) {
        var row = '<div class="fab-side-item' + (activeUid === c.id ? ' active' : '') + '" data-sid="' + c.id + '" onclick="fabSelect(' + c.id + ')">';
        row += '<div class="fab-pc-avatar">' + _fabEsc(_fabAva(c.name)) + '</div>';
      row += '<div class="fab-pc-main">';
      row += '<div class="fab-pc-name"><span class="fab-pc-name-txt">' + _fabEsc(c.name) + '</span>' + (c.hint ? ' <span class="fab-chip-hot">' + _fabEsc(c.hint) + '</span>' : '') + (c.hot ? ' <span class="fab-chip-hot">常问</span>' : '') + '</div>';
      if (c.last_preview) row += '<div class="fab-pc-preview">' + _fabEsc(c.last_preview) + '</div>';
      row += '</div>';
      row += '<div class="fab-pc-side">';
      if (c.last_ts) row += '<div class="fab-pc-time">' + _fabEsc(String(c.last_ts).slice(5, 16)) + '</div>';
      if (c.unread) row += '<span class="fab-pc-unread">' + c.unread + '</span>';
      row += '</div></div>';
      return row;
      }).join('');
      if (q && !searching && !(contacts && contacts.length)) {
        rows += '<div style="font-size:.66rem;color:var(--gray-400);padding:10px 8px;">未找到联系人</div>';
      }
      list.innerHTML = rows;
    }
    function _fabSideActive(uid) {
      var list = document.getElementById('fabSideList');
      if (!list) return;
      Array.prototype.forEach.call(list.querySelectorAll('.fab-side-item'), function (n) {
        n.classList.toggle('active', String(n.getAttribute('data-sid')) === String(uid || 0));
      });
    }
    /* 左侧选会话 */
    function fabPeerDelById(peerId) {
      if (!peerId) return;
      var c = _fabContacts.filter(function (x) { return x.id === peerId; })[0] || null;
      if (!(c && c.last_ts)) return;
      if (!confirm('删除与「' + (c.name || c.username || '') + '」的会话？会话记录将被清空。')) return;
      _fabPeerDelDo(peerId);
    }
    function fabPeerDelete() {
      if (!_fabPeerUid) return;
      var p = _fabPeerUser || {};
      if (!confirm('删除与「' + (p.name || p.username || '') + '」的会话？会话记录将被清空。')) return;
      _fabPeerDelDo(_fabPeerUid);
    }
    function _fabPeerDelDo(peerId) {
      if (!peerId) return;
      fetch('/api/chat/conversation/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ peer_id: peerId }) })
        .then(function (r) { return r.json(); }).then(function (d) {
          if (!(d && d.ok)) { _fabAppendMsg({ kind: 'bot', is_mine: false, content: '⚠ 删除失败：' + ((d && d.error) || '未知错误'), bad: true, time_hm: _fabNowHm() }); return; }

          if (String(_fabPeerUid || 0) === String(peerId)) {
            _fabPeerUid = 0;
            _fabPeerUser = null;
            fabPeerQuoteClear();
            var peer = document.getElementById('fabPeer');
            var chat = document.getElementById('fabChatBox');
            if (peer) { peer.style.display = ''; peer.setAttribute('hidden', ''); }
            if (chat) chat.style.display = '';
            _fabSetFoot(false);
          }
          _fabSideReset();
          fabSideBuild();
          _fabRefreshPeerStatus();
          _fabUpdatePeerName();
          fabChatUnreadRefresh();
        }).catch(function () {
          _fabAppendMsg({ kind: 'bot', is_mine: false, content: '⚠ 网络异常，删除失败。', bad: true, time_hm: _fabNowHm() });
        });
    }
    function _fabSetFoot(peer) {
      var chatFoot = document.getElementById('fabChatFoot');
      var peerFoot = document.getElementById('fabPeerFoot');
      if (chatFoot) chatFoot.classList.toggle('d-none', !!peer);
      if (peerFoot) peerFoot.classList.toggle('d-none', !peer);
      var clr = document.getElementById('fabChatClear');
      if (clr) clr.classList.toggle('d-none', !!peer);
    }
    function fabSelectAssist() {
      _fabPeerUid = 0;
      _fabPeerUser = null;
      fabPeerQuoteClear();
      var peer = document.getElementById('fabPeer');
      var chat = document.getElementById('fabChatBox');
      if (peer) { peer.style.display = ''; peer.setAttribute('hidden', ''); }
      if (chat) chat.style.display = '';
      _fabSetFoot(false);
      _fabRefreshInput();
      fabMentionHide();
      _fabSideReset();
      positionFabSheet();
      var inp = document.getElementById('fabChatInput');
      if (inp) inp.focus();
    }
    function fabSelect(uid) {
      if (_fabBotPending || !uid) return;
      var _ff = document.getElementById('quickFab');
      if (_ff && !_ff.classList.contains('open')) _ff.classList.add('open');
      _fabPeerUid = uid;
      var c = _fabContacts.filter(function (x) { return x.id === uid; })[0] || null;
      if (c) _fabPeerUser = { id: c.id, name: c.name, username: c.username };
      var peer = document.getElementById('fabPeer');
      var chat = document.getElementById('fabChatBox');
      var msgs = document.getElementById('fabPeerMsgs');
      if (chat) chat.style.display = 'none';
      _fabSetFoot(true);
      if (peer) { peer.style.display = 'flex'; peer.removeAttribute('hidden'); }
      if (msgs) { msgs.innerHTML = '<div class="fab-chat-empty">加载中…</div>'; msgs.dataset.uid = uid; }
      _fabRefreshPeerStatus();
      _fabUpdatePeerName();
      _fabRefreshInput();
      fabMentionHide();
      fabPeerQuoteClear();
      _fabSideReset();
      positionFabSheet();
      fetch('/api/chat/with/' + uid).then(function (r) { return r.json(); }).then(function (d) {
        if (!(d && d.ok)) { if (msgs) msgs.innerHTML = '<div class="fab-chat-empty">' + _fabEsc((d && d.error) || '加载失败') + '</div>'; return; }
        if (d.peer) {
          _fabPeerUser = { id: d.peer.id, name: d.peer.name, username: d.peer.username };
          var known = _fabContacts.some(function (x) { return x.id === d.peer.id; });
          if (!known) {
            _fabContacts.unshift({ id: d.peer.id, name: d.peer.name, username: d.peer.username, online: !!d.peer.online, last_ts: '' });
          }
          _fabRefreshPeerStatus();
          _fabUpdatePeerName();
          _fabRefreshInput();
          fabSideBuild();
        }
        _fabRenderMsgs(d.messages || []);
        fabChatUnreadRefresh();
        var pinput = document.getElementById('fabPeerInput');
        if (pinput) pinput.focus();
      }).catch(function () { if (msgs) msgs.innerHTML = '<div class="fab-chat-empty">加载失败，请重试</div>'; });
    }
    function _fabRefreshPeerStatus() {
      var el = document.getElementById('fabPeerStatus');
      if (!el || !_fabPeerUid) return;
      var c = _fabContacts.filter(function (x) { return x.id === _fabPeerUid; })[0];
      var online = c ? !!c.online : null;
      if (online === null && !_fabPeerUser) return;
      el.className = 'fab-peer-status' + (online ? ' on' : '');
      el.innerHTML = '<span class="fab-status-dot"></span>' + (online ? '在线' : '离线');
    }
    function _fabUpdatePeerName() {
      var el = document.getElementById('fabPeerName');
      if (!el) return;
      el.textContent = _fabPeerUser ? (_fabPeerUser.name || _fabPeerUser.username || '') : '';
    }
    function _fabStoreMsg(m) {
      if (m && m.id) _fabMsgsById[m.id] = m;
      else if (m) { _fabMsgsById._tmp = m; }
    }
    var _nlSeq = 0;
    function _nlNid() { return --_nlSeq; }
    function _fabMsgHtml(m) {
      var mine = !!m.is_mine;
      var isBot = m.kind === 'bot';
      var nl = !!m.nl;
      var cls = isBot ? 'fab-msg-bot' : (mine ? 'fab-msg-mine' : 'fab-msg-theirs');
      var tid = String(m.threadId || m.reply_to_id || m.id || 0);
      var hrefsJson = m.links && m.links.length ? _fabEsc(JSON.stringify(m.links.map(function (l) { return (l && l.href) || l; }))) : '';
      var html = '<div class="fab-msg ' + cls + (m.bad ? ' fab-msg-bot' : '') + (m.pending ? ' fab-msg-ask-pending' : '') + '" data-id="' + m.id + '" data-nl="' + (nl ? '1' : '') + '" data-bot="' + (isBot ? '1' : '0') + '" data-loading="' + (m.loading ? '1' : '') + '" data-thread="' + tid + '"' + (nl && m.content ? ' data-txt="' + _fabEsc(String(m.content).slice(0, 4000)) + '"' : '') + (hrefsJson ? ' data-hrefs="' + hrefsJson + '"' : '') + (nl && m.content ? ' data-c="' + _fabEsc(String(m.content).trim().slice(0, 120)) + '"' : '') + (nl && m.question ? ' data-q="' + _fabEsc(String(m.question).slice(0, 1000)) + '"' : '') + '>';
      html += '<div class="fab-msg-row">';
      if (!mine && !isBot) html += '<div class="fab-msg-ava">' + _fabEsc(_fabAva(_fabPeerUser ? _fabPeerUser.name : (nl ? '小知' : '?'))) + '</div>';
      html += '<div style="flex:1;min-width:0;display:flex;flex-direction:column;' + (mine ? 'align-items:flex-end' : 'align-items:flex-start') + '">';
      if (isBot) html += '<span class="fab-msg-ai-tag">' + (nl ? '🤖 小知' : '🤖 AI 代答') + '</span>';
      html += '<div class="fab-msg-bubble">';
      if (m.loading) html += '<div class="fab-chat-loading">检索资料中…</div>';
      else {
        if (m.reply_content) html += '<div class="fab-msg-quote">' + _fabEsc(m.reply_content) + '</div>';
        html += '<div class="fab-msg-content">';
        if (!mine && isBot && (m.links && m.links.length)) html += _fabBotAnswer(m);
        else html += '<div style="white-space:pre-wrap;">' + _fabEsc(m.content || '') + '</div>';
        html += '</div>';
        html += '<div class="fab-msg-actions">';
        if (!m.loading && !m.bad) html += '<button class="fab-msg-act" onclick="' + (nl ? 'fabNlQuote' : 'fabPeerQuote') + '(' + m.id + ')">引用</button>';
        if (!m.loading && !m.bad && (m.source === 'ask' || m.kind === 'bot')) html += '<button class="fab-msg-act" onclick="' + (nl ? 'fabNlReanswer' : 'fabPeerReanswer') + '(' + m.id + ')">🤖 重新回答</button>';
        if (!m.loading && !m.bad && isBot && (m.content || '')) html += '<button class="fab-msg-act fab-tidy-chip" onclick="fabAskTidy(this)" data-id="' + m.id + '" data-txt="' + _fabEsc(String(m.content).slice(0, 4000)) + '" data-hrefs="' + hrefsJson + '">✨ LLM 整理</button>';
        html += '</div>';
      }
      html += '</div></div></div>';
      html += '<div class="fab-msg-time">' + _fabEsc(m.time_hm || _fabNowHm()) + '</div>';
      html += '</div>';
      return html;
    }
    function _fabBotAnswer(m) {
      var hrefs = (m.links || []).map(function (l) { return l.href || '#'; });
      var safe = _fabEsc(m.content || '');
      var out = safe.replace(/\[资料\s*(\d+)\]/g, function (mm, n) {
        var h = hrefs[parseInt(n, 10) - 1];
        return h ? '<a class="fab-chat-ref" target="_blank" rel="noopener" href="' + _fabEsc(h) + '">' + mm + '</a>' : mm;
      });
      return '<div style="white-space:pre-wrap;">' + out + '</div>';
    }
    function _fabRenderMsgs(msgs) {
      var boxm = document.getElementById('fabPeerMsgs');
      if (!boxm) return;
      if (!msgs.length) { boxm.innerHTML = '<div class="fab-chat-empty">开始新的对话</div>'; return; }
      _fabMsgsById = {};
      msgs.forEach(_fabStoreMsg);
      boxm.innerHTML = msgs.map(_fabMsgHtml).join('');
      _fabScroll();
    }
    function _fabAppendMsg(m) {
      var boxm = document.getElementById('fabPeerMsgs');
      if (!boxm) return;
      if (m.id) _fabStoreMsg(m);
      boxm.insertAdjacentHTML('beforeend', _fabMsgHtml(m));
      _fabScroll();
    }
    function _fabRemoveLoading() {
      var boxm = document.getElementById('fabPeerMsgs');
      if (!boxm) return;
      var n = boxm.querySelector('[data-loading="1"]');
      if (n) n.remove();
    }
    function _fabPeerDoAsk(question, replyTo) {
      if (_fabBotPending || !_fabPeerUid) return;
      var boxm = document.getElementById('fabPeerMsgs');
      _fabAppendMsg({ kind: 'user', is_mine: true, pending: true, source: 'ask', content: question, reply_content: replyTo ? replyTo.content : '', time_hm: _fabNowHm(), reply_to_id: replyTo ? replyTo.id : null });
      _fabAppendMsg({ kind: 'bot', is_mine: false, loading: true, time_hm: _fabNowHm() });
      _fabBotPending = true;
      var body = { to_user_id: _fabPeerUid, question: question };
      if (replyTo) body.reply_to_id = replyTo.id;
      fetch('/api/chat/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        .then(function (r) { return r.json(); }).then(function (d) {
          _fabRemoveLoading();
          if (d && d.ok) {
            var pendEl = boxm.querySelector('.fab-msg-ask-pending');
            if (pendEl && d.ask && d.ask.id) {
              pendEl.setAttribute('data-id', d.ask.id);
              pendEl.classList.remove('fab-msg-ask-pending');
              _fabMsgsById[d.ask.id] = d.ask;
            }
            var nb = d.bot || {};
            nb.links = (d.links || nb.links || []).map(function (l) { return { href: l.href || l }; });
            nb.threadId = d.ask && d.ask.id;
            nb.reply_content = (nb.reply_content || '') || question;
            _fabAppendMsg(nb);
          } else {
            var hint = (d && d.error) || '代答失败';
            _fabAppendMsg({ kind: 'bot', is_mine: false, content: '⚠ ' + hint, bad: true, time_hm: _fabNowHm() });
          }
          _fabBotPending = false;
          fabContactsLoad(null);
        }).catch(function () {
          _fabRemoveLoading();
          _fabAppendMsg({ kind: 'bot', is_mine: false, content: '⚠ 网络异常，代答失败。', bad: true, time_hm: _fabNowHm() });
          _fabBotPending = false;
          fabContactsLoad(null);
        });
    }
    function fabPeerDoAsk(question, replyTo) { _fabPeerDoAsk(question, replyTo); }
    function _fabSendMsg(text, quote) {
      if (_fabBotPending || !_fabPeerUid) return;
      var boxm = document.getElementById('fabPeerMsgs');
      _fabAppendMsg({ kind: 'user', is_mine: true, pending: true, source: quote ? 'reply' : 'chat', content: text, reply_content: quote ? quote.content : '', reply_to_id: quote ? quote.id : null, time_hm: _fabNowHm() });
      _fabBotPending = true;
      var body = { to_user_id: _fabPeerUid, content: text };
      if (quote) body.reply_to_id = quote.id;
      fetch('/api/chat/send', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        .then(function (r) { return r.json(); }).then(function (d) {
          _fabBotPending = false;
          if (!(d && d.ok)) {
            _fabAppendMsg({ kind: 'bot', is_mine: false, content: '⚠ ' + ((d && d.error) || '发送失败'), bad: true, time_hm: _fabNowHm() });
            fabContactsLoad(null);
            return;
          }
          var pendEl = boxm.querySelector('.fab-msg-ask-pending');
          if (pendEl && d.message && d.message.id) {
            pendEl.setAttribute('data-id', d.message.id);
            pendEl.classList.remove('fab-msg-ask-pending');
            _fabMsgsById[d.message.id] = d.message;
          }
          if (d.bot) {
            var nb = d.bot;
            nb.links = (d.links || nb.links || []).map(function (l) { return { href: l.href || l }; });
            nb.threadId = d.message && d.message.id;
            nb.reply_content = (nb.reply_content || '') || text;
            _fabAppendMsg(nb);
          }
          fabContactsLoad(null);
        }).catch(function () {
          _fabBotPending = false;
          _fabAppendMsg({ kind: 'bot', is_mine: false, content: '⚠ 网络异常，发送失败。', bad: true, time_hm: _fabNowHm() });
          fabContactsLoad(null);
        });
    }
    function fabPeerSend() {
      var input = document.getElementById('fabPeerInput');
      var text = input.value.trim();
      if (!text || fabMentionIsOpen()) return;
      input.value = '';
      var quote = _fabQuoteMsg;
      fabPeerQuoteClear();
      if (!_fabPeerUid) { fabMentionScan(); return; }
      _fabSendMsg(text, quote);
    }
    function fabPeerAskCurrent() {
      var input = document.getElementById('fabPeerInput');
      var text = input.value.trim();
      if (!text || !_fabPeerUid) return;
      input.value = '';
      var quote = _fabQuoteMsg;
      fabPeerQuoteClear();
      _fabPeerDoAsk(text, quote);
    }
    function fabPeerReanswer(msgId) {
      if (_fabBotPending) return;
      var tgt = _fabMsgsById[msgId] || null;
      var threadId = (tgt && tgt.kind === 'bot') ? (tgt.reply_to_id || msgId) : msgId;
      _fabAppendMsg({ kind: 'bot', is_mine: false, loading: true, threadId: threadId, time_hm: _fabNowHm() });
      _fabBotPending = true;
      var body = { message_id: msgId };
      fetch('/api/chat/reanswer', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        .then(function (r) { return r.json(); }).then(function (d) {
          _fabRemoveLoading();
          if (d && d.ok) {
            var boxm = document.getElementById('fabPeerMsgs');
            if (boxm) boxm.querySelectorAll('[data-bot="1"][data-thread="' + threadId + '"]').forEach(function (n) { if (!n.getAttribute('data-loading')) n.remove(); });
            var nb = d.bot || {};
            nb.links = nb.links || (d.links || []).map(function (l) { return { href: l.href || l }; });
            nb.threadId = threadId;
            _fabAppendMsg(nb);
          } else {
            _fabAppendMsg({ kind: 'bot', is_mine: false, content: '⚠ 重新回答失败：' + ((d && d.error) || ''), bad: true, time_hm: _fabNowHm() });
          }
          _fabBotPending = false;
        }).catch(function () {
          _fabRemoveLoading();
          _fabAppendMsg({ kind: 'bot', is_mine: false, content: '⚠ 网络异常，重新回答失败。', bad: true, time_hm: _fabNowHm() });
          _fabBotPending = false;
        });
    }
    function _fabSetQuoteFromData(id, m) {
      m = m || _fabMsgsById[id] || null;
      if (!m || m.loading || m.bad) return;
      var content = String(m.content || '').trim();
      if (!content) return;
      if (_fabQuoteMsg && String(_fabQuoteMsg.id) === String(id)) { fabPeerQuoteClear(); return; }
      _fabQuoteMsg = { id: id, content: content.slice(0, 120), kind: m.kind };
      var bar = document.getElementById('fabQuoteBar');
      if (bar) {
        document.getElementById('fabQuoteTxt').textContent = (m.kind === 'bot' ? '🤖 ' : '') + _fabQuoteMsg.content;
        bar.classList.remove('d-none');
      }
    }
    function fabPeerQuote(id) {
      _fabSetQuoteFromData(id, null);
      var inp = document.getElementById('fabPeerInput');
      if (inp) inp.focus();
    }
    function fabNlQuote(id) {
      var box = document.getElementById('fabChatBox');
      var m = _fabMsgsById[id] || null;
      if ((!m || !m.content) && box) {
        var el = box.querySelector('.fab-msg[data-id="' + id + '"]');
        if (el) {
          var ca = el.getAttribute('data-c');
          if (ca !== null && ca !== '') m = { content: ca, kind: el.getAttribute('data-bot') === '1' ? 'bot' : 'user' };
        }
      }
      _fabSetQuoteFromData(id, m);
      var inp = document.getElementById('fabChatInput');
      if (inp) inp.focus();
    }
    function fabPeerQuoteClear() {
      _fabQuoteMsg = null;
      var bar = document.getElementById('fabQuoteBar');
      if (bar) bar.classList.add('d-none');
    }
    function _fabNlTurn() {
      var box = document.getElementById('fabChatBox');
      var turns = box ? box.querySelectorAll('.fab-turn') : null;
      var turn = turns ? turns[turns.length - 1] : null;
      return turn || fabChatAddTurn();
    }
    function _fabNlAppend(m) {
      var turn = _fabNlTurn();
      if (m.id != null) _fabStoreMsg(m);
      var wrap = document.createElement('div');
      wrap.innerHTML = _fabMsgHtml(m);
      var node = wrap.firstElementChild;
      if (node) turn.appendChild(node);
      var box = document.getElementById('fabChatBox');
      if (box) box.scrollTop = box.scrollHeight;
      return node;
    }
    function _fabNlRemoveLoading() {
      var box = document.getElementById('fabChatBox');
      if (!box) return;
      var n = box.querySelector('[data-loading="1"]');
      if (n) n.remove();
    }
    function _fabNlBotMsg(d, askId) {
      var links = (d.links || []).map(function (l) {
        if (typeof l === 'string') return { href: l, tag: '' };
        return { href: (l && l.href) || '#', title: (l && l.title) || '', tag: (l && l.tag) || '' };
      });
      return { id: _nlNid(), kind: 'bot', is_mine: false, source: 'intent', content: d.content || '', links: links, rows: d.rows || [], threadId: askId, nl: true, time_hm: _fabNowHm() };
    }
    function _fabNlAppendNlBot(d, askId) { _fabNlAppend(_fabNlBotMsg(d, askId)); }
    function fabNlReanswer(msgId) {
      if (_fabBotPending) return;
      var box = document.getElementById('fabChatBox');
      if (!box) return;
      var tgt = _fabMsgsById[msgId] || null;
      var el = box.querySelector('.fab-msg[data-id="' + msgId + '"]');
      var askId = msgId;
      if (el) {
        var ta = el.getAttribute('data-thread');
        if (ta && ta !== '0') askId = ta;
      }
      var askEl = box.querySelector('.fab-msg[data-id="' + askId + '"]') || el;
      var question = '';
      var qAttr = askEl ? askEl.getAttribute('data-q') : null;
      if (qAttr !== null && qAttr !== '') question = qAttr;
      else if (tgt && tgt.kind === 'bot') {
        var src = tgt.reply_to_id || tgt.threadId;
        var sm = src ? _fabMsgsById[src] : null;
        if (sm) question = sm.content || '';
      }
      else if (tgt && tgt.kind === 'user') question = tgt.content || '';
      question = String(question || '').trim();
      if (!question) return;
      _fabNlAppend({ id: _nlNid(), kind: 'bot', is_mine: false, loading: true, threadId: askId, nl: true, time_hm: _fabNowHm() });
      _fabBotPending = true;
      var cfg = window.FAB_CONFIG || {};
      fetch(cfg.nlAsk || '/api/chat/nl', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: question }) })
        .then(function (r) { return r.json(); }).then(function (d) {
          _fabNlRemoveLoading();
          if (d && d.ok) {
            box.querySelectorAll('[data-nl="1"][data-bot="1"][data-thread="' + askId + '"]').forEach(function (n) { if (!n.getAttribute('data-loading')) n.remove(); });
            _fabNlAppendNlBot(d, askId);
          } else {
            _fabNlAppend({ id: _nlNid(), kind: 'bot', is_mine: false, content: '⚠ ' + ((d && d.error) || '重新回答失败'), bad: true, nl: true, time_hm: _fabNowHm() });
          }
          _fabBotPending = false;
          fabChatCommit();
        }).catch(function () {
          _fabNlRemoveLoading();
          _fabNlAppend({ id: _nlNid(), kind: 'bot', is_mine: false, content: '⚠ 网络异常，重新回答失败。', bad: true, nl: true, time_hm: _fabNowHm() });
          _fabBotPending = false;
          fabChatCommit();
        });
    }
    /* ---- @联想下拉 ---- */
    function fabMentionScan() {
      var inp = _fabInput();
      var val = inp.value;
      var mt = val.match(/(?:^|\s)@([\u4e00-\u9fa5A-Za-z0-9_]*)!?$/);
      if (!mt) { fabMentionHide(); return; }
      var prefix = mt[1].toLowerCase();
      var list = _fabContacts.filter(function (c) { return !prefix || (c.name || '').toLowerCase().indexOf(prefix) === 0 || (c.username || '').toLowerCase().indexOf(prefix) === 0; });
      list.sort(function (a, b) { return (b.hot ? 1 : 0) - (a.hot ? 1 : 0) || (b.unread ? 1 : 0) - (a.unread ? 1 : 0); });
      list = list.slice(0, 12);
      var box = _fabMentionBox();
      if (!box) return;
      if (!list.length) { fabMentionHide(); return; }
      box.innerHTML = list.map(function (c, i) {
        return '<div class="fab-mention-item" data-id="' + c.id + '" data-i="' + i + '" onclick="fabMentionPick(' + c.id + ')">' +
          '<div class="fab-pc-avatar">' + _fabEsc(_fabAva(c.name)) + '</div>' +
          '<span class="fab-mention-name">' + _fabEsc(c.name) + '</span>' +
          (c.hot ? '<span class="fab-mention-hot">常问</span>' : '') +
          '</div>';
      }).join('');
      box.style.display = '';
      _fabMentionIdx = -1;
      _fabMentionHighlight();
    }
    var _fabMentionIdx = -1;
    function _fabMentionHighlight() {
      var box = _fabMentionBox();
      if (!box) return;
      Array.prototype.forEach.call(box.querySelectorAll('.fab-mention-item'), function (n) {
        n.style.background = (n.getAttribute('data-i') === String(_fabMentionIdx)) ? 'var(--gray-100)' : '';
      });
    }
    function fabMentionPick(uid) {
      var contact = _fabContacts.filter(function (x) { return x.id === uid; })[0] || null;
      if (contact) _fabPeerUser = { id: contact.id, name: contact.name, username: contact.username };
      var fromBear = !_fabPeerUid;
      if (fromBear) { var bi = document.getElementById('fabChatInput'); if (bi) bi.value = ''; }
      fabSelect(uid);
      fabMentionHide();
    }
    function fabMentionHide() {
      var box = _fabMentionBox();
      if (box) box.style.display = 'none';
    }
    function fabMentionIsOpen() { var box = _fabMentionBox(); return box && box.style.display !== 'none'; }
    function fabMentionCycle(dy) {
      var box = _fabMentionBox();
      if (!box || box.style.display === 'none') return false;
      var items = box.querySelectorAll('.fab-mention-item');
      if (!items.length) return true;
      _fabMentionIdx = (_fabMentionIdx + dy + items.length) % items.length;
      _fabMentionHighlight();
      var it = items[_fabMentionIdx];
      if (it) it.scrollIntoView({ block: 'nearest' });
      return true;
    }
    /* ---- 发送/快捷键/未读角标 ---- */
    function fabSend() {
      if (_fabPeerUid) { fabPeerSend(); return; }
      fabAsk();
    }
    function fabKeydown(e) {
      if (e.key === 'Enter') {
        if (fabMentionIsOpen()) {
          var box = _fabMentionBox();
          var it = box.querySelector('[data-i="' + _fabMentionIdx + '"]');
          if (it) { fabMentionPick(parseInt(it.getAttribute('data-id'), 10)); }
          e.preventDefault(); return false;
        }
        e.preventDefault();
        fabSend();
        return false;
      }
      if (e.key === 'ArrowDown') { if (fabMentionCycle(1)) { e.preventDefault(); } return; }
      if (e.key === 'ArrowUp') { if (fabMentionCycle(-1)) { e.preventDefault(); } return; }
      if (e.key === 'Escape') { fabMentionHide(); fabPeerQuoteClear(); }
      return true;
    }
    function fabChatUnreadRefresh() {
      fetch('/api/chat/unread').then(function (r) { return r.json(); }).then(function (d) {
        var n = (d && d.count) || 0;
        var b = document.getElementById('fabUnreadBadge');
        if (b) { b.textContent = n > 99 ? '99+' : n; b.classList.toggle('d-none', !(n > 0)); }
      }).catch(function () {});
    }
    (function () {
      fabChatUnreadRefresh();
      setInterval(function () { fabContactsLoad(null); }, 20000);
      var bi = document.getElementById('fabChatInput');
      if (bi) bi.addEventListener('input', fabMentionScan);
      var pi = document.getElementById('fabPeerInput');
      if (pi) pi.addEventListener('input', fabMentionScan);
    })();
    function fabAsk() {
      var box = document.getElementById('fabChatBox');
      var input = document.getElementById('fabChatInput');
      if (!box || !input) return;
      var raw = input.value.trim();
      if (!raw) return;
      var q = raw;  
      if (!q) return;
      var intentM = q.match(/^(待办|随记|随手记|上传|教育|问答)[\s:：]*(.*)$/);
      if (intentM) {
        var intent = intentM[1], rest5 = (intentM[2] || '').trim();
        if (intent === '待办') { input.value = ''; fabDialogAction(function(){ showQuickTaskModal(); }); return; }
        if (intent === '随记' || intent === '随手记') { input.value = ''; fabDialogAction(function(){ showQuickNoteModal(); if (rest5) { var _ne = document.getElementById('fabNoteContent') || document.getElementById('qnContent'); if (_ne) _ne.value = rest5; } }); return; }
        if (intent === '上传') { input.value = ''; fabDialogAction(function(){ fabKb(); }); return; }
        if (intent === '教育') { input.value = ''; fabDialogAction(function(){ fabMode(); }); return; }
        if (intent === '问答') { input.value = ''; fabNlAsk(q, raw); return; }
      }
      var mAt = q.match(/^@([\u4e00-\u9fa5A-Za-z0-9_]+)(?:\s+(.*))?$/);
      if (mAt) {
        fabMentionHide();
        var cAt = _fabFindContact(mAt[1]);
        if (cAt) {
          input.value = '';
          fabSelect(cAt.id);
          if (mAt[2] && mAt[2].trim()) fabPeerDoAsk(mAt[2].trim(), null);
          return;
        }
      }
      input.value = '';
      var empty = document.getElementById('fabChatEmpty');
      if (empty) empty.style.display = 'none';
      fabNlAsk(q, raw);
    }
    function fabChatAddTurn() {
      var box = document.getElementById('fabChatBox');
      var t = document.createElement('div');
      t.className = 'fab-turn';
      box.appendChild(t);
      return t;
    }
    function fabAskHint(text) {
      var turns = document.querySelectorAll('#fabChatBox .fab-turn');
      var turn = turns[turns.length - 1];
      if (!turn) {
        var box = document.getElementById('fabChatBox');
        if (!box) return;
        turn = fabChatAddTurn();
      }
      fabChatBubble(turn, 'avatar', '<div class="fab-hint" style="white-space:pre-wrap;">' + _fabEsc(text) + '</div>');
      fabChatCommit();
    }
    function fabNlAction(btn) {
      var act = btn.getAttribute('data-act');
      if (act === 'task_create') fabDialogAction(function () { showQuickTaskModal(); });
      else if (act === 'note_create') fabDialogAction(function () { showQuickNoteModal(); });
      else if (act === 'education') fabDialogAction(function () { fabMode(); });
      else if (act === 'upload') fabDialogAction(function () { fabKb(); });
    }
    function fabAskTidy(btn) {
      function close() { var s = btn.querySelector ? btn.querySelector('.fab-tidy-spin') : null; if (s) s.remove(); }
      var spin = document.createElement('span');
      spin.className = 'fab-tidy-spin';
      spin.textContent = ' ✨整理中…';
      btn.appendChild(spin);
      var txt = btn.getAttribute('data-txt') || '';
      var hrefs = [];
      var hrefsStr = btn.getAttribute('data-hrefs');
      if (hrefsStr) {
        try {
          var parr = JSON.parse(hrefsStr);
          if (Array.isArray(parr)) hrefs = parr.map(function (h) { return (h && h.href) ? h.href : h; });
        } catch (e) { hrefs = []; }
      }
      if (!txt && btn.getAttribute('data-id')) {
        var m = _fabMsgsById[String(btn.getAttribute('data-id'))];
        if (m) {
          txt = m.content || '';
          hrefs = ((m.links) || []).map(function (l) { return (l && l.href) || '#'; });
        }
      }
      var text = (txt || '').trim();
      if (!text) { close(); return; }
      fetch('/api/chat/tidy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: text.slice(0, 6000) })
      }).then(function (r) { return r.json(); }).then(function (d) {
        close();
        if (d && d.ok && d.answer) {
          var bubble = btn.closest ? btn.closest('.fab-msg-bubble') : null;
          var holder = bubble ? bubble.querySelector('.fab-msg-content') : null;
          if (holder) holder.innerHTML = fabChatRefLinks(d.answer, hrefs, 'fab-tidy-box');
          else fabAskHint('✨ LLM 整理：\n' + d.answer);
        } else {
          fabAskHint('⚠ ' + ((d && d.error) || '整理失败，请稍后再试。'));
        }
      }).catch(function () {
        close();
        fabAskHint('⚠ 网络异常，整理失败。');
      });
    }
    function fabNlAsk(q, raw) {
      var box = document.getElementById('fabChatBox');
      if (!box) return;
      var empty = document.getElementById('fabChatEmpty');
      if (empty) empty.style.display = 'none';
      var turn = fabChatAddTurn();
      var askId = _nlNid();
      var qtext = (raw || q);
      var quote = _fabQuoteMsg;
      fabPeerQuoteClear();
      _fabNlAppend({ id: askId, kind: 'user', is_mine: true, pending: true, source: 'ask', content: qtext, question: qtext, threadId: askId, reply_content: quote ? quote.content : '', reply_to_id: quote ? quote.id : null, nl: true, time_hm: _fabNowHm() });
      _fabNlAppend({ id: _nlNid(), kind: 'bot', is_mine: false, loading: true, threadId: askId, nl: true, time_hm: _fabNowHm() });
      _fabBotPending = true;
      var cfg = window.FAB_CONFIG || {};
      fetch(cfg.nlAsk || '/api/chat/nl', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q })
      }).then(function (r) { return r.json(); }).then(function (d) {
        _fabNlRemoveLoading();
        if (!(d && d.ok)) {
          _fabNlAppend({ id: _nlNid(), kind: 'bot', is_mine: false, content: '⚠ ' + ((d && d.error) || '理解失败，换个说法试试？'), bad: true, nl: true, time_hm: _fabNowHm() });
          fabChatCommit();
          _fabBotPending = false;
          return;
        }
        var actionActs = { task_create: 1, note_create: 1, education: 1, upload: 1 };
        if (actionActs[d.intent]) {
          var actions = {
            task_create: ['打开「快速创建待办」', 'task_create'],
            note_create: ['打开「随手记」', 'note_create'],
            education: ['进入教育娱乐', 'education'],
            upload: ['打开「上传知识」', 'upload']
          };
          var node = _fabNlAppend(_fabNlBotMsg(d, askId));
          var a = actions[d.intent] || [];
          if (a.length && node) {
            var contentEl = node.querySelector('.fab-msg-content') || node;
            contentEl.insertAdjacentHTML('beforeend', '<div class="fab-action-hint"><button type="button" class="fab-tidy-btn" data-act="' + a[1] + '" onclick="fabNlAction(this)">' + a[0] + '</button></div>');
          }
          fabChatCommit();
          _fabBotPending = false;
          return;
        }
        _fabNlAppendNlBot(d, askId);
        _fabBotPending = false;
        fabChatCommit();
      }).catch(function () {
        _fabNlRemoveLoading();
        _fabNlAppend({ id: _nlNid(), kind: 'bot', is_mine: false, content: '⚠ 网络异常，暂时无法回答。', bad: true, nl: true, time_hm: _fabNowHm() });
        _fabBotPending = false;
        fabChatCommit();
      });
    }
    function showQuickNoteModal() {
      var m = document.getElementById('quickNoteModal');
      if (m) { bootstrap.Modal.getOrCreateInstance(m).show(); return; }
      var newModalHtml = '<div id="quickNoteModal" class="modal fade" tabindex="-1"><div class="modal-dialog modal-dialog-centered"><div class="modal-content"><div class="modal-header py-2"><span style="font-weight:600;"><i class="bi bi-pencil-square" style="color:var(--success);"></i> 随手记</span><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div><div class="modal-body"><textarea id="qnContent" class="form-control" rows="4" placeholder="记录点什么... 支持 Markdown" style="font-size:.9rem;resize:none;"></textarea><input type="text" id="qnTags" class="form-control form-control-sm mt-2" placeholder="标签（逗号分隔，可留空）" style="font-size:.78rem;"><small class="text-muted" style="font-size:.7rem;" id="qnHint"></small></div><div class="modal-footer py-2"><button class="btn btn-sm btn-primary" onclick="quickNote()"><i class="bi bi-check"></i> 保存</button></div></div></div></div>';
      document.body.insertAdjacentHTML('beforeEnd', newModalHtml);
      if (typeof window.quickNote !== 'function') {
        window.quickNote = function () {
          var content = document.getElementById('qnContent').value.trim();
          var hint = document.getElementById('qnHint');
          var tagsRaw = document.getElementById('qnTags') ? document.getElementById('qnTags').value : '';
          var tags = tagsRaw.split(/[,，;；\s]+/).map(function (t) { return t.replace(/^#+/, '').trim(); }).filter(Boolean).slice(0, 8);
          if (!content) return;
          fetch('/api/quick-note', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content: content, tags: tags }) })
            .then(function (r) { return r.json(); }).then(function (d) {
              if (d.ok) {
                document.getElementById('qnContent').value = '';
                var qt = document.getElementById('qnTags'); if (qt) qt.value = '';
                bootstrap.Modal.getOrCreateInstance(document.getElementById('quickNoteModal')).hide();
                toast((d.warnings && d.warnings.length) ? ('已保存 · ⚠️ 疑似重复:' + d.warnings.map(function (w) { return w.title; }).join(',')) : '随手记已保存', (d.warnings && d.warnings.length) ? 'warning' : 'success');
              } else { hint.textContent = d.error || '保存失败'; }
            }).catch(function () { hint.textContent = '保存失败'; });
        };
      }
      bootstrap.Modal.getOrCreateInstance(document.getElementById('quickNoteModal')).show();
    }
    if (_fab && _fabBtn) {
      (function () {
        var fab = _fab, btn = _fabBtn;
        var sh = document.getElementById('fabSheet');
        if (sh) sh.addEventListener('click', function (e) { e.stopPropagation(); });
        function openFabDialog() {
          fab.classList.add('open');
          btn.setAttribute('aria-expanded', 'true');
          positionFabSheet();
          setTimeout(fabSheetScrollBottom, 30);
          if (!_fabContacts.length) fabContactsLoad(null);
          fabChatUnreadRefresh();
        }
        function handleToggle() {
          if (fab.classList.contains('d-none')) return;
          if (fab.classList.contains('open')) { closeFab(); } else { openFabDialog(); }
        }
        document.addEventListener('click', function (e) {
          if (fab.classList.contains('open') && !fab.contains(e.target)) closeFab();
        });
        window.addEventListener('resize', function () { if (fab.classList.contains('open')) positionFabSheet(); });
        window.addEventListener('orientationchange', function () { if (fab.classList.contains('open')) positionFabSheet(); });
        btn.addEventListener('click', function (e) {
          if (window._fabDragged) { window._fabDragged = false; e.stopPropagation(); return; }
          e.stopPropagation();
          handleToggle();
        });
        btn.addEventListener('keydown', function (e) {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); handleToggle(); }
        });
        document.addEventListener('shown.bs.modal', function () { fab.classList.add('d-none'); });
        document.addEventListener('hidden.bs.modal', function () { fab.classList.remove('d-none'); fab.classList.remove('open'); btn.setAttribute('aria-expanded', 'false'); });
      })();
      // 悬浮球可拖动 (仅拖动按钮本身, 避免误拖菜单项导致点击失效)
      (function () {
        var fab = _fab, btn = _fabBtn;
        var dragging = false, moved = false, startX = 0, startY = 0, origRight = 0, origBottom = 0;
        var stored = null;
        try { stored = JSON.parse(localStorage.getItem('quickFabPos') || 'null'); } catch (e) { stored = null; }
        if (stored && stored.right != null && stored.bottom != null) {
          fab.style.right = stored.right + 'px';
          fab.style.bottom = stored.bottom + 'px';
        }
        function onDown(e) {
          var isTouch = !!e.touches;
          var point = e.touches ? e.touches[0] : e;
          dragging = true; moved = false;
          startX = point.clientX; startY = point.clientY;
          var cs = getComputedStyle(fab);
          origRight = parseFloat(cs.right) || 24;
          origBottom = parseFloat(cs.bottom) || 96;
          if (!isTouch) e.preventDefault();
        }
        function onMove(e) {
          if (!dragging) return;
          var point = e.touches ? e.touches[0] : e;
          var dx = point.clientX - startX;
          var dy = point.clientY - startY;
          if (Math.abs(dx) + Math.abs(dy) > 8) moved = true;
          if (moved) {
            e.preventDefault();
            var newRight = origRight - dx;
            var newBottom = origBottom - dy;
            var vw = window.innerWidth, vh = window.innerHeight;
            var fw = fab.offsetWidth || 54, fh = fab.offsetHeight || 54;
            newRight = Math.max(4, Math.min(vw - fw - 4, newRight));
            newBottom = Math.max(4, Math.min(vh - fh - 4, newBottom));
            fab.style.right = newRight + 'px';
            fab.style.bottom = newBottom + 'px';
            if (fab.classList.contains('open')) closeFab();
          }
        }
        function onUp() {
          if (!dragging) return;
          dragging = false;
          if (moved) {
            window._fabDragged = true;
            setTimeout(function () { window._fabDragged = false; }, 50);
            var cs = getComputedStyle(fab);
            try { localStorage.setItem('quickFabPos', JSON.stringify({ right: parseFloat(cs.right), bottom: parseFloat(cs.bottom) })); } catch (e2) {}
          }
        }
        btn.addEventListener('touchstart', onDown, { passive: false });
        document.addEventListener('touchmove', onMove, { passive: false });
        document.addEventListener('touchend', onUp);
        document.addEventListener('touchcancel', onUp);
        btn.addEventListener('mousedown', onDown);
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
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

    // 全局 Toast 提示：由 base.html 提供单一实现(含 actionLabel 撤销按钮/类型配色)

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

    // ---- 剪切板待办自动检测 ----
    (function () {
      var KEYWORDS = [
        '会议通知', '培训通知', '会议安排', '培训安排',
        '请参加', '请出席', '请参会', '请务必参加',
        '全体员工', '全员参加', '所有人参加', '所有人',
        '请各位', '请各部门', '请各单位', '各处室',
        '开会', '例会', '晨会', '周会', '月会',
        '评审会', '研讨会', '复盘会', '站会', '协调会',
        '培训', '培训会', '课程', '集训', '学习班',
        '研修班', '岗前培训', '入职培训',
        '截止', '提交', '完成时间', 'deadline'
      ];
      var _pending = false;
      var _polling = false;
      var POLL_MS = 3000;
      var STORE_KEY = '_clip_shown';

      function _hash(s) {
        var h = 0;
        for (var i = 0; i < s.length; i++) {
          h = ((h << 5) - h + s.charCodeAt(i)) | 0;
        }
        return h.toString(36);
      }

      function _norm(s) {
        return s.replace(/[^\u4e00-\u9fa5a-zA-Z0-9]/g, '').trim();
      }

      function _getShown() {
        try { return JSON.parse(sessionStorage.getItem(STORE_KEY) || '{}'); }
        catch (e) { return {}; }
      }
      function _saveShown(obj) {
        try { sessionStorage.setItem(STORE_KEY, JSON.stringify(obj)); } catch (e) {}
      }
      function _markShown(text) {
        var obj = _getShown();
        obj[_norm(text)] = Date.now();
        _saveShown(obj);
      }
      function _isShown(text) {
        var obj = _getShown();
        return !!obj[_norm(text)];
      }

      function _matchKeywords(text) {
        if (!text || text.length < 6) return false;
        for (var i = 0; i < KEYWORDS.length; i++) {
          if (text.indexOf(KEYWORDS[i]) !== -1) return true;
        }
        return false;
      }

      function _esc(s) {
        var d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
      }

      function _qtResetAndParse() {
        // 先回到输入步骤(若停留确认页), 再自动解析直接进入确认发布页
        if (typeof quickTaskBack === 'function') { try { quickTaskBack(); } catch (e) {} }
        if (typeof quickTaskParse === 'function') { try { quickTaskParse(); } catch (e) {} }
      }
      function _openQuickTask(text) {
        var ta = document.getElementById('adminTaskText');
        if (ta) {
          ta.value = text;
          ta.dispatchEvent(new Event('input'));
          var btn = document.getElementById('taskParseBtn');
          if (btn && typeof taskParse === 'function') taskParse(btn);
          return;
        }
        var qm = document.getElementById('quickTaskModal');
        if (qm) {
          var qt = document.getElementById('qtText');
          if (qt) { qt.value = text; qt.dispatchEvent(new Event('input')); }
          bootstrap.Modal.getOrCreateInstance(qm).show();
          _qtResetAndParse();
          return;
        }
        if (typeof showQuickTaskModal === 'function') {
          showQuickTaskModal();
          setTimeout(function () {
            var qt2 = document.getElementById('qtText');
            if (qt2) { qt2.value = text; qt2.dispatchEvent(new Event('input')); }
            _qtResetAndParse();
          }, 150);
        }
      }

      function showClipConfirm(text) {
        if (_pending) return;
        if (!_matchKeywords(text)) return;
        _pending = true;
        var c = document.getElementById('globalToast');
        if (!c) {
          c = document.createElement('div');
          c.id = 'globalToast';
          c.style.cssText = 'position:fixed;right:18px;top:72px;z-index:2000;display:flex;flex-direction:column;gap:8px;max-width:340px;';
          document.body.appendChild(c);
        }
        var preview = text.substring(0, 80) + (text.length > 80 ? '...' : '');
        var el = document.createElement('div');
        el.style.cssText = 'background:#fff;border:1px solid var(--gray-200);border-left:4px solid var(--primary);border-radius:10px;box-shadow:var(--shadow-lg);padding:12px 14px;font-size:.83rem;color:var(--gray-700);animation:tmFadeIn .18s ease-out;max-width:340px;';
        el.innerHTML =
          '<div style="font-weight:600;margin-bottom:6px;"><i class="bi bi-clipboard-check" style="color:var(--primary);"></i> 检测到待办内容</div>' +
          '<div style="font-size:.78rem;color:var(--gray-500);margin-bottom:10px;word-break:break-word;max-height:60px;overflow:hidden;">' + _esc(preview) + '</div>' +
          '<div style="display:flex;gap:8px;">' +
            '<button class="btn btn-sm btn-primary" id="_clipConfirm" style="flex:1;"><i class="bi bi-plus-lg"></i> 创建待办</button>' +
            '<button class="btn btn-sm btn-outline-secondary" id="_clipCancel" style="flex:1;">取消</button>' +
          '</div>';
        c.appendChild(el);
        var timer = setTimeout(function () { _remove(); }, 8000);
        function _remove() {
          clearTimeout(timer);
          _pending = false;
          _markShown(text);
          el.style.opacity = '0';
          el.style.transition = 'opacity .3s';
          setTimeout(function () { el.remove(); }, 320);
        }
        document.getElementById('_clipConfirm').onclick = function () {
          _remove();
          _openQuickTask(text);
        };
        document.getElementById('_clipCancel').onclick = _remove;
      }

      // 轮询剪切板:内容变化时自动检测(需页面聚焦 + HTTPS)
      function _pollClip() {
        if (_pending || !navigator.clipboard || !navigator.clipboard.readText) return;
        // toast 已在显示中,跳过
        var existing = document.getElementById('globalToast');
        if (existing && existing.children.length > 0) return;
        navigator.clipboard.readText().then(function (text) {
          if (!text) return;
          var trimmed = text.trim();
          if (!trimmed || trimmed.length < 6) return; // 少于6个字自动过滤
          if (_isShown(trimmed)) return;        // 已提示过,跳过
          showClipConfirm(trimmed);
        }).catch(function () { /* 无权限或页面失焦,静默跳过 */ });
      }

      // 启动轮询(页面可见时才轮询,节省资源)
      function _startPoll() {
        if (_polling) return;
        _polling = true;
        setInterval(function () {
          if (document.hidden) return;
          _pollClip();
        }, POLL_MS);
      }
      if (document.readyState === 'complete') { _startPoll(); }
      else { window.addEventListener('load', _startPoll); }

      window.showClipConfirm = showClipConfirm;
      window._clipOpenQuickTask = _openQuickTask;
    })();
