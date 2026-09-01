(function () {
  'use strict';
  var C = window.Edu.Constants;
  var M = window.Edu.MathUtils;
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

    if (s.submits === 1 && !s.badges.first_win) { s.badges.first_win = Date.now(); newly.push('first_win'); }
    if (comboRun >= 3 && !s.badges.streak_3) { s.badges.streak_3 = Date.now(); newly.push('streak_3'); }
    if (comboRun >= 5 && !s.badges.streak_5) { s.badges.streak_5 = Date.now(); newly.push('streak_5'); }

    var subjRight = { zh:0, math:0, en:0 };
    (s.records || []).forEach(function(r){ if (r.ok && subjRight[r.subj] !== undefined) subjRight[r.subj]++; });
    if (subjRight.math >= 50 && !s.badges.math_50) { s.badges.math_50 = Date.now(); newly.push('math_50'); }
    if (subjRight.zh >= 50 && !s.badges.zh_50) { s.badges.zh_50 = Date.now(); newly.push('zh_50'); }
    if (subjRight.en >= 50 && !s.badges.en_50) { s.badges.en_50 = Date.now(); newly.push('en_50'); }

    if (s.stars >= 100 && !s.badges.star_100) { s.badges.star_100 = Date.now(); newly.push('star_100'); }
    if (s.stars >= 500 && !s.badges.star_500) { s.badges.star_500 = Date.now(); newly.push('star_500'); }

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
      setTimeout(function(){ el.classList.add('show'); }, 50);
      setTimeout(function(){ el.classList.remove('show'); setTimeout(function(){ el.remove(); }, 300); }, 3000);
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