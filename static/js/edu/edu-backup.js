(function () {
  'use strict';
  var C = window.Edu.Constants;
  var Store = window.Edu.Store;
  var Speech = window.Edu.Speech;
  var Nav = window.Edu.Nav;

  // =====================================================================
  // 数据备份与恢复(第四批): 导出为匿名化 JSON(不含真实姓名/全名,
  // 仅 id/性别/出生年份), 保存在本地; 导入时按「宝贝」回写到各自的
  // localStorage 键(edu_state_v1_<id> / edu_wb_v1_<id>), 全程本地完成.
  // 参考 幼小衔接工作台 备份/恢复 · 芽芽星 三端同步的本地版.
  // =====================================================================

  function load(k) { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } }

  function currentKids() {
    var kids = (window.eduKids ? window.eduKids.all() : []) || [];
    return kids.filter(function (k) { return k && k.id; });
  }

  // 匿名化: 不包含 name/avatar 等可识别字段
  function buildBackup() {
    var out = { app: 'edu', type: 'backup', version: 1, exportedAt: new Date().toISOString(), kids: [] };
    currentKids().forEach(function (k) {
      var state = load(Store.stateKeyFor(k.id));
      var wb = load(Store.wbKeyFor(k.id));
      var item = { id: k.id, gender: k.gender || 'male', birthYear: k.birthYear || (new Date().getFullYear() - 5), state: state || {}, wb: wb || {} };
      out.kids.push(item);
    });
    return out;
  }

  function download(filename, text) {
    if (typeof document === 'undefined') return;
    try {
      var blob = new Blob([text], { type: 'application/json;charset=utf-8' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      setTimeout(function () {
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }, 400);
    } catch (e) {
      if (Speech && Speech.toast) Speech.toast('导出失败');
    }
  }

  window.Edu.Backup = {
    buildBackup: buildBackup
  };

  window.Edu.Backup.exportJson = function () {
    var data = buildBackup();
    var name = '芽芽学习备份_' + data.exportedAt.slice(0, 10) + '.json';
    download(name, JSON.stringify(data, null, 2));
    if (Speech && Speech.toast) Speech.toast('已导出匿名备份(不含姓名)');
  };

  window.Edu.Backup.restoreJson = function (json) {
    if (!json || json.app !== 'edu' || json.type !== 'backup' || !Array.isArray(json.kids)) {
      if (Speech && Speech.toast) Speech.toast('备份文件无效');
      return false;
    }
    var restored = 0;
    json.kids.forEach(function (item) {
      if (!item || !item.id) return;
      var keyS = Store.stateKeyFor(item.id);
      var keyW = Store.wbKeyFor(item.id);
      try {
        localStorage.setItem(keyS, JSON.stringify(item.state || {}));
        localStorage.setItem(keyW, JSON.stringify(item.wb || {}));
        restored++;
      } catch (e) {}
    });
    Store.loadAllState();
    if (Nav && Nav.enter) Nav.enter();
    if (Speech && Speech.toast) Speech.toast(restored > 0 ? ('已恢复 ' + restored + ' 个宝贝的数据') : '备份中没有可恢复的数据');
    return restored > 0;
  };

  // 文件选择 → 读取内容 → 恢复(浏览器端)
  window.Edu.Backup.importFromFile = function (file) {
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function () {
      try {
        var json = JSON.parse(String(reader.result));
        window.Edu.Backup.restoreJson(json);
      } catch (e) {
        if (Speech && Speech.toast) Speech.toast('解析备份失败');
      }
    };
    reader.readAsText(file);
  };

  window.exportBackup = window.Edu.Backup.exportJson;

  window.importBackup = function () {
    var input = document.getElementById('backupFile');
    if (!input) return;
    if (!input.files || !input.files.length) { if (Speech && Speech.toast) Speech.toast('请选择备份文件'); return; }
    window.Edu.Backup.importFromFile(input.files[0]);
  };

  if (window.Edu.Settings) window.Edu.Settings.Backup = window.Edu.Backup;
})();