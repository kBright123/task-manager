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
  function add(kid) {
    var d = load();
    kid.id = kid.id || ('k' + Date.now() + '-' + Math.floor(Math.random() * 10000));
    d.list.push(kid);
    if (!d.activeId) d.activeId = kid.id;
    save(d);
    return kid;
  }
  function update(kid) {
    var d = load();
    d.list = d.list.map(function (k) { return k.id === kid.id ? kid : k; });
    save(d);
    return kid;
  }
  function remove(id) {
    var d = load();
    d.list = d.list.filter(function (k) { return k.id !== id; });
    if (d.activeId === id) d.activeId = d.list.length ? d.list[0].id : null;
    save(d);
  }
  function setActive(id) { var d = load(); d.activeId = id; save(d); }
  function hasAny() { return load().list.length > 0; }
  function genderLabel(g) { return g === 'male' ? '男孩' : (g === 'female' ? '女孩' : '未设置'); }
  function genderIcon(g) { return g === 'male' ? '👦' : (g === 'female' ? '👧' : '🧒'); }
  return {
    KEY: KEY, load: load, save: save, all: all, active: active,
    add: add, update: update, remove: remove, setActive: setActive, hasAny: hasAny,
    ageOf: ageOf, tierOf: tierOf, tierLabel: tierLabel,
    genderLabel: genderLabel, genderIcon: genderIcon
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
