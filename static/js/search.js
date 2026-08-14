/* 统一检索
 *
 * 输入框(桌面/移动端都显示) → 聚焦且为空时弹出 个人检索历史 top5 + 热门标签 下拉提示;
 * 输入关键词 → 弹出三列结果弹框(知识库/待办/随手记),不遮挡导航栏,不做全屏,
 * 点击空白/Esc/关闭按钮 关闭;命中关键字在结果中加粗高亮。
 */
(function () {
  'use strict';

  var CFG = window.SEARCH_CONFIG || {};
  if (!CFG.api) return;

  var _debTimer = null;   // 防抖定时器
  var _sel = -1;          // 键盘选中索引
  var _items = [];        // 当前可见结果 [{obj}]
  var _inp = null;        // 输入框
  var _modal = null;      // 结果弹框
  var _composing = false; // 中文输入法组合中(组合期间不检索)
  var _lastQ = '';        // 最近一次已检索关键词(避免重复请求)

  /* ---------------- 工具 ---------------- */
  function esc(s) {
    s = (s == null ? '' : String(s));
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }
  function highlight(str, q) {
    if (!str) return '';
    var out = esc(str);
    (q || '').split(/\s+/).forEach(function (t) {
      t = esc(t);
      if (t) out = out.split(t).join('<mark>' + t + '</mark>');
    });
    return out;
  }
  function priEmoji(p) { return p === '高' ? '🔴' : p === '中' ? '🟡' : '🟢'; }
  function priCls(p) { return p === '高' ? 'pri-hi' : p === '中' ? 'pri-mid' : 'pri-low'; }
  function clip(s, n) {
    s = (s == null ? '' : String(s)).replace(/\s+/g, ' ').trim();
    return s.length > n ? s.slice(0, n) + '…' : s;
  }
  function stripHtml(s) {
    var d = document.createElement('div');
    d.innerHTML = (s == null ? '' : String(s));
    return d.textContent;
  }

  /* ---------------- 结果条目 ---------------- */
  function moreLink(n, q) {
    if (n <= 3) return '';
    return '<a class="us-more" href="' + CFG.resultsPage + '?q=' +
      encodeURIComponent(q) + '">查看全部 ' + n + ' 条 ›</a>';
  }
  function kbItem(idx, k, q) {
    var snip = (k.pages && k.pages[0] && k.pages[0].snippet) ? clip(stripHtml(k.pages[0].snippet), 60) : '';
    return '<a href="' + k.detail_url + '" target="_blank" rel="noopener" data-idx="' + idx + '" class="us-r-item">' +
      '<span class="us-item-ico">📄</span>' +
      '<div class="us-item-main">' +
      '<div class="us-item-title">' + highlight(k.title, q) + '</div>' +
      (snip ? '<div class="us-item-sub">' + highlight(snip, q) + '</div>' :
        '<div class="us-item-sub">' + esc(k.path || '未分类') + ' · ' + esc(k.score) + '%</div>') +
      '</div></a>';
  }
  function taskItem(idx, t, q) {
    return '<a href="' + t.detail_url + '" target="_blank" rel="noopener" data-idx="' + idx + '" class="us-r-item">' +
      '<span class="us-item-ico">✅</span>' +
      '<div class="us-item-main">' +
      '<div class="us-item-title">' + highlight(t.title, q) + '</div>' +
      '<div class="us-item-sub">' + priEmoji(t.priority) + ' ' +
      '<span class="' + priCls(t.priority) + '">' + esc(t.priority) + '</span> · ' +
      esc(t.end_date || '') + ' 截止</div>' +
      '</div></a>';
  }
  function noteItem(idx, n, q) {
    var meta = esc(n.date || '') + ' 创建';
    var body = (n.content && n.content.length) ? clip(n.content, 60) : (n.title || '(无标题)');
    return '<a href="' + n.detail_url + '" target="_blank" rel="noopener" data-idx="' + idx + '" class="us-r-item">' +
      '<span class="us-item-ico">📝</span>' +
      '<div class="us-item-main">' +
      '<div class="us-item-title">' + highlight(body, q) + '</div>' +
      '<div class="us-item-sub">' + meta + '</div>' +
      '</div></a>';
  }
  function emptyCol() {
    return '<div class="us-empty" style="padding:14px 6px;">暂无匹配</div>';
  }
  function skeletonHtml() {
    var rows = '';
    for (var i = 0; i < 3; i++) {
      rows += '<div class="sk-row"><div class="sk-dot"></div>' +
        '<div class="sk-main"><div class="sk-line" style="width:' + (70 + i * 7) + '%"></div>' +
        '<div class="sk-line sk-thin" style="width:' + (40 + i * 9) + '%"></div></div></div>';
    }
    return '<div class="us-skeleton">' + rows + '</div>';
  }
  function hotHtml(hot) {
    if (!hot || !hot.length) return '';
    return '<div class="us-hist-head"><i class="bi bi-fire"></i> 热门标签</div>' +
      '<div class="us-hot-chips">' + hot.map(function (t) {
        return '<span class="us-hot-chip" data-tag="' + encodeURIComponent(t) + '">#' +
          esc(t) + '</span>';
      }).join('') + '</div>';
  }
  function historyItemsHtml(items) {
    return '<div class="us-hist-head"><i class="bi bi-clock-history"></i> 最近搜索</div>' +
      items.map(function (it) {
        return '<div class="us-item" data-q="' + encodeURIComponent(it) + '">' +
          '<i class="bi bi-clock-history"></i><span class="text-truncate">' + esc(it) + '</span>' +
          '<span class="us-item-tag">搜索</span></div>';
      }).join('');
  }

  /* ---------------- 三列结果渲染 ---------------- */
  function renderColumns(q, data) {
    var kb = data.kb || [];
    var tasks = data.tasks || [];
    var notes = data.notes || [];
    var total = kb.length + tasks.length + notes.length;
    _items = [];

    function fill(list, containerId, itemFn) {
      var col = document.getElementById(containerId);
      if (!col) return;
      if (!list.length) { col.innerHTML = emptyCol(); return; }
      var html = '';
      list.slice(0, 3).forEach(function (o) {
        _items.push({ obj: o });
        html += itemFn(_items.length - 1, o, q);
      });
      html += moreLink(list.length, q);
      col.innerHTML = html;
    }
    fill(kb, 'usKbCol', kbItem);
    fill(tasks, 'usTaskCol', taskItem);
    fill(notes, 'usNoteCol', noteItem);

    document.getElementById('usKbCount').textContent = kb.length;
    document.getElementById('usTaskCount').textContent = tasks.length;
    document.getElementById('usNoteCount').textContent = notes.length;
    var body = document.getElementById('usModalBody');
    if (body) {
      body.querySelectorAll('.us-modal-col').forEach(function (el) { el.style.display = ''; });
      var empty = document.getElementById('usModalEmpty');
      if (empty) empty.classList.add('d-none');
    }
    var foot = document.getElementById('usModalFoot');
    if (foot) {
      var fl = document.getElementById('usModalFootLink');
      var ft = document.getElementById('usModalFootText');
      fl.href = CFG.resultsPage + '?q=' + encodeURIComponent(q);
      ft.textContent = '查看全部 ' + total + ' 条结果';
      foot.style.display = total ? 'flex' : 'none';
    }
  }
  /* ---------------- 键盘选择 ---------------- */
  function setSel(scope, idx) {
    _sel = idx;
    (scope || document).querySelectorAll('.us-r-item').forEach(function (el) {
      el.classList.toggle('us-active', parseInt(el.getAttribute('data-idx'), 10) === idx);
    });
  }
  function moveSel(scope, dir) {
    var n = _items.length;
    if (!n) return;
    setSel(scope, (_sel + dir + n) % n);
    var el = (scope || document).querySelector('.us-r-item[data-idx="' + _sel + '"]');
    if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest' });
  }
  function jump() {
    var it = _items[_sel >= 0 ? _sel : 0];
    if (it && it.obj) location.href = it.obj.detail_url;
  }

  /* ---------------- 弹框: 显示/隐藏/搜索 ---------------- */
  function modalShow() { if (_modal) _modal.classList.add('show'); }
  function modalHide() {
    if (!_modal) return;
    _modal.classList.remove('show');
    _items = [];
    _sel = -1;
  }
  function runSearch(q) {
    _lastQ = q;
    var mInp = document.getElementById('usModalSearchInput');
    if (mInp && mInp.value !== q) mInp.value = q;
    var body = document.getElementById('usModalBody');
    body.querySelectorAll('.us-modal-col').forEach(function (el) { el.style.display = ''; });
    var emptyEl = document.getElementById('usModalEmpty');
    if (emptyEl) emptyEl.classList.add('d-none');
    ['usKbCol', 'usTaskCol', 'usNoteCol'].forEach(function (id) {
      var col = document.getElementById(id);
      if (col) col.innerHTML = skeletonHtml();
    });
    var foot = document.getElementById('usModalFoot');
    if (foot) foot.style.display = 'none';
    modalShow();
    fetch(CFG.api + '?q=' + encodeURIComponent(q))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && d.ok) { renderColumns(q, d); return; }
        renderColumns(q, {});
      })
      .catch(function () { renderColumns(q, {}); });
  }

  /* ---------------- 历史/热门下拉提示 ---------------- */
  function initSuggest() {
    var wrap = document.getElementById('unifiedSearchWrap');
    var sg = document.getElementById('usSuggest');
    if (!sg) return;
    var sgBody = document.getElementById('usSuggestBody');
    var loaded = false;

    function show() { sg.style.display = 'block'; }
    function hide() { sg.style.display = 'none'; }
    function load() {
      loaded = true;
      sgBody.innerHTML = '<div class="us-sg-empty">加载中...</div>';
      show();
      fetch(CFG.historyApi)
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (!d.ok) { sgBody.innerHTML = '<div class="us-sg-empty">暂无搜索历史</div>'; return; }
          var html = '';
          if (d.items && d.items.length) html += historyItemsHtml(d.items);
          html += hotHtml(d.hot);
          sgBody.innerHTML = html || '<div class="us-sg-empty">暂无搜索历史</div>';
        })
        .catch(function () { sgBody.innerHTML = '<div class="us-sg-empty">加载失败</div>'; });
    }
    function use(q) {
      hide();
      _inp.value = q;
      runSearch(q);
    }

    sgBody.addEventListener('click', function (e) {
      var chip = e.target.closest('.us-hot-chip');
      if (chip) { use(decodeURIComponent(chip.getAttribute('data-tag'))); return; }
      var it = e.target.closest('.us-item[data-q]');
      if (it) use(decodeURIComponent(it.getAttribute('data-q')));
    });
    document.addEventListener('click', function (e) {
      if (wrap && wrap.contains(e.target)) return;
      hide();
    });
    window.suggest = {
      show: show, hide: hide, load: load,
      opened: function () { return loaded; }
    };
  }

  /* ---------------- 输入框 + 三列结果弹框 ---------------- */
  function initModal() {
    _inp = document.getElementById('unifiedSearchInput');
    if (!_inp) return;
    var btn = document.getElementById('unifiedSearchBtn');
    var navBtn = document.getElementById('navSearchBtn');
    _modal = document.getElementById('unifiedResultModal');
    if (!_modal) return;
    var sg = window.suggest;

    _inp.addEventListener('focus', function () {
      if (!_inp.value.trim()) { if (!sg.opened()) sg.load(); else sg.show(); }
    });
    _inp.addEventListener('compositionstart', function () {
      _composing = true;
      clearTimeout(_debTimer);
    });
    _inp.addEventListener('compositionend', function () {
      _composing = false;
      var v = _inp.value.trim();
      if (!v) return;
      sg.hide();
      _debTimer = setTimeout(function () { runSearch(v); }, 350);
    });
    _inp.addEventListener('input', function (e) {
      var v = _inp.value.trim();
      clearTimeout(_debTimer);
      if (_composing || (e && e.isComposing)) return;
      if (!v) { modalHide(); if (!sg.opened()) sg.load(); else sg.show(); return; }
      if (v === _lastQ) return;
      sg.hide();
      _debTimer = setTimeout(function () { runSearch(v); }, 500);
    });
    _inp.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        var v = _inp.value.trim();
        if (!v) return;
        if (_items.length && _modal.classList.contains('show')) { jump(); }
        else { location.href = CFG.resultsPage + '?q=' + encodeURIComponent(v); }
      } else if (e.key === 'Escape') { modalHide(); sg.hide(); _inp.blur(); }
      else if (e.key === 'ArrowDown') { e.preventDefault(); if (_modal.classList.contains('show')) moveSel(_modal, 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); if (_modal.classList.contains('show')) moveSel(_modal, -1); }
    });
    if (btn) btn.addEventListener('click', function () {
      var v = _inp.value.trim();
      if (v) runSearch(v); else { _inp.focus(); if (!sg.opened()) sg.load(); else sg.show(); }
    });
    if (navBtn) navBtn.addEventListener('click', function (e) {
      e.preventDefault();
      _inp.focus();
      if (!_inp.value.trim()) { if (!sg.opened()) sg.load(); else sg.show(); }
    });
    document.getElementById('usModalMask').addEventListener('click', modalHide);
    document.getElementById('usModalClose').addEventListener('click', modalHide);
    _modal.addEventListener('mouseover', function (e) {
      var el = e.target.closest('.us-r-item');
      if (el) setSel(_modal, parseInt(el.getAttribute('data-idx'), 10));
    });

    // 弹框内检索框: 修改关键词后回车/点按钮继续检索
    var mInp = document.getElementById('usModalSearchInput');
    var mBtn = document.getElementById('usModalSearchBtn');
    function modalSearch() {
      var v = mInp ? mInp.value.trim() : '';
      if (!v) return;
      if (v === _lastQ && _modal.classList.contains('show')) { modalHide(); return; }
      runSearch(v);
    }
    if (mInp) {
      mInp.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); modalSearch(); }
        e.stopPropagation();
      });
      mInp.addEventListener('focus', function (e) { e.stopPropagation(); });
      mInp.addEventListener('click', function (e) { e.stopPropagation(); });
    }
    if (mBtn) mBtn.addEventListener('click', function (e) { e.stopPropagation(); modalSearch(); });
  }

  initSuggest();
  initModal();
})();
