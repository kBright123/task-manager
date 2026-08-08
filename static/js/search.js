/* 统一检索: 顶栏下拉(桌面) + 全屏检索(移动端)
 *
 * 结果统一按「知识库 / 待办 / 随手记」分组,每组最多 3 条;
 * 每条仅展示「标题 + 一行元信息」(路径/优先级+截止/创建时间),
 * 每组底部「查看全部 ›」跳转独立结果页 /search?q=。
 * 交互: 输入防抖 300ms、加载骨架屏、↑↓ 选择、Enter 跳转、Esc/下滑 退出。
 */
(function () {
  'use strict';

  var CFG = window.SEARCH_CONFIG || {};
  if (!CFG.api) return;

  var _debTimer = null;   // 防抖定时器
  var _sel = -1;          // 键盘选中索引
  var _items = [];        // 当前可见结果 [{type:'kb'|'task'|'note', obj}]

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

  /* ---------------- 共享结果渲染 ---------------- */
  function groupHead(emoji, label, color, count) {
    return '<div class="us-group-head">' + emoji + '<span>' + label + '</span>' +
      '<span class="us-count" style="background:' + color + ';">' + count + '</span></div>';
  }
  function moreLink(n, q) {
    if (n <= 3) return '';
    return '<a class="us-more" href="' + CFG.resultsPage + '?q=' +
      encodeURIComponent(q) + '">查看全部 ' + n + ' 条 ›</a>';
  }
  function kbItem(idx, k, q) {
    return '<a href="' + k.detail_url + '" data-idx="' + idx + '" class="us-r-item">' +
      '<span class="us-item-ico">📄</span>' +
      '<div class="us-item-main">' +
      '<div class="us-item-title">' + highlight(k.title, q) + '</div>' +
      '<div class="us-item-sub">' + esc(k.path || '未分类') + ' · ' + esc(k.score) + '%</div>' +
      '</div></a>';
  }
  function taskItem(idx, t, q) {
    return '<a href="' + t.detail_url + '" data-idx="' + idx + '" class="us-r-item">' +
      '<span class="us-item-ico">✅</span>' +
      '<div class="us-item-main">' +
      '<div class="us-item-title">' + highlight(t.title, q) + '</div>' +
      '<div class="us-item-sub">' + priEmoji(t.priority) + ' ' +
      '<span class="' + priCls(t.priority) + '">' + esc(t.priority) + '</span> · ' +
      esc(t.end_date || '') + ' 截止</div>' +
      '</div></a>';
  }
  function noteItem(idx, n, q) {
    var meta = esc(n.date || '') + ' 创建' + (n.thread ? ' · ' + esc(n.thread) : '');
    return '<a href="' + n.detail_url + '" data-idx="' + idx + '" class="us-r-item">' +
      '<span class="us-item-ico">📝</span>' +
      '<div class="us-item-main">' +
      '<div class="us-item-title">' + highlight(n.title || '(无标题)', q) + '</div>' +
      '<div class="us-item-sub">' + meta + '</div>' +
      '</div></a>';
  }
  function emptyHtml(q) {
    return '<div class="us-empty"><i class="bi bi-search"></i> 暂无匹配结果</div>' +
      '<div class="us-empty-sub">没有找到与「' + esc(q) + '」相关的内容，换个关键词试试</div>';
  }
  function skeletonHtml() {
    var rows = '';
    for (var i = 0; i < 4; i++) {
      rows += '<div class="sk-row"><div class="sk-dot"></div>' +
        '<div class="sk-main"><div class="sk-line" style="width:' + (62 + i * 7) + '%"></div>' +
        '<div class="sk-line sk-thin" style="width:' + (30 + i * 9) + '%"></div></div></div>';
    }
    return '<div class="us-skeleton">' + rows + '</div>';
  }
  function footHtml(total, q) {
    return '<a class="us-foot-link" href="' + CFG.resultsPage + '?q=' +
      encodeURIComponent(q) + '"><i class="bi bi-list"></i> 共 ' + total +
      ' 条结果，查看全部 ›</a>';
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

  /* 渲染分组结果到容器,返回条目数组(供键盘导航) */
  function renderResults(body, q, data) {
    var items = [];
    var parts = [];
    var kb = data.kb || [];
    var tasks = data.tasks || [];
    var notes = data.notes || [];
    var total = kb.length + tasks.length + notes.length;
    var per = 3;

    if (!total) {
      body.innerHTML = emptyHtml(q);
      return items;
    }
    function sec(html) { return '<div class="us-sec">' + html + '</div>'; }
    if (kb.length) {
      var p = [groupHead('📄', '知识库', 'var(--warning)', kb.length)];
      kb.slice(0, per).forEach(function (k) {
        items.push({ type: 'kb', obj: k });
        p.push(kbItem(items.length - 1, k, q));
      });
      p.push(moreLink(kb.length, q));
      parts.push(sec(p.join('')));
    }
    if (tasks.length) {
      var t2 = [groupHead('✅', '待办', 'var(--primary)', tasks.length)];
      tasks.slice(0, per).forEach(function (t) {
        items.push({ type: 'task', obj: t });
        t2.push(taskItem(items.length - 1, t, q));
      });
      t2.push(moreLink(tasks.length, q));
      parts.push(sec(t2.join('')));
    }
    if (notes.length) {
      var n2 = [groupHead('📝', '随手记', 'var(--success)', notes.length)];
      notes.slice(0, per).forEach(function (n) {
        items.push({ type: 'note', obj: n });
        n2.push(noteItem(items.length - 1, n, q));
      });
      n2.push(moreLink(notes.length, q));
      parts.push(sec(n2.join('')));
    }
    body.innerHTML = parts.join('');
    return items;
  }

  /* ---------------- 键盘选择(两处共用) ---------------- */
  function setSel(body, idx) {
    _sel = idx;
    body.querySelectorAll('.us-r-item').forEach(function (el) {
      el.classList.toggle('us-active', parseInt(el.getAttribute('data-idx'), 10) === idx);
    });
  }
  function moveSel(body, dir) {
    var n = _items.length;
    if (!n) return;
    setSel(body, (_sel + dir + n) % n);
    var el = body.querySelector('.us-r-item[data-idx="' + _sel + '"]');
    if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest' });
  }
  function jump() {
    var it = _items[_sel >= 0 ? _sel : 0];
    if (it) location.href = it.obj.detail_url;
  }

  /* ================ 桌面: 顶栏下拉 ================ */
  function initDesktop() {
    var input = document.getElementById('unifiedSearchInput');
    if (!input) return;
    var btn = document.getElementById('unifiedSearchBtn');
    var overlay = document.getElementById('unifiedSearchOverlay');
    var suggest = document.getElementById('unifiedSuggestBox');
    var body = document.getElementById('unifiedSearchBody');
    var footer = document.getElementById('unifiedSearchFooter');

    function openOverlay() { if (overlay) overlay.classList.remove('d-none'); }
    function closeOverlay() { if (overlay) overlay.classList.add('d-none'); }
    function openSuggest() { if (suggest) suggest.classList.remove('d-none'); }
    function closeSuggest() { if (suggest) suggest.classList.add('d-none'); }

    function doSearch() {
      var q = input.value.trim();
      if (!q) { closeOverlay(); closeSuggest(); return; }
      closeSuggest();
      if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner-border spinner-border-sm" style="width:.7rem;height:.7rem;"></span>'; }
      body.innerHTML = skeletonHtml();
      if (footer) footer.classList.add('d-none');
      openOverlay();
      fetch(CFG.api + '?q=' + encodeURIComponent(q))
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (!d.ok) { body.innerHTML = '<div class="us-empty">检索失败，请重试</div>'; return; }
          _items = renderResults(body, q, d);
          setSel(body, -1);
          if (footer) {
            footer.innerHTML = footHtml(d.total, q);
            footer.classList.remove('d-none');
            if (d.total === 0) footer.classList.add('d-none');
          }
        })
        .catch(function () { body.innerHTML = '<div class="us-empty">网络错误，请重试</div>'; })
        .finally(function () {
          if (btn) { btn.innerHTML = '<i class="bi bi-search"></i> <span class="us-btn-label">检索</span>'; btn.disabled = false; }
        });
    }

    function loadHistory() {
      if (input.value.trim() || !suggest) return;
      var list = document.getElementById('unifiedSuggestList');
      if (!list) return;
      fetch(CFG.historyApi)
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (!d.ok) { closeSuggest(); return; }
          var html = '';
          if (d.items && d.items.length) html += historyItemsHtml(d.items);
          html += hotHtml(d.hot);
          if (!html) { closeSuggest(); return; }
          list.innerHTML = html;
          openSuggest();
        }).catch(function () { closeSuggest(); });
    }

    input.addEventListener('focus', loadHistory);
    input.addEventListener('input', function () {
      clearTimeout(_debTimer);
      if (!input.value.trim()) { closeOverlay(); closeSuggest(); return; }
      _debTimer = setTimeout(doSearch, 300);
    });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        if (_items.length) { jump(); }
        else if (input.value.trim()) {
          location.href = CFG.resultsPage + '?q=' + encodeURIComponent(input.value.trim());
        }
      } else if (e.key === 'Escape') { closeOverlay(); closeSuggest(); input.blur(); }
      else if (e.key === 'ArrowDown') { e.preventDefault(); moveSel(body, 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); moveSel(body, -1); }
    });
    if (btn) btn.addEventListener('click', doSearch);
    body.addEventListener('mouseover', function (e) {
      var el = e.target.closest('.us-r-item');
      if (el) setSel(body, parseInt(el.getAttribute('data-idx'), 10));
    });
    if (suggest) {
      suggest.addEventListener('click', function (e) {
        var chip = e.target.closest('.us-hot-chip');
        if (chip) {
          input.value = decodeURIComponent(chip.getAttribute('data-tag'));
          closeSuggest();
          doSearch();
          return;
        }
        var it = e.target.closest('.us-item');
        if (!it) return;
        input.value = decodeURIComponent(it.getAttribute('data-q'));
        closeSuggest();
        doSearch();
      });
    }
    document.addEventListener('click', function (e) {
      if (e.target.closest('#unifiedSearchWrap')) return;
      closeOverlay(); closeSuggest();
    });
  }

  /* ================ 移动端: 全屏检索 ================ */
  function initFullscreen() {
    var overlay = document.getElementById('fullscreenSearch');
    if (!overlay) return;
    var input = document.getElementById('fsSearchInput');
    var body = document.getElementById('fsBody');
    var openBtn = document.getElementById('navSearchBtn');
    var touchStart = null;

    function open() {
      overlay.classList.remove('d-none');
      requestAnimationFrame(function () { overlay.classList.add('fs-open'); });
      document.body.style.overflow = 'hidden';
      setTimeout(function () { input.focus(); }, 80);
      showHistory();
    }
    function close() {
      overlay.classList.remove('fs-open');
      overlay.classList.add('d-none');
      document.body.style.overflow = '';
      input.value = '';
      _items = [];
      _sel = -1;
    }
    function showHistory() {
      if (input.value.trim()) return;
      body.innerHTML = '<div class="fs-hint"><i class="bi bi-search"></i>' +
        '<div>输入关键词，检索待办、随手记与知识库</div></div>';
      fetch(CFG.historyApi)
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (!d.ok) return;
          var html = '';
          if (d.items && d.items.length) html += historyItemsHtml(d.items);
          html += hotHtml(d.hot);
          if (html) body.innerHTML = html;
        }).catch(function () { /* 保留空态提示 */ });
    }
    function doSearch() {
      var q = input.value.trim();
      if (!q) { showHistory(); return; }
      body.innerHTML = skeletonHtml();
      fetch(CFG.api + '?q=' + encodeURIComponent(q))
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (!d.ok) { body.innerHTML = '<div class="us-empty">检索失败，请重试</div>'; return; }
          _items = renderResults(body, q, d);
          setSel(body, -1);
        })
        .catch(function () { body.innerHTML = '<div class="us-empty">网络错误，请重试</div>'; });
    }

    if (openBtn) openBtn.addEventListener('click', open);
    document.getElementById('fsBackBtn').addEventListener('click', close);
    document.getElementById('fsClearBtn').addEventListener('click', function () {
      input.value = '';
      showHistory();
      input.focus();
    });
    input.addEventListener('input', function () {
      clearTimeout(_debTimer);
      if (!input.value.trim()) { showHistory(); return; }
      _debTimer = setTimeout(doSearch, 300);
    });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        if (_items.length) { jump(); }
        else if (input.value.trim()) {
          location.href = CFG.resultsPage + '?q=' + encodeURIComponent(input.value.trim());
        }
      } else if (e.key === 'Escape') { close(); }
      else if (e.key === 'ArrowDown') { e.preventDefault(); moveSel(body, 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); moveSel(body, -1); }
    });
    body.addEventListener('mouseover', function (e) {
      var el = e.target.closest('.us-r-item');
      if (el) setSel(body, parseInt(el.getAttribute('data-idx'), 10));
    });
    body.addEventListener('click', function (e) {
      var chip = e.target.closest('.us-hot-chip');
      if (chip) {
        input.value = decodeURIComponent(chip.getAttribute('data-tag'));
        doSearch();
        return;
      }
      var it = e.target.closest('.us-item');
      if (!it) return;
      input.value = decodeURIComponent(it.getAttribute('data-q'));
      doSearch();
    });
    // 手势: 结果区已滚到顶部时,下拉关闭
    overlay.addEventListener('touchstart', function (e) {
      touchStart = { y: e.touches[0].clientY, x: e.touches[0].clientX };
    }, { passive: true });
    overlay.addEventListener('touchmove', function (e) {
      if (!touchStart) return;
      var dy = e.touches[0].clientY - touchStart.y;
      var dx = e.touches[0].clientX - touchStart.x;
      if (dy > 80 && Math.abs(dy) > Math.abs(dx) && body.scrollTop <= 0) {
        touchStart = null;
        close();
      }
    }, { passive: true });
  }

  initDesktop();
  initFullscreen();
})();
