(function () {
  'use strict';
  var C = window.Edu.Constants;
  var Store = window.Edu.Store;
  var Speech = window.Edu.Speech;

  var kidEditId = null;
  var kidGenderVal = null;

  function esc(s) { return String(s === undefined || s === null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'); }

  function populateYears() {
    var sel = document.getElementById('kidYearInput') || document.getElementById('editYearInput');
    if (!sel) return;
    var cur = new Date().getFullYear();
    sel.innerHTML = '';
    for (var y=cur; y>=cur-10; y--) {
      var opt = document.createElement('option');
      opt.value = y; opt.textContent = y + '年';
      if (y === cur - 6) opt.selected = true;
      sel.appendChild(opt);
    }
  }

  function openKidMask(title, sub, kid) {
    var mask = document.getElementById('eduMask');
    var mtitle = document.getElementById('kidModalTitle');
    var msub = document.getElementById('kidModalSub');
    var delBtn = document.getElementById('kidDelBtn');
    var nameIn = document.getElementById('kidNameInput');
    if (!mask) return;
    if (mtitle) mtitle.textContent = title;
    if (msub) msub.textContent = sub || '';
    populateYears();
    if (kid) {
      kidEditId = kid.id;
      if (nameIn) nameIn.value = kid.name;
      var ysel = document.getElementById('kidYearInput');
      if (ysel) ysel.value = kid.birthYear;
      kidGenderVal = kid.gender;
      document.getElementById('g-male').classList.toggle('active', kid.gender === 'male');
      document.getElementById('g-female').classList.toggle('active', kid.gender === 'female');
      if (delBtn) delBtn.style.display = '';
    } else {
      kidEditId = null;
      if (nameIn) nameIn.value = '';
      kidGenderVal = 'male';
      document.getElementById('g-male').classList.add('active');
      document.getElementById('g-female').classList.remove('active');
      if (delBtn) delBtn.style.display = 'none';
    }
    mask.style.display = 'flex';
  }

  window.kidGender = function (g) {
    kidGenderVal = g;
    document.getElementById('g-male').classList.toggle('active', g === 'male');
    document.getElementById('g-female').classList.toggle('active', g === 'female');
  };

  window.kidAdd = function () { openKidMask('👶 添加孩子资料', '填写后即可按年龄段自动进入对应的学习内容'); };

  window.kidSave = function () {
    var b = document.getElementById('kidSaveBtn');
    if (b && b.disabled) return;            // 防止重复点击
    var name = document.getElementById('kidNameInput').value.trim();
    var year = parseInt(document.getElementById('kidYearInput').value, 10);
    if (!name || !year) { Speech.toast('请填写完整'); return; }
    var data = { kids: [{ clientId: 'local_'+Date.now(), name: name, birthYear: year, gender: kidGenderVal }], removedIds: [] };
    if (kidEditId) data.kids[0].dbId = kidEditId;
    // 异步操作 loading 状态 + 禁用重复提交
    if (b) { b.disabled = true; var _t = b.textContent; b.textContent = '保存中…'; }
    fetch('/edu/api/kids', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data) })
      .then(function(r){ return r.json(); })
      .then(function(res){
        if (b) { b.disabled = false; b.textContent = _t; }
        if (res.ok) {
          document.getElementById('eduMask').style.display = 'none';
          window.Edu.Nav.enter();
        } else { Speech.toast(res.error || '保存失败'); }
      })
      .catch(function(){ if (b) { b.disabled = false; b.textContent = _t; } Speech.toast('网络异常，保存失败'); });
  };

  window.kidDelete = function () {
    if (!kidEditId) return;
    var kid = null;
    var all = (window.eduKids ? window.eduKids.all() : []) || [];
    for (var i = 0; i < all.length; i++) if (all[i].id === kidEditId) kid = all[i];
    var expectName = (kid && kid.name) || '删除';
    window.openConfirm({
      title: '🗑️ 删除宝贝',
      sub: '删除后，这个宝贝的学习进度、星星与徽章都将清除且无法恢复。请输入宝贝昵称以确认删除：',
      expect: expectName,
      okText: '删除',
      cb: function () {
        window.requireParent(function () {
          fetch('/edu/api/kids', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kids: [], removedIds: [kidEditId] }) })
            .then(function (r) { return r.json(); })
            .then(function (res) {
              if (res.ok) { document.getElementById('eduMask').style.display = 'none'; window.Edu.Nav.enter(); }
              else { Speech.toast(res.error || '删除失败'); }
            })
            .catch(function () { Speech.toast('网络异常，删除失败'); });
        });
      }
    });
  };

  function renderStarBar() {
    var bar = document.getElementById('kbStarBar');
    if (!bar) return;
    var s = Store.state.stars || 0;
    var html = '';
    for (var i=0;i<5;i++) html += '<i class="bi bi-star-fill" style="color:'+(i<s?'#ffd93d':'var(--edu-border-2)')+';font-size:.85rem;margin-right:2px;"></i>';
    bar.innerHTML = html;
  }

  function renderKidBar() {
    var active = window.eduKids ? window.eduKids.active() : null;
    var bar = document.getElementById('kidBar');
    if (!bar) return;
    if (!active) { bar.style.display = 'none'; return; }
    bar.style.display = 'flex';
    document.getElementById('kidAva').textContent = active.avatar || '🧒';
    document.getElementById('kidIdent').textContent = active.name + ' · ' + (new Date().getFullYear() - active.birthYear) + '岁';
    document.getElementById('kidLv').textContent = 'Lv.' + (Store.stateLevel ? Store.stateLevel('zh') : 1);
    renderStarBar();
    populateYears();
    renderKidDrop(active);
  }

  // 顶部条宝贝下拉: 切换 + 添加 (统一身份入口, 首页不再重复展示)
  function renderKidDrop(active) {
    var drop = document.getElementById('kidPickDrop');
    if (!drop) return;
    var kids = (window.eduKids ? window.eduKids.all() : []) || [];
    var items = kids.map(function (k) {
      var on = k.id === active.id;
      var ava = k.avatar || (window.eduKids.genderIcon ? window.eduKids.genderIcon(k.gender) : '🧒');
      return '<div class="kit-item' + (on ? ' on' : '') + '" onclick="window.switchKid(\'' + k.id + '\')">' +
        '<span class="ki-ava">' + ava + '</span><span class="ki-name">' + esc(k.name || '宝贝') + '</span>' +
        (on ? '<i class="bi bi-check2" style="margin-left:auto;color:var(--edu-primary);"></i>' : '') +
        '</div>';
    }).join('');
    items += '<div class="kit-item" onclick="kidAdd()"><span class="ki-ava">➕</span><span class="ki-name">添加宝贝</span></div>';
    drop.innerHTML = items;
  }

  window.toggleMoreMenu = function (ev) {
    ev.stopPropagation();
    var drop = document.getElementById('moreMenuDrop');
    if (drop) drop.classList.toggle('show');
  };

  window.closeMoreMenu = function () {
    var drop = document.getElementById('moreMenuDrop');
    if (drop) drop.classList.remove('show');
  };

  window.menuGo = function (which) {
    closeMoreMenu();
    if (which === 'parent') { window.openParentMode(); return; }
    if (which === 'settings') { window.openSettings(); return; }
    if (which === 'regen' || which === 'restart') {
      var qe = window.Edu.QuizEngine;
      if (!(qe && qe.quiz && !qe.quiz.submitted)) { Speech.toast('进入答题后再操作'); return; }
      if (which === 'regen') { qe.regenQuiz(); }
      else { qe.restartQuiz(); }
      return;
    }
    if (which === 'help') {
      Speech.toast('幼小衔接学习乐园：选择宝贝进入闯关，攒星星换星愿，完成关卡解锁徽章～');
      return;
    }
  };

  window.toggleKidDrop = function () {
    var drop = document.getElementById('kidPickDrop');
    if (drop) drop.classList.toggle('show');
  };

  document.addEventListener('click', function (e) {
    var wrap = document.getElementById('kidPickWrap');
    if (wrap && !wrap.contains(e.target)) {
      var drop = document.getElementById('kidPickDrop');
      if (drop) drop.classList.remove('show');
    }
    var moreWrap = document.getElementById('moreMenuBtn');
    var moreDrop = document.getElementById('moreMenuDrop');
    if (moreDrop && moreWrap && !moreWrap.contains(e.target) && !moreDrop.contains(e.target)) {
      moreDrop.classList.remove('show');
    }
  });

  window.Edu.Kids = {
    kidEditId: kidEditId,
    kidGenderVal: kidGenderVal,
    populateYears: populateYears,
    openKidMask: openKidMask,
    renderStarBar: renderStarBar,
    renderKidBar: renderKidBar,
    toggleMoreMenu: toggleMoreMenu,
    closeMoreMenu: closeMoreMenu,
    menuGo: menuGo
  };
})();