(function () {
  'use strict';
  var C = window.Edu.Constants;
  var M = window.Edu.MathUtils;
  var Store = window.Edu.Store;
  var Legacy = window.Edu.Legacy;

  function badgeCard(k) {
    var b = Legacy.BADGES[k];
    var got = Store.state.badges && Store.state.badges[k];
    return '<div class="badge-card '+(got?'on':'dim')+'" id="badge-'+k+'" onclick="window.Edu.Legacy.badgePulse(\''+k+'\')">'+
      '<div class="badge-icon">'+(b?b.name.split(' ')[0]:'🏅')+'</div>'+
      '<div class="badge-name">'+(b?b.name:k)+'</div>'+
      '<div class="badge-desc">'+(b?b.desc:'')+'</div>'+
      (got?'<div class="badge-got">已获得</div>':'')+
      '</div>';
  }

  function renderBadges() {
    var body = document.getElementById('eduBadgesBody');
    if (!body) return;
    renderWelcomeInto('badgesWelcome', '闯关赢星星，集齐你的勋章');
    var keys = Object.keys(Legacy.BADGES);
    var unlocked = 0;
    for (var i=0;i<keys.length;i++) if (Store.state.badges && Store.state.badges[keys[i]]) unlocked++;
    var kids = window.eduKids ? window.eduKids.all() : [];
    var act = window.eduKids ? window.eduKids.active() : (kids[0] || null);
    var name = act ? (act.name || '宝贝') : '宝贝';
    var pct = keys.length ? Math.round(unlocked * 100 / keys.length) : 0;
    body.innerHTML =
      '<div class="bd-hero">'+
        '<div class="bd-hero-em">🏆</div>'+
        '<div class="bd-hero-meta"><div class="bd-hero-t">' + name + ' 的勋章墙</div>'+
        '<div class="bd-hero-sub">已解锁 <b>' + unlocked + '</b> / ' + keys.length + ' 枚 · 星星 ⭐ ' + (Store.state.stars || 0) + '</div>'+
        '<div class="bd-prog"><div class="bd-fill" style="width:' + pct + '%;"></div></div></div>'+
      '</div>'+
      '<div class="badge-count">已解锁 '+unlocked+' / '+keys.length+' 枚勋章</div>'+
      '<div class="badge-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(min(140px,100%),1fr));gap:12px;">'+keys.map(badgeCard).join('')+'</div>'+
      '<p class="bd-tip">💡 闯关、极速练习与每日挑战都能赢星星换新勋章，继续加油！</p>';
    // 渲染宝贝切换器
    var picker = document.getElementById('badgesKidPicker');
    if (picker && kids.length > 1) {
      picker.innerHTML = '<div class="kp-label">切换宝贝：</div>' +
        '<div class="kp-list">' + kids.map(function(k){
          var on = act && k.id === act.id;
          return '<button type="button" class="kp-btn'+(on?' on':'')+'" onclick="window.switchKid(\''+k.id+'\')">'+
            (k.gender==='female'?'👧':'👦')+' '+esc(k.name)+'</button>';
        }).join('') + '</div>';
    }
  }

  window.Edu.Badges = {
    renderBadges: renderBadges,
    badgeCard: badgeCard
  };
})();