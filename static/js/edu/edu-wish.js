(function () {
  'use strict';
  var Store = window.Edu.Store;
  var Speech = window.Edu.Speech;
  var Kids = window.Edu.Kids;

  // 兑换区分区: 每个专区(e.g. 武器区/奥特曼区)互斥折叠, 选中的才展示
  var GIFT_SECTIONS = [
    { id: 'weapon', icon: '🗡️', title: '武器专区', intro: '武器宝库的收藏，喜欢就兑换，可重复收集!' },
    { id: 'ultra', icon: '🦸', title: '奥特曼专区', intro: '稀有的奥特曼英雄，每位只能兑换一次，独一无二!' }
  ];
  function sectionOf(id) { for (var i = 0; i < GIFT_SECTIONS.length; i++) if (GIFT_SECTIONS[i].id === id) return GIFT_SECTIONS[i]; return null; }

  // 礼物目录: sec 归属专区, unique 表示该礼物不可重复拥有(奥特曼)
  // voice: 详情自动朗读的名称/口播; slogan: 专属口号(朗读时附带)
  var GIFT_CATALOG = [
    // ===== 武器专区(可重复收集) =====
    { id: 'feidao', sec: 'weapon', emoji: '🗡️', name: '飞刀', price: 15, desc: '例无虚发的飞刀，又快又准！', voice: '飞刀' },
    { id: 'dao', sec: 'weapon', emoji: '🔪', name: '宝刀', price: 25, desc: '削铁如泥的宝刀，挥舞起来呼呼作响！', voice: '宝刀' },
    { id: 'dun', sec: 'weapon', emoji: '🛡️', name: '神盾', price: 30, desc: '坚固无比的神盾，守护你不受伤害！', voice: '神盾' },
    { id: 'gong', sec: 'weapon', emoji: '🏹', name: '长弓', price: 40, desc: '百步穿杨的长弓，射出一支神箭！', voice: '长弓' },
    { id: 'jian', sec: 'weapon', emoji: '⚔️', name: '宝剑', price: 40, desc: '寒光闪闪的宝剑，勇士的最爱！', voice: '宝剑' },
    { id: 'qiang', sec: 'weapon', emoji: '🔫', name: '亮枪', price: 45, desc: '一击必中的亮枪，火力十足！', voice: '亮枪' },
    { id: 'car', sec: 'weapon', emoji: '🏎️', name: '炫酷跑车', price: 50, desc: '风驰电掣的炫酷跑车，出发兜风吧！', voice: '炫酷跑车' },
    { id: 'cannon', sec: 'weapon', emoji: '💣', name: '大炮', price: 55, desc: '威力无穷的大炮，轰出一发炮火！', voice: '大炮' },
    { id: 'tank', sec: 'weapon', emoji: '💥', name: '坦克', price: 60, desc: '火力全开的坦克，铁甲护体所向披靡！', voice: '坦克' },
    { id: 'armor', sec: 'weapon', emoji: '🚗', name: '装甲战车', price: 65, desc: '铁甲护体的装甲战车，开进战场如履平地！', voice: '装甲战车' },
    { id: 'heli', sec: 'weapon', emoji: '🚁', name: '武装直升机', price: 75, desc: '展翅高飞的武装直升机，盘旋空中守护大地！', voice: '武装直升机' },
    { id: 'plane', sec: 'weapon', emoji: '✈️', name: '战斗机', price: 80, desc: '制霸天空的战斗机，呼啸着冲上云霄！', voice: '战斗机' },
    { id: 'ship', sec: 'weapon', emoji: '🚢', name: '航空母舰', price: 90, desc: '巡游四海的航空母舰，海上编队的指挥舰！', voice: '航空母舰' },
    { id: 'mech', sec: 'weapon', emoji: '🤖', name: '机甲英雄', price: 100, desc: '勇敢无畏的机甲英雄，拯救世界的超级卫士！', voice: '机甲英雄', slogan: '机甲英雄，出击！' },
    // ===== 奥特曼专区(独一无二, 不可重复) =====
    { id: 'diga', sec: 'ultra', unique: true, emoji: '🦸', name: '迪迦奥特曼', price: 180, desc: '光的继承者，把希望带给人类，化作光芒冲向未来！', voice: '迪迦奥特曼', slogan: '化作光，飞向未来！' },
    { id: 'zero', sec: 'ultra', unique: true, emoji: '🦸', name: '赛罗奥特曼', price: 170, desc: '正义的首席詹奈纳，武器大师，速度与力量并存的战士！', voice: '赛罗奥特曼', slogan: '拯救，不靠蛮力，靠这颗炽热的心！' },
    { id: 'zeta', sec: 'ultra', unique: true, emoji: '🦸', name: '泽塔奥特曼', price: 160, desc: '相信伙伴的年轻战士，把勇气化作光芒！', voice: '泽塔奥特曼', slogan: '奥特曼不是无所不能的，但它会拼尽全力！' },
    { id: 'triga', sec: 'ultra', unique: true, emoji: '🦸', name: '特利迦奥特曼', price: 160, desc: '三千年前的光之勇者，用笑容守护未来！', voice: '特利迦奥特曼', slogan: '笑容，就是力量！' },
    { id: 'taro', sec: 'ultra', unique: true, emoji: '🦸', name: '泰罗奥特曼', price: 150, desc: '勇猛的 V 字战士，拥有压倒性的力量！', voice: '泰罗奥特曼', slogan: '泰罗奥特曼，出击！' },
    { id: 'mebius', sec: 'ultra', unique: true, emoji: '🦸', name: '梦比优斯奥特曼', price: 130, desc: '年轻的守护者，相信大家的心连在一起的力量！', voice: '梦比优斯奥特曼', slogan: '我一直相信，爱能拯救宇宙！' },
    { id: 'dyna', sec: 'ultra', unique: true, emoji: '🦸', name: '戴拿奥特曼', price: 140, desc: '来自未来的战士，在无垠宇宙中自由飞翔！', voice: '戴拿奥特曼', slogan: '感受宇宙的力量吧！' },
    { id: 'gaia', sec: 'ultra', unique: true, emoji: '🦸', name: '盖亚奥特曼', price: 130, desc: '大地之子，与地球的意志同在，守护我们成长的大地！', voice: '盖亚奥特曼', slogan: '大地的力量，与我同在！' },
    { id: 'orb', sec: 'ultra', unique: true, emoji: '🦸', name: '欧布奥特曼', price: 150, desc: '融合了两个光之力量的全新勇者！', voice: '欧布奥特曼', slogan: '燃烧吧，圣光！' },
    { id: 'geed', sec: 'ultra', unique: true, emoji: '🦸', name: '捷德奥特曼', price: 140, desc: '背负命运的少年战士，守护自己的信念！', voice: '捷德奥特曼', slogan: '我只相信，我能守护的东西！' }
  ];
  var DEFAULT_PRICES = {};
  GIFT_CATALOG.forEach(function (g) { DEFAULT_PRICES[g.id] = g.price; });

  function esc(s) { return String(s === undefined || s === null ? '' : s).replace(/</g, '&lt;').replace(/&/g, '&amp;'); }
  function imgOf(id) {
    var g = giftOf(id);
    return (g && g.sec === 'ultra') ? '/static/edu/ultra/' + id + '.svg' : '/static/edu/weapons/' + id + '.svg';
  }
  function isImageGift(id) { return !!giftOf(id); }
  function giftIcon(id) {
    return isImageGift(id)
      ? '<img class="gift-emoji" src="' + imgOf(id) + '" alt="" draggable="false">'
      : '<div class="gift-emoji">' + ((giftOf(id) || {}).emoji || '🎁') + '</div>';
  }
  function giftOf(id) {
    for (var i = 0; i < GIFT_CATALOG.length; i++) if (GIFT_CATALOG[i].id === id) return GIFT_CATALOG[i];
    return null;
  }
  // 补全缺失的礼物数据（旧宝贝可能没有 redeemed/wishes），价格一律使用默认定价
  function ensureGiftData() {
    Store.state.redeemed = (Store.state.redeemed && Array.isArray(Store.state.redeemed)) ? Store.state.redeemed : [];
    Store.state.wishes = (Store.state.wishes && typeof Store.state.wishes === 'object' && !Array.isArray(Store.state.wishes)) ? [] : (Store.state.wishes || []);
  }
  function giftPriceOf(id) {
    var p = DEFAULT_PRICES[id];
    return (typeof p === 'number' && p >= 0) ? p : 20;
  }
  // 卖出返还: 比购入价少 5 颗星星(最低 0), 避免「买进卖出」零成本刷星
  function sellRefundOf(r) {
    var price = (r && typeof r.price === 'number' && r.price >= 0) ? r.price : giftPriceOf(r && r.id);
    return Math.max(0, price - 5);
  }
  function redeemedAll() {
    return (Store.state.redeemed && Array.isArray(Store.state.redeemed)) ? Store.state.redeemed : [];
  }
  function giftCount(id) {
    var c = 0, red = redeemedAll();
    for (var i = 0; i < red.length; i++) if (red[i] && red[i].id === id) c++;
    return c;
  }
  // 当前选中的专区(互斥折叠)
  function curTab() {
    return (Store.state && Store.state.giftTab === 'ultra') ? 'ultra' : 'weapon';
  }
  window.giftTab = function (sec) {
    Store.state.giftTab = (sec === 'ultra') ? 'ultra' : 'weapon';
    Store.saveState();
    renderWish();
  };
  

  function renderWish() {
    var body = document.getElementById('eduWishBody');
    if (!body) return;
    renderWelcomeInto('wishWelcome', '攒星星，兑换你想要的小心愿');
    ensureGiftData();
    var wishes = Store.state.wishes || [];
    var stars = Store.state.stars || 0;
    var tab = curTab();
    var html = '<div class="wish-summary" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;padding:12px;background:linear-gradient(135deg,#fff3d6,#ffe1ae);border-radius:12px;border:1.5px solid #ffd9a8;">'+
      '<div style="display:flex;gap:8px;">'+
      '<button type="button" class="btn-soft" onclick="window.wishAdd()">+ 新增星愿</button>'+
      '<button type="button" class="btn-soft" onclick="window.parentAddStars()">👑 家长加星</button>'+
      '</div>'+
      '</div>';

    // ---- 互斥专区 Tab(武器区 / 奥特曼区): 选中的展开, 另一个自动折叠 ----
    html += '<div class="gift-tabs" role="tablist">' + GIFT_SECTIONS.map(function (s) {
      var on = s.id === tab;
      return '<button type="button" class="gift-tab' + (on ? ' on' : '') + '" onclick="window.giftTab(\'' + s.id + '\')">' +
        s.icon + ' ' + esc(s.title) + '</button>';
    }).join('') + '</div>';

    // ---- 当前专区的兑换区(已兑换并入同区, 按区折叠展示) ----
    html += renderGiftSection(tab, stars);

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

  // 渲染一个专区的完整内容: 兑换卡片(卖出/兑换在卡片上直接操作)
  function renderGiftSection(sec, stars) {
    var secMeta = sectionOf(sec) || GIFT_SECTIONS[0];
    var html = '<div class="gift-section">' +
      '<h3 class="gift-title">' + secMeta.icon + ' 兑换区 · ' + esc(secMeta.title) + '</h3>' +
      '<div class="gift-intro">' + esc(secMeta.intro) + '</div>' +
      '<div class="gift-grid">';
    GIFT_CATALOG.filter(function (g) { return g.sec === sec; }).forEach(function (g) {
      html += giftCardHtml(g, stars);
    });
    html += '</div></div>';
    return html;
  }

  function giftCardHtml(g, stars) {
    var price = giftPriceOf(g.id);
    var can = stars >= price;
    var cnt = giftCount(g.id);
    var owned = cnt > 0;
    var badge = '';
    if (owned) badge = g.unique
      ? '<span class="gift-owned">已拥有</span>'
      : '<span class="gift-count">×' + cnt + '</span>';
    var actions;
    if (g.unique) {
      if (owned) {
        actions = '<button type="button" class="gift-sell" onclick="event.stopPropagation();window.giftSellOf(\'' + g.id + '\')">卖出 ' + sellRefundOf({ id: g.id, price: price }) + '⭐</button>';
      } else {
        actions = '<button type="button" class="gift-buy" ' + (can ? '' : 'disabled') + ' onclick="event.stopPropagation();window.giftRedeem(\'' + g.id + '\')">兑换</button>';
      }
    } else {
      actions = '<button type="button" class="gift-buy" ' + (can ? '' : 'disabled') + ' onclick="event.stopPropagation();window.giftRedeem(\'' + g.id + '\')">兑换</button>' +
        (owned ? '<button type="button" class="gift-sell" onclick="event.stopPropagation();window.giftSellOf(\'' + g.id + '\')">卖出 ' + sellRefundOf({ id: g.id, price: price }) + '⭐</button>' : '');
    }
    return '<div class="gift-card' + (can ? '' : ' off') + '" onclick="window.giftOpen(\'' + g.id + '\')">' +
      badge +
      '<img class="gift-emoji" src="' + imgOf(g.id) + '" alt="' + esc(g.name) + '" draggable="false">' +
      '<div class="gift-info">' +
      '<span class="gift-name">' + esc(g.name) + '</span>' +
      '<span class="gift-price">' + price + ' ⭐</span>' +
      '</div>' +
      '<div class="gift-actions">' + actions + '</div>' +
      '</div>';
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

  // 兑换礼物（二次确认后，家长验证后扣星入已兑换）; 奥特曼不可重复
  window.giftRedeem = function (id) {
    var g = giftOf(id);
    if (!g) { Speech.toast('没有这件礼物'); return; }
    if (g.unique && giftCount(id) > 0) { Speech.toast(g.name + ' 已拥有，不能重复兑换'); return; }
    var price = giftPriceOf(id);
    if ((Store.state.stars || 0) < price) { Speech.toast('星星不足'); return; }
    giftConfirmTarget = { id: id, price: price };
    var t = document.getElementById('gcTitle');
    var s = document.getElementById('gcSub');
    if (t) t.textContent = '确认兑换 ' + g.name;
    if (s) s.textContent = '将花费 ' + price + ' 颗星星，确定吗？';
    var m = document.getElementById('eduMaskGiftConfirm');
    if (m) m.style.display = 'flex';
  };
  var giftConfirmTarget = null;
  window.giftConfirmOk = function () {
    var m = document.getElementById('eduMaskGiftConfirm');
    if (m) m.style.display = 'none';
    var t = giftConfirmTarget;
    giftConfirmTarget = null;
    if (!t) return;
    var g = giftOf(t.id);
    if (!g) return;
    window.requireParent(function () {
      if (Store.awardStars) Store.awardStars(-t.price, '兑换·' + g.name);
      else Store.state.stars -= t.price;
      Store.state.redeemed = (Store.state.redeemed && Array.isArray(Store.state.redeemed)) ? Store.state.redeemed : [];
      Store.state.redeemed.push({ id: g.id, name: g.name, emoji: g.emoji, price: t.price, t: Date.now(), date: fmtDate(new Date()) });
      Store.saveState();
      Kids.renderStarBar();
      renderWish();
      Speech.toast('兑换成功！获得 ' + g.name + ' 💫');
    });
  };
  window.giftConfirmCancel = function () {
    var m = document.getElementById('eduMaskGiftConfirm');
    if (m) m.style.display = 'none';
    giftConfirmTarget = null;
  };

  // 家长手动加星（需备注）
  window.parentAddStars = function () {
    var m = document.getElementById('eduMaskParentAddStars');
    if (!m) return;
    var starsInput = document.getElementById('pasStars');
    var noteInput = document.getElementById('pasNote');
    if (starsInput) starsInput.value = '10';
    if (noteInput) noteInput.value = '';
    m.style.display = 'flex';
    setTimeout(function () { if (noteInput) noteInput.focus(); }, 100);
  };
  window.parentAddStarsCancel = function () {
    var m = document.getElementById('eduMaskParentAddStars');
    if (m) m.style.display = 'none';
  };
  window.parentAddStarsConfirm = function () {
    var starsInput = document.getElementById('pasStars');
    var noteInput = document.getElementById('pasNote');
    var stars = starsInput ? parseInt(starsInput.value, 10) : 0;
    var note = noteInput ? noteInput.value.trim() : '';
    if (!stars || stars < 1) { Speech.toast('请输入有效的星星数'); return; }
    if (!note) { Speech.toast('请填写备注说明'); if (noteInput) noteInput.focus(); return; }
    window.requireParent(function () {
      if (Store.awardStars) Store.awardStars(stars, '家长加星·' + note);
      else Store.state.stars = (Store.state.stars || 0) + stars;
      Store.saveState();
      Kids.renderStarBar();
      renderWish();
      Speech.toast('家长加星成功：+' + stars + ' ⭐');
      parentAddStarsCancel();
    });
  };

  function fmtDate(d) {
    return (d.getFullYear()) + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  // 打开礼物细节弹窗, 自动朗读名称与专属口号
  function openGiftDetail(g, extra) {
    var title = document.getElementById('detailTitle');
    var sub = document.getElementById('detailSub');
    var body = document.getElementById('detailBody');
    var price = giftPriceOf(g.id);
    if (title) title.textContent = '🎁 ' + g.name;
    if (sub) sub.textContent = extra || ('需要 ' + price + ' 颗星星兑换');
    var cnt = giftCount(g.id);
    var secName = sectionOf(g.sec) ? sectionOf(g.sec).title : '';
    var sloganHtml = '';
    if (g.slogan) {
      var replay = (window.Edu.Speech && window.Edu.Speech.spkBtn) ? window.Edu.Speech.spkBtn(g.slogan) : '';
      sloganHtml = '<div class="gdetail-slogan">「' + esc(g.slogan) + '」' + replay + '</div>';
    }
    if (body) body.innerHTML =
      '<div class="gift-detail">' +
      (isImageGift(g.id)
        ? '<img class="gdetail-emoji" src="' + imgOf(g.id) + '" alt="' + esc(g.name) + '" draggable="false">'
        : '<div class="gdetail-emoji">' + (g.emoji || '🎁') + '</div>') +
      '<div class="gdetail-name">' + esc(g.name) + '<span class="gdetail-sec">' + esc(secName) + '</span></div>' +
      '<div class="gdetail-desc">' + esc(g.desc) + '</div>' +
      sloganHtml +
      '<div class="gdetail-meta">价格 ' + price + ' ⭐' + (cnt ? ' · 已拥有 ' + cnt + (g.unique ? ' 位' : ' 个') : '') + '</div>' +
      '</div>';
    var mask = document.getElementById('eduMaskDetail');
    if (mask) mask.style.display = 'flex';
    speakGift(g);
  }
  function speakGift(g) {
    try {
      if (!g || !window.Edu.Speech || !window.Edu.Speech.playSpeak) return;
      window.Edu.Speech.playSpeak(g.voice || g.name);
      if (g.slogan) setTimeout(function () { window.Edu.Speech.playSpeak(g.slogan); }, 1600);
    } catch (e) {}
  }
  window.giftDetail = function (id) {
    var g = giftOf(id);
    if (!g) return;
    openGiftDetail(g);
  };
  // 卡片/图片点击查看
  window.giftOpen = window.giftDetail;
  window.giftDetailByIdx = function (i) {
    var red = redeemedAll();
    var r = red[i];
    if (!r) return;
    var g = giftOf(r.id) || { id: r.id, sec: 'weapon', emoji: r.emoji || '🎁', name: r.name || '礼物', desc: '已兑换的礼物' };
    openGiftDetail(g, r.name ? '已拥有' : '');
  };

  window.wishAdd = function () {
    var m = document.getElementById('eduMaskWishAdd');
    if (!m) return;
    var titleInput = document.getElementById('waTitle');
    var costInput = document.getElementById('waCost');
    if (titleInput) titleInput.value = '';
    if (costInput) costInput.value = '30';
    m.style.display = 'flex';
    setTimeout(function () { if (titleInput) titleInput.focus(); }, 100);
  };
  window.wishAddCancel = function () {
    var m = document.getElementById('eduMaskWishAdd');
    if (m) m.style.display = 'none';
  };
  window.wishAddConfirm = function () {
    var titleInput = document.getElementById('waTitle');
    var costInput = document.getElementById('waCost');
    var title = titleInput ? titleInput.value.trim() : '';
    var cost = costInput ? parseInt(costInput.value, 10) : 0;
    if (!title) { Speech.toast('请输入星愿名称'); if (titleInput) titleInput.focus(); return; }
    if (!cost || cost < 1) { Speech.toast('星星数需大于0'); return; }
    Store.state.wishes = (Store.state.wishes && typeof Store.state.wishes === 'object' && !Array.isArray(Store.state.wishes)) ? [] : (Store.state.wishes || []);
    Store.state.wishes.push({ title: title, cost: cost, created: Date.now() });
    Store.saveState();
    renderWish();
    wishAddCancel();
    Speech.toast('新星愿已添加：' + title + ' 💫');
  };

  window.wishRedeem = function (i) {
    var wishes = (Store.state.wishes && Array.isArray(Store.state.wishes)) ? Store.state.wishes : [];
    var w = wishes[i];
    if (!w) return;
    if ((Store.state.stars || 0) < w.cost) { Speech.toast('星星不足'); return; }
    window.requireParent(function () {
      if (Store.awardStars) Store.awardStars(-w.cost, '心愿达成·' + w.title);
      else Store.state.stars -= w.cost;
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

  // 卖出已兑换礼物: 按购入价减 5 星返还(防零成本刷星)
  window.giftSell = function (i) {
    var red = redeemedAll();
    var r = red[i];
    if (!r) return;
    var g = giftOf(r.id);
    var name = r.name || (g ? g.name : '礼物');
    var refund = sellRefundOf(r);
    window.requireParent(function () {
      if (Store.awardStars) Store.awardStars(refund, '卖出·' + name);
      else Store.state.stars = (Store.state.stars || 0) + refund;
      red.splice(i, 1);
      Store.saveState();
      Kids.renderStarBar();
      renderWish();
      Speech.toast('已卖出 ' + name + '，返还 ' + refund + ' 颗星星 💫');
    });
  };
  // 卡片上的卖出: 卖掉最近购入的一件该礼物
  window.giftSellOf = function (id) {
    var red = redeemedAll();
    for (var i = red.length - 1; i >= 0; i--) {
      if (red[i] && red[i].id === id) { window.giftSell(i); return; }
    }
    Speech.toast('没有可卖出的 ' + (giftOf(id) ? giftOf(id).name : '礼物'));
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
    GIFT_SECTIONS: GIFT_SECTIONS,
    GIFT_CATALOG: GIFT_CATALOG,
    DEFAULT_PRICES: DEFAULT_PRICES,
    renderWish: renderWish,
    giftOf: giftOf,
    giftPriceOf: giftPriceOf,
    sellRefundOf: sellRefundOf,
    giftCount: giftCount,
    giftRedeem: window.giftRedeem,
    giftConfirmOk: window.giftConfirmOk,
    giftConfirmCancel: window.giftConfirmCancel,
    giftSell: window.giftSell,
    giftSellOf: window.giftSellOf,
    giftOpen: window.giftOpen,
    giftDetail: window.giftDetail,
    giftDetailByIdx: window.giftDetailByIdx,
    giftTab: window.giftTab,
    wishAdd: window.wishAdd,
    wishAddCancel: window.wishAddCancel,
    wishAddConfirm: window.wishAddConfirm,
    wishRedeem: window.wishRedeem,
    wishRemove: window.wishRemove,
    wishRemoveP: window.wishRemoveP,
    parentAddStars: window.parentAddStars,
    parentAddStarsCancel: window.parentAddStarsCancel,
    parentAddStarsConfirm: window.parentAddStarsConfirm
  };
})();