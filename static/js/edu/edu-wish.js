(function () {
  'use strict';
  var Store = window.Edu.Store;
  var Speech = window.Edu.Speech;
  var Kids = window.Edu.Kids;

  function renderWish() {
    var body = document.getElementById('eduWishBody');
    if (!body) return;
    var wishes = Store.state.wishes || [];
    var stars = Store.state.stars || 0;
    var html = '<div class="wish-summary" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;padding:12px;background:linear-gradient(135deg,#fff3d6,#ffe1ae);border-radius:12px;border:1.5px solid #ffd9a8;">'+
      '<div>当前星星：<b style="font-size:1.2rem;color:#b7791f;">'+stars+'</b> ⭐</div>'+
      '<button type="button" class="btn-soft" onclick="window.wishAdd()">+ 新增星愿</button>'+
      '</div>';
    if (!wishes.length) {
      html += '<div style="text-align:center;padding:30px;color:var(--edu-muted);">暂无星愿，点击「新增星愿」添加心愿吧～</div>';
    } else {
      html += '<div class="wish-list">';
      wishes.forEach(function(w, i){
        var can = stars >= (w.cost || 10);
        html += '<div class="wish-item" style="display:flex;align-items:center;gap:12px;padding:12px;background:var(--edu-surface);border:1px solid var(--edu-border-2);border-radius:12px;margin-bottom:10px;">'+
          '<div style="flex:1;"><div style="font-weight:700;">'+w.title+'</div><div style="font-size:.85rem;color:var(--edu-muted);">价值 '+w.cost+' 颗星星</div></div>'+
          '<div style="display:flex;gap:8px;">'+
          '<button type="button" class="btn-soft '+(can?'':'')+'" '+(can?'':'disabled')+' onclick="window.wishRedeem('+i+')">兑换</button>'+
          '<button type="button" class="btn-ghost" onclick="window.wishRemove('+i+')">删除</button>'+
          '</div></div>';
      });
      html += '</div>';
    }
    body.innerHTML = html;
  }

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
    renderWish: renderWish,
    wishAdd: window.wishAdd,
    wishRedeem: window.wishRedeem,
    wishRemove: window.wishRemove,
    wishRemoveP: window.wishRemoveP
  };
})();