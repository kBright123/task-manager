(function () {
  'use strict';
  var Store = window.Edu.Store;

  function esc(s) { return String(s === undefined || s === null ? '' : s).replace(/</g, '&lt;').replace(/&/g, '&amp;'); }

  function avaOf(k) {
    if (!k) return '🧒';
    var g = k.gender === 'female' ? '👧' : '👦';
    return g;
  }
  function levelOf(k) {
    if (!k) return 1;
    var s = Store.curSettings();
    return s && s.lv ? s.lv : 1;
  }

  function renderMine() {
    var body = document.getElementById('eduMineBody');
    if (!body) return;
    var kids = window.eduKids ? window.eduKids.all() : [];
    var act = window.eduKids ? window.eduKids.active() : (kids[0] || null);
    var stars = 0;
    try { stars = (Store.state && Store.state.stars) || 0; } catch (e) {}
    var s = Store.curSettings();
    var goal = s && s.goal ? s.goal : 5;
    var name = act ? (act.name || '宝贝') : '宝贝';

    var kidSwitch = '<div class="mine-kids">' +
      '<div class="mine-kids-head"><h3>👨‍👩‍👧‍👦 宝贝</h3>' +
      '<a href="javascript:void(0)" class="mgr-link" onclick="openKidsMgr()">管理</a></div>' +
      '<div class="mine-kid-scroll">' + kids.map(function (k) {
        var on = act && k.id === act.id;
        return '<button type="button" class="mine-kid' + (on ? ' on' : '') + '" onclick="window.switchKid(\'' + k.id + '\')">' +
          '<span class="mine-kid-ava">' + avaOf(k) + '</span>' +
          '<span class="mine-kid-name">' + esc(k.name || '宝贝') + '</span>' +
          (on ? '<span class="mine-kid-cur">学习中</span>' : '') +
          '</button>';
      }).join('') + '</div></div>';

    var actions = '<div class="mine-actions">' +
      '<button type="button" class="mine-act" onclick="openParentMode()"><span class="ma-emo">⚙️</span><span>家长设置</span><i class="bi bi-chevron-right"></i></button>' +
      '<button type="button" class="mine-act" onclick="eduNav(\'stats\')"><span class="ma-emo">📈</span><span>学习报告</span><i class="bi bi-chevron-right"></i></button>' +
      '<button type="button" class="mine-act" onclick="openKidsMgr()"><span class="ma-emo">👤</span><span>宝贝管理</span><i class="bi bi-chevron-right"></i></button>' +
      '</div>';

    body.innerHTML =
      '<div class="mine-head">' +
        '<div class="mine-ava-big">' + avaOf(act) + '</div>' +
        '<div class="mine-meta"><div class="mine-name">' + esc(name) + '</div>' +
        '<div class="mine-sub">今日目标 ' + goal + ' 题 · Lv.' + levelOf(act) + '</div></div>' +
        '<div class="mine-stars">⭐ ' + stars + '</div>' +
      '</div>' +
      kidSwitch + actions +
      '<p class="mine-foot">幼小衔接 · 快乐学习乐园</p>';
  }

  window.Edu.Mine = { renderMine: renderMine, avaOf: avaOf, levelOf: levelOf };
  window.renderMine = renderMine;
})();
