(function () {
  'use strict';
  var C = window.Edu.Constants;
  var Store = window.Edu.Store;

  function endOfToday() { var t = new Date(); t.setHours(23, 59, 59, 999); return t.getTime(); }

  function leitnerDue(box) {
    var due = new Date();
    due.setTime(endOfToday() + C.LEITNER_DAYS[box] * 86400000);
    return due.getTime();
  }

  function dueWrongList() {
    var now = Date.now();
    return (Store.state.wrong || []).filter(function(w){
      var box = w.box || 0;
      return w.due <= now;
    });
  }

  var BADGES = {
    s1: { name:'⭐ 第一颗星', desc:'累计获得 1 颗星' },
    s10: { name:'🌟 十星小达人', desc:'累计获得 10 颗星' },
    s50: { name:'💎 学习小超人', desc:'累计获得 50 颗星' },
    r100: { name:'📈 百日之基', desc:'累计完成 100 题' },
    c5: { name:'🔥 连对五题', desc:'一组里连续答对 5 题' },
    c10: { name:'⚡ 全对风暴', desc:'一组里连续答对 10 题' },
    d3: { name:'📅 坚持三天', desc:'连续打卡 3 天' },
    d7: { name:'🗓️ 七日成习', desc:'连续打卡 7 天' },
    z1: { name:'🎉 初次答卷', desc:'完成第 1 份卷子' },
    z10: { name:'📚 十卷成材', desc:'完成 10 份卷子' },
    z25: { name:'🏛️ 心得成篇', desc:'完成 25 份卷子' },
    m5: { name:'🧮 口算小神童', desc:'数学口算答对 30 题' },
    f20: { name:'🍃 诗词小书生', desc:'古诗答对 20 题' },
    p10: { name:'🎈 乐园常客', desc:'快乐乐园玩满 5 次' },
    all: { name:'🎨 全面发展', desc:'语文 / 数学 / 英语 / 乐园 都练过' },
    w0: { name:'🧹 错题清零', desc:'把错题全部消灭' }
  };

  function evalBadges(prevWrong, comboRun) {
    var newly = [];
    var s = Store.state;
    if (!s.badges) s.badges = {};
    var got = function (k) { return !!(s.badges && s.badges[k]); };
    var take = function (k) { if (got(k)) return; s.badges[k] = Date.now(); newly.push(k); };

    var stars = s.stars || 0;
    var submits = s.submits || 0;
    if (stars >= 1) take('s1');
    if (stars >= 10) take('s10');
    if (stars >= 50) take('s50');
    if (submits >= 100) take('r100');
    if (comboRun >= 5) take('c5');
    if (comboRun >= 10) take('c10');

    // 连续打卡: 依据做题记录出现的连续天数
    var daySet = {};
    function pad2(n) { return n < 10 ? '0' + n : '' + n; }
    (s.records || []).forEach(function (r) { if (r && r.date) daySet[r.date] = 1; });
    var d = new Date(), dayK = pad2(d.getFullYear()) + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
    var streak = 0;
    if (!daySet[dayK]) d = new Date(d.getTime() - 86400000);
    dayK = pad2(d.getFullYear()) + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
    while (daySet[dayK]) { streak++; d = new Date(d.getTime() - 86400000); dayK = pad2(d.getFullYear()) + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()); }
    if (streak >= 7) take('d7');
    else if (streak >= 3) take('d3');

    if (submits >= 1) take('z1');
    if (submits >= 10) take('z10');
    if (submits >= 25) take('z25');

    // 各学科累计答对
    var subjRight = { zh: 0, math: 0, en: 0 };
    (s.records || []).forEach(function (r) { if (r && r.ok && subjRight[r.subj] !== undefined) subjRight[r.subj]++; });
    if (subjRight.math >= 30) take('m5');
    if (subjRight.zh >= 20) take('f20');

    // 乐园玩满 5 次: 极速练习完成次数
    if (((s.wb && s.wb.done) || []).length >= 5) take('p10');

    // 全面发展: 语文 / 数学 / 英语 / 乐园 都练过(乐园记入 wb.done)
    var hasSubj = {};
    (s.records || []).forEach(function (r) { if (r && r.subj) hasSubj[r.subj] = 1; });
    if (hasSubj.zh && hasSubj.math && hasSubj.en && ((s.wb && s.wb.done) || []).length >= 1) take('all');

    // 错题清零: 无任何逾期错题(全部消灭)
    var rest = dueWrongList();
    if (rest.length === 0 && ((s.wrong || []).length > 0 || submits > 0)) take('w0');

    if (newly.length) { Store.saveState(); badgeReveal(newly); }
  }

  function badgeReveal(keys) {
    var host = document.getElementById('badgeRevealHost');
    if (!host) return;
    keys.forEach(function(k){
      var b = BADGES[k];
      if (!b) return;
      var el = document.createElement('div');
      el.className = 'badge-reveal';
      el.innerHTML = '<div class="badge-icon">'+b.name.split(' ')[0]+'</div><div class="badge-text"><div class="badge-name">'+b.name+'</div><div class="badge-desc">'+b.desc+'</div></div>';
      host.appendChild(el);
      setTimeout(function(){ if (el.classList) el.classList.remove('show'); setTimeout(function(){ if (el.remove) el.remove(); }, 300); }, 3000);
    });
  }

  window.closeBadgeReveal = function () {
    var host = document.getElementById('badgeRevealHost');
    if (host) host.innerHTML = '';
  };

  function badgePulse(k) {
    var el = document.getElementById('badge-'+k);
    if (el) { el.classList.add('pulse'); setTimeout(function(){ el.classList.remove('pulse'); }, 600); }
  }

  window.Edu.Legacy = {
    endOfToday: endOfToday,
    leitnerDue: leitnerDue,
    dueWrongList: dueWrongList,
    BADGES: BADGES,
    evalBadges: evalBadges,
    badgeReveal: badgeReveal,
    badgePulse: badgePulse
  };
})();