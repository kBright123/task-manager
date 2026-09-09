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

  var BADGE_CATS = [
    { key: 'all',  label: '综合成长', icon: '⭐' },
    { key: 'zh',   label: '语文', icon: '📖' },
    { key: 'math', label: '数学', icon: '🧮' },
    { key: 'en',   label: '英语', icon: '🌍' },
    { key: 'go',   label: '围棋', icon: '⚫' },
    { key: 'lit',  label: '文学', icon: '📜' }
  ];

  var BADGES = {
    // ⭐ 综合成长
    s1: { cat: 'all', name:'⭐ 第一颗星', desc:'累计获得 1 颗星' },
    s10: { cat: 'all', name:'🌟 十星小达人', desc:'累计获得 10 颗星' },
    s50: { cat: 'all', name:'💎 学习小超人', desc:'累计获得 50 颗星' },
    s200: { cat: 'all', name:'🏆 星星收藏家', desc:'累计获得 200 颗星' },
    r100: { cat: 'all', name:'📈 百日之基', desc:'累计完成 100 题' },
    r500: { cat: 'all', name:'🏅 题海小将', desc:'累计完成 500 题' },
    c5: { cat: 'all', name:'🔥 连对五题', desc:'一组里连续答对 5 题' },
    c10: { cat: 'all', name:'⚡ 全对风暴', desc:'一组里连续答对 10 题' },
    c20: { cat: 'all', name:'🌀 无敌旋风', desc:'一组里连续答对 20 题' },
    d3: { cat: 'all', name:'📅 坚持三天', desc:'连续打卡 3 天' },
    d7: { cat: 'all', name:'🗓️ 七日成习', desc:'连续打卡 7 天' },
    z1: { cat: 'all', name:'🎉 初次答卷', desc:'完成第 1 份卷子' },
    z10: { cat: 'all', name:'📚 十卷成材', desc:'完成 10 份卷子' },
    z25: { cat: 'all', name:'🏛️ 心得成篇', desc:'完成 25 份卷子' },
    p10: { cat: 'all', name:'🎈 乐园常客', desc:'快乐乐园玩满 5 次' },
    all: { cat: 'all', name:'🎨 全面发展', desc:'语文 / 数学 / 英语 / 围棋 / 文学 / 乐园 都练过' },
    w0: { cat: 'all', name:'🧹 错题清零', desc:'把错题全部消灭' },
    // 📖 语文
    f10: { cat: 'zh', name:'🌱 识字小芽', desc:'语文答对 10 题' },
    f20: { cat: 'zh', name:'🍃 诗词小书生', desc:'语文答对 20 题' },
    zh50: { cat: 'zh', name:'✒️ 语文小文豪', desc:'语文答对 50 题' },
    zh150: { cat: 'zh', name:'📚 书香小博士', desc:'语文答对 150 题' },
    zh300: { cat: 'zh', name:'🎓 语文翰林学士', desc:'语文答对 300 题' },
    // 🧮 数学
    m10: { cat: 'math', name:'🔢 数数小能手', desc:'数学答对 10 题' },
    m5: { cat: 'math', name:'🧮 口算小神童', desc:'数学答对 30 题' },
    math50: { cat: 'math', name:'⚡ 计算小能手', desc:'数学答对 50 题' },
    math150: { cat: 'math', name:'🎯 数学小达人', desc:'数学答对 150 题' },
    math300: { cat: 'math', name:'🚀 数学智多星', desc:'数学答对 300 题' },
    // 🌍 英语
    en10: { cat: 'en', name:'🔡 字母小新芽', desc:'英语答对 10 题' },
    en20: { cat: 'en', name:'🔤 英语小萌牙', desc:'英语答对 20 题' },
    en50: { cat: 'en', name:'🌍 单词小达人', desc:'英语答对 50 题' },
    en150: { cat: 'en', name:'🦜 英语小外交官', desc:'英语答对 150 题' },
    en300: { cat: 'en', name:'🎓 英语小大学士', desc:'英语答对 300 题' },
    // ⚫ 围棋
    go10: { cat: 'go', name:'⚪ 围棋小新星', desc:'围棋答对 10 题' },
    go20: { cat: 'go', name:'⚫ 围棋小棋手', desc:'围棋答对 20 题' },
    go50: { cat: 'go', name:'⚪ 围棋小高手', desc:'围棋答对 50 题' },
    go150: { cat: 'go', name:'👑 围棋小棋圣', desc:'围棋答对 150 题' },
    go300: { cat: 'go', name:'♟️ 围棋小国手', desc:'围棋答对 300 题' },
    // 📜 文学
    lit10: { cat: 'lit', name:'📖 故事小听众', desc:'文学答对 10 题' },
    lit20: { cat: 'lit', name:'📜 名著小读者', desc:'文学答对 20 题' },
    lit50: { cat: 'lit', name:'🏯 名著小达人', desc:'文学答对 50 题' },
    lit150: { cat: 'lit', name:'🎓 名著小状元', desc:'文学答对 150 题' },
    lit300: { cat: 'lit', name:'🏆 文学大文豪', desc:'文学答对 300 题' }
  };

  function catBadges(cat) {
    var keys = [];
    for (var k in BADGES) if (BADGES[k].cat === cat) keys.push(k);
    return keys;
  }

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
    if (stars >= 200) take('s200');
    if (submits >= 100) take('r100');
    if (submits >= 500) take('r500');
    if (comboRun >= 5) take('c5');
    if (comboRun >= 10) take('c10');
    if (comboRun >= 20) take('c20');

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

    // 各学科累计答对 → 学科徽章
    var subjRight = { zh: 0, math: 0, en: 0, go: 0, lit: 0 };
    (s.records || []).forEach(function (r) { if (r && r.ok && subjRight[r.subj] !== undefined) subjRight[r.subj]++; });
    if (subjRight.math >= 10) take('m10');
    if (subjRight.math >= 30) take('m5');
    if (subjRight.math >= 50) take('math50');
    if (subjRight.math >= 150) take('math150');
    if (subjRight.math >= 300) take('math300');
    if (subjRight.zh >= 10) take('f10');
    if (subjRight.zh >= 20) take('f20');
    if (subjRight.zh >= 50) take('zh50');
    if (subjRight.zh >= 150) take('zh150');
    if (subjRight.zh >= 300) take('zh300');
    if (subjRight.en >= 10) take('en10');
    if (subjRight.en >= 20) take('en20');
    if (subjRight.en >= 50) take('en50');
    if (subjRight.en >= 150) take('en150');
    if (subjRight.en >= 300) take('en300');
    if (subjRight.go >= 10) take('go10');
    if (subjRight.go >= 20) take('go20');
    if (subjRight.go >= 50) take('go50');
    if (subjRight.go >= 150) take('go150');
    if (subjRight.go >= 300) take('go300');
    if (subjRight.lit >= 10) take('lit10');
    if (subjRight.lit >= 20) take('lit20');
    if (subjRight.lit >= 50) take('lit50');
    if (subjRight.lit >= 150) take('lit150');
    if (subjRight.lit >= 300) take('lit300');

    // 乐园玩满 5 次: 极速练习完成次数
    if (((s.wb && s.wb.done) || []).length >= 5) take('p10');

    // 全面发展: 语文 / 数学 / 英语 / 围棋 / 文学 / 乐园 都练过(乐园记入 wb.done)
    var hasSubj = {};
    (s.records || []).forEach(function (r) { if (r && r.subj) hasSubj[r.subj] = 1; });
    if (hasSubj.zh && hasSubj.math && hasSubj.en && hasSubj.go && hasSubj.lit && ((s.wb && s.wb.done) || []).length >= 1) take('all');

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
    BADGE_CATS: BADGE_CATS,
    catBadges: catBadges,
    evalBadges: evalBadges,
    badgeReveal: badgeReveal,
    badgePulse: badgePulse
  };
})();