(function () {
  'use strict';
  var QUIZ_LEN = 10;
  var LS_BASE = 'edu_record_v1';
  var STR_BASE = 'edu_workbench_v1';
  var DEFAULT_SET = { range: 20, nocarry: false, dailyQ: 20, dailyMin: 0 };
  var state = { stars: 0, records: [], wrong: [], settings: {}, usage: {}, maxCombo: 0, badges: {}, submits: 0, wishes: [], wishLog: [] };
  var wb = {};

  function load(k){ try { return JSON.parse(localStorage.getItem(k)); } catch(e){ return null; } }
  function save(k, v){ try { localStorage.setItem(k, JSON.stringify(v)); } catch(e){} }
  function clone(o){ return JSON.parse(JSON.stringify(o)); }
  // 异步出题(拉题库/生成)期间的轻量加载态 + 竞态保护(快速切换学习项时丢弃过期结果)
  var quizSeq = 0;
  function showQuizFetching(id){
    var c = document.getElementById(id);
    if (!c) return;
    c.innerHTML = '<div class="quiz-fetching"><i></i><i></i><i></i> 正在出题…</div>';
  }
  // 学习记录按当前孩子隔离
  function kidSyncKey(){ var a = window.eduKids.active(); return a ? a.id : 'default'; }
  function stateKeyFor(kidId){ return LS_BASE + '_' + (kidId || kidSyncKey()); }
  function wbKeyFor(kidId){ return STR_BASE + '_' + (kidId || kidSyncKey()); }
  function stateKey(){ return stateKeyFor(); }
  function wbKey(){ return wbKeyFor(); }
  function loadAllState(){
    var raw = load(stateKey());
    state = raw || { stars: 0, records: [], wrong: [], settings: {}, usage: {}, maxCombo: 0, badges: {}, submits: 0, wishes: [], wishLog: [], level: {zh:3,math:3,en:3}, adv: {} };
    state.settings = mergeSet(state.settings);
    state.usage = state.usage || { date: '', n: 0, secs: 0 };
    state.badges = state.badges || {};
    state.level = state.level || { zh:3, math:3, en:3 };
    state.adv = state.adv || {};
    if (!Array.isArray(state.records)) state.records = [];
    if (!Array.isArray(state.wrong)) state.wrong = [];
    if (!Array.isArray(state.wishes)) state.wishes = [];
    if (!Array.isArray(state.wishLog)) state.wishLog = [];
    if (!state.maxCombo) state.maxCombo = 0;
    if (!state.submits) state.submits = 0;
    wb = load(wbKey()) || {};
  }
  function mergeSet(s){
    var out = {};
    for (var k in DEFAULT_SET) out[k] = (s && s[k] !== undefined && s[k] !== null) ? s[k] : DEFAULT_SET[k];
    return out;
  }
  function curSettings(){ return state.settings; }
  function saveState(){
    save(stateKey(), state);
    renderStars();
    var kid = window.eduKids.active();
    if (kid && window.eduSync) window.eduSync.pushState(kid.id, 'state', state);
  }
  function saveWb(){
    save(wbKey(), wb);
    var kid = window.eduKids.active();
    if (kid && window.eduSync) window.eduSync.pushState(kid.id, 'workbench', wb);
  }

  // ======== 家长口令（保护家长操作：新增/删除星愿、重置数据、家长控制） ========
  var PWD_KEY = 'edu_parent_pwd_v1';
  var parentUnlocked = false;
  var pwdPending = null;
  function parentPwd(){ var v = load(PWD_KEY); return (v && /^\d{4}$/.test(v)) ? v : '0000'; }
  window.requireParent = function (cb){
    if (parentUnlocked){ cb(); return; }
    pwdPending = cb;
    var inp = document.getElementById('pwdInput');
    if (inp){ inp.value = ''; }
    document.getElementById('eduMaskPwd').style.display = 'flex';
    if (inp) setTimeout(function(){ inp.focus(); }, 60);
    return false;
  }
  window.pwdConfirm = function (){
    var inp = document.getElementById('pwdInput');
    var val = (inp ? inp.value : '').replace(/\s+/g, '');
    if (val === parentPwd()){
      parentUnlocked = true;
      document.getElementById('eduMaskPwd').style.display = 'none';
      if (inp) inp.value = '';
      var cb = pwdPending; pwdPending = null;
      if (cb) cb();
      toast('家长确认通过');
    } else {
      if (inp) inp.value = '';
      toast('口令不正确');
    }
  }
  window.pwdCancel = function (){
    pwdPending = null;
    document.getElementById('eduMaskPwd').style.display = 'none';
  };;
  // 首页右上角"家长模式"：验证口令后进入 星愿/家长管理
  window.openParentMode = function (){
    requireParent(function(){
      var b = document.getElementById('parentModeBtn');
      if (b) b.classList.add('unlocked');
      eduNav('wish');
    });
  };

  // 每日使用量统计
  function usageForToday(){
    var t = todayStr();
    if (!state.usage || state.usage.date !== t){ state.usage = { date: t, n: 0, secs: 0 }; }
    return state.usage;
  }
  // 家长控制: 每日上限拦截
  function minsUsed(){ return Math.ceil((usageForToday().secs || 0) / 60); }
  function checkLimit(){
    var s = curSettings();
    var u = usageForToday();
    if (s && s.dailyQ > 0 && u.n >= s.dailyQ) return '今日题量已达上限（' + s.dailyQ + ' 题）';
    if (s && s.dailyMin > 0 && minsUsed() >= s.dailyMin) return '今日用时已达上限（' + s.dailyMin + ' 分钟）';
    return null;
  }

  var toastT = null;
  function toast(msg){
    var el = document.getElementById('eduToast');
    if (!el) return;
    el.textContent = msg; el.classList.add('show');
    if (toastT) clearTimeout(toastT);
    toastT = setTimeout(function(){ el.classList.remove('show'); }, 1800);
  }
  function renderStars(){
    var el = document.getElementById('kidBarStars');
    if (el) el.textContent = '⭐ ' + (state.stars || 0);
  }

  // ======================= 幼小衔接工作台 =======================
  function todayStr(){
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
  }
  function yesterdayStr(){
    var y = new Date(Date.now()-86400000);
    return y.getFullYear() + '-' + String(y.getMonth()+1).padStart(2,'0') + '-' + String(y.getDate()).padStart(2,'0');
  }
  // 每日打卡：新的一天推进连续打卡计数并重置"今日完成"清单
  function ensureDay(){
    var t = todayStr();
    if (!wb.last) wb.last = '';
    if (wb.last !== t){
      wb.streak = (wb.last === yesterdayStr()) ? (wb.streak||0)+1 : 1;
      wb.last = t;
      wb.done = [];
    }
    saveWb();
    return t;
  }
  function wbInit(){
    updateDonePill();
    wbSubject(subjNow || 'zh');
  }

  window.wbSubject = function (s){
    subjNow = s;
    prefSet('subj', s);
    document.querySelectorAll('#wb-zh,#wb-math,#wb-en').forEach(function(el){ el.style.display='none'; });
    document.getElementById('wb-'+s).style.display='';
    if (s==='zh') wbZh('poem');
    if (s==='math') wbMath('calc');
    if (s==='en') wbEn('word');
    renderNav();
  };
  function setTab(containerId, k){
    document.querySelectorAll('#'+containerId+' .sm-tab').forEach(function(b){
      b.classList.toggle('active', b.getAttribute('data-s')===k);
    });
  }

  // ================= 10 题批量卷 =================
  // 当前进行中的卷: { subj,type, items:[{id,prompt,big,options|input|order,correct,note}], answers:{}, _t:开始时间 }
  var quiz = null;
  var quizContainerId = null;
  var quizSubject = null;
  var quizOrder = {};   // 排序题: idx -> 已点顺序数组

  function isCorrect(it, my){
    if (it.order) return String(my) === String(it.correct);
    if (it.input) return String(my) === String(it.correct);
    return it.options.some(function(o){ return o.v === my && o.v === it.correct; });
  }

  // 每日上限检查(含家长确认放行); 返回 true = 允许继续
  function applyLimit(){
    var lim = checkLimit();
    if (lim){
      var go = window.confirm(lim + '，今天的练习已完成。\n\n如家长同意继续加练，点「确定」。');
      if (!go){
        blockedHint(lim);
        return false;
      }
    }
    return true;
  }

  function startQuiz(subj, type, items, levelInfo){
    if (!applyLimit()) return;
    quiz = { subj: subj, type: type, items: items, answers: {}, submitted: false, _t: Date.now() };
    quizSubject = subj;
    quizOrder = {};
    renderQuiz();
  }

  function blockedHint(msg){
    var c = document.getElementById(quizContainerId || 'eduLearnPage');
    c.innerHTML = '';
    var card = document.createElement('div');
    card.className = 'edu-card';
    card.style.textAlign = 'center';
    card.innerHTML = '<div style="font-size:2.4rem;">🛌</div><h4>今天的练习已经完成啦</h4>'+
      '<p class="muted">'+esc(msg)+'。<br>家长可在孩子档案中打开「家长控制」设置调整上限。</p>';
    c.appendChild(card);
  }

  // 选择题: 标记选中
  window.pickOpt = function (idx, v){
    if (quiz.submitted) return;
    quiz.answers[idx] = v;
    var item = document.getElementById('qi-'+idx);
    item.querySelectorAll('.qi-opt button').forEach(function(b){
      b.classList.toggle('pick', b.getAttribute('data-v')===v);
    });
    if (quiz.items[idx] && quiz.items[idx].order) return;
    updateQuizProg();
  };

  // 排序题: 点选排列
  window.tapOrder = function (idx, v){
    if (quiz.submitted) return;
    var seq = quizOrder[idx] || (quizOrder[idx] = []);
    var pos = seq.indexOf(v);
    if (pos >= 0) seq.splice(pos, 1); else seq.push(v);
    var it = quiz.items[idx];
    it.correct = it.expected.slice().sort(function(a,b){ return a-b; }).join('|');
    renderOrderSeq(idx);
    var chips = document.getElementById('qi-'+idx).querySelectorAll('.qo-chip');
    chips.forEach(function(b){
      b.classList.toggle('picked', seq.indexOf(b.getAttribute('data-v')) >= 0);
    });
    updateQuizProg();
  };
  window.clearOrder = function (idx){
    if (quiz.submitted) return;
    quizOrder[idx] = [];
    renderOrderSeq(idx);
    var chips = document.getElementById('qi-'+idx).querySelectorAll('.qo-chip');
    chips.forEach(function(b){ b.classList.remove('picked'); });
    updateQuizProg();
  };
  function renderOrderSeq(idx){
    var box = document.getElementById('qseq-'+idx);
    if (!box) return;
    var seq = quizOrder[idx] || [];
    box.innerHTML = seq.length
      ? seq.map(function(v, i){ return '<span class="qo-seq-chip">'+esc(v)+'</span>'; }).join('')
      : '<span class="qo-empty">从小到大点出顺序…</span>';
  }
  // 答题进度: 一个题口的作答状态(选择/填数/排序是否点完)
  function answeredCount(){
    var n = 0;
    quiz.items.forEach(function(it, i){
      if (it.order){ if ((quizOrder[i]||[]).length === (it.expected||[]).length) n++; return; }
      if (it.input){ if (String(quiz.answers[i]||'').trim()) n++; return; }
      if (quiz.answers[i] !== undefined && quiz.answers[i] !== '') n++;
    });
    return n;
  }
  function updateQuizProg(){
    var el = document.getElementById('qtProg');
    if (!el || !quiz) return;
    var done = quiz.submitted ? quiz.items.length : answeredCount();
    var tip = quiz.submitted ? '已完成' : ((done === quiz.items.length) ? '已全部作答，可以交卷打分啦' : '做一题点一题，答完点「交卷打分」');
    el.textContent = '📄 共 '+quiz.items.length+' 题 · 已答 '+done+' · '+tip;
  }

  // 交卷自动打分
  window.submitQuiz = function (){
    if (quiz.submitted) return;
    var inputs = document.querySelectorAll('#quizShell input.qi-in');
    inputs.forEach(function(inp){
      var idx = parseInt(inp.getAttribute('data-idx'), 10);
      if (quiz.items[idx] && quiz.items[idx].input){
        quiz.answers[idx] = inp.value.replace(/\s+/g,'');
      }
    });
    var okFlags = [];
    var combo = 0, maxCombo = 0, count = 0;
    quiz.items.forEach(function(it, i){
      if (it.order) quiz.answers[i] = (quizOrder[i] || []).join('|');
      var my = quiz.answers[i];
      var ok = isCorrect(it, my);
      okFlags.push(ok);
      if (ok){ combo++; maxCombo = Math.max(maxCombo, combo); count++; }
      else combo = 0;
    });
    var prevWrong = state.wrong.length;
    // 记录 & 错题入本 & 加星
    quiz.items.forEach(function(it, i){
      recordAnswer(quiz.subj, it.wtype || quiz.type, it.id, it.prompt, it.correct, quiz.answers[i], okFlags[i]);
    });
    // 时长/每日量/完成记录/连击
    var secs = Math.max(1, Math.round((Date.now() - (quiz._t || Date.now())) / 1000));
    var usage = usageForToday();
    usage.n += quiz.items.length;
    usage.secs += secs;
    state.submits = (state.submits || 0) + 1;
    state.maxCombo = Math.max(state.maxCombo || 0, maxCombo);
    var bonus = maxCombo >= 8 ? 6 : (maxCombo >= 5 ? 3 : (maxCombo >= 3 ? 1 : 0));
    if (bonus > 0) state.stars += bonus;
    wb.done = wb.done || [];
    var doneKey = quiz.subj + ':' + quiz.type;
    if (wb.done.indexOf(doneKey) < 0) wb.done.push(doneKey);
    evalBadges(prevWrong, maxCombo);
    saveState();
    saveWb();
    quiz.submitted = true;
    // 统一引擎: 调档 + 记录过关 + qbank 作答反馈
    if (window.eduEngine && quizSubject !== 'par'){
      var passed = window.eduEngine.grade(quizSubject, quiz.type, count);
      // 逐题上报作答(用于 qbank 统计)
      if (window.eduSync && window.eduSync.qbankLearn){
        quiz.items.forEach(function(it, i){
          var my = quiz.answers[i];
          if (my === undefined) return;
          var ok = isCorrect(it, my);
          window.eduSync.qbankLearn({ subj:quizSubject, type:quiz.type, prompt:it.prompt, correct:ok, difficulty:window.eduEngine.diffOf(quizSubject) });
        });
      }
    }
    gradeQuiz(count, maxCombo, bonus);
  };

  // 适合幼儿的暖心反馈: 答对鼓励, 答错给温柔引导(不冷冰冰)
  var PRAISE_MSGS = ['真棒！','答对啦，太厉害！','好聪明呀～','漂亮！','你越来越棒咯！','太赞了！'];
  var WRONG_MSGS = ['没关系，再想想','差一点，再试一次','别灰心，再数一数','不小心走神啦，再看一看'];
  function warmCheck(){
    return PRAISE_MSGS[Math.floor(Math.random()*PRAISE_MSGS.length)];
  }
  function warmWrong(it){
    var shown = (it.input || it.order)
      ? String(it.correct).split('|').join(' → ')
      : (it.note || '');
    var open = WRONG_MSGS[Math.floor(Math.random()*WRONG_MSGS.length)];
    return open + '，正确答案是「' + shown + '」哦';
  }
  // 星星散落动画(答对成就感)
  function starBurst(){
    var host = document.getElementById('quizShell');
    if (!host) return;
    var wrap = document.createElement('div');
    wrap.className = 'star-burst';
    host.appendChild(wrap);
    for (var i=0;i<24;i++){
      var s = document.createElement('i');
      s.className = 'burst-star';
      s.textContent = (i%3===0)?'⭐':((i%3===1)?'🌟':'✨');
      s.style.left = (8 + Math.random()*84) + '%';
      s.style.animationDelay = (Math.random()*0.5) + 's';
      wrap.appendChild(s);
    }
    setTimeout(function(){ if (wrap.parentNode) wrap.parentNode.removeChild(wrap); }, 2600);
  }

  function gradeQuiz(count, maxCombo, bonus){
    var score = count;
    // 逐题上色 + 暖心提示
    quiz.items.forEach(function(it, i){
      var item = document.getElementById('qi-'+i);
      if (!item) return;
      var my = quiz.answers[i];
      var ok = isCorrect(it, my);
      item.classList.add('graded');
      if (!ok) item.classList.add('bad');
      var feed = item.querySelector('.qi-feed');
      feed.className = 'qi-feed ' + (ok ? 'ok' : 'no');
      feed.textContent = ok ? ('🎉 ' + warmCheck()) : ('💡 ' + warmWrong(it));
      item.querySelectorAll('.qi-opt button').forEach(function(b){
        var val = b.getAttribute('data-v');
        if (val === it.correct){ b.classList.add('correct'); }
        else if (val === my){ b.classList.add('wrong'); }
        b.disabled = true;
      });
    });
    // 结果显示区
    var box = document.getElementById('quizShell');
    // 交卷后更新工具栏提示，避免残留"交卷打分"按钮造成重复信息
    var tb = box.querySelector('.quiz-toolbar .qt-progress');
    if (tb) tb.textContent = '✅ 已交卷 · 下方查看结果（可再做一组）';
    var sb = box.querySelector('.quiz-toolbar .btn-soft');
    if (sb){ sb.textContent = '已交卷'; sb.disabled = true; }
    updateQuizProg();
    var medal = score >= 9 ? '🏆' : (score >= 7 ? '🌟' : '💪');
    var praise = score === quiz.items.length
      ? '全对！你是小天才！'
      : (score >= 7 ? '很不错，继续加油！' : '多练习就会更好，别灰心～');
    var result = document.createElement('div');
    result.className = 'qs-result';
    var comboHtml = (maxCombo >= 3)
      ? '<p style="margin-bottom:8px;">🔥 最高连对 '+maxCombo+' 题' +
        (bonus > 0 ? '，连击奖励 <b>+'+bonus+' 星</b>' : '') + '</p>'
      : '';
    result.innerHTML =
      '<div class="big">'+medal+' '+score+' / '+quiz.items.length+'</div>'+
      '<p>'+praise+' 已自动记录，答对的题加星、答错的已加入错题本</p>'+
      comboHtml+
      '<button type="button" class="btn-soft" onclick="'+restartExpr()+'">再做一组</button>';
    box.appendChild(result);
    if (score >= quiz.items.length * 0.7){
      starBurst();
      result.classList.add('celebrate');
    }
    updateDonePill();
    scrollToShell();
  }
  function updateDonePill(){
    var pill = document.getElementById('wbDoneToday');
    if (!pill) return;
    var n = (wb.done && wb.done.length) || 0;
    pill.style.display = n > 0 ? 'inline-flex' : 'none';
    pill.textContent = '✅ 今日完成 ' + n + ' 组';
    var strip = document.getElementById('wbStrip');
    if (strip) strip.style.display = n > 0 ? 'flex' : 'none';
  }
  function restartExpr(){
    if (quizSubject === 'par') return 'parPlay(\''+quiz.type+'\')';
    if (quizSubject === 'en') return 'wbEn(\''+wbEnMode+'\')';
    if (quizSubject === 'math' && wbWrongActive) return 'wbWrongQuiz()';
    if (quizSubject === 'math') return 'wbMath(\''+wbMathMode+'\')';
    return 'wbZh(\''+wbZhMode+'\')';
  }
  window.restartQuiz = function (){
    if (quizSubject === 'par'){ parPlay(quiz.type); return; }
    if (quizSubject === 'en'){ wbEn(wbEnMode); return; }
    if (quizSubject === 'math' && wbWrongActive){ wbWrongQuiz(); return; }
    if (quizSubject === 'math'){ wbMath(wbMathMode); return; }
    wbZh(wbZhMode);
  };
  function scrollToShell(){ try { document.getElementById('quizShell').scrollIntoView({behavior:'smooth',block:'start'}); } catch(e){} }

  // 记录答题(自动打分 + 自动保存 + 错题入本)
  function recordAnswer(subj, type, qid, prompt, correct, got, ok){
    var rec = { t: Date.now(), date: todayStr(), subj: subj, type: type, prompt: prompt, correct: correct, got: got, ok: ok };
    state.records.push(rec);
    if (ok){
      state.stars = (state.stars||0) + 1;
      state.wrong = state.wrong.filter(function(w){ return !(w.subj===subj && w.type===type && w.q===qid); });
    } else {
      var widx = state.wrong.findIndex(function(w){ return w.subj===subj && w.type===type && w.q===qid; });
      if (widx >= 0){ state.wrong[widx].times = (state.wrong[widx].times||0)+1; }
      else { state.wrong.push({ subj:subj, type:type, q:qid, times:1, prompt:prompt, correct:correct }); }
    }
    saveState();
  }

  // 成就徽章
  var BADGES = {
    s1: ['⭐', '第一颗星', '累计获得 1 颗星'],
    s10: ['🌟', '十星小达人', '累计获得 10 颗星'],
    s50: ['💎', '学习小超人', '累计获得 50 颗星'],
    c5: ['🔥', '连对五题', '一组里连续答对 5 题'],
    c10: ['⚡', '全对风暴', '一组里连续答对 10 题'],
    d3: ['📅', '坚持三天', '连续打卡 3 天'],
    d7: ['🗓️', '七日成习', '连续打卡 7 天'],
    z1: ['🎉', '初次答卷', '完成第 1 份卷子'],
    z10: ['📚', '十卷成材', '完成 10 份卷子'],
    all: ['🎨', '全面发展', '语文 / 数学 / 英语 / 乐园 都练过'],
    w0: ['🧹', '错题清零', '把错题全部消灭']
  };
  function evalBadges(prevWrong, comboRun){
    state.badges = state.badges || {};
    var want = {};
    if (state.stars >= 1) want.s1 = 1;
    if (state.stars >= 10) want.s10 = 1;
    if (state.stars >= 50) want.s50 = 1;
    if (comboRun >= 5) want.c5 = 1;
    if (comboRun >= 10) want.c10 = 1;
    if ((wb.streak || 0) >= 3) want.d3 = 1;
    if ((wb.streak || 0) >= 7) want.d7 = 1;
    if (state.submits >= 1) want.z1 = 1;
    if (state.submits >= 10) want.z10 = 1;
    var subjs = {};
    state.records.forEach(function(r){ subjs[r.subj] = 1; });
    if (subjs.zh && subjs.math && subjs.en && subjs.par) want.all = 1;
    if (prevWrong > 0 && state.wrong.length === 0) want.w0 = 1;
    for (var k in want){
      if (!state.badges[k]){
        state.badges[k] = Date.now();
        if (BADGES[k]) toast('🏅 解锁徽章：' + BADGES[k][1] + '（' + BADGES[k][2] + '）');
      }
    }
  }

  // 生成 10 题: 随机 & 优先错题

  // 生成选项: correct + 从 distractors 抽 n-1
  function makeOptions(correct, distractors, count, labelFn){
    var opts = [];
    var others = distractors.filter(function(d){ return String(d)!==String(correct); })
      .sort(function(){ return Math.random()-0.5; }).slice(0, count-1);
    var all = [correct].concat(others).sort(function(){ return Math.random()-0.5; });
    all.forEach(function(v){ opts.push({ v: String(v), label: labelFn ? labelFn(v) : v }); });
    return opts;
  }

  // ---------- 语文: 古诗 ----------
  // 每首古诗可有多个"空格变体"，同一首诗也能考不同位置/不同描述
  var POEMS = [
    { id:'q1', title:'静夜思', full:'床前明月光，疑是地上霜，举头望明月，低头思故乡',
      variants:[ {blanks:'床前____光，疑是地上霜', words:['明月','清风','晚风']},
                 {blanks:'床前明月光，____地上霜', words:['疑是','更是','已是']},
                 {blanks:'举头望明月，____思故乡', words:['低头','抬头','回头']} ] },
    { id:'q2', title:'春晓', full:'春眠不觉晓，处处闻啼鸟。夜来风雨声，花落知多少',
      variants:[ {blanks:'春眠不觉晓，____闻啼鸟', words:['处处','时时','家家']},
                 {blanks:'夜来风雨声，____知多少', words:['花落','花开','叶落']} ] },
    { id:'q3', title:'咏鹅', full:'鹅鹅鹅，曲项向天歌。白毛浮绿水，红掌拨清波',
      variants:[ {blanks:'鹅鹅鹅，____向天歌', words:['曲项','抬头','低头']},
                 {blanks:'白毛浮绿水，____拨清波', words:['红掌','黄掌','白掌']} ] },
    { id:'q4', title:'登鹳雀楼', full:'白日依山尽，黄河入海流。欲穷千里目，更上一层楼',
      variants:[ {blanks:'欲穷千里目，更上____楼', words:['一层','一座','一片']},
                 {blanks:'白日依山尽，____入海流', words:['黄河','长江','河水']} ] },
    { id:'q5', title:'悯农', full:'锄禾日当午，汗滴禾下土。谁知盘中餐，粒粒皆辛苦',
      variants:[ {blanks:'锄禾____，汗滴禾下土', words:['日当午','在田间','到中午']},
                 {blanks:'谁知盘中餐，粒粒____辛苦', words:['皆','都','全']} ] },
    { id:'q6', title:'静夜思·思', full:'举头望明月，低头思故乡', variants:[ {blanks:'举头望明月，____思故乡', words:['低头','抬头','回头']} ] },
    { id:'q7', title:'小池', full:'泉眼无声惜细流，树阴照水爱晴柔。小荷才露尖尖角，早有蜻蜓立上头',
      variants:[ {blanks:'小荷才露尖尖角，早有____立上头', words:['蜻蜓','蝴蝶','蜜蜂']},
                 {blanks:'____无声惜细流，树阴照水爱晴柔', words:['泉眼','泉声','池塘']} ] },
    { id:'q8', title:'江南', full:'江南可采莲，莲叶何田田。鱼戏莲叶间',
      variants:[ {blanks:'江南可采莲，____何田田', words:['莲叶','荷叶','柳叶']},
                 {blanks:'鱼戏____间', words:['莲叶','荷叶','荷花']} ] },
    { id:'q9', title:'画', full:'远看山有色，近听水无声。春去花还在，人来鸟不惊',
      variants:[ {blanks:'远看山有色，____水无声', words:['近听','静听','聆听']},
                 {blanks:'春去花还在，____鸟不惊', words:['人来','人去','鸟儿']} ] },
    { id:'q10', title:'风', full:'解落三秋叶，能开二月花。过江千尺浪，入竹万竿斜',
      variants:[ {blanks:'解落三秋叶，能开____花', words:['二月','六月','九月']},
                 {blanks:'____千尺浪，入竹万竿斜', words:['过江','入水','翻江']} ] },
    { id:'q11', title:'寻隐者不遇', full:'松下问童子，言师采药去。只在此山中，云深不知处',
      variants:[ {blanks:'松下问童子，____采药去', words:['言师','云深','林间']},
                 {blanks:'只在此山中，____不知处', words:['云深','松下','林深']} ] },
    { id:'q12', title:'古朗月行', full:'小时不识月，呼作白玉盘。又疑瑶台镜，飞在青云端',
      variants:[ {blanks:'小时不识月，呼作____盘', words:['白玉','金黄','银白']},
                 {blanks:'又疑瑶台镜，飞在____端', words:['青云','白云','蓝天']} ] },
    { id:'q13', title:'山村咏怀', full:'一去二三里，烟村四五家。亭台六七座，八九十枝花',
      variants:[ {blanks:'一去二三里，____四五家', words:['烟村','山村','小村']},
                 {blanks:'亭台六七座，____十枝花', words:['八九','七八','五六']} ] },
    { id:'q14', title:'悯农·农', full:'春种一粒粟，秋收万颗子。四海无闲田，农夫犹饿死',
      variants:[ {blanks:'春种一粒粟，____万颗子', words:['秋收','秋耕','丰收']},
                 {blanks:'四海无闲田，____犹饿死', words:['农夫','农民','耕牛']} ] }
  ];
  var wbZhMode = 'poem';
  function wbRenderZh(){
    var body = document.getElementById('wb-zh-body');
    if (wbZhMode==='trace'){ traceRender(body); return; }
    if (wbZhMode==='poem' || wbZhMode==='zi' || wbZhMode==='stroke' || wbZhMode==='pinyin' || wbZhMode==='ciyu'){
      quizContainerId = 'wb-zh-body';
      quizSubject = 'zh';
      var type = wbZhMode;
      if (wbZhMode==='pinyin') type = (wbPinyinMode==='yun') ? 'yun' : ((wbPinyinMode==='read') ? 'read' : 'pinyin');
      if (wbZhMode==='ciyu') type = (wbCiyuMode==='liang') ? 'liang' : 'fan';
      var seq = ++quizSeq;
      showQuizFetching('wb-zh-body');
      window.eduEngine.assemble('zh', type).then(function(items){
        if (seq !== quizSeq) return;
        startQuiz('zh', type, items);
      });
      return;
    }
  }
  window.wbZh = function (k){ wbZhMode=k; setTab('wb-zh', k); wbRenderZh(); };

  // ---------- 语文: 识字 ----------
  var ZI = [
    { id:'z1', zi:'日', pinyin:'rì', word:'太阳', emoji:'☀️' },
    { id:'z2', zi:'月', pinyin:'yuè', word:'月亮', emoji:'🌙' },
    { id:'z3', zi:'山', pinyin:'shān', word:'大山', emoji:'⛰️' },
    { id:'z4', zi:'水', pinyin:'shuǐ', word:'水滴', emoji:'💧' },
    { id:'z5', zi:'火', pinyin:'huǒ', word:'火焰', emoji:'🔥' },
    { id:'z6', zi:'木', pinyin:'mù', word:'树木', emoji:'🌳' },
    { id:'z7', zi:'人', pinyin:'rén', word:'人们', emoji:'🧍' },
    { id:'z8', zi:'口', pinyin:'kǒu', word:'嘴巴', emoji:'👄' },
    { id:'z9', zi:'土', pinyin:'tǔ', word:'泥土', emoji:'🟫' },
    { id:'z10', zi:'田', pinyin:'tián', word:'田地', emoji:'🌾' },
    { id:'z11', zi:'手', pinyin:'shǒu', word:'小手', emoji:'✋' },
    { id:'z12', zi:'雨', pinyin:'yǔ', word:'下雨', emoji:'🌧️' }
  ];

  // ---------- 语文: 笔顺(数笔画) ----------
  var STROKES = [
    { id:'s1', zi:'大', order:['横','撇','捺'] },
    { id:'s2', zi:'小', order:['竖钩','撇','点'] },
    { id:'s3', zi:'上', order:['竖','横','横'] },
    { id:'s4', zi:'下', order:['横','竖','点'] },
    { id:'s5', zi:'人', order:['撇','捺'] },
    { id:'s6', zi:'口', order:['竖','横折','横'] },
    { id:'s7', zi:'山', order:['竖','竖折','竖'] },
    { id:'s8', zi:'中', order:['竖','横折','横','竖'] },
    { id:'s9', zi:'天', order:['横','横','撇','捺'] },
    { id:'s10', zi:'木', order:['横','竖','撇','捺'] },
    { id:'s11', zi:'十', order:['横','竖'] }
  ];

  // ---------- 语文: 拼音 (声母/韵母/拼读) ----------
  var P_SHENG = [
    { id:'p1', s:'b', zi:'八', py:'bā', e:'8️⃣' }, { id:'p2', s:'p', zi:'皮', py:'pí', e:'🧒' },
    { id:'p3', s:'m', zi:'妈', py:'mā', e:'👩' }, { id:'p4', s:'f', zi:'飞', py:'fēi', e:'✈️' },
    { id:'p5', s:'d', zi:'大', py:'dà', e:'🅰️' }, { id:'p6', s:'t', zi:'天', py:'tiān', e:'☁️' },
    { id:'p7', s:'n', zi:'牛', py:'niú', e:'🐮' }, { id:'p8', s:'l', zi:'六', py:'liù', e:'6️⃣' },
    { id:'p9', s:'g', zi:'瓜', py:'guā', e:'🍉' }, { id:'p10', s:'k', zi:'口', py:'kǒu', e:'👄' },
    { id:'p11', s:'h', zi:'花', py:'huā', e:'🌸' }, { id:'p12', s:'j', zi:'鸡', py:'jī', e:'🐔' },
    { id:'p13', s:'q', zi:'七', py:'qī', e:'7️⃣' }, { id:'p14', s:'x', zi:'小', py:'xiǎo', e:'🐭' },
    { id:'p15', s:'zh', zi:'猪', py:'zhū', e:'🐷' }, { id:'p16', s:'ch', zi:'车', py:'chē', e:'🚗' },
    { id:'p17', s:'sh', zi:'书', py:'shū', e:'📖' }, { id:'p18', s:'r', zi:'日', py:'rì', e:'☀️' },
    { id:'p19', s:'z', zi:'子', py:'zǐ', e:'👶' }, { id:'p20', s:'c', zi:'菜', py:'cài', e:'🥬' },
    { id:'p21', s:'s', zi:'三', py:'sān', e:'3️⃣' }, { id:'p22', s:'y', zi:'鱼', py:'yú', e:'🐟' },
    { id:'p23', s:'w', zi:'我', py:'wǒ', e:'🧑' }
  ];
  var P_YUN = [
    { id:'y1', u:'a', zi:'爸', py:'bà', e:'👨' }, { id:'y2', u:'o', zi:'喔', py:'ō', e:'😯' },
    { id:'y3', u:'e', zi:'鹅', py:'é', e:'🦢' }, { id:'y4', u:'i', zi:'衣', py:'yī', e:'👕' },
    { id:'y5', u:'u', zi:'乌', py:'wū', e:'🐦' }, { id:'y6', u:'ü', zi:'鱼', py:'yú', e:'🐟' },
    { id:'y7', u:'ai', zi:'爱', py:'ài', e:'❤️' }, { id:'y8', u:'ei', zi:'杯', py:'bēi', e:'🥤' },
    { id:'y9', u:'ui', zi:'水', py:'shuǐ', e:'💧' }, { id:'y10', u:'ao', zi:'猫', py:'māo', e:'🐱' },
    { id:'y11', u:'ou', zi:'口', py:'kǒu', e:'👄' }, { id:'y12', u:'iu', zi:'六', py:'liù', e:'6️⃣' },
    { id:'y13', u:'ie', zi:'姐', py:'jiě', e:'👧' }, { id:'y14', u:'an', zi:'山', py:'shān', e:'⛰️' },
    { id:'y15', u:'en', zi:'门', py:'mén', e:'🚪' }, { id:'y16', u:'in', zi:'心', py:'xīn', e:'💖' },
    { id:'y17', u:'ang', zi:'羊', py:'yáng', e:'🐑' }, { id:'y18', u:'ong', zi:'虫', py:'chóng', e:'🐛' }
  ];
  var P_READ = [
    { id:'r1', zi:'马', py:'mǎ', e:'🐴' }, { id:'r2', zi:'树', py:'shù', e:'🌳' },
    { id:'r3', zi:'火', py:'huǒ', e:'🔥' }, { id:'r4', zi:'门', py:'mén', e:'🚪' },
    { id:'r5', zi:'羊', py:'yáng', e:'🐑' }, { id:'r6', zi:'雨', py:'yǔ', e:'🌧️' },
    { id:'r7', zi:'手', py:'shǒu', e:'✋' }, { id:'r8', zi:'金', py:'jīn', e:'💰' },
    { id:'r9', zi:'鸟', py:'niǎo', e:'🐦' }, { id:'r10', zi:'狗', py:'gǒu', e:'🐶' },
    { id:'r11', zi:'花', py:'huā', e:'🌸' }
  ];
  var wbPinyinMode = 'sheng';
  window.wbPinyin = function (k){ wbPinyinMode=k; setTab('wb-pinyin', k); wbRenderZh(); };

  // ---------- 语文: 词语 (反义词 / 量词) ----------
  var FANCI = [
    { id:'f1', zi:'大', fan:'小', e:'🐘' }, { id:'f2', zi:'高', fan:'矮', e:'🦒' },
    { id:'f3', zi:'长', fan:'短', e:'📏' }, { id:'f4', zi:'多', fan:'少', e:'🍎' },
    { id:'f5', zi:'黑', fan:'白', e:'🐼' }, { id:'f6', zi:'快', fan:'慢', e:'🐢' },
    { id:'f7', zi:'上', fan:'下', e:'⬆️' }, { id:'f8', zi:'开', fan:'关', e:'🚪' },
    { id:'f9', zi:'冷', fan:'热', e:'🥶' }, { id:'f10', zi:'前', fan:'后', e:'🫏' }
  ];
  var LIANGCI = [
    { id:'l1', zi:'一', n:'猫', m:'只' }, { id:'l2', zi:'一', n:'苹果', m:'个' },
    { id:'l3', zi:'一', n:'花', m:'朵' }, { id:'l4', zi:'一', n:'树', m:'棵' },
    { id:'l5', zi:'一', n:'鱼', m:'条' }, { id:'l6', zi:'一', n:'书', m:'本' },
    { id:'l7', zi:'一', n:'车', m:'辆' }, { id:'l8', zi:'一', n:'鞋', m:'双' },
    { id:'l9', zi:'一', n:'笔', m:'支' }, { id:'l10', zi:'一', n:'纸', m:'张' },
    { id:'l11', zi:'一', n:'老虎', m:'只' }
  ];
  var wbCiyuMode = 'fan';
  window.wbCiyu = function (k){ wbCiyuMode=k; setTab('wb-ciyu', k); wbRenderZh(); };

  // ---------- 语文: 手写描红 (Canvas, 不评判, 只描轨迹) ----------
  var TR_CHARS = [
    { zi:'大', hint:['横','撇','捺'], lines:[ [[15,70],[85,70]], [[50,25],[40,58],[32,78]], [[50,25],[60,55],[74,84]] ] },
    { zi:'小', hint:['竖钩','撇','点'], lines:[ [[50,20],[50,62],[44,70]], [[52,14],[40,34]], [[50,14],[63,34]] ] },
    { zi:'上', hint:['竖','横','横'], lines:[ [[50,15],[50,60]], [[30,24],[70,24]], [[10,76],[90,76]] ] },
    { zi:'下', hint:['横','竖','点'], lines:[ [[10,24],[90,24]], [[50,24],[50,74]], [[50,76],[63,92]] ] },
    { zi:'人', hint:['撇','捺'], lines:[ [[45,30],[40,56],[33,80]], [[55,30],[61,60],[74,88]] ] },
    { zi:'口', hint:['竖','横折','横'], lines:[ [[24,24],[24,76]], [[24,24],[76,24],[76,76]], [[24,76],[76,76]] ] },
    { zi:'山', hint:['竖','竖折','竖'], lines:[ [[50,18],[50,80]], [[20,42],[20,72],[80,72]], [[80,18],[80,72]] ] },
    { zi:'中', hint:['竖','横折','横','竖'], lines:[ [[50,8],[50,92]], [[24,24],[76,24],[76,64]], [[24,64],[76,64]], [[24,24],[24,64]] ] },
    { zi:'日', hint:['竖','横折','横','横'], lines:[ [[28,22],[28,78]], [[28,22],[72,22],[72,78]], [[28,50],[72,50]], [[28,78],[72,78]] ] },
    { zi:'一', hint:['横'], lines:[ [[10,50],[90,50]] ] },
    { zi:'二', hint:['横','横'], lines:[ [[25,32],[75,32]], [[10,68],[90,68]] ] },
    { zi:'三', hint:['横','横','横'], lines:[ [[10,22],[90,22]], [[10,50],[90,50]], [[10,78],[90,78]] ] }
  ];
  var trIdx = 0, trCi = 0, trTick = Date.now();
  var trBase = null, trInk = null, trBaseCtx = null, trInkCtx = null, trDrawing = false;
  function traceCur(){ return TR_CHARS[trIdx]; }
  function linePath(ctx, pts, s){
    ctx.beginPath();
    pts.forEach(function(p, i){ if (i===0) ctx.moveTo(p[0]*s, p[1]*s); else ctx.lineTo(p[0]*s, p[1]*s); });
  }
  function traceSetup(){
    var wrap = document.querySelector('.tr-canvas-wrap');
    var size = Math.min(wrap ? wrap.clientWidth : 320, 360);
    var dpr = window.devicePixelRatio || 1;
    ['trBase','trInk'].forEach(function(id){
      var c = document.getElementById(id);
      c.width = size * dpr; c.height = size * dpr;
      c.style.width = size + 'px'; c.style.height = size + 'px';
    });
    trBase = document.getElementById('trBase');
    trInk = document.getElementById('trInk');
    trBaseCtx = trBase.getContext('2d');
    trInkCtx = trInk.getContext('2d');
    trBaseCtx.save(); trBaseCtx.scale(dpr, dpr);
    trInkCtx.save(); trInkCtx.scale(dpr, dpr);
    trInkCtx.strokeStyle = 'rgba(255,107,74,.85)';
    trInkCtx.lineWidth = 5.5;
    trInkCtx.lineCap = 'round';
    trInkCtx.lineJoin = 'round';
    trInk.addEventListener('pointerdown', trDown);
    trInk.addEventListener('pointermove', trMove);
    trInk.addEventListener('pointerup', trUp);
    traceDrawBase();
    traceResetInk();
    updateTrHint();
  }
  function traceResetInk(){
    trInkCtx.clearRect(0, 0, trInkCtx.canvas.width, trInkCtx.canvas.height);
  }
  function traceDrawBase(){
    var ctx = trBaseCtx;
    ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
    var W = trBase.clientWidth, s = W / 100;
    ctx.strokeStyle = 'rgba(150,140,120,.18)';
    ctx.lineWidth = 1;
    ctx.strokeRect(3, 3, W - 6, W - 6);
    ctx.beginPath();
    ctx.moveTo(0,0); ctx.lineTo(W,W); ctx.moveTo(W,0); ctx.lineTo(0,W);
    ctx.moveTo(W/2,0); ctx.lineTo(W/2,W); ctx.moveTo(0,W/2); ctx.lineTo(W,W/2);
    ctx.stroke();
    var ch = traceCur();
    ctx.strokeStyle = 'rgba(170,155,130,.55)';
    ctx.lineWidth = 7;
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    for (var i = 0; i < trCi; i++){ linePath(ctx, ch.lines[i], s); ctx.stroke(); }
    if (trCi < ch.lines.length){
      ctx.save();
      ctx.strokeStyle = '#ff6b4a';
      ctx.lineWidth = 5;
      ctx.setLineDash([6, 5]);
      linePath(ctx, ch.lines[trCi], s);
      ctx.stroke();
      ctx.restore();
    }
  }
  function updateTrHint(){
    var ch = traceCur();
    document.getElementById('trChar').textContent = ch.zi;
    var el = document.getElementById('trHint');
    el.textContent = (trCi >= ch.lines.length)
      ? '🎉 这个字写完啦！'
      : ('第 ' + (trCi + 1) + ' / ' + ch.lines.length + ' 笔 · 笔画【' + ch.hint[trCi] + '】');
  }
  function trPos(e){
    var r = trInk.getBoundingClientRect();
    var t = (e.touches && e.touches[0]) || e;
    return { x: t.clientX - r.left, y: t.clientY - r.top };
  }
  function trDown(e){ e.preventDefault(); trDrawing = true; trInkCtx.beginPath(); var p = trPos(e); trInkCtx.moveTo(p.x, p.y); }
  function trMove(e){ if (!trDrawing) return; e.preventDefault(); var p = trPos(e); trInkCtx.lineTo(p.x, p.y); trInkCtx.stroke(); }
  function trUp(e){ if (!trDrawing) return; trDrawing = false; trCheckDone(); }
  function trCheckDone(){
    var ch = traceCur();
    if (trCi >= ch.lines.length) return;
    var pts = ch.lines[trCi];
    var minx = 200, miny = 200, maxx = -1, maxy = -1;
    pts.forEach(function(p){
      minx = Math.min(minx, p[0]); maxx = Math.max(maxx, p[0]);
      miny = Math.min(miny, p[1]); maxy = Math.max(maxy, p[1]);
    });
    var s = trInk.clientWidth / 100, dpr = window.devicePixelRatio || 1, pad = 10;
    var bx = Math.max(0, Math.floor(((minx - 2) * s - pad) * dpr));
    var by = Math.max(0, Math.floor(((miny - 2) * s - pad) * dpr));
    var bw = Math.min(trInk.width, Math.ceil(((maxx + 2) * s + pad) * dpr)) - bx;
    var bh = Math.min(trInk.height, Math.ceil(((maxy + 2) * s + pad) * dpr)) - by;
    if (bw <= 0 || bh <= 0) return;
    var data = trInkCtx.getImageData(bx, by, bw, bh).data;
    var hit = 0, tot = 0;
    for (var i = 3; i < data.length; i += 4){ tot++; if (data[i] > 60) hit++; }
    if (hit / (tot || 1) > 0.12){
      trCi++;
      traceDrawBase();
      if (trCi >= ch.lines.length) traceDone();
      else { toast('真棒，下一笔！'); updateTrHint(); }
    }
  }
  function traceDone(){
    var ch = traceCur();
    updateTrHint();
    var usage = usageForToday();
    usage.n += 1;
    usage.secs += Math.max(1, Math.round((Date.now() - (trTick||Date.now())) / 1000));
    trTick = Date.now();
    recordAnswer('zh', 'trace', 'trace_' + ch.zi, '描红：' + ch.zi, '完成', '完成', true);
    wb.done = wb.done || [];
    if (wb.done.indexOf('zh:trace') < 0){ wb.done.push('zh:trace'); saveWb(); }
    saveState();
    if (checkLimit()){ toast('今日练习已达上限啦，休息一下吧～'); }
    else toast('🎉 「' + ch.zi + '」描完啦，+1 星！');
    setTimeout(traceNext, 900);
  }
  function traceRender(body){
    body.innerHTML =
      '<div class="edu-card trace-card">' +
        '<div class="tr-head"><span class="tr-char" id="trChar">大</span><span class="tr-hint" id="trHint"></span></div>' +
        '<div class="tr-canvas-wrap"><canvas id="trBase"></canvas><canvas id="trInk"></canvas></div>' +
        '<div class="tr-actions">' +
          '<button type="button" class="btn-ghost" onclick="traceRedo()">🔄 重写</button>' +
          '<button type="button" class="btn-ghost" onclick="traceSkip()">⏭️ 跳过这笔</button>' +
          '<button type="button" class="btn-soft" onclick="traceNext()">📖 换一个字</button>' +
        '</div>' +
        '<p class="muted" style="text-align:center;margin:10px 0 0;">👆 用手指沿着橙色的虚线描红，描完会自动进入下一笔</p>' +
      '</div>';
    trIdx = randInt(TR_CHARS.length);
    trCi = 0;
    traceSetup();
  }
  window.traceRedo = function (){
    traceResetInk();
    trCi = 0;
    traceDrawBase();
    updateTrHint();
  };
  window.traceSkip = function (){
    var ch = traceCur();
    if (trCi >= ch.lines.length) return;
    trCi++;
    traceDrawBase();
    updateTrHint();
    if (trCi >= ch.lines.length) toast('这个字描完啦');
  };
  window.traceNext = function (){
    trIdx = (trIdx + 1) % TR_CHARS.length;
    trCi = 0;
    traceDrawBase();
    traceResetInk();
    updateTrHint();
  };

  // ---------- 英语: 配对 (点选连线, 触屏友好) ----------
  var matchL = [], matchR = [], selL = -1, selR = -1, matchedN = 0, matchedMap = {}, matchT = Date.now();
  window.renderMatch = function (body){
    if (!applyLimit()){ quizContainerId = 'wb-en-body'; blockedHint('英语配对今天的练习已完成'); return; }
    matchT = Date.now();
    body.innerHTML =
      '<div class="edu-card" style="text-align:center;">' +
        '<h4>🤝 单词配图</h4>' +
        '<p class="muted">先点左边的英文单词，再点右边对应的图片</p>' +
        '<div class="match-wrap" id="matchWrap"></div>' +
        '<div class="quiz-score-bar" style="justify-content:center;margin-top:14px;">' +
          '<div class="qs-item" style="flex:0 0 auto;min-width:120px;"><div class="n"><span id="matchN">0</span>/4</div><div class="l">已配对</div></div>' +
        '</div>' +
      '</div>';
    var pool = WORDS.slice().sort(function(){ return Math.random() - 0.5; }).slice(0, 4);
    matchL = pool.slice();
    matchR = pool.slice().sort(function(){ return Math.random() - 0.5; });
    selL = -1; selR = -1; matchedN = 0; matchedMap = {};
    matchDraw();
  }
  function matchDraw(){
    var wrap = document.getElementById('matchWrap');
    wrap.innerHTML =
      '<div class="m-col">' + matchL.map(function(w, i){
        var on = selL === i, ok = matchedMap[w.en];
        return '<button type="button" class="m-item left ' + (on ? 'pick' : '') + (ok ? ' lock' : '') + '" onclick="matchLpick(' + i + ')">' + esc(w.en) + '</button>';
      }).join('') + '</div>' +
      '<div class="m-col">' + matchR.map(function(w, i){
        var on = selR === i, ok = matchedMap[w.en];
        return '<button type="button" class="m-item right ' + (on ? 'pick' : '') + (ok ? ' lock' : '') + '" onclick="matchRpick(' + i + ')">' + w.emoji + '<span class="m-zh">' + esc(w.zh) + '</span></button>';
      }).join('') + '</div>';
    document.getElementById('matchN').textContent = matchedN;
  }
  window.matchLpick = function (i){
    if (matchedMap[matchL[i].en]) return;
    selL = (selL === i) ? -1 : i;
    selR = -1;
    matchDraw();
  };
  window.matchRpick = function (i){
    var w = matchR[i];
    if (matchedMap[w.en]) return;
    if (selL < 0){ selR = (selR === i) ? -1 : i; matchDraw(); return; }
    if (matchL[selL].en === w.en){
      matchedMap[w.en] = 1; matchedN++;
      selL = -1; selR = -1;
      matchDraw();
      if (matchedN === matchL.length) matchDone();
    } else {
      selL = -1; selR = -1;
      matchDraw();
      toast('再想想，配错了哦～');
    }
  };
  function matchDone(){
    var usage = usageForToday();
    usage.n += matchL.length;
    usage.secs += Math.max(1, Math.round((Date.now() - (matchT||Date.now())) / 1000));
    state.stars = (state.stars || 0) + 4;
    matchL.forEach(function(w){
      state.records.push({ t: Date.now(), date: todayStr(), subj: 'en', type: 'match', prompt: '单词配对：' + w.en, correct: w.en, got: w.en, ok: true });
    });
    wb.done = wb.done || [];
    if (wb.done.indexOf('en:match') < 0){ wb.done.push('en:match'); }
    evalBadges(state.wrong.length, 0);
    saveState();
    saveWb();
    var box = document.getElementById('matchWrap');
    box.innerHTML = '<div class="m-done">' +
      '<div style="font-size:2.6rem;">🏆</div>' +
      '<h4>全部配对成功！+4 星</h4>' +
      '<div class="edu-actions" style="justify-content:center;">' +
        '<button type="button" class="btn-ghost" onclick="renderMatch(document.getElementById(\'wb-en-body\'))">再来一轮</button>' +
        '<button type="button" class="btn-soft" onclick="wbEn(\'word\')">去背单词</button>' +
      '</div></div>';
  }

  // 卷渲染(共用)
  function renderQuiz(){
    var container = document.getElementById(quizContainerId);
    container.innerHTML = '';

    var shell = document.createElement('div');
    shell.id = 'quizShell';
    // 闯关横幅: 让每个学习项都一眼看出是"闯关"模式(难度档 + 过关目标 + 已通关状态)
    if (quizSubject !== 'par'){
      var lv = window.eduEngine ? window.eduEngine.diffOf(quizSubject) : 3;
      var passed = (state.adv && state.adv[quizSubject] && state.adv[quizSubject][quiz.type] && state.adv[quizSubject][quiz.type].passed);
      var itemName = ({zh:{poem:'古诗',zi:'识字',stroke:'笔顺',pinyin:'拼音',yun:'拼音',read:'拼音',fan:'词语',liang:'词语'},
                       math:{calc:'口算',judge:'判断',word:'应用题',order:'排序'},
                       en:{word:'单词',dialogue:'对话'}}[quizSubject]||{})[quiz.type] || quiz.type;
      var stars = '';
      for (var si=0; si<lv; si++) stars += '⭐';
      var banner = document.createElement('div');
      banner.className = 'lv-banner';
      banner.innerHTML =
        '<div class="lv-left"><span class="lv-badge">🗺️ 闯关 · '+esc(itemName)+'</span>'+
        '<span class="lv-sub">难度'+stars+' · 答对 '+(window.eduEngine?window.eduEngine.PASS_Q:7)+' 题过关</span></div>'+
        '<div class="lv-right">'+(passed?'<span class="lv-passed">✅ 已通过本关</span>':'<span class="lv-notyet">⏳ 待通关</span>')+
        '<span class="lv-at">难度档 '+lv+'/5</span></div>';
      shell.appendChild(banner);
    }
    var toolbar = document.createElement('div');
    toolbar.className = 'quiz-toolbar';
    toolbar.innerHTML = '<span class="qt-progress" id="qtProg"></span>'+
      '<button type="button" class="btn-ghost" onclick="regenQuiz()">换一组题</button>'+
      '<button type="button" class="btn-soft" onclick="submitQuiz()">交卷打分</button>';
    shell.appendChild(toolbar);
    updateQuizProg();

    quiz.items.forEach(function(it, i){
      var card = document.createElement('div');
      card.className = 'quiz-item';
      card.id = 'qi-'+i;
      var h = '<div class="qi-head"><span class="qi-no">'+(i+1)+'</span><span class="qi-prompt">'+esc(it.prompt)+'</span></div>';
      if (it.big && it.big !== it.prompt) h += '<div class="qi-big">'+esc(it.big)+'</div>';
      if (it.options){
        h += '<div class="qi-opt">'+it.options.map(function(o, oi){
          return '<button type="button" data-v="'+esc(o.v)+'" id="qo-'+i+'-'+oi+'" onclick="pickOpt('+i+',\''+esc(o.v)+'\')">'+esc(o.label)+'</button>';
        }).join('')+'</div>';
      } else if (it.order){
        h += '<div class="qi-order">'+
          '<div class="qo-seq" id="qseq-'+i+'"><span class="qo-empty">从小到大点出顺序…</span></div>'+
          '<div class="qo-chips">'+it.expected.slice().sort(function(){ return Math.random()-0.5; }).map(function(v){
            return '<button type="button" class="qo-chip" data-v="'+esc(v)+'" onclick="tapOrder('+i+',\''+esc(v)+'\')">'+esc(v)+'</button>';
          }).join('')+'</div>'+
          '<button type="button" class="qo-clear" onclick="clearOrder('+i+')">清空顺序</button>'+
          '</div>';
      } else {
        h += '<div class="qi-fill"><input class="qi-in" data-idx="'+i+'" type="number" inputmode="numeric" autocomplete="off" placeholder="填答案" onkeydown="if(event.key===\'Enter\')submitQuiz()"></div>';
      }
      h += '<div class="qi-feed"></div>';
      card.innerHTML = h;
      renderOrderSeq(i);
      shell.appendChild(card);
    });
    container.appendChild(shell);
  }
  window.regenQuiz = function (){
    if (quiz.submitted) return;
    if (quizSubject === 'par'){ parPlay(quiz.type); return; }
    if (quizSubject === 'en'){ wbEn(wbEnMode); return; }
    if (quizSubject === 'math' && wbWrongActive){ wbWrongQuiz(); return; }
    if (quizSubject === 'math'){ wbMath(wbMathMode); return; }
    wbZh(wbZhMode);
  };

  // ---------- 数学: 口算 / 判断 / 应用题 / 排序 ----------
  function randInt(n){ return Math.floor(Math.random()*n); }
  function makeCalc(max, nocarry){
    for (var i=0;i<40;i++){
      var a = randInt(max+1), b = randInt(max+1);
      var op = Math.random() < 0.5 ? '+' : '-';
      if (a===0 && b===0) continue;
      if (op==='-' && b>a){ var t=a; a=b; b=t; }
      if (nocarry){
        if (op==='+' && a>0 && (a+b) <= 9){
          return { a:a, b:b, text: a+' + '+b+' = ?', ans: a+b, expr: a+' + '+b+' = '+(a+b) };
        }
        if (op==='-' && a!==0 && b!==0 && a>=b && (a%10) >= (b%10)){
          return { a:a, b:b, text: a+' - '+b+' = ?', ans: a-b, expr: a+' - '+b+' = '+(a-b) };
        }
      } else {
        if (op==='+'){
          return { a:a, b:b, text: a+' + '+b+' = ?', ans: a+b, expr: a+' + '+b+' = '+(a+b) };
        }
        if (a > b){
          return { a:a, b:b, text: a+' - '+b+' = ?', ans: a-b, expr: a+' - '+b+' = '+(a-b) };
        }
      }
    }
    return { a:1, b:1, text:'1 + 1 = ?', ans:2, expr:'1 + 1 = 2' };
  }
  function makeCalcItem(q){
    return { id:'calc_'+q.text, prompt:q.text, input:true, correct:String(q.ans), note:q.expr };
  }
  function makeJudgeItem(q, k){
    var computed = q.ans;
    var wrong = Math.random() < 0.5;
    var shown = wrong ? (computed + (computed >= 2 ? -1 : 1)) : computed;
    var tf = (shown === computed) ? '对' : '错';
    return { id:'judge_'+q.text, prompt:q.text.replace('=?','＝ '+shown+'，对吗？'),
      options:[{v:'对',label:'✅ 对'},{v:'错',label:'❌ 错'}], correct:tf, note:q.expr };
  }
  var WORD_PLUS = [
    function(a,b){ return '小明有 '+a+' 个苹果，又买了 '+b+' 个，一共有多少个？'; },
    function(a,b){ return '树上有 '+a+' 只小鸟，又飞来了 '+b+' 只，现在一共有几只？'; },
    function(a,b){ return '鱼缸里有 '+a+' 条小鱼，妈妈又放进 '+b+' 条，现在共有几条？'; },
    function(a,b){ return '地上有 '+a+' 颗糖，又掉下来 '+b+' 颗，一共几颗？'; }
  ];
  var WORD_MINUS = [
    function(a,b){ return '盘子里有 '+a+' 个苹果，吃了 '+b+' 个，还剩几个？'; },
    function(a,b){ return '书架上有 '+a+' 本书，借走了 '+b+' 本，还剩几本？'; },
    function(a,b){ return '公交车上有 '+a+' 人，下去了 '+b+' 人，车上还有几人？'; },
    function(a,b){ return '池塘里有 '+a+' 条鱼，游走了 '+b+' 条，还剩几条？'; }
  ];
  function makeWordItem(q){
    var tpl = (q.ans === q.a + q.b) ? WORD_PLUS[randInt(WORD_PLUS.length)] : WORD_MINUS[randInt(WORD_MINUS.length)];
    var sentence = tpl(q.a, q.b);
    return { id:'word_'+q.expr, prompt:'应用题：'+sentence, big:sentence, input:true, correct:String(q.ans), note:q.expr+' → '+q.ans };
  }
  // 把 qbank 拉回的题转成统一题目对象
  // ---------- 难度档位(1~5): 用于自适应调难 ----------
  var LEVEL_RANGE = [5, 10, 20, 50, 100];
  function levelRange(subj){
    var d = stateLevel(subj);
    return LEVEL_RANGE[Math.max(0, Math.min(4, d - 1))];
  }
  function stateLevel(subj){
    state.level = state.level || {};
    return state.level[subj] || 3;
  }
  function setLevel(subj, v){
    state.level = state.level || {};
    state.level[subj] = Math.max(1, Math.min(5, v));
    saveState();
  }
  // ======================= 统一自适应闯关引擎 =======================
  // 每个学习项(古诗/识字/口算/单词等) 本身就是"一关":
  //   错题优先复现(~一半) -> 题库拉取待巩固 -> 现场生成新题并入库去重
  //   难度档 diff(1~5) 逐题渐进, 整组按正确率自动升降档
  //   达标即标记该学习项过关(攒星), 未达标停留重练
  // 题库存于后端 edu_qbank, 随出题不断丰富且不重复。
  window.eduEngine = (function(){
    var PASS_Q = 7;   // 10题答对7题算过关
    function diffOf(subj){ return stateLevel(subj); }
    // ---- 生成器: 每种学习项在难度 diff 下产出一个"新"题目(内容池懒引用, 兼容后续定义) ----
    var GEN = {
      zh_poem: function(d){ var w=POEMS[randInt(POEMS.length)]; var v=w.variants[randInt(w.variants.length)];
        var f=v.blanks.split('____');
        var head=f[0].replace(/[，。！？、\s]+$/,''), tail=f[1].replace(/^[，。！？、\s]+/,'');
        var p= head ? ('《'+w.title+'》'+head+'…') : ('《'+w.title+'》…'+tail);
        return { id:'poem_'+w.id+'_'+v.words[0], prompt:p, big:v.blanks,
          options:makeOptions(v.words[0], v.words, 3), correct:v.words[0], note:w.full }; },
      zh_zi: function(d){ var z=ZI[randInt(ZI.length)];
        return { id:'zi_'+z.id, prompt:'“'+z.word+'”对应的汉字是？', big:z.emoji+' '+z.word,
          options:makeOptions(z.zi, ZI.map(function(x){return x.zi;}), d>=4?4:3), correct:z.zi, note:z.zi+'（'+z.pinyin+'）' }; },
      zh_stroke: function(d){ var s=STROKES[randInt(STROKES.length)]; var c=s.order.length;
        return { id:'stroke_'+s.id, prompt:'「'+s.zi+'」这个字一共有几笔？', big:s.zi,
          options:makeOptions(c, [Math.max(2,c-1), c-2, c+1], d>=4?4:3), correct:c, note:c+' 笔' }; },
      zh_pinyin: function(d){ var x=P_SHENG[randInt(P_SHENG.length)];
        return { id:'pinyin_'+x.id, prompt:'「'+x.zi+'（'+x.py+'）」的声母是？', big:x.e+' '+x.zi,
          options:makeOptions(x.s, P_SHENG.map(function(t){return t.s;}), d>=4?4:3), correct:x.s, note:'声母 '+x.s }; },
      zh_yun: function(d){ var x=P_YUN[randInt(P_YUN.length)];
        return { id:'yun_'+x.id, prompt:'「'+x.zi+'（'+x.py+'）」的韵母是？', big:x.e+' '+x.zi,
          options:makeOptions(x.u, P_YUN.map(function(t){return t.u;}), d>=4?4:3), correct:x.u, note:'韵母 '+x.u }; },
      zh_read: function(d){ var x=P_READ[randInt(P_READ.length)];
        return { id:'read_'+x.id, prompt:'「'+x.zi+'」这个字怎么读？', big:x.e+' '+x.zi,
          options:makeOptions(x.py, P_READ.map(function(t){return t.py;}), d>=4?4:3), correct:x.py, note:x.py }; },
      zh_fan: function(d){ var x=FANCI[randInt(FANCI.length)];
        return { id:'fan_'+x.id, prompt:'「'+x.zi+'」的反义词是？', big:x.e+' '+x.zi,
          options:makeOptions(x.fan, FANCI.map(function(t){return t.fan;}), d>=4?4:3), correct:x.fan, note:x.zi+'——'+x.fan }; },
      zh_liang: function(d){ var x=LIANGCI[randInt(LIANGCI.length)];
        return { id:'liang_'+x.id, prompt:'「'+x.zi+' __ '+x.n+'」填哪个量词？', big:x.zi+' __',
          options:makeOptions(x.m, ['个','只','朵','条','棵','本','辆','双'], 4), correct:x.m, note:x.zi+x.m+x.n }; },
      math_calc: function(d){ var q=makeCalc(LEVEL_RANGE[Math.max(0,Math.min(4,d-1))], d<=1); return makeCalcItem(q); },
      math_judge: function(d){ var q=makeCalc(LEVEL_RANGE[Math.max(0,Math.min(4,d-1))], d<=1); return makeJudgeItem(q, randInt(10)); },
      math_word: function(d){ var q=makeCalc(LEVEL_RANGE[Math.max(0,Math.min(4,d-1))], d<=1); return makeWordItem(q); },
      math_order: function(d){ var pool=[]; var max=LEVEL_RANGE[Math.max(0,Math.min(4,d-1))];
        for (var n=1;n<=max;n++) pool.push(n);
        pool.sort(function(){ return Math.random()-0.5; });
        var nums=pool.slice(0,5).sort(function(a,b){ return a-b; });
        return { id:'order_'+nums.join(','), order:true, prompt:'从小到大排一排：'+nums.join('、'),
          expected:nums, correct:nums.join('|'), note:'从小到大：'+nums.join(' → ') }; },
      en_word: function(d){ var w=WORDS[randInt(WORDS.length)];
        return { id:'enword_'+w.id, prompt:(w.zh ? '“'+w.zh+'”的英文是？' : '看图画，选对应的英文单词'), big:w.emoji,
          options:makeOptions(w.en, WORDS.map(function(x){return x.en;}), d>=4?4:3), correct:w.en, note:w.en+'（'+w.zh+'）' }; },
      en_dialogue: function(d){ var x=DIALOGUES[randInt(DIALOGUES.length)];
        return { id:'endia_'+x.id, prompt:'“'+x.zh+'”用英语怎么说？', big:x.emoji+' '+x.zh,
          options:makeOptions(x.en, DIALOGUES.map(function(t){return t.en;}), d>=4?4:3), correct:x.en, note:x.en }; }
    };
    function genOne(subj, type, diff){
      var f = GEN[subj+'_'+type];
      return f ? f(diff||3) : null;
    }
    // 把 qbank 题转成题目对象
    function qbToItem(q){
      return { id:'qb_'+q.id, prompt:q.prompt,
        options:(q.options && q.options.length) ? q.options : undefined,
        input:(q.options && q.options.length) ? undefined : true,
        correct:String(q.correct), note:q.note||'' , wtype:q.type};
    }
    // 旧版固定描述(题面缺失/不完整), 需重建成完整题目
    function isLegacyPrompt(p){
      var s = p || '';
      return /(《.+?》里，空格处填什么？|这个词语对应的汉字是？|这个字怎么读？|看图画，选对应的英文单词|这句话用英语怎么说？|把数字按从小到大排好|补全《.+?》|……)/.test(s);
    }
    function poemTitle(p){ var m = (p||'').match(/《(.+?)》/); return m ? m[1] : ''; }
    // 错题重做: 尽量按存入的 prompt 从内容池重建"完整一致"的题目; 找不到就新出一题
    function rebuildWrong(subj, type, w, diff){
      var d = diff || 3;
      var out = function(it){ return it || genOne(subj, type, d); };
      var m;
      if (subj === 'zh'){
        if (type === 'poem'){
          var t = poemTitle(w.prompt);
          var src = t && POEMS.find(function(x){ return x.title === t; });
          if (src){
            var v = src.variants[randInt(src.variants.length)];
            var f2 = v.blanks.split('____');
            var hd = f2[0].replace(/[，。！？、\s]+$/,''), tl = f2[1].replace(/^[，。！？、\s]+/,'');
            return out({ id:w.q, prompt:(hd ? '《'+src.title+'》'+hd+'…' : '《'+src.title+'》…'+tl), big:v.blanks,
              options:makeOptions(v.words[0], v.words, 3), correct:v.words[0], note:src.full });
          }
        } else if (type === 'zi'){
          m = (w.prompt||'').match(/"(.+?)"对应的汉字是？/);
          var zs = m && ZI.find(function(x){ return x.word === m[1]; });
          if (zs) return out({ id:w.q, prompt:'“'+zs.word+'”对应的汉字是？', big:zs.emoji+' '+zs.word,
            options:makeOptions(zs.zi, ZI.map(function(x){ return x.zi; }), 3), correct:zs.zi, note:zs.zi+'（'+zs.pinyin+'）' });
        } else if (type === 'read'){
          m = (w.prompt||'').match(/「(.+?)」这个字怎么读？/);
          var rs = m && P_READ.find(function(x){ return x.zi === m[1]; });
          if (rs) return out({ id:w.q, prompt:'「'+rs.zi+'」这个字怎么读？', big:rs.e+' '+rs.zi,
            options:makeOptions(rs.py, P_READ.map(function(x){ return x.py; }), 3), correct:rs.py, note:rs.py });
        } else if (type === 'fan'){
          m = (w.prompt||'').match(/「(.+?)」的反义词是？/);
          var fs = m && FANCI.find(function(x){ return x.zi === m[1]; });
          if (fs) return out({ id:w.q, prompt:'「'+fs.zi+'」的反义词是？', big:fs.e+' '+fs.zi,
            options:makeOptions(fs.fan, FANCI.map(function(x){ return x.fan; }), 3), correct:fs.fan, note:fs.zi+'——'+fs.fan });
        } else if (type === 'liang'){
          m = (w.prompt||'').match(/「(.+?)\s*__\s*(.+?)」填哪个量词？/);
          var ls = m && LIANGCI.find(function(x){ return x.n === (m[2]||''); });
          if (ls) return out({ id:w.q, prompt:'「'+ls.zi+' __ '+ls.n+'」填哪个量词？', big:ls.zi+' __',
            options:makeOptions(ls.m, ['个','只','朵','条','棵','本','辆','双','支','张'], 4), correct:ls.m, note:ls.zi+ls.m+ls.n });
        }
      } else if (subj === 'en'){
        if (type === 'word'){
          m = (w.prompt||'').match(/"(.+?)"的英文是？/);
          var ws = m && WORDS.find(function(x){ return x.zh === m[1]; });
          if (ws) return out({ id:w.q, prompt:'“'+ws.zh+'”的英文是？', big:ws.emoji,
            options:makeOptions(ws.en, WORDS.map(function(x){ return x.en; }), 3), correct:ws.en, note:ws.en+'（'+ws.zh+'）' });
        } else if (type === 'dialogue'){
          m = (w.prompt||'').match(/"(.+?)"用英语怎么说？/);
          var ds = m && DIALOGUES.find(function(x){ return x.zh === m[1]; });
          if (ds) return out({ id:w.q, prompt:'“'+ds.zh+'”用英语怎么说？', big:ds.emoji+' '+ds.zh,
            options:makeOptions(ds.en, DIALOGUES.map(function(x){ return x.en; }), 3), correct:ds.en, note:ds.en });
        }
      } else if (subj === 'math'){
        if (type === 'calc'){
          m = (w.prompt||'').match(/(\d+)\s*([+\-])\s*(\d+)\s*=\s*\?/);
          if (m){
            var a=+m[1], b=+m[3], ans = m[2]==='+' ? a+b : a-b;
            return out({ id:w.q, prompt:w.prompt, input:true, correct:String(ans), note:w.prompt.replace('=?','= '+ans) });
          }
        } else if (type === 'judge'){
          m = (w.prompt||'').match(/(\d+)\s*([+\-])\s*(\d+)\s*＝\s*(\d+)/);
          if (m){
            var ja=+m[1], jb=+m[3], real = m[2]==='+' ? ja+jb : ja-jb, shown = +m[4];
            var tf = real === shown ? '对' : '错';
            return out({ id:w.q, prompt:w.prompt, options:[{v:'对',label:'✅ 对'},{v:'错',label:'❌ 错'}],
              correct:tf, note:w.prompt.replace('，对吗？','')+'（答：'+tf+'）' });
          }
        } else if (type === 'order'){
          var nums = String(w.correct||'').split('|').map(function(x){ return +x; }).sort(function(x,y){ return x-y; });
          if (nums.length) return out({ id:w.q, order:true, prompt:'从小到大排一排：'+nums.join('、'),
            expected:nums, correct:nums.join('|'), note:'从小到大：'+nums.join(' → ') });
        }
      }
      return out(null);
    }
    // 组装一关(异步): 错题优先(约半) + qbank拉题 + 现场生成补足并入库
    function assemble(subj, type){
      var diff = diffOf(subj);
      return new Promise(function(resolve){
        var items = [];
        var seen = {};
        function add(it){ if (it && it.prompt && !seen[it.prompt] && items.length<QUIZ_LEN){ seen[it.prompt]=1; items.push(it); } }
        // 1) 错题优先(~一半): 按存入的 prompt 重建完整一致的题目(旧数据自动补全/换新)
        var wrongs = (state.wrong||[]).filter(function(w){ return w.subj===subj && w.type===type; })
          .slice().sort(function(){ return Math.random()-0.5; }).slice(0, Math.ceil(QUIZ_LEN/2));
        wrongs.forEach(function(w){
          var it2 = rebuildWrong(subj, type, w, diff);
          if (!it2) return;
          it2.id = 'wg_'+w.q;
          if (isLegacyPrompt(w.prompt)) it2.note = it2.note || '';
          it2.note = (it2.note||'') + ' · 巩固';
          add(it2);
        });
        var exclude = items.map(function(i){ return i.prompt; });
        if (window.eduSync && window.eduSync.qbankPull){
          window.eduSync.qbankPull({ subj:subj, type:type, difficulty:diff, limit:QUIZ_LEN, exclude:exclude })
            .then(function(res){
              (res && res.items || []).forEach(function(q){ if (!isLegacyPrompt(q.prompt)) add(qbToItem(q)); });
              // 3) 现场生成补足, 并入库扩充题库
              var fresh = [];
              var guard=0;
              while (items.length<QUIZ_LEN && guard++<80){
                var it=genOne(subj,type,diff); if (it) fresh.push(it); add(it);
              }
              if (window.eduSync && window.eduSync.qbankEnsure && fresh.length){
                window.eduSync.qbankEnsure({ subj:subj, type:type, difficulty:diff,
                  items: fresh.filter(function(x){return x&&x.prompt;}).map(function(x){
                    return { prompt:x.prompt, options:x.options||[], correct:x.correct, note:x.note||'' };
                  }) });
              }
              resolve(items);
            })
            .catch(function(){
              var guard=0;
              while (items.length<QUIZ_LEN && guard++<80){ add(genOne(subj,type,diff)); }
              resolve(items);
            });
        } else {
          var guard=0;
          while (items.length<QUIZ_LEN && guard++<80){ add(genOne(subj,type,diff)); }
          resolve(items);
        }
      });
    }
    // 达标判断 & 记录完成 + 难度升降档
    function grade(subj, type, count){
      var passed = count >= PASS_Q;
      var pct = count / QUIZ_LEN;
      var cur = stateLevel(subj);
      if (passed && pct >= 0.9) setLevel(subj, Math.min(5, cur+1));
      else if (pct <= 0.4) setLevel(subj, Math.max(1, cur-1));
      state.adv = state.adv || {};
      state.adv[subj] = state.adv[subj] || {};
      state.adv[subj][type] = {
        passed: (state.adv[subj][type] && state.adv[subj][type].passed) ? 1 : (passed?1:0),
        best: Math.max((state.adv[subj][type]&&state.adv[subj][type].best)||0, count),
        t: Date.now() };
      saveState();
      return passed;
    }
    return { diffOf:diffOf, genOne:genOne, qbToItem:qbToItem, assemble:assemble, grade:grade, PASS_Q:PASS_Q,
             levelRange:levelRange, stateLevel:stateLevel, setLevel:setLevel };
  })();
  var wbMathMode = 'calc';
  var wbWrongActive = false;
  function wbRenderMath(){
    var body = document.getElementById('wb-math-body');
    if (wbMathMode==='wrong'){ renderWrongList(body); return; }
    wbWrongActive = false;
    quizContainerId = 'wb-math-body';
    quizSubject = 'math';
    var type = (wbMathMode==='order') ? 'order' : wbMathMode;
    var seq = ++quizSeq;
    showQuizFetching('wb-math-body');
    window.eduEngine.assemble('math', type).then(function(items){
      if (seq !== quizSeq) return;
      startQuiz('math', type, items);
    });
  }
  window.wbMath = function (k){
    wbMathMode = k;
    setTab('wb-math', k);
    wbRenderMath();
  };

  // 错题本
  function renderWrongList(body){
    var wrongs = (state.wrong||[]).filter(function(w){ return w.subj==='math'; });
    body.innerHTML = '';
    if (!wrongs.length){
      var c = document.createElement('div');
      c.className = 'edu-card';
      c.style.textAlign='center';
      c.innerHTML = '<div style="font-size:2rem;">🎉</div><h4>太棒了，数学没有错题！</h4><p class="muted">坚持练习，继续保持～</p>';
      body.appendChild(c);
      return;
    }
    var head = document.createElement('div');
    head.className = 'quiz-score-bar';
    head.style.alignItems = 'center';
    head.innerHTML = '<div class="qs-item"><div class="n">'+wrongs.length+'</div><div class="l">数学错题</div></div>'+
      '<button type="button" class="btn-soft" onclick="wbWrongQuiz()">📚 重练错题</button>';
    body.appendChild(head);
    var set = document.createElement('div');
    set.className = 'wb-set';
    wrongs.forEach(function(w){
      var item = document.createElement('div');
      item.className = 'wb-set-item';
      var shown = String(w.correct).split('|').join(' → ');
      item.innerHTML = '<span class="si-emoji">📕</span><div><div class="si-t">'+esc(w.prompt)+'</div><div class="si-d">答错 '+w.times+' 次 · 正确答案 '+esc(shown)+'</div></div>';
      set.appendChild(item);
    });
    body.appendChild(set);
  }
  window.wbWrongQuiz = function (){
    var wrongs = (state.wrong||[]).filter(function(w){ return w.subj==='math'; }).slice(0, 10);
    if (!wrongs.length){ toast('没有错题啦'); wbMath('calc'); return; }
    var items = wrongs.map(function(w){
      var t = w.type || 'calc';
      if (t==='judge'){
        return { id:w.q, wtype:'judge', prompt:w.prompt, options:[{v:'对',label:'✅ 对'},{v:'错',label:'❌ 错'}], correct:String(w.correct)==='对'?'对':'错', note:String(w.correct) };
      }
      if (t==='order'){
        var nums = String(w.correct).split('|').map(function(x){ return parseInt(x,10); }).sort(function(a,b){ return a-b; });
        return { id:w.q, wtype:'order', order:true, prompt:'把数字按从小到大排好（按顺序点一点）', expected:nums, correct:nums.join('|'), note:'从小到大：'+nums.join(' → ') };
      }
      if (t==='word'){
        var wq = String(w.prompt||'').replace(/^应用题：/,'');
        return { id:w.q, wtype:'word', prompt:'应用题', big:wq, input:true, correct:String(w.correct), note:'答案：'+w.correct };
      }
      return { id:w.q, wtype:'calc', prompt:w.prompt || String(w.q).replace(/^calc_/,''), input:true, correct:String(w.correct), note:String(w.q).replace(/^calc_/,'').replace('=?','= '+w.correct) };
    });
    quizContainerId = 'wb-math-body';
    quizSubject = 'math';
    wbWrongActive = true;
    startQuiz('math', 'wrong', items);
  };

  // ---------- 英语: 单词 ----------
  var WORDS = [
    { id:'w1', en:'apple', zh:'苹果', emoji:'🍎' },
    { id:'w2', en:'cat', zh:'小猫', emoji:'🐱' },
    { id:'w3', en:'dog', zh:'小狗', emoji:'🐶' },
    { id:'w4', en:'sun', zh:'太阳', emoji:'🌞' },
    { id:'w5', en:'book', zh:'书本', emoji:'📚' },
    { id:'w6', en:'fish', zh:'小鱼', emoji:'🐟' },
    { id:'w7', en:'ball', zh:'皮球', emoji:'⚽' },
    { id:'w8', en:'tree', zh:'大树', emoji:'🌳' },
    { id:'w9', en:'moon', zh:'月亮', emoji:'🌙' },
    { id:'w10', en:'car', zh:'汽车', emoji:'🚗' }
  ];
  var wbEnMode = 'word';
  function wbRenderEn(){
    var body = document.getElementById('wb-en-body');
    if (wbEnMode==='match'){ renderMatch(body); return; }
    quizContainerId = 'wb-en-body';
    quizSubject = 'en';
    var type = (wbEnMode==='dialogue') ? 'dialogue' : 'word';
    var seq = ++quizSeq;
    showQuizFetching('wb-en-body');
    window.eduEngine.assemble('en', type).then(function(items){
      if (seq !== quizSeq) return;
      startQuiz('en', type, items);
    });
  }
  window.wbEn = function (k){
    wbEnMode = k;
    setTab('wb-en', k);
    wbRenderEn();
  };

  // ---------- 英语: 对话 ----------
  var DIALOGUES = [
    { id:'d1', zh:'早上好！', en:'Good morning!', emoji:'🌅' },
    { id:'d2', zh:'你好！', en:'Hello!', emoji:'👋' },
    { id:'d3', zh:'谢谢！', en:'Thank you!', emoji:'🙏' },
    { id:'d4', zh:'再见！', en:'Goodbye!', emoji:'👋' },
    { id:'d5', zh:'你叫什么名字？', en:'What is your name?', emoji:'❓' },
    { id:'d6', zh:'我五岁。', en:'I am five.', emoji:'🖐️' },
    { id:'d7', zh:'对不起。', en:'I am sorry.', emoji:'😔' },
    { id:'d8', zh:'请进。', en:'Come in, please.', emoji:'🚪' },
    { id:'d9', zh:'晚安！', en:'Good night!', emoji:'🌙' },
    { id:'d10', zh:'见到你很高兴。', en:'Nice to meet you.', emoji:'😊' },
    { id:'d11', zh:'我是一个女孩。', en:'I am a girl.', emoji:'👧' }
  ];

  // ======================= 宝贝启蒙乐园 =======================
  var PAR_GAMES = [
    { key:'number', emoji:'🔢', name:'认数字', desc:'看数字选个数·1-10' },
    { key:'letter', emoji:'🅰️', name:'认字母', desc:'看图选字母 A-Z' },
    { key:'animal', emoji:'🐾', name:'动物认知', desc:'看动物选名字' },
    { key:'color', emoji:'🎨', name:'颜色认知', desc:'看颜色选名字' },
    { key:'shape', emoji:'🔷', name:'形状认知', desc:'看形状选名字' },
    { key:'picword', emoji:'🖼️', name:'看图识字', desc:'看图画选汉字' }
  ];
  var PAR = {
    number: { q:['1','2','3','4','5','6','7','8'], label:'这是数字几？', emoji:function(x){return x+' 🍎';} },
    letter: { q:['A','B','C','D','E','F','G','H'], label:'这是哪个字母？', emoji:function(x){return x;} },
    animal: { q:[{e:'🐱',n:'猫'},{e:'🐶',n:'狗'},{e:'🐮',n:'牛'},{e:'🐷',n:'猪'},{e:'🐔',n:'鸡'},{e:'🐟',n:'鱼'},{e:'🐰',n:'兔'},{e:'🐻',n:'熊'}], label:'这是什么动物？', choices:1, emoji:function(x){return x.e;} },
    color: { q:[{e:'🔴',n:'红色'},{e:'🟡',n:'黄色'},{e:'🔵',n:'蓝色'},{e:'🟢',n:'绿色'},{e:'🟣',n:'紫色'},{e:'🟠',n:'橙色'}], label:'这是什么颜色？', choices:1, emoji:function(x){return x.e;} },
    shape: { q:[{e:'🔺',n:'三角形'},{e:'🔵',n:'圆形'},{e:'🟦',n:'正方形'},{e:'⬜',n:'长方形'},{e:'⭐',n:'五角星'},{e:'💎',n:'菱形'}], label:'这是什么形状？', choices:1, emoji:function(x){return x.e;} },
    picword: { q:[{e:'🍎',n:'苹果'},{e:'🐱',n:'小猫'},{e:'🌞',n:'太阳'},{e:'📚',n:'书本'},{e:'🐟',n:'小鱼'},{e:'🌳',n:'大树'},{e:'🏠',n:'房子'},{e:'🌙',n:'月亮'}], label:'看图画，选汉字', choices:1, emoji:function(x){return x.e;} }
  };
  function parInit(){
    renderNav();
    var grid = document.getElementById('parGameGrid');
    var kid = window.eduKids.active();
    var tier = kid ? window.eduKids.tierOf(window.eduKids.ageOf(kid.birthYear)) : 'paradise';
    var pn = document.getElementById('parStarN');
    if (pn) pn.textContent = state.stars || 0;
    // 低龄(0-2)只给最基础游戏
    var allow = (tier === 'paradise_lite') ? ['number','letter','color','shape'] : null;
    var list = allow ? PAR_GAMES.filter(function(g){ return allow.indexOf(g.key) >= 0; }) : PAR_GAMES.slice();
    // 自动进入该孩子上次玩的小游戏
    var p = getPref();
    var target = (p && p.par) || parNow;
    if (target && list.some(function(g){ return g.key === target; })){
      parPlay(target);
      return;
    }
    parNow = null;
    grid.innerHTML = list.map(function(g){
      return '<button type="button" class="par-game" onclick="parPlay(\''+g.key+'\')">'+
        '<span class="pg-emoji">'+g.emoji+'</span><span class="pg-t">'+g.name+'</span><span class="pg-d">'+g.desc+'</span></button>';
    }).join('');
  }
  window.parPlay = function (key){
    parNow = key;
    prefSet('par', key);
    prefSet('mode', 'paradise');
    renderNav();
    document.getElementById('parHome').style.display='none';
    var play = document.getElementById('parPlay');
    play.style.display='';
    var cfg = PAR[key];
    // 生成 10 题
    var pool = [];
    for (var i=0;i<QUIZ_LEN;i++){
      pool.push(cfg.q[Math.floor(Math.random()*cfg.q.length)]);
    }
    var items = pool.map(function(quiz, i){
      var correctVal = cfg.choices ? quiz.n : String(quiz);
      var others = cfg.q.filter(function(x){ return String(cfg.choices?x.n:x)!==correctVal; })
        .sort(function(){ return Math.random()-0.5; }).slice(0,3);
      var opts = [correctVal].concat(others.map(function(x){ return cfg.choices?x.n:String(x); }))
        .sort(function(){ return Math.random()-0.5; });
      var lbls = opts.map(function(v){ return v; });
      return { id: key+'_'+(cfg.choices ? quiz.n : String(quiz)), prompt:cfg.label, big:(cfg.emoji ? cfg.emoji(quiz) : (quiz.e || String(quiz))), options:makeOptions(correctVal, cfg.choices?cfg.q.map(function(x){return x.n;}):cfg.q.slice(), 4), correct:correctVal, note:correctVal };
    });
    quizContainerId = 'parPlay';
    quizSubject = 'par';
    startQuiz('par', key, items);
  };
  window.parBack = function (){
    parNow = null;
    renderNav();
    document.getElementById('parPlay').style.display='none';
    document.getElementById('parHome').style.display='';
  };

  // ======================= 孩子资料 / 年龄段 =======================
  var kidEditId = null;
  var kidGenderVal = null;

  function populateYears(){
    var sel = document.getElementById('kidYearInput');
    if (!sel || sel.options.length) return;
    var y = new Date().getFullYear();
    for (var i = 0; i <= 15; i++){
      var o = document.createElement('option');
      o.value = String(y - i);
      o.textContent = (y - i) + ' 年';
      sel.appendChild(o);
    }
  }
  function openKidMask(title, sub, kid){
    populateYears();
    kidEditId = kid ? kid.id : null;
    kidGenderVal = kid ? kid.gender : null;
    document.getElementById('kidModalTitle').textContent = title;
    document.getElementById('kidModalSub').textContent = sub;
    document.getElementById('kidNameInput').value = kid ? (kid.name || '') : '';
    document.getElementById('kidYearInput').value = kid ? String(kid.birthYear) : (new Date().getFullYear());
    document.querySelectorAll('.edu-gender button').forEach(function(b){ b.classList.toggle('pick', b.getAttribute('data-g')===kidGenderVal); });
    var del = document.getElementById('kidDelBtn');
    if (del) del.style.display = kid ? 'inline-flex' : 'none';
    document.getElementById('eduMask').style.display = 'flex';
  }
  window.kidGender = function (g){
    kidGenderVal = g;
    document.querySelectorAll('.edu-gender button').forEach(function(b){ b.classList.toggle('pick', b.getAttribute('data-g')===g); });
  };
  window.kidAdd = function (){
    openKidMask('👶 新增孩子资料', '填写出生年份与性别，自动匹配年龄段内容', null);
  };
  window.kidSave = function (){
    var name = (document.getElementById('kidNameInput').value || '').trim() || '宝贝';
    var birthYear = parseInt(document.getElementById('kidYearInput').value, 10);
    if (!birthYear){ toast('请选择出生年份'); return; }
    if (!kidGenderVal){ toast('请选择性别'); return; }
    if (kidEditId){
      var old = window.eduKids.active();
      var existed = window.eduKids.byId(kidEditId);
      var merged = existed ? Object.assign({}, existed, { name: name, birthYear: birthYear, gender: kidGenderVal })
                           : { id: kidEditId, name: name, birthYear: birthYear, gender: kidGenderVal };
      window.eduKids.update(merged);
      // 若编辑的是当前孩子且没换孩子, 刷新当前页面
      if (old && old.id === kidEditId){
        if (navNow === 'learn'){ eduNav('learn'); }
        else { eduNav(navNow); }
      } else if (navNow === 'learn'){ enter(); } else { eduNav('home'); }
    } else {
      var kid = window.eduKids.add({ name: name, birthYear: birthYear, gender: kidGenderVal, created: Date.now() });
      window.eduKids.setActive(kid.id);
      eduNav('learn');
    }
    document.getElementById('eduMask').style.display = 'none';
  };
  window.kidDelete = function (){
    var id = kidEditId;
    if (!id) return;
    if (!window.confirm('确定删除这个孩子？\n该孩子的所有学习记录 / 星星 / 错题 / 星愿将一并删除，且不可恢复。')) return;
    window.eduKids.remove(id);
    try {
      localStorage.removeItem(LS_BASE + '_' + id);
      localStorage.removeItem(STR_BASE + '_' + id);
      localStorage.removeItem(EDU_PREF_PREFIX + id);
    } catch (e) {}
    document.getElementById('eduMask').style.display = 'none';
    if (window.eduKids.hasAny()){ enter(); }
    else { eduNav('home'); }
    toast('已删除孩子');
  };

  function renderKidBar(){
    var bar = document.getElementById('kidBar');
    bar.style.display = 'flex';
    var kids = window.eduKids.all();
    var kid = window.eduKids.active();
    if (!kid){
      document.getElementById('kidAva').textContent = '🧒';
      document.getElementById('kidAva').className = 'kb-ava';
      document.getElementById('kidName').textContent = '添加孩子';
      document.getElementById('kidAge').textContent = '登记后按年龄段进入学习';
      document.getElementById('kidBarStars').textContent = '';
      document.getElementById('kidPickDrop').innerHTML = '';
      return;
    }
    var age = window.eduKids.ageOf(kid.birthYear);
    var tier = window.eduKids.tierOf(age);
    document.getElementById('kidAva').textContent = window.eduKids.genderIcon(kid.gender);
    document.getElementById('kidAva').className = 'kb-ava ' + (kid.gender === 'female' ? 'b' : '');
    document.getElementById('kidName').textContent = kid.name || '宝贝';
    document.getElementById('kidAge').textContent = age + ' 岁 · ' + window.eduKids.tierLabel(tier);
    var kidStars = (load(LS_BASE + '_' + String(kid.id)) || {}).stars || 0;
    document.getElementById('kidBarStars').textContent = '⭐ ' + kidStars;
    // 下拉
    var drop = document.getElementById('kidPickDrop');
    var html = kids.map(function(k){
      var ka = window.eduKids.ageOf(k.birthYear);
      return '<div class="kit-item ' + (kid && kid.id === k.id ? 'on' : '') + '" onclick="switchKid(\''+k.id+'\')">'+
        window.eduKids.genderIcon(k.gender) + ' ' + esc(k.name || '宝贝') + '<span style="margin-left:auto;font-size:.72rem;">' + ka + '岁</span></div>';
    }).join('');
    html += '<div class="kit-item" onclick="kidAdd()"><i class="bi bi-plus-lg"></i> 添加孩子</div>';
    html += '<div class="kit-item" onclick="openBadges()"><i class="bi bi-patch-check"></i> 荣誉墙</div>';
    html += '<div class="kit-item" onclick="openSettings()"><i class="bi bi-gear"></i> 家长控制</div>';
    drop.innerHTML = html;
  }
  window.switchKid = function (id){
    window.eduKids.setActive(id);
    document.getElementById('kidPickDrop').classList.remove('show');
    enter();
  };
  window.toggleKidDrop = function (){
    document.getElementById('kidPickDrop').classList.toggle('show');
  };
  document.addEventListener('click', function (e){
    var wrap = document.getElementById('kidPickWrap');
    if (wrap && !wrap.contains(e.target)) document.getElementById('kidPickDrop').classList.remove('show');
  });

  // ======================= 教育娱乐模式：学习模式(幼小衔接/快乐乐园) =======================
  // 每个孩子独立记录 { mode, subj, par }，进入学习时自动回到该孩子上次学的课模块
  var EDU_PREF_PREFIX = 'edu_pref_v1_';
  function activeKidId(){ var k = window.eduKids.active(); return k ? String(k.id) : null; }
  function getPref(){
    var id = activeKidId();
    return id ? (load(EDU_PREF_PREFIX + id) || null) : null;
  }
  function savePref(p){
    var id = activeKidId();
    if (id) save(EDU_PREF_PREFIX + id, p);
  }
  function prefSet(k, v){
    var p = getPref() || {};
    p[k] = v;
    savePref(p);
  }
  function defaultModeFor(){
    var kid = window.eduKids.active();
    var tier = kid ? window.eduKids.tierOf(window.eduKids.ageOf(kid.birthYear)) : 'workbench';
    return (tier === 'workbench') ? 'workbench' : 'paradise';
  }
  function currentMode(){
    var p = getPref();
    var m = p && p.mode;
    return (m === 'workbench' || m === 'paradise') ? m : defaultModeFor();
  }
  function setModeUI(m){
    var wb = document.getElementById('eduWorkbench');
    var pa = document.getElementById('eduParadise');
    if (wb) wb.style.display = (m === 'workbench') ? '' : 'none';
    if (pa) pa.style.display = (m === 'paradise') ? '' : 'none';
    var opts = document.querySelectorAll('.mt-opt');
    for (var i = 0; i < opts.length; i++) opts[i].classList.toggle('active', opts[i].getAttribute('data-mode') === m);
  }
  window.switchMode = function (m){
    if (m !== 'workbench' && m !== 'paradise') return;
    var p = getPref() || {};
    p.mode = m;
    savePref(p);
    if (m === 'workbench'){ subjNow = p.subj || 'zh'; parNow = null; }
    else { parNow = p.par || null; }
    renderLearn();
    renderNav();
    toast(m === 'workbench' ? '🏫 已切换为幼小衔接' : '🌈 已切换为快乐乐园');
  };

  // ======================= 教育娱乐模式：底部导航 =======================
  var eduPages = { home: 'eduHomePage', learn: 'eduLearnPage', wish: 'eduWishPage', badges: 'eduBadgesPage' };
  var navNow = 'home';
  var subjNow = 'zh';
  var parNow = null;
  window.eduNav = function (p){
    navNow = p;
    for (var k in eduPages) document.getElementById(eduPages[k]).style.display = (k === p) ? '' : 'none';
    var kb = document.getElementById('kidBar');
    if (kb) kb.style.display = (p === 'learn' || p === 'wish') ? 'flex' : 'none';
    anim(document.getElementById(eduPages[p]));
    if (p === 'home') renderHome();
    if (p === 'wish'){ loadAllState(); renderStars(); renderWish(); }
    if (p === 'badges'){ loadAllState(); renderBadges(); }
    if (p === 'learn'){
      renderKidBar();
      loadAllState();
      renderStars();
      renderLearn();
    }
    renderNav();
  };

  // 学习页内容：按所选模式显示 幼小衔接 / 快乐乐园
  function renderLearn(){
    var m = currentMode();
    setModeUI(m);
    if (m === 'workbench') wbInit();
    else parInit();
  }

  // 动态底部导航：幼小衔接 → 语文/数学/英语；快乐乐园 → 乐园
  function renderNav(){
    var nav = document.getElementById('eduBottomNav');
    if (!nav) return;
    var m = currentMode();
    var courseIcon = { zh:'📖', math:'🔢', en:'🔤' };
    var courseLabel = { zh:'语文', math:'数学', en:'英语' };
    var items = [];
    items.push({ act: navNow === 'home', oc: "eduNav('home')", icon: '<i class="bi bi-house-door"></i>', label: '首页' });
    if (m === 'workbench'){
      ['zh','math','en'].forEach(function (s){
        items.push({ act: navNow === 'learn' && subjNow === s, oc: "navCourse('" + s + "')",
          icon: '<span class="emo">' + courseIcon[s] + '</span>', label: courseLabel[s] });
      });
    } else {
      var kid = window.eduKids.active();
      var tier = kid ? window.eduKids.tierOf(window.eduKids.ageOf(kid.birthYear)) : 'paradise';
      var allowL = (tier === 'paradise_lite') ? ['number','letter','color','shape'] : null;
      PAR_GAMES.forEach(function (g){
        if (allowL && allowL.indexOf(g.key) < 0) return;
        items.push({ act: navNow === 'learn' && parNow === g.key, oc: "navParPlay('" + g.key + "')",
          icon: '<span class="emo">' + g.emoji + '</span>', label: g.name });
      });
    }
    nav.innerHTML = items.map(function (it){
      return '<button type="button" class="edu-nav-btn' + (it.act ? ' active' : '') + '" onclick="' + it.oc + '">' +
        it.icon + '<span>' + it.label + '</span></button>';
    }).join('');
  }
  window.navCourse = function (s){
    var p = getPref() || {};
    p.mode = 'workbench';
    p.subj = s;
    savePref(p);
    subjNow = s;
    parNow = null;
    eduNav('learn');
    wbSubject(s);
  };
  window.navParPlay = function (key){
    var p = getPref() || {};
    p.mode = 'paradise';
    p.par = key;
    savePref(p);
    parNow = key;
    eduNav('learn');
    parPlay(key);
  };

  // ======================= 首页：小孩卡片 + 汇总 =======================
  function anim(el){
    if (!el) return;
    el.classList.remove('page-enter');
    void el.offsetWidth;
    el.classList.add('page-enter');
  }
  function kidSummary(id){
    var st = load(LS_BASE + '_' + String(id)) || { records: [], wrong: [], stars: 0, submits: 0, maxCombo: 0 };
    var w = load(STR_BASE + '_' + String(id)) || {};
    var recs = st.records || [];
    var ok = 0;
    recs.forEach(function(r){ if (r.ok) ok++; });
    var today = (st.usage && st.usage.date === todayStr()) ? (st.usage.n || 0) : 0;
    var wishes = st.wishes || [];
    var wishDone = wishes.filter(function(x){ return x.done; }).length;
    return {
      stars: st.stars || 0, submits: st.submits || 0, maxCombo: st.maxCombo || 0,
      n: recs.length, ok: ok, pct: recs.length ? Math.round(ok / recs.length * 100) : 0,
      wrong: (st.wrong || []).length, streak: w.streak || 0, today: today,
      wishTotal: wishes.length, wishDone: wishDone
    };
  }
  function renderHome(){
    var body = document.getElementById('eduHomeBody');
    if (!body) return;
    var kids = window.eduKids.all();
    var active = window.eduKids.active();
    var head = '<div class="edu-head"><div><div class="eh-title">🧒 我的宝贝们</div>' +
      '<div class="eh-sub">选择孩子开始学习吧</div></div>' +
      '<button type="button" class="parent-btn' + (parentUnlocked ? ' unlocked' : '') + '" id="parentModeBtn" onclick="openParentMode()"><i class="bi bi-person-gear"></i> 家长模式</button></div>';
    var all = kids.map(function(k){
      var age = window.eduKids.ageOf(k.birthYear);
      var tier = window.eduKids.tierOf(age);
      var s = kidSummary(k.id);
      var isActive = active && active.id === k.id;
      var wst = load(LS_BASE + '_' + String(k.id)) || { stars: 0, wishes: [], wishLog: [] };
      var wList = wst.wishes || [];
      var wDone = wList.filter(function(w){ return w.done; }).length;
      var wOpen = wList.filter(function(w){ return !w.done; });
      var wNext = null;
      wOpen.forEach(function(w){ if (!wNext || w.cost < wNext.cost) wNext = w; });
      var wishHtml;
      if (!wList.length){
        wishHtml = '<div class="kk-wish empty"><span class="kk-wish-title">⭐ 星愿未设置</span>' +
          '<button type="button" class="kk-btn tiny" onclick="event.stopPropagation();addWishFor(\''+k.id+'\')">➕ 添加星愿</button></div>';
      } else {
        var wpct = wList.length ? Math.round(wDone / wList.length * 100) : 0;
        var gapMsg = wOpen.length
          ? (wNext ? '距「'+esc(wNext.name)+'」（'+wNext.cost+' 星）还差 <b>'+Math.max(0, wNext.cost - (wst.stars||0))+'</b> 星'
             : '还有 '+wOpen.length+' 个心愿待兑换')
          : '🎉 全部心愿已兑换';
        wishHtml = '<div class="kk-wish">' +
          '<div class="kk-wish-head"><span class="kk-wish-title">⭐ 星愿进度</span>' +
            '<span class="kk-wish-badge">'+wDone+'/'+wList.length+'</span>' +
            '<button type="button" class="kk-btn tiny ghost" onclick="event.stopPropagation();addWishFor(\''+k.id+'\')">➕ 添加</button></div>' +
          '<div class="kw-bar"><div class="kw-bar-fill" style="width:'+wpct+'%;"></div></div>' +
          '<div class="kk-wish-sub">'+gapMsg+'</div></div>';
      }
      // 荣誉徽章(已解锁)
      var stL = load(LS_BASE + '_' + String(k.id)) || {};
      var bad = stL.badges || {};
      var badKeys = Object.keys(bad).filter(function(x){ return BADGES[x]; });
      var badgeHtml = badKeys.length
        ? '<div class="kk-badges"><span class="kk-badge-title">🏅 荣誉</span>' +
            badKeys.slice(0, 8).map(function(x){ return '<span class="kk-badge" title="'+esc(BADGES[x][1])+'：'+esc(BADGES[x][2])+'">'+BADGES[x][0]+'</span>'; }).join('') +
            (badKeys.length > 8 ? '<span class="kk-badge more">+'+(badKeys.length-8)+'</span>' : '') +
          '</div>'
        : '<div class="kk-badges empty"><span class="kk-badge-title">🏅 努力闯关，解锁更多荣誉</span></div>';
      return '<div class="kid-card' + (isActive ? ' on' : '') + '" onclick="kidEnter(\'' + k.id + '\')">' +
        '<div class="kk-top">' +
          '<span class="kk-ava' + (k.gender === 'female' ? ' b' : '') + '">' + window.eduKids.genderIcon(k.gender) + '</span>' +
          '<div class="kk-info">' +
            '<div class="kk-name">' + esc(k.name || '宝贝') + (isActive ? ' <span class="kk-cur">学习中</span>' : '') + '</div>' +
            '<div class="kk-sub">' + age + ' 岁 · ' + window.eduKids.tierLabel(tier) + '</div>' +
          '</div>' +
          '<span class="kk-stars"><i class="bi bi-star-fill"></i> ' + (s.stars || 0) + '</span>' +
        '</div>' +
        '<div class="kk-stats">' +
          '<span>今日 ' + s.today + ' 题</span><span>正确率 ' + s.pct + '%</span>' +
        '</div>' +
        badgeHtml +
        wishHtml +
        '<div class="kk-actions">' +
          '<button type="button" class="kk-btn" onclick="event.stopPropagation();kidEnter(\'' + k.id + '\')">🚀 开始学习</button>' +
          '<button type="button" class="kk-btn ghost" onclick="event.stopPropagation();kidEditById(\'' + k.id + '\')">✏️ 编辑</button>' +
        '</div>' +
      '</div>';
    }).join('');
    var add = '<div class="kid-card add" onclick="kidAdd()"><div class="kk-add"><i class="bi bi-plus-lg"></i><span>新增孩子</span></div></div>';
    var hero = kids.length ? '' :
      '<div class="edu-hero empty-hero"><div style="font-size:2.6rem;line-height:1;">👶</div>' +
      '<h2 style="margin:10px 0 4px;">欢迎来到教育乐园</h2>' +
      '<p style="color:var(--edu-muted);margin:0;">先登记一个宝贝，就能开始闯关攒星星咯</p></div>';
    body.innerHTML = head + hero + '<div class="kid-grid">' + (kids.length ? all + add : add) + '</div>';
    anim(body);
  }
  // 为指定孩子添加星愿(家长口令后跳转星愿页填写表单)
  window.addWishFor = function (id){
    requireParent(function(){
      window.eduKids.setActive(id);
      loadAllState();
      eduNav('wish');
    });
  };
  window.kidEnter = function (id){
    window.eduKids.setActive(id);
    loadAllState();
    var p = getPref();
    if (p && p.mode === 'paradise'){
      subjNow = 'zh';
      parNow = p.par || null;
    } else {
      subjNow = (p && p.subj) || 'zh';
      parNow = null;
    }
    eduNav('learn');
  };
  window.kidEditById = function (id){
    var kids = window.eduKids.all();
    for (var i = 0; i < kids.length; i++){
      if (kids[i].id === id){ openKidMask('✏️ 编辑孩子资料', '修改后按新年龄段自动切换内容', kids[i]); return; }
    }
  };

  // ======================= 星愿 =======================
  function badgeCard(k){
    var b = BADGES[k];
    var unlocked = state.badges && state.badges[k];
    return '<div class="badge-card' + (unlocked ? ' on' : '') + '">' +
      '<div class="bc-ico">' + b[0] + '</div>' +
      '<div class="bc-name">' + esc(b[1]) + '</div>' +
      '<div class="bc-desc">' + esc(b[2]) + '</div>' +
      '</div>';
  }
  function renderBadges(){
    var body = document.getElementById('eduBadgesBody');
    if (!body) return;
    var kid = window.eduKids.active();
    if (!kid){
      body.innerHTML = '<div class="edu-card" style="text-align:center;"><h4>还没有孩子</h4><p class="muted">先到首页添加孩子吧～</p></div>';
      return;
    }
    var keys = Object.keys(BADGES);
    var unlocked = keys.filter(function(k){ return state.badges && state.badges[k]; }).length;
    var html = '<div class="badge-count">🏅 已解锁 <b>' + unlocked + '</b> / ' + keys.length + ' 枚徽章</div>' +
      '<div class="badge-grid">' + keys.map(badgeCard).join('') + '</div>';
    body.innerHTML = html;
    anim(body);
  }
  function renderWish(){
    var body = document.getElementById('eduWishBody');
    if (!body) return;
    var kid = window.eduKids.active();
    if (!kid){
      body.innerHTML = '<div class="edu-card" style="text-align:center;"><h4>还没有孩子</h4><p class="muted">先到首页添加孩子吧～</p></div>';
      return;
    }
    var wishes = state.wishes || [];
    var html =
      '<div class="edu-card wish-balance"><div class="wish-stars"><i class="bi bi-star-fill"></i> ' + (state.stars || 0) + '</div>' +
      '<p class="wish-sub">攒够 ⭐ 就能兑换小心愿哦 · 可在下方「新增星愿」由家长设置</p></div>';
    if (!wishes.length){
      html += '<div class="edu-card" style="text-align:center;"><h4>🌟 还没有星愿</h4><p class="muted">家长可在下方「新增星愿」设置激励奖励～</p></div>';
    } else {
      html += '<div class="edu-card"><h4>🎯 心愿清单</h4><div class="wish-list">' + wishes.map(function(w, i){
        var can = (state.stars || 0) >= w.cost;
        return '<div class="wish-item">' +
          '<span class="wi-emoji">' + w.e + '</span>' +
          '<div class="wi-info"><div class="wi-name">' + esc(w.name) + '</div><div class="wi-cost">' + w.cost + ' 星</div></div>' +
          (w.done
            ? '<span class="wi-state">✅ 已兑换</span>'
            : '<button type="button" class="wi-btn' + (can ? ' ok' : '') + '"' + (can ? '' : ' disabled') + ' onclick="wishRedeem(' + i + ')">兑换</button>') +
          '<button type="button" class="wi-del" onclick="wishRemoveP(' + i + ')" title="删除（家长）">✕</button>' +
        '</div>';
      }).join('') + '</div></div>';
    }
    var log = state.wishLog || [];
    if (log.length){
      html += '<div class="edu-card"><h4>📜 兑换记录</h4><div class="wish-log">' +
        log.slice().reverse().slice(0, 10).map(function(l){
          return '<div class="wish-log-item"><span>' + l.date + '</span><span>' + esc(l.name) + '</span><span>−' + l.cost + ' 星</span></div>';
        }).join('') + '</div></div>';
    }
    html += parentUnlocked
      ? '<div class="edu-card" id="wishFormWrap"><h4>🎁 新增星愿（家长）</h4>' +
        '<div class="wish-form">' +
          '<div class="edu-field" style="flex:0 0 96px;"><label>图标</label><input type="text" id="wishEmoji" maxlength="2" placeholder="🎁" style="text-align:center;"></div>' +
          '<div class="edu-field" style="flex:1;"><label>心愿内容</label><input type="text" id="wishName" maxlength="12" placeholder="例如：周末去游乐场"></div>' +
          '<div class="edu-field" style="flex:0 0 92px;"><label>所需星星</label><input type="number" id="wishCost" min="1" max="999" value="10"></div>' +
        '</div>' +
        '<div class="edu-actions"><button type="button" class="btn-soft" style="flex:1;" onclick="wishAdd()">添加星愿</button></div></div>'
      : '<div class="edu-card" style="text-align:center;"><h4>🎁 新增星愿（家长）</h4>' +
        '<p class="muted" style="margin:6px 0 12px;">星愿由家长设置，孩子攒星兑换。</p>' +
        '<button type="button" class="btn-soft" onclick="requireParent(function(){ renderWish(); })">🔓 家长模式</button></div>';
    body.innerHTML = html;
    anim(body);
  }
  window.wishAdd = function (){
    var name = (document.getElementById('wishName').value || '').trim();
    if (!name){ toast('请输入心愿内容'); return; }
    var e = (document.getElementById('wishEmoji').value || '').trim() || '🎁';
    var cost = parseInt(document.getElementById('wishCost').value, 10) || 10;
    state.wishes = state.wishes || [];
    state.wishes.push({ id: 'w' + Date.now(), e: e, name: name, cost: Math.max(1, cost), done: false });
    saveState();
    renderWish();
    toast('星愿已添加');
  };
  window.wishRedeem = function (i){
    var w = state.wishes[i];
    if (!w || w.done) return;
    if ((state.stars || 0) < w.cost){ toast('星星还不够哦（还差 ' + (w.cost - state.stars) + ' 星）'); return; }
    state.stars -= w.cost;
    w.done = true;
    state.wishLog = state.wishLog || [];
    state.wishLog.push({ t: Date.now(), date: todayStr(), name: w.name, cost: w.cost });
    evalBadges(state.wrong.length, 0);
    saveState();
    renderWish();
    renderStars();
    toast('🎉 兑换成功：' + w.name + '！');
  };
  window.wishRemove = function (i){
    if (!window.confirm('删除这个星愿？')) return;
    state.wishes.splice(i, 1);
    saveState();
    renderWish();
  };
  window.wishRemoveP = function (i){
    requireParent(function(){
      if (!window.confirm('删除这个星愿？')) return;
      state.wishes.splice(i, 1);
      saveState();
      renderWish();
    });
  };

  window.resetAll = function (){
    requireParent(function(){
      if (!window.confirm('确定清空该孩子的所有学习数据（星星/记录/错题/徽章/星愿）？\n此操作不可恢复。')) return;
      state = { stars: 0, records: [], wrong: [], settings: mergeSet({}), usage: { date: todayStr(), n: 0, secs: 0 }, maxCombo: 0, badges: {}, submits: 0, wishes: [], wishLog: [] };
      wb = {};
      saveState();
      saveWb();
      toast('已重置学习数据');
      renderStars();
    });
  };

  // ======================= 家长控制设置 =======================
  window.openBadges = function (){
    document.getElementById('kidPickDrop').classList.remove('show');
    eduNav('badges');
  };
  window.openSettings = function (){
    requireParent(function(){
      var s = curSettings();
      document.getElementById('setRange').value = String(s.range);
      document.getElementById('setNoCarry').checked = !!s.nocarry;
      document.getElementById('setDailyQ').value = String(s.dailyQ);
      document.getElementById('setDailyMin').value = String(s.dailyMin);
      document.getElementById('setPwd').placeholder = parentPwd() === '0000' ? '未设置（当前为 0000）' : '已设置';
      document.getElementById('setPwd').value = '';
      document.getElementById('eduMaskSet').style.display = 'flex';
    });
  };
  window.setSave = function (){
    var pwd = (document.getElementById('setPwd').value || '').replace(/\s+/g, '');
    if (pwd && !/^\d{4}$/.test(pwd)){ toast('口令需为 4 位数字'); return; }
    if (pwd) save(PWD_KEY, pwd);
    state.settings = mergeSet({
      range: parseInt(document.getElementById('setRange').value, 10) || 20,
      nocarry: document.getElementById('setNoCarry').checked,
      dailyQ: parseInt(document.getElementById('setDailyQ').value, 10) || 0,
      dailyMin: parseInt(document.getElementById('setDailyMin').value, 10) || 0
    });
    saveState();
    document.getElementById('eduMaskSet').style.display = 'none';
    toast('学习设置已保存');
  };

  function enter(){
    renderKidBar();
    loadAllState();
    renderStars();
    eduNav('home');
  }

  // 注册后端数据回填回调：把后端该孩子的学习数据写回本地缓存(仅当本地为空)
  if (window.eduSync){
    window.eduSync.setOnState(function (kidId, dkey, data){
      if (!data) return;
      var key = (dkey === 'workbench') ? wbKeyFor(kidId) : stateKeyFor(kidId);
      if (load(key)) return; // 本地已有数据则不覆盖(以后端校验日期为准)
      save(key, data);
      var a = window.eduKids.active();
      if (a && a.id === kidId){
        if (dkey === 'workbench'){ wb = data; eduNav('learn'); }
        else { state = data; renderStars(); }
      }
    });
  }

  // 初始化
  renderNav(); // 预渲染底部导航（学习模式可能已在本地记忆）
  function boot(){
    if (window.eduKids.hasAny()){
      enter();
    } else {
      renderStars();
      eduNav('home');
      openKidMask('👶 欢迎来到教育乐园', '首次使用请先登记孩子的出生年份与性别，之后自动进入对应年龄段内容');
    }
  }
  boot();
  // 从后端数据库恢复(免登录按匿名ID / 已登录按账号)，若后端有新档案则刷新进入
  if (window.eduSync){
    window.eduSync.hydrate().then(function(){
      if (window.eduKids.hasAny()){
        var mask = document.getElementById('eduMask');
        if (mask && mask.style.display === 'flex'){
          mask.style.display = 'none';
          enter();
        }
      }
    });
  }

  // 进入时的过渡加载动画（淡出后移除，双重保险确保必被移除）
  (function(){
    var hide = null;
    function dismiss(){
      if (hide) return;
      var l = document.getElementById('eduLoader');
      if (!l) return;
      hide = 1;
      l.style.opacity = '0';
      setTimeout(function(){ if (l.parentNode) l.parentNode.removeChild(l); }, 450);
    }
    if (document.readyState === 'loading'){
      window.addEventListener('load', dismiss);
    } else { dismiss(); }
    setTimeout(dismiss, 1300);
  })();
})();
