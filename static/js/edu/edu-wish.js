(function () {
  'use strict';
  var Store = window.Edu.Store;
  var Speech = window.Edu.Speech;
  var Kids = window.Edu.Kids;

  // 预置武器礼物目录（兑换区）
  var GIFT_CATALOG = [
    { id: 'dao', emoji: '🔪', name: '宝刀', desc: '削铁如泥的宝刀，挥舞起来呼呼作响！' },
    { id: 'gong', emoji: '🏹', name: '长弓', desc: '百步穿杨的长弓，射出一支神箭！' },
    { id: 'qiang', emoji: '🔫', name: '亮枪', desc: '一击必中的亮枪，火力十足！' },
    { id: 'jian', emoji: '⚔️', name: '宝剑', desc: '寒光闪闪的宝剑，勇士的最爱！' },
    { id: 'dun', emoji: '🛡️', name: '神盾', desc: '坚固无比的神盾，守护你不受伤害！' },
    { id: 'feidao', emoji: '🗡️', name: '飞刀', desc: '例无虚发的飞刀，又快又准！' }
  ];
  var DEFAULT_PRICES = { dao: 20, gong: 30, qiang: 40, jian: 50, dun: 30, feidao: 25 };

  function esc(s) { return String(s === undefined || s === null ? '' : s).replace(/</g, '<').replace(/&/g, '&'); }
  function giftOf(id) {
    for (var i = 0; i < GIFT_CATALOG.length; i++) if (GIFT_CATALOG[i].id === id) return GIFT_CATALOG[i];
    return null;
  }
  // 补全缺失的礼物价格（默认值），持久化到当前宝贝状态
  function ensureGiftData() {
    Store.state.giftPrices = (Store.state.giftPrices && typeof Store.state.giftPrices === 'object') ? Store.state.giftPrices : {};
    Store.state.redeemed = (Store.state.redeemed && Array.isArray(Store.state.redeemed)) ? Store.state.redeemed : [];
    var changed = false;
    for (var i = 0; i < GIFT_CATALOG.length; i++) {
      var id = GIFT_CATALOG[i].id;
      if (typeof Store.state.giftPrices[id] !== 'number') {
        Store.state.giftPrices[id] = DEFAULT_PRICES[id];
        changed = true;
      }
    }
    if (changed) Store.saveState();
  }
  function giftPriceOf(id) {
    ensureGiftData();
    var p = Store.state.giftPrices[id];
    return (typeof p === 'number' && p >= 0) ? p : DEFAULT_PRICES[id];
  }
  function giftCount(id) {
    var red = (Store.state.redeemed && Array.isArray(Store.state.redeemed)) ? Store.state.redeemed : [];
    var c = 0;
    for (var i = 0; i < red.length; i++) if (red[i] && red[i].id === id) c++;
    return c;
  }

  function renderWish() {
    var body = document.getElementById('eduWishBody');
    if (!body) return;
    renderWelcomeInto('wishWelcome', '攒星星，兑换你想要的小心愿');
    ensureGiftData();
    var wishes = Store.state.wishes || [];
    var stars = Store.state.stars || 0;
    var html = '<div class="wish-summary" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;padding:12px;background:linear-gradient(135deg,#fff3d6,#ffe1ae);border-radius:12px;border:1.5px solid #ffd9a8;">'+
      '<div>当前星星：<b style="font-size:1.2rem;color:#b7791f;">'+stars+'</b> ⭐</div>'+
      '<button type="button" class="btn-soft" onclick="window.wishAdd()">+ 新增星愿</button>'+
      '</div>';

    // ---- 兑换区：预置武器礼物 ----
    html += '<div class="gift-section">' +
      '<h3 class="gift-title">🎁 兑换区 · 武器宝库</h3>' +
      '<div class="gift-grid">';
    GIFT_CATALOG.forEach(function (g) {
      var price = giftPriceOf(g.id);
      var can = stars >= price;
      var cnt = giftCount(g.id);
      html += '<div class="gift-card' + (can ? '' : ' off') + '">' +
        '<div class="gift-emoji">' + g.emoji + '</div>' +
        '<div class="gift-name">' + esc(g.name) + '</div>' +
        '<div class="gift-price">' + price + ' ⭐' + (cnt ? ' · 已有 ' + cnt + ' 个' : '') + '</div>' +
        '<div class="gift-actions">' +
        '<button type="button" class="btn-ghost" onclick="window.giftDetail(\'' + g.id + '\')">查看</button>' +
        '<button type="button" class="btn-soft" ' + (can ? '' : 'disabled') + ' onclick="window.giftRedeem(\'' + g.id + '\')">兑换</button>' +
        '</div>' +
        '</div>';
    });
    html += '</div></div>';

    // ---- 已兑换列表 ----
    var redeemed = (Store.state.redeemed && Array.isArray(Store.state.redeemed)) ? Store.state.redeemed : [];
    html += '<div class="gift-section">' +
      '<h3 class="gift-title">📦 已兑换</h3>';
    if (!redeemed.length) {
      html += '<p class="gift-empty">还没有兑换礼物，去兑换区挑一件心仪的武器吧！</p>';
    } else {
      html += '<div class="redeem-list">' + redeemed.map(function (r, i) {
        var g = giftOf(r.id);
        var emoji = g ? g.emoji : '🎁';
        var name = r.name || (g ? g.name : '礼物');
        return '<button type="button" class="redeem-item" onclick="window.giftDetailByIdx(' + i + ')">' +
          '<span class="ri-emoji">' + emoji + '</span>' +
          '<span class="ri-name">' + esc(name) + '</span>' +
          '<span class="ri-date">' + esc(r.date || '') + '</span>' +
          '<i class="bi bi-chevron-right"></i>' +
          '</button>';
      }).join('') + '</div>';
    }
    html += '</div>';

    // ---- 我的星愿 ----
    html += '<h3 class="gift-title">✨ 我的星愿</h3>';
    if (!wishes.length) {
      html += '<div style="text-align:center;padding:24px;color:var(--edu-muted);">暂无星愿，点击「新增星愿」添加心愿吧～</div>';
    } else {
      html += '<div class="wish-list">';
      wishes.forEach(function(w, i){
        var can = stars >= (w.cost || 10);
        html += '<div class="wish-item" style="display:flex;align-items:center;gap:12px;padding:12px;background:var(--edu-surface);border:1px solid var(--edu-border-2);border-radius:12px;margin-bottom:10px;">'+
          '<div style="flex:1;"><div style="font-weight:700;">'+esc(w.title)+'</div><div style="font-size:.85rem;color:var(--edu-muted);">价值 '+w.cost+' 颗星星</div></div>'+
          '<div style="display:flex;gap:8px;">'+
          '<button type="button" class="btn-soft '+(can?'':'')+'" '+(can?'':'disabled')+' onclick="window.wishRedeem('+i+')">兑换</button>'+
          '<button type="button" class="btn-ghost" onclick="window.wishRemove('+i+')">删除</button>'+
          '</div></div>';
      });
      html += '</div>';
    }
    body.innerHTML = html;
    renderWishKidPicker();
  }
  function renderWishKidPicker() {
    var picker = document.getElementById('wishKidPicker');
    if (!picker) return;
    var kids = window.eduKids ? window.eduKids.all() : [];
    if (kids.length <= 1) { picker.innerHTML = ''; return; }
    var act = window.eduKids ? window.eduKids.active() : (kids[0] || null);
    picker.innerHTML = '<div class="kp-label">切换宝贝：</div>' +
      '<div class="kp-list">' + kids.map(function(k){
        var on = act && k.id === act.id;
        return '<button type="button" class="kp-btn'+(on?' on':'')+'" onclick="window.switchKid(\''+k.id+'\')">'+
          (k.gender==='female'?'👧':'👦')+' '+esc(k.name)+'</button>';
      }).join('') + '</div>';
  }

  // 兑换武器礼物（家长确认后扣星并入已兑换）
  window.giftRedeem = function (id) {
    var g = giftOf(id);
    if (!g) { Speech.toast('没有这件礼物'); return; }
    var price = giftPriceOf(id);
    if ((Store.state.stars || 0) < price) { Speech.toast('星星不足'); return; }
    window.requireParent(function () {
      Store.state.stars -= price;
      Store.state.redeemed = (Store.state.redeemed && Array.isArray(Store.state.redeemed)) ? Store.state.redeemed : [];
      Store.state.redeemed.push({ id: g.id, name: g.name, emoji: g.emoji, t: Date.now(), date: fmtDate(new Date()) });
      Store.saveState();
      Kids.renderStarBar();
      renderWish();
      Speech.toast('兑换成功！获得 ' + g.name + ' ' + g.emoji);
    });
  };

  function fmtDate(d) {
    return (d.getFullYear()) + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  // 打开礼物细节弹窗
  function openGiftDetail(g, extra) {
    var title = document.getElementById('detailTitle');
    var sub = document.getElementById('detailSub');
    var body = document.getElementById('detailBody');
    if (title) title.textContent = g.emoji + ' ' + g.name;
    if (sub) sub.textContent = extra || ('需要 ' + giftPriceOf(g.id) + ' 颗星星兑换');
    var cnt = giftCount(g.id);
    if (body) body.innerHTML =
      '<div class="gift-detail">' +
      '<div class="gdetail-emoji">' + g.emoji + '</div>' +
      '<div class="gdetail-name">' + esc(g.name) + '</div>' +
      '<div class="gdetail-desc">' + esc(g.desc) + '</div>' +
      '<div class="gdetail-meta">价格 ' + giftPriceOf(g.id) + ' ⭐' + (cnt ? ' · 已获得 ' + cnt + ' 个' : '') + '</div>' +
      '</div>';
    var mask = document.getElementById('eduMaskDetail');
    if (mask) mask.style.display = 'flex';
  }
  window.giftDetail = function (id) {
    var g = giftOf(id);
    if (!g) return;
    openGiftDetail(g);
  };
  window.giftDetailByIdx = function (i) {
    var red = (Store.state.redeemed && Array.isArray(Store.state.redeemed)) ? Store.state.redeemed : [];
    var r = red[i];
    if (!r) return;
    var g = giftOf(r.id) || { id: r.id, emoji: r.emoji || '🎁', name: r.name || '礼物', desc: '已兑换的礼物' };
    openGiftDetail(g, '于 ' + (r.date || '') + ' 兑换');
  };

  // 在「我的」设置某件礼物的星星价格(家长)
  window.giftSetPrice = function (id, val) {
    var g = giftOf(id);
    if (!g) return;
    var v = parseInt(val, 10);
    if (!(v >= 0)) { Speech.toast('价格需≥0'); return; }
    ensureGiftData();
    Store.state.giftPrices[id] = v;
    Store.saveState();
  };

  window.wishAdd = function () {
    var title = prompt('星愿名称（如：买乐高、去动物园）');
    if (!title) return;
    var cost = parseInt(prompt('需要多少星星？（如：50）'), 10);
    if (!cost || cost < 1) { Speech.toast('星星数需大于0'); return; }
    Store.state.wishes = (Store.state.wishes && typeof Store.state.wishes === 'object' && !Array.isArray(Store.state.wishes)) ? [] : (Store.state.wishes || []);
    Store.state.wishes.push({ title: title, cost: cost, created: Date.now() });
    Store.saveState();
    renderWish();
  };

  window.wishRedeem = function (i) {
    var wishes = (Store.state.wishes && Array.isArray(Store.state.wishes)) ? Store.state.wishes : [];
    var w = wishes[i];
    if (!w) return;
    if ((Store.state.stars || 0) < w.cost) { Speech.toast('星星不足'); return; }
    window.requireParent(function () {
      Store.state.stars -= w.cost;
      Store.state.wishLog = Store.state.wishLog || [];
      Store.state.wishLog.push({ title: w.title, cost: w.cost, t: Date.now() });
      Store.state.wishes = (Store.state.wishes && Array.isArray(Store.state.wishes)) ? Store.state.wishes : [];
      Store.state.wishes.splice(i, 1);
      Store.saveState();
      Kids.renderStarBar();
      renderWish();
      Speech.toast('兑换成功！'+w.title);
    });
  };

  window.wishRemove = function (i) {
    window.requireParent(function(){
      Store.state.wishes = (Store.state.wishes && Array.isArray(Store.state.wishes)) ? Store.state.wishes : [];
      Store.state.wishes.splice(i, 1);
      Store.saveState();
      renderWish();
    });
  };

  window.wishRemoveP = function (i) {
    window.requireParent(function(){
      Store.state.wishLog = (Store.state.wishLog && Array.isArray(Store.state.wishLog)) ? Store.state.wishLog : [];
      Store.state.wishLog.splice(i, 1);
      Store.saveState();
      renderWish();
    });
  };

  window.Edu.Wish = {
    GIFT_CATALOG: GIFT_CATALOG,
    DEFAULT_PRICES: DEFAULT_PRICES,
    renderWish: renderWish,
    giftOf: giftOf,
    giftPriceOf: giftPriceOf,
    giftCount: giftCount,
    giftRedeem: window.giftRedeem,
    giftDetail: window.giftDetail,
    giftDetailByIdx: window.giftDetailByIdx,
    giftSetPrice: window.giftSetPrice,
    wishAdd: window.wishAdd,
    wishRedeem: window.wishRedeem,
    wishRemove: window.wishRemove,
    wishRemoveP: window.wishRemoveP
  };
})();
