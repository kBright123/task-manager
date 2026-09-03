(function () {
  'use strict';
  var Store = window.Edu.Store;

  function esc(s) { return String(s === undefined || s === null ? '' : s).replace(/</g, '<').replace(/&/g, '&'); }

  function avaOf(k) {
    if (!k) return '🧒';
    return k.gender === 'female' ? '👧' : '👦';
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

    // 宝贝管理入口：有宝贝显示"管理宝贝"，无宝贝显示"添加宝贝"
    var kidsHtml = kids.length > 0
      ? '<button type="button" class="mine-kid-link" onclick="openKidsMgr()">' +
          '<span class="mkl-ava">' + avaOf(act) + '</span>' +
          '<div class="mkl-info">' +
            '<span class="mkl-title">管理宝贝</span>' +
            '<span class="mkl-sub">' + kids.length + ' 个宝贝 · 当前 ' + esc(name) + '</span>' +
          '</div>' +
          '<span class="mkl-chevron"><i class="bi bi-chevron-right"></i></span>' +
        '</button>'
      : '<button type="button" class="mine-kid-link empty" onclick="openKidsMgr()">' +
          '<span class="mkl-ava">🧒</span>' +
          '<div class="mkl-info">' +
            '<span class="mkl-title">添加宝贝</span>' +
            '<span class="mkl-sub">点击添加第一个宝贝</span>' +
          '</div>' +
          '<span class="mkl-plus">+</span>' +
        '</button>';

    // 设置分组
    var settingsHtml = '<div class="mine-settings">' +
      '<div class="ms-group">' +
        '<h4>学习设置</h4>' +
        '<button type="button" class="ms-item" onclick="openParentMode()">' +
          '<span class="ms-icon">📚</span><span>课程与难度</span><i class="bi bi-chevron-right"></i>' +
        '</button>' +
        '<button type="button" class="ms-item" onclick="openParentMode(\'eye\')">' +
          '<span class="ms-icon">👁️</span><span>护眼提醒</span><i class="bi bi-chevron-right"></i>' +
        '</button>' +
        '<button type="button" class="ms-item" onclick="openParentMode(\'daily\')">' +
          '<span class="ms-icon">📅</span><span>每日题量/时长</span><i class="bi bi-chevron-right"></i>' +
        '</button>' +
      '</div>' +
      '<div class="ms-group">' +
        '<h4>声音与显示</h4>' +
        '<button type="button" class="ms-item" onclick="openParentMode(\'sound\')">' +
          '<span class="ms-icon">🔊</span><span>朗读与音效</span><i class="bi bi-chevron-right"></i>' +
        '</button>' +
        '<button type="button" class="ms-item" onclick="openParentMode(\'font\')">' +
          '<span class="ms-icon">🔤</span><span>字体大小</span><i class="bi bi-chevron-right"></i>' +
        '</button>' +
      '</div>' +
      '<div class="ms-group">' +
        '<h4>账号与数据</h4>' +
        '<button type="button" class="ms-item" onclick="exportBackup()">' +
          '<span class="ms-icon">📤</span><span>导出备份</span><i class="bi bi-chevron-right"></i>' +
        '</button>' +
        '<button type="button" class="ms-item" onclick="document.getElementById(\'backupFile\').click()">' +
          '<span class="ms-icon">📥</span><span>导入备份</span><i class="bi bi-chevron-right"></i>' +
        '</button>' +
        '<button type="button" class="ms-item danger" onclick="openResetConfirm()">' +
          '<span class="ms-icon">🗑️</span><span>重置所有数据</span><i class="bi bi-chevron-right"></i>' +
        '</button>' +
      '</div>' +
    '</div>';

    var hiddenFile = '<input type="file" id="backupFile" accept=".json,application/json" style="display:none;" onchange="importBackup()">';

    body.innerHTML =
      '<div class="mine-head">' +
        '<div class="mine-ava-big">' + avaOf(act) + '</div>' +
        '<div class="mine-meta"><div class="mine-name">' + esc(name) + '</div>' +
        '<div class="mine-sub">今日目标 ' + goal + ' 题 · Lv.' + levelOf(act) + '</div></div>' +
        '<div class="mine-stars">⭐ ' + stars + '</div>' +
      '</div>' +
      kidsHtml +
      settingsHtml +
      hiddenFile +
      '<p class="mine-foot">幼小衔接 · 快乐学习乐园</p>';
  }

  window.Edu.Mine = { renderMine: renderMine, avaOf: avaOf, levelOf: levelOf };
  window.renderMine = renderMine;
})();
