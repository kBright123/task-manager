// 全局共享常量与工具(时间轴渲染/分类色板), 页面内联脚本依赖本文件先加载
window.KB_CAT_COLORS = { '工作': 'var(--primary)', '个人': 'var(--success)', '会议': 'var(--meeting)', '培训': 'var(--training)', '考试': 'var(--exam)' };
window.KB_TL_ORDER = ['past', 'past_month', 'past_week', 'today', 'tomorrow', 'future_week', 'future_month', 'later'];
window.KB_TL_FUTURE = ['tomorrow', 'future_week', 'future_month', 'later'];
window.KB_TL_PAST = ['past_week', 'past_month', 'past'];

// ============ 教育·孩子资料(生日/性别/多个孩子/活跃孩子) ============
// 数据存 localStorage, 供 教育乐园 与 个人信息 两页共享;
// 年龄段映射: 5岁+ -> 幼小衔接工作台; 3-4岁 -> 宝贝启蒙乐园; 0-2岁 -> 低幼启蒙
window.eduKids = (function () {
  var KEY = 'edu_kids_v1';
  function load() {
    var raw = null;
    try { raw = JSON.parse(localStorage.getItem(KEY)); } catch (e) { raw = null; }
    if (!raw || !Array.isArray(raw.list)) raw = { list: [], activeId: null };
    return raw;
  }
  function save(d) { try { localStorage.setItem(KEY, JSON.stringify(d)); } catch (e) {} }
  // 孩子档案改动后，异步同步到后端数据库(本地仍为缓存/离线可用)
  function kick() {
    if (window.eduSync) window.eduSync.pushKids();
  }
  function ageOf(birthYear) {
    var y = new Date().getFullYear();
    return Math.max(0, (y - birthYear));
  }
  function tierOf(age) {
    if (age >= 5) return 'workbench';
    if (age >= 3) return 'paradise';
    return 'paradise_lite';
  }
  function tierLabel(tier) {
    return { workbench: '幼小衔接(5-6岁)', paradise: '启蒙乐园(3-4岁)', paradise_lite: '低幼启蒙(0-2岁)' }[tier] || '';
  }
  function all() { return load().list; }
  function active() {
    var d = load();
    var idx = -1;
    for (var i = 0; i < d.list.length; i++) { if (d.list[i].id === d.activeId) { idx = i; break; } }
    return idx >= 0 ? d.list[idx] : (d.list[0] || null);
  }
  function byId(id) {
    return load().list.filter(function (k) { return k.id === id; })[0] || null;
  }
  function add(kid) {
    var d = load();
    kid.id = kid.id || ('k' + Date.now() + '-' + Math.floor(Math.random() * 10000));
    d.list.push(kid);
    if (!d.activeId) d.activeId = kid.id;
    save(d);
    kick();
    return kid;
  }
  // 直接加入一个孩子(用于后端 hydration, 不触发二次同步)
  function addLocal(kid) {
    var d = load();
    if (d.list.some(function (k) { return k.id === kid.id; })) { save(d); return kid; }
    d.list.push(kid);
    if (!d.activeId) d.activeId = kid.id;
    save(d);
    return kid;
  }
  function update(kid) {
    var d = load();
    d.list = d.list.map(function (k) { return k.id === kid.id ? kid : k; });
    save(d);
    if (window.eduSync && kid.dbId) window.eduSync.pushKids();
    return kid;
  }
  function remove(id) {
    var d = load();
    var target = d.list.filter(function (k) { return k.id === id; })[0];
    d.list = d.list.filter(function (k) { return k.id !== id; });
    if (d.activeId === id) d.activeId = d.list.length ? d.list[0].id : null;
    save(d);
    if (window.eduSync && target && target.dbId) window.eduSync.deleteKid(target.dbId);
  }
  function setActive(id) { var d = load(); d.activeId = id; save(d); }
  function setDbId(id, dbId) {
    var d = load();
    d.list = d.list.map(function (k) { return k.id === id ? (function (o){ o.dbId = dbId; return o; })(k) : k; });
    save(d);
  }
  function hasAny() { return load().list.length > 0; }
  function genderLabel(g) { return g === 'male' ? '男孩' : (g === 'female' ? '女孩' : '未设置'); }
  function genderIcon(g) { return g === 'male' ? '👦' : (g === 'female' ? '👧' : '🧒'); }
  return {
    KEY: KEY, load: load, save: save, all: all, list: all, active: active, byId: byId,
    add: add, addLocal: addLocal, update: update, remove: remove,
    setActive: setActive, setDbId: setDbId, hasAny: hasAny,
    ageOf: ageOf, tierOf: tierOf, tierLabel: tierLabel,
    genderLabel: genderLabel, genderIcon: genderIcon
  };
})();

// ============ 教育数据 <-> 后端数据库 双向同步桥 ============
// 教育模式使用独立后端数据库(edu.db)，本模块把 localStorage 缓存镜像到后端；
// 后端为权威来源，本地为缓存/离线兜底。未登录按匿名 ID 归属，已登录按账号归属。
window.eduSync = (function () {
  var pushTimer = null;
  function anonId() {
    var k = 'edu_anon_id';
    var v = null;
    try { v = localStorage.getItem(k); } catch (e) {}
    if (!v) {
      v = 'a' + Date.now() + '-' + Math.floor(Math.random() * 1000000);
      try { localStorage.setItem(k, v); } catch (e) {}
    }
    return v;
  }
  function api(method, url, body) {
    return fetch('/edu/api' + url, {
      method: method,
      headers: { 'Content-Type': 'application/json', 'X-Edu-Anon': anonId() },
      body: body ? JSON.stringify(body) : undefined
    }).then(function (r) { return r.json().catch(function () { return {}; }); })
      .catch(function () { return {}; });
  }
  function dbIdOf(kid) { return kid && kid.dbId ? kid.dbId : null; }
  // 由服务端档案生成/合并本地孩子记录: 保留本地 clientId(id), 字段以服务端为准
  function buildLocalKid(sk, lk) {
    return {
      id: lk ? lk.id : ('db' + sk.id),
      dbId: Number(sk.id),
      name: sk.name,
      birthYear: Number(sk.birthYear),
      gender: sk.gender || '',
      created: lk ? lk.created : Date.now()
    };
  }
  // 整体推送孩子档案并回填 dbId
  function pushKids() {
    var kids = window.eduKids.all();
    return api('POST', '/kids', {
      kids: kids.map(function (k, i) {
        return { dbId: dbIdOf(k), clientId: k.id, name: k.name, birthYear: k.birthYear, gender: k.gender };
      }),
      removedIds: []
    }).then(function (res) {
      if (res && res.ok && res.kids) {
        res.kids.forEach(function (sk) {
          var local = window.eduKids.all().filter(function (k) { return k.id === sk.clientId; })[0];
          if (local && !dbIdOf(local)) window.eduKids.setDbId(local.id, sk.id);
        });
      }
      return res;
    });
  }
  function pushKidsDebounced() {
    if (pushTimer) return;
    pushTimer = setTimeout(function () { pushTimer = null; pushKids(); }, 400);
  }
  function pushState(kidId, dkey, data) {
    // 空弹不推: 初始 Store.state 为 {} / 零值默认结构时不应覆盖后端已有数据(收养/归并流程的
    // 空推曾把两端已合并的星星清成 0), 有真实内容才同步。
    if (isEmptyBlob(data)) return;
    var kid = window.eduKids.byId(kidId);
    if (!kid) return;
    if (!dbIdOf(kid)) {
      pushKids().then(function () {
        var k2 = window.eduKids.byId(kidId);
        if (k2 && dbIdOf(k2)) api('POST', '/kids/' + dbIdOf(k2) + '/state', { dkey: dkey, data: data });
      });
      return;
    }
    api('POST', '/kids/' + dbIdOf(kid) + '/state', { dkey: dkey, data: data });
  }
  function deleteKid(dbId) {
    api('POST', '/kids/' + dbId + '/delete', {});
  }
  // 页面注册的回调：把后端的某孩子某一类数据回填到本地缓存
  var onState = null;
  function setOnState(fn){ onState = fn; }

  // ---- 题库(qbank): 拉取待巩固题 / 批量入库 / 记录作答反馈 ----
  function qbankPull(p) {
    return api('POST', '/qbank/pull', p || {});
  }
  function qbankEnsure(p) {
    return api('POST', '/qbank/ensure', p || {});
  }
  function qbankLearn(p) {
    return api('POST', '/qbank/learn', p || {});
  }
  // 与后端 _merge_blob 同一套保守归并规则: stars 求和, 数组按 JSON 去重并集,
  // 对象键合并(先到先得), maxCombo/submits 取较大, usage 求和, settings 以已存端为准
  function mergeBlob(base, ext) {
    base = base && typeof base === 'object' && !Array.isArray(base) ? JSON.parse(JSON.stringify(base)) : {};
    if (!ext || typeof ext !== 'object' || Array.isArray(ext)) return base;
    try { base.stars = (Number(base.stars) || 0) + (Number(ext.stars) || 0); } catch (e) {}
    ['records', 'wrong', 'wishLog', 'redeemed', 'starLog', 'wishes'].forEach(function (key) {
      var e = ext[key];
      if (!Array.isArray(e)) return;
      var b = Array.isArray(base[key]) ? base[key] : (base[key] = []);
      var seen = {};
      b.forEach(function (it) { try { seen[JSON.stringify(it)] = 1; } catch (e2) {} });
      e.forEach(function (it) {
        var h;
        try { h = JSON.stringify(it); } catch (e3) { h = null; }
        if (h && !seen[h]) { seen[h] = 1; b.push(it); }
      });
    });
    ['badges', 'adv', 'level', 'dailySecs', 'giftPrices'].forEach(function (key) {
      var e = ext[key];
      if (!e || typeof e !== 'object' || Array.isArray(e)) return;
      var b = base[key];
      if (!b || typeof b !== 'object' || Array.isArray(b)) b = base[key] = {};
      for (var k in e) { if (b[k] === undefined) b[k] = e[k]; }
    });
    ['maxCombo', 'submits'].forEach(function (key) {
      base[key] = Math.max(Number(base[key]) || 0, Number(ext[key]) || 0);
    });
    var bu = base.usage, eu = ext.usage;
    if (eu && typeof eu === 'object' && bu && typeof bu === 'object') {
      ['secs', 'n', 'count'].forEach(function (k) {
        bu[k] = (Number(bu[k]) || 0) + (Number(eu[k]) || 0);
      });
    }
    return base;
  }
  function readBlob(key) {
    try { var v = JSON.parse(localStorage.getItem(key)); return v && typeof v === 'object' ? v : {}; } catch (e) { return {}; }
  }
  function writeBlob(key, v) {
    try { localStorage.setItem(key, JSON.stringify(v)); } catch (e) {}
  }
  // 判定 blob 是否「空/默认值」: 只含 0/空数组/空对象/空串 等脚手架值时视为空,
  // 避免把归并时生成的零值默认结构(如 {stars:0,maxCombo:0,submits:0})误当成有效数据上传覆盖后端。
  function isEmptyBlob(v) {
    if (!v || typeof v !== 'object') return true;
    if (Array.isArray(v)) return v.length === 0;
    var keys = Object.keys(v);
    if (!keys.length) return true;
    for (var i = 0; i < keys.length; i++) {
      var val = v[keys[i]];
      if (val === undefined || val === null) continue;
      if (Array.isArray(val)) { if (val.length) return false; continue; }
      if (typeof val === 'object') { if (!isEmptyBlob(val)) return false; continue; }
      if (val !== 0 && val !== '' && val !== false) return false;
    }
    return true;
  }
  // 启动时从后端恢复：孩子档案若无本地则用后端；本地孩子回填 dbId。
  function hydrate() {
    return api('POST', '/bootstrap').then(function (res) {
      if (!res || !res.ok) return { ok: false };
      var serverKids = res.kids || [];
      var local = window.eduKids.all();
      // 若后端做了「匿名→账号」归并, 返回了 dbIdMap: 把本地 dbId 从匿名档案纠正到账号档案,
      // 避免 stale dbId 在 next push 时被当作新宝贝重建出重复。
      var remap = res.dbIdMap || {};
      var remapKeys = Object.keys(remap);
      if (remapKeys.length) {
        var d = window.eduKids.load();
        d.list = d.list.map(function (k) {
          if (k.dbId && remap[String(k.dbId)]) k.dbId = Number(remap[String(k.dbId)]);
          return k;
        });
        window.eduKids.save(d);
        local = window.eduKids.all();
      }
      // 后端可能把同名宝贝合并成同一服务端档案(多端/多次收养后 dbId 相同):
      // 本地残留的重复宝贝在此收敛, 只保留一个, 并把被删宝贝未同步的本地数据弹
      // 按后端规则并入保留档案, 保证界面上同账号下不再出现同名残留。
      var store = window.Edu && window.Edu.Store;
      var dups = [];
      var seenDbId = {};
      (local || []).forEach(function (k) {
        var did = dbIdOf(k);
        if (!did) return;
        if (seenDbId[did]) { dups.push(k); } else { seenDbId[did] = 1; }
      });
      if (dups.length && store) {
        var dx = window.eduKids.load();
        var gone = {};
        dups.forEach(function (k) { gone[k.id] = 1; });
        var survivors = {};
        dx.list.forEach(function (k) {
          if (!gone[k.id] && dbIdOf(k) && !survivors[dbIdOf(k)]) survivors[dbIdOf(k)] = k.id;
        });
        dups.forEach(function (k) {
          var sid = survivors[k.dbId];
          if (sid == null) return;
          var st = store.stateKeyFor(sid);
          var sb = mergeBlob(readBlob(st), readBlob(store.stateKeyFor(k.id)));
          if (!isEmptyBlob(sb)) writeBlob(st, sb);
          var wt = store.wbKeyFor(sid);
          var wb2 = mergeBlob(readBlob(wt), readBlob(store.wbKeyFor(k.id)));
          if (!isEmptyBlob(wb2)) writeBlob(wt, wb2);
          try { localStorage.removeItem(store.stateKeyFor(k.id)); } catch (e) {}
          try { localStorage.removeItem(store.wbKeyFor(k.id)); } catch (e) {}
        });
        dx.list = dx.list.filter(function (k) { return !gone[k.id]; });
        window.eduKids.save(dx);
        local = window.eduKids.all();
      }
      // ---- 以服务端为权威同步孩子档案: 登录后以服务器为准下载, 本地没有的再传上去 ----
      // 用 (dbId 优先, 否则 name+year+gender 匹配) 把服务端孩子覆盖/合并进本地,
      // 只保留服务端仍存在的孩子(服务端删除后, 其它设备本地不应再显示), 并回填 dbId。
      var serverMap = {};
      serverKids.forEach(function (sk) {
        serverMap[Number(sk.id)] = sk;
      });
      var finalList = [];
      var serverSeen = {};
      local.forEach(function (lk) {
        var sk = null;
        var m = Number(dbIdOf(lk));
        if (m && m in serverMap) sk = serverMap[m];
        else {
          for (var s in serverMap) {
            if (serverSeen[s]) continue;
            var c = serverMap[s];
            if (c.name === lk.name && Number(c.birthYear) === Number(lk.birthYear) && c.gender === lk.gender) { sk = c; break; }
          }
        }
        if (sk) { serverSeen[sk.id] = 1; finalList.push(buildLocalKid(sk, lk)); }
        else if (!dbIdOf(lk)) { finalList.push(lk); }  // 本地未同步孩子: 保留, 稍后上传到服务端
      });
      serverKids.forEach(function (sk) {
        if (serverSeen[sk.id]) return;
        finalList.push(buildLocalKid(sk, null));
      });
      var d0 = window.eduKids.load();
      var prevIds = {};
      (local || []).forEach(function (k) { prevIds[k.id] = 1; });
      var goneList = [];
      d0.list = finalList;
      finalList.forEach(function (k) {
        if (prevIds[k.id]) delete prevIds[k.id];
      });
      Object.keys(prevIds).forEach(function (oldId) { goneList.push(oldId); });
      window.eduKids.save(d0);
      local = window.eduKids.all();
      // 服务端已删除/已被归并的孩子: 清掉本地残留的学习数据, 避免旧宝贝幽灵数据复活
      if (store) {
        goneList.forEach(function (oldId) {
          try { localStorage.removeItem(store.stateKeyFor(oldId)); } catch (e) {}
          try { localStorage.removeItem(store.wbKeyFor(oldId)); } catch (e) {}
        });
      }
      // hydration 成功后统一做一次 profile 回推: 保证本设备回填的 dbId 及排序
      // 与(可能残留在本设备但服务端已删)清理结果同步上去, 避免下次被当作新宝贝重建;
      // 上传后把服务端返回的 dbId 回填到本地未同步的孩子, 完成首次建档。
      pushKids().then(function (res) {
        if (res && res.ok && res.kids) {
          var dl = window.eduKids.load();
          res.kids.forEach(function (sk) {
            var lm = dl.list.filter(function (k) { return k.id === sk.clientId && !dbIdOf(k); })[0];
            if (lm) lm.dbId = Number(sk.id);
          });
          window.eduKids.save(dl);
        }
      });
      // 跨设备档案以服务端为权威: 名字/生日/性别已在上面 buildLocalKid 时以服务端为准合并,
      // 这里仅标志是否发生过合并, 供上层触发重绘。
      var reconciled = false;
      (local || []).forEach(function (lk) {
        serverKids.forEach(function (sk) {
          if (Number(dbIdOf(lk)) !== Number(sk.id)) return;
          if (lk.name !== sk.name || Number(lk.birthYear) !== Number(sk.birthYear) || lk.gender !== sk.gender) reconciled = true;
        });
      });
      // 回填每个孩子的学习数据: 服务端有数据则以服务端为权威直接下载,
      // 服务端没有而本地有则上传补全
      local.forEach(function (k) {
        if (!dbIdOf(k)) return;
        ['state', 'workbench'].forEach(function (dkey) {
          api('GET', '/kids/' + dbIdOf(k) + '/state?dkey=' + dkey).then(function (s) {
            if (!s || !s.ok) return;
            var key = (dkey === 'workbench') ? store.wbKeyFor(k.id) : store.stateKeyFor(k.id);
            var localBlob = readBlob(key);
            var hasServer = s.data && typeof s.data === 'object' && Object.keys(s.data).length;
            if (hasServer) {
              // 以服务端为权威: 无条件下载覆盖本地(force)
              if (onState) onState(k.id, dkey, s.data, true);
            } else if (!isEmptyBlob(localBlob)) {
              // 服务端没有该孩子数据而本地有(真实)数据: 上传本地数据(本地向服务端补全)
              pushState(k.id, dkey, localBlob);
            }
          });
        });
      });
      return { ok: true, reconciled: reconciled };
    });
  }
  return {
    anonId: anonId, api: api, pushKids: pushKids, pushKidsDebounced: pushKidsDebounced,
    pushState: pushState, deleteKid: deleteKid, hydrate: hydrate, setOnState: setOnState,
    qbankPull: qbankPull, qbankEnsure: qbankEnsure, qbankLearn: qbankLearn
  };
})();

// ============ 工作 / 教育娱乐 双模式悬浮球 ============
// base.html 的 .mode-ball 调用本项目全局函数:
// 教育页(/edu/) -> 工作模式(/); 其他页 -> 教育娱乐模式(/edu/)
window.toggleEduMode = function () {
  var path = window.location.pathname.replace(/\/+$/, '');
  var target = (path === '/edu') ? '/' : '/edu/';
  try { localStorage.setItem('edu_mode', target === '/edu/' ? 'edu' : 'work'); } catch (e) {}
  window.location.href = target;
};
