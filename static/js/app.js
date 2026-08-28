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
              document.getElementById('qtDupWarn').innerHTML = (d.duplicate_tasks && d.duplicate_tasks.length) ? '<div class="alert alert-warning py-1 px-2" style="font-size:.75rem;">⚠️ 存在相似待办：' + d.duplicate_tasks.map(function (t) { return t.title; }).slice(0, 3).join('、') + '</div>' : '';
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
          var html = '';
          for (var i = 0; i < ids.length; i++) {
            var checked = ids[i] === selfId ? 'checked' : '';
            html += '<label class="form-check form-check-inline" style="font-size:.78rem;cursor:pointer;margin-right:6px;"><input type="checkbox" class="form-check-input qt-assignee" value="' + ids[i] + '" ' + checked + '> ' + (names[i] || ('用户' + ids[i])) + '</label>';
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
        function openFab() { fab.classList.add('open'); btn.setAttribute('aria-expanded', 'true'); }
        btn.addEventListener('click', function (e) { if (window._fabDragged) { window._fabDragged = false; e.stopPropagation(); return; } e.stopPropagation(); if (fab.classList.contains('open')) closeFab(); else openFab(); });
        btn.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); if (fab.classList.contains('open')) closeFab(); else openFab(); } });
        fab.addEventListener('focusout', function (e) { if (!fab.contains(e.relatedTarget)) closeFab(); });
        document.addEventListener('click', function (e) { if (!fab.contains(e.target)) closeFab(); });
        document.addEventListener('shown.bs.modal', function () { fab.classList.add('d-none'); });
        document.addEventListener('hidden.bs.modal', function () { fab.classList.remove('d-none'); });
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
