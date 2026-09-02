(function () {
  'use strict';
  var C = window.Edu.Constants;
  var M = window.Edu.MathUtils;
  var Store = window.Edu.Store;
  var Speech = window.Edu.Speech;
  var Core = window.Edu.Core;

  var quizSeq = 0;
  // 骨架屏: 进入/续学加载时的占位动画(先展示一个「生成中」的卡片骨架, 题目就绪后由调用方替换)
  function showQuizFetching(id) {
    var el = document.getElementById(id);
    if (!el) return;
    el.innerHTML =
      '<div class="quiz-skeleton" aria-busy="true">'+
        '<div class="qs-mascot">🐻</div>'+
        '<div class="qs-title">正在准备题目…</div>'+
        '<div class="qs-line qs-w60"></div>'+
        '<div class="qs-line qs-w40"></div>'+
        '<div class="qs-opt"></div><div class="qs-opt"></div><div class="qs-opt"></div>'+
      '</div>';
  }

  var quiz = null;
  var quizContainerId = null;
  var quizSubject = null;
  var quizOrder = {};
  var recentExclude = [];

  function quizStateKey() { return 'edu_quiz_v1_' + String((window.eduKids && window.eduKids.active ? (window.eduKids.active() || {}).id : null) || 'kk'); }
  function saveQuizState() {
    try {
      if (!quiz || quiz.submitted) return;
      var inputs = document.querySelectorAll('#quizShell input.qi-in');
      inputs.forEach(function(inp){
        var idx = parseInt(inp.getAttribute && inp.getAttribute('data-idx'), 10);
        if (quiz.items[idx] && quiz.items[idx].input) quiz.answers[idx] = inp.value.replace(/\s+/g, '');
      });
      var snap = { subj: quizSubject, type: quiz.type, items: quiz.items, answers: quiz.answers || {},
        order: quizOrder || {}, view: quiz.view, submitted: false, _t: quiz._t || Date.now() };
      localStorage.setItem(quizStateKey(), JSON.stringify(snap));
    } catch (e) {}
  }
  function clearQuizState() {
    try { localStorage.removeItem(quizStateKey()); } catch (e) {}
  }

  // 上次未完成的练习快照(待用户确认是否续学)
  var resumeSnap = null;
  // 本次会话内已被用户「取消」的续学(subj+type), 取消后再进入该练习直接生成新题, 不再反复弹窗
  var dismissedResume = {};

  // 校验并缓存一个「可续学」的快照; 返回是否命中(不自动恢复)
  function hasResume(subj, type) {
    resumeSnap = null;
    if (dismissedResume[subj + ':' + type]) return false;
    var raw = null;
    try { raw = localStorage.getItem(quizStateKey()); } catch (e) { return false; }
    if (!raw || raw === 'null') return false;
    var snap = null;
    try { snap = JSON.parse(raw); } catch (e) { return false; }
    if (!snap || (snap._t && (Date.now() - snap._t > 12 * 3600 * 1000))) { clearQuizState(); return false; }
    if (snap.submitted || !snap.items || !snap.items.length) return false;
    if (snap.subj !== subj) return false;
    // 只恢复「同科目且同题型」的未完成练习；切换题型时生成新题，避免恢复错题型导致「类型对不上」
    if (snap.type !== type) return false;
    // 校验题目结构，避免恢复损坏/旧结构的题目导致页面空白「无法显示题目」
    for (var vi = 0; vi < snap.items.length; vi++) {
      var vit = snap.items[vi];
      if (!vit || typeof vit.prompt !== 'string' || !vit.prompt ||
          (vit.input === undefined && vit.order === undefined && !(vit.options && vit.options.length))) {
        clearQuizState(); return false;
      }
    }
    if (snap.view !== undefined && (snap.view < 0 || snap.view >= snap.items.length)) { clearQuizState(); return false; }
    resumeSnap = snap;
    return true;
  }

  // 真正执行恢复(用户在「继续上次」确认后调用)
  function restoreNow() {
    var snap = resumeSnap;
    resumeSnap = null;
    if (!snap) return false;
    quiz = { subj: snap.subj, type: snap.type, items: snap.items, answers: snap.answers || {}, submitted: false, _t: snap._t || Date.now(), startedAt: Date.now() };
    quiz.view = Math.min(snap.view || 0, snap.items.length - 1);
    quizSubject = snap.subj;
    quizOrder = snap.order || {};
    window.Edu.QuizEngine.quiz = quiz;
    if (snap.type === 'daily' || snap.subj === 'daily') quizContainerId = 'wb-daily';
    else if (snap.subj === 'par') quizContainerId = 'parPlay';
    else if (snap.subj === 'math') quizContainerId = 'wb-math-body';
    else if (snap.subj === 'en') quizContainerId = 'wb-en-body';
    else quizContainerId = 'wb-zh-body';
    try {
      renderQuiz();
      reapplyAnswers();
    } catch (e2) { clearQuizState(); return false; }
    if (window.Edu && window.Edu.Speech && window.Edu.Speech.toast) {
      window.Edu.Speech.toast('已为你恢复上次的练习 🌱');
    }
    return true;
  }

  function showResumePrompt() {
    var mask = document.getElementById('eduMaskResume');
    if (!mask) { restoreNow(); return; }   // 兜底: 无覆盖层则直接续学
    mask.style.display = 'flex';
  }
  function resumeYes() {
    var mask = document.getElementById('eduMaskResume');
    if (mask) { mask.style.display = 'none'; }
    restoreNow();
    if (window.renderNav) window.renderNav();
  }
  function resumeNo() {
    var mask = document.getElementById('eduMaskResume');
    if (mask) { mask.style.display = 'none'; }
    if (resumeSnap) dismissedResume[resumeSnap.subj + ':' + resumeSnap.type] = true;
    resumeSnap = null;   // 仅取消弹窗, 不开始新练习, 停留在进入前页面
  }
  function reapplyAnswers() {
    if (!quiz) return;
    var a = quiz.answers || {};
    quiz.items.forEach(function(it, i){
      if (String(a[i] || '') === '') return;
      var item = document.getElementById('qi-' + i);
      if (!item) return;
      if (it.input) {
        var inp = item.querySelector('input.qi-in');
        if (inp) inp.value = a[i];
        return;
      }
      if (it.options && a[i] !== undefined) {
        item.querySelectorAll('.qi-opt .qo-pick').forEach(function(b){ b.classList.toggle('pick', b.getAttribute('data-v') === a[i]); });
      }
    });
    updateQuizProg();
    if (window.Edu.Header) window.Edu.Header.refreshQuizHeader();
  }

  function answeredCount() {
    if (!quiz || !quiz.items) return 0;
    return quiz.items.filter(function(it, i){ return quiz.answers && quiz.answers[i] !== undefined && quiz.answers[i] !== ''; }).length;
  }

  function updateQuizProg() {
    var dots = document.getElementById('qzDots');
    var txt = document.getElementById('qzProgTxt');
    var bar = document.getElementById('qzProgBar');
    if (!quiz) return;
    var total = quiz.items.length;
    var cur = Math.min((quiz.view || 0) + 1, total);
    var pct = Math.round((cur / total) * 100);
    if (dots) dots.querySelectorAll('.qz-dot').forEach(function(d, i){
      d.classList.toggle('done', i < quiz.view);
      d.classList.toggle('cur', i === quiz.view);
    });
    if (txt) txt.textContent = '第 ' + cur + ' 题 / 共 ' + total + ' 题';
    if (bar) bar.style.width = pct + '%';
  }

  function quizAnsweredRight() {
    if (!quiz) return 0;
    return quiz.items.filter(function(it, i){ return quiz.answers && M.isCorrect(it, quiz.answers[i]); }).length;
  }

  function renderQuizProgTop() {
    if (!quiz) return '';
    var total = quiz.items.length;
    var cur = Math.min((quiz.view || 0) + 1, total);
    var pct = Math.round((cur / total) * 100);
    var dots = '';
    for (var i=0;i<total;i++) dots += '<span class="qz-dot '+(i<quiz.view?'done':'')+' '+(i===quiz.view?'cur':'')+'"></span>';
    return '<div class="qz-prog-top">'+
      '<div class="qz-prog-head"><span class="qz-prog-txt" id="qzProgTxt">第 ' + cur + ' 题 / 共 ' + total + ' 题</span>'+
      '<span class="qz-prog-pct">'+pct+'%</span></div>'+
      '<div class="qz-track"><div class="qz-fill" id="qzProgBar" style="width:'+pct+'%"></div></div>'+
      '<div class="qz-dots" id="qzDots">'+dots+'</div>'+
      '</div>';
  }

  function renderQuizFooter() {
    if (!quiz) return '';
    var total = quiz.items.length;
    var right = quizAnsweredRight();
    var allDone = (answeredCount() === total);
    var it = quiz.items[quiz.view];
    // 选择题/排序题需要先选答案, 再点「确认答案」提交(防误操作, 支持修改)
    var needConfirm = !!(it && it.options);
    var hasPicked = it && it.options && quiz.answers[quiz.view] !== undefined && quiz.answers[quiz.view] !== '';
    var actionRow = '<div class="qz-action-bar">'+
      '<div class="qz-stars">⭐ 已获得 <b>'+right+'</b> 颗星星</div>'+
      '<button type="button" class="qz-finish'+(allDone ? ' ready' : '')+'" '+(allDone ? '' : 'disabled')+' onclick="window.Edu.QuizEngine.submitQuiz()">🎉 完成闯关</button>'+
      '</div>';
    if (needConfirm) {
      actionRow += '<div class="qz-confirm-row">'+
        '<button type="button" class="btn-confirm" '+(hasPicked ? '' : 'disabled')+' id="qzConfirm" onclick="window.Edu.QuizEngine.confirmAnswer()">✅ 确认答案</button>'+
        '</div>';
    }
    return '<div class="qz-footer">'+ actionRow + '</div>';
  }

  function buildQuizCard(i) {
    var it = quiz.items[i];
    var spk = Speech.spkBtn(it.prompt, 'qi-spk');
    var h = '<div class="quiz-item" id="qi-'+i+'">';
    h += '<div class="qi-head"><span class="qi-no">'+(i+1)+'</span><span class="qi-prompt">'+M.stripBlank(it.prompt)+'</span>'+spk+'</div>';
    if (it.order) {
      h += '<div class="qi-order"><div class="qi-target" id="qo-target-'+i+'"></div>';
      h += '<div class="qi-opts" id="qo-opts-'+i+'">';
      (it.options||[]).forEach(function(o, oi){
        h += '<button type="button" class="qo-pick" data-v="'+M.stripBlank(String(M.optVal(o)))+'" onclick="window.Edu.QuizEngine.tapOrder('+i+','+oi+')">'+M.optLabel(o)+'</button>';
      });
      h += '</div><div class="qi-seq" id="qo-seq-'+i+'"></div>';
      h += '<button type="button" class="qo-clear" onclick="window.Edu.QuizEngine.clearOrder('+i+')">清空</button>';
      h += '</div>';
    } else if (it.input) {
      h += '<div class="qi-expr">'+M.stripBlank(String(it.note||it.prompt).replace(/\s*=\s*\?+\s*$/, ''))+'</div>';
      h += '<div class="qi-ans">'+(/\s*=\s*\?+\s*$/.test(String(it.prompt)) ? '<span class="qi-eq">＝</span>' : '')+'';
      h += '<input id="qi-in-'+i+'" class="qi-in" data-idx="'+i+'" type="number" inputmode="numeric" autocomplete="off" placeholder="?" aria-label="答案" oninput="window.Edu.QuizEngine.onQuizInput('+i+',this.value)" onkeydown="if(event.key===\'Enter\'){event.preventDefault();window.Edu.QuizEngine.quizInputSubmit('+i+',this.value)}">';
      h += '<button type="button" class="qi-submit" onclick="window.Edu.QuizEngine.quizInputSubmit('+i+',document.getElementById(\'qi-in-'+i+'\').value)">确认</button>';
      h += '</div></div>';
    } else {
      h += '<div class="qi-opts" id="qi-opts-'+i+'">';
      (it.options||[]).forEach(function(o, oi){
        var cls = 'qo-pick';
        var v = String(M.optVal(o));
        h += '<button type="button" class="'+cls+'" data-v="'+M.stripBlank(v)+'" onclick="window.Edu.QuizEngine.pickOpt('+i+',\''+M.stripBlank(v).replace(/'/g,"\\'")+'\')">'+M.optLabel(o)+'</button>';
      });
      h += '</div></div>';
    }
    return h;
  }

  function renderQuiz() {
    if (!quiz || !quiz.items.length) return;
    window.Edu.FAB.quickFabSet(false);
    if (quiz.view === undefined) quiz.view = 0;
    var container = document.getElementById(quizContainerId);
    if (!container) return;
    var bannerHtml = '';
    if (quizSubject !== 'par' && quizSubject) {
      bannerHtml = '<div id="quizHeader">' + window.Edu.Header.quizHeaderHtml('quiz', quizSubject, quiz.type) + '</div>';
    }
    container.innerHTML = bannerHtml + renderQuizProgTop() + buildQuizCard(quiz.view) + renderQuizFooter();
    if (quiz.items[quiz.view].input) {
      var inp = document.getElementById('qi-in-'+quiz.view);
      if (inp) setTimeout(function(){ inp.focus(); }, 100);
    }
    updateQuizProg();
    syncRestTimer();
  }

  // 每题答错的尝试次数: 用于「再试一次」重试机会(而非答错即跳过)
  var wrongTries = {};

  var advTimer = null;
  function scheduleNext(ms) {
    clearTimeout(advTimer);
    advTimer = setTimeout(function(){ advTimer = null; window.Edu.QuizEngine.quizNext(); }, ms);
  }

  window.Edu.QuizEngine = {
    showQuizFetching: showQuizFetching,
    answeredCount: answeredCount,
    updateQuizProg: updateQuizProg,
    quizAnsweredRight: quizAnsweredRight,
    renderQuizFooter: renderQuizFooter,
    buildQuizCard: buildQuizCard,
    renderQuiz: renderQuiz,
    scheduleNext: scheduleNext,
    restartExpr: restartExpr,
    get advTimer() { return advTimer; },
    set advTimer(v) { advTimer = v; },
    hasResume: hasResume,
    restoreNow: restoreNow,
    resumeYes: resumeYes,
    resumeNo: resumeNo
  };

  Object.defineProperty(window.Edu.QuizEngine, 'quiz', {
    enumerable: true,
    configurable: true,
    get: function () { return Core.quiz; },
    set: function (v) {
      quiz = v;
      Core.quiz = v;
    }
  });
  Object.defineProperty(window.Edu.QuizEngine, 'quizOrder', {
    enumerable: true,
    configurable: true,
    get: function () { return quizOrder; },
    set: function (v) { quizOrder = v; }
  });
  Object.defineProperty(window.Edu.QuizEngine, 'recentExclude', {
    enumerable: true,
    configurable: true,
    get: function () { return recentExclude; },
    set: function (v) { recentExclude = v; }
  });
  Object.defineProperty(window.Edu.QuizEngine, 'quizContainerId', {
    enumerable: true,
    configurable: true,
    get: function () { return quizContainerId; },
    set: function (v) { quizContainerId = v; }
  });
  Object.defineProperty(window.Edu.QuizEngine, 'quizSubject', {
    enumerable: true,
    configurable: true,
    get: function () { return quizSubject; },
    set: function (v) { quizSubject = v; }
  });
  Object.defineProperty(window.Edu.QuizEngine, 'quizSeq', {
    enumerable: true,
    configurable: true,
    get: function () { return quizSeq; },
    set: function (v) { quizSeq = v; }
  });

  window.resumeYes = resumeYes;
  window.resumeNo = resumeNo;

  window.Edu.QuizEngine.onQuizInput = function (idx, val) {
    if (!quiz) return;
    quiz.answers = quiz.answers || [];
    quiz.answers[idx] = val;
    updateQuizProg();
    saveQuizState();
    if (window.Edu.Header) window.Edu.Header.refreshQuizHeader();
  };

  window.Edu.QuizEngine.pickOpt = function (idx, v) {
    if (!quiz || quiz.submitted) return;
    // 仅选中答案, 不立即提交: 可修改, 需点「确认答案」才判题(防误操作)
    window.Edu.QuizEngine.onQuizInput(idx, v);
    var item = document.getElementById('qi-'+idx);
    if (item) {
      item.querySelectorAll('.qi-opts .qo-pick').forEach(function(b){
        b.classList.remove('picked-wrong');
        b.classList.toggle('selected', b.getAttribute('data-v') === v);
      });
    }
    var cbtn = document.getElementById('qzConfirm');
    if (cbtn) cbtn.disabled = false;
    // 排序题满10题时可直接确认
    if (quiz.items[idx] && quiz.items[idx].options && quiz.items[idx].type === 'order') {
      var joined = (quizOrder[idx]||[]).map(function(i){ return M.stripBlank(String(M.optVal(quiz.items[idx].options[i]))); }).join('');
      if (quizOrder[idx] && quizOrder[idx].length === quiz.items[idx].options.length) {
        window.Edu.QuizEngine.onQuizInput(idx, joined);
        if (cbtn) cbtn.disabled = false;
      }
    }
  };

  window.Edu.QuizEngine.confirmAnswer = function () {
    if (!quiz || quiz.submitted) return;
    var idx = quiz.view;
    var it = quiz.items[idx];
    if (!it) return;
    var val = quiz.answers && quiz.answers[idx];
    if (it.options && it.type === 'order') {
      // 排序题: 由已选顺序拼出答案
      var arr = quizOrder[idx] || [];
      if (arr.length === it.options.length) {
        val = arr.map(function(i){ return M.stripBlank(String(M.optVal(it.options[i]))); }).join('');
        window.Edu.QuizEngine.onQuizInput(idx, val);
      }
    }
    if (val === undefined || val === '') return;
    var ok = M.isCorrect(it, val);
    var cbtn = document.getElementById('qzConfirm');
    var item = document.getElementById('qi-'+idx);
    // 输入型题目做成: 答错给一次重试, 再错即揭示正确答案
    if (it.options && it.type === 'order') {
      if (ok) {
        lockOptions(idx, cbtn, '下一题 ▶');
        showSingleFeedback(idx, true);
        scheduleNext(1500);
      } else {
        wrongTries[idx] = (wrongTries[idx] || 0) + 1;
        if (wrongTries[idx] >= 2) { lockOptions(idx, cbtn); showSingleFeedback(idx, false, true); addNextButton(); }
        else { showSingleFeedback(idx, false, false); if (cbtn) cbtn.disabled = true; }
      }
      return;
    }
    if (it.options) {
      // 选择题: 提供「再试一次」的重试机会, 而非答错即跳过
      if (ok) {
        lockOptions(idx, cbtn, '下一题 ▶');
        showSingleFeedback(idx, true);
        scheduleNext(1500);
      } else {
        wrongTries[idx] = (wrongTries[idx] || 0) + 1;
        if (wrongTries[idx] >= 2) {
          revealCorrect(idx);
          lockOptions(idx, cbtn);
          showSingleFeedback(idx, false, true);
          addNextButton();
        } else {
          // 第一次答错: 温和提示, 保留可选, 再给一次机会
          showSingleFeedback(idx, false, false);
          if (cbtn) { cbtn.disabled = true; cbtn.textContent = '再试一次'; }
          if (item) {
            item.querySelectorAll('.qi-opts .qo-pick').forEach(function (b) {
              b.classList.add('picked-wrong');
              var okB = b.getAttribute('data-v') === it.correct;
              if (!okB) { /* 保留已选的高亮, 稍作弱化 */ }
            });
          }
        }
      }
      return;
    }
    // 无 options 的输入题由 quizInputSubmit 处理
    lockOptions(idx, cbtn, '下一题 ▶');
    showSingleFeedback(idx, ok);
    scheduleNext(1400);
  };

  function addNextButton() {
    if (!quiz || quiz.submitted) return;
    var container = document.getElementById(quizContainerId);
    if (!container) return;
    var isLast = (quiz.view >= quiz.items.length - 1);
    var label = isLast ? '🎉 查看结果' : '下一题 ▶';
    var h = '<div class="qz-next-row"><button type="button" class="qz-next" onclick="window.Edu.QuizEngine.quizNext()">'+label+'</button></div>';
    // 去重: 避免多次触发时累计多个本地按钮(insertAdjacentHTML 与 append 两条路径)
    var parentBox = container;
    var prev = (container.querySelector ? container.querySelector('.qz-next-row') : null);
    if (prev && prev.parentNode) prev.parentNode.removeChild(prev);
    var bar = (container.querySelector ? container.querySelector('.qz-action-bar') : null);
    if (bar && bar.insertAdjacentHTML) { bar.insertAdjacentHTML('afterend', h); return; }
    if (!container.querySelector || !container.appendChild) return;
    var div = document.createElement('div');
    div.className = 'qz-next-row';
    div.innerHTML = h;
    container.appendChild(div);
  }

  function lockOptions(idx, cbtn, label) {
    if (cbtn) { cbtn.disabled = true; cbtn.textContent = label || '已提交'; }
    var item = document.getElementById('qi-' + idx);
    if (item) {
      item.querySelectorAll('.qi-opts .qo-pick').forEach(function (b) { b.disabled = true; });
      item.querySelectorAll('.qo-clear').forEach(function (b) { b.disabled = true; });
    }
  }

  function revealCorrect(idx) {
    var it = quiz.items[idx];
    if (!it || !it.options) return;
    var item = document.getElementById('qi-' + idx);
    if (!item) return;
    item.querySelectorAll('.qi-opts .qo-pick').forEach(function (b) {
      if (b.getAttribute('data-v') === it.correct) b.classList.add('reveal-correct');
      else if (b.classList.contains('selected')) b.classList.add('picked-wrong');
    });
  }

  window.Edu.QuizEngine.tapOrder = function (idx, oi) {
    if (!quiz || quiz.submitted) return;
    var it = quiz.items[idx];
    quizOrder[idx] = quizOrder[idx] || [];
    if (quizOrder[idx].includes(oi)) return;
    quizOrder[idx].push(oi);
    renderOrderSeq(idx);
    var cbtn = document.getElementById('qzConfirm');
    if (cbtn) cbtn.disabled = !(quizOrder[idx].length === (it.options||[]).length);
  };

  window.Edu.QuizEngine.clearOrder = function (idx) {
    quizOrder[idx] = [];
    renderOrderSeq(idx);
  };

  function renderOrderSeq(idx) {
    var seq = document.getElementById('qo-seq-'+idx);
    var target = document.getElementById('qo-target-'+idx);
    if (!seq || !quiz || !quiz.items[idx]) return;
    var it = quiz.items[idx];
    var arr = quizOrder[idx] || [];
    seq.innerHTML = arr.map(function(oi, si){
      return '<span class="qo-chip">'+(si+1)+'. '+M.optLabel(it.options[oi])+'</span>';
    }).join('');
    target.innerHTML = arr.length ? '' : '点击下方选项排序...';
  }

  function showSingleFeedback(idx, ok, reveal) {
    if (!quiz) return;
    var it = quiz.items[idx];
    var item = document.getElementById('qi-'+idx);
    if (!item) return;
    if (ok === undefined) ok = M.isCorrect(it, quiz.answers[idx]);
    var feed = item.querySelector('.qi-feed') || (function(){
      var f = document.createElement('div');
      f.className = 'qi-feed';
      item.appendChild(f);
      return f;
    })();
    if (ok) {
      // 正确: 正向激励(星星收集动画 + 奖杯/鼓励语)
      feed.className = 'qi-feed offer';
      feed.innerHTML = '<span class="pr-emoji">⭐</span><span class="star-collect" aria-hidden="true">⭐</span><span>'+Speech.encPick(C.PRAISE_MSGS)+'</span>';
      rewardFloat('⭐', Speech.encPick(C.PRAISE_MSGS));
      Speech.playSpeak('答对啦');
    } else if (reveal) {
      // 第二次答错: 揭示正确答案, 作为「教学时刻」(先给机会, 再展示答案)
      feed.className = 'qi-feed reveal';
      var correctTxt = String(it.correct == null ? '' : it.correct).split('|').join(' ');
      feed.innerHTML = '<span>💡</span><span>正确答案是 <b>'+esc(correctTxt)+'</b></span>';
      Speech.playSpeak('正确答案是 ' + correctTxt);
    } else {
      // 第一次答错: 温和提示, 用「再试一次✨」鼓励重试(选项保持可选)
      feed.className = 'qi-feed gentle';
      feed.innerHTML = '<span>🌱</span><span>'+Speech.encPick(C.WRONG_MSGS)+' 再试一次✨</span>';
      Speech.playSpeak(Speech.encPick(C.ENC_WRONG) || '再试一次');
    }
  }

  function rewardFloat(emoji, txt) {
    var old = document.querySelector('.reward-float');
    if (old && old.parentNode) old.parentNode.removeChild(old);
    var el = document.createElement('div');
    el.className = 'reward-float';
    el.innerHTML = '<span class="rf-emoji">'+emoji+'</span><span class="rf-txt">'+txt+'</span>';
    document.body.appendChild(el);
    setTimeout(function(){ if (el.parentNode) el.parentNode.removeChild(el); }, 1400);
  }

  function starBurst() {
    var bar = document.getElementById('kbStarBar');
    if (bar) { bar.style.transform = 'scale(1.3)'; setTimeout(function(){ bar.style.transform = ''; }, 150); }
  }

  window.Edu.QuizEngine.submitQuiz = function () {
    if (!quiz || quiz.submitted) return;
    quiz.submitted = true;
    var right = 0, maxCombo = 0, combo = 0;
    quiz.items.forEach(function(it, i){
      var ok = M.isCorrect(it, quiz.answers && quiz.answers[i]);
      if (ok) { right++; combo++; maxCombo = Math.max(maxCombo, combo); }
      else { combo = 0; }
      recordAnswer(quizSubject, it.type || quizSubject, it.id, it.prompt, it.correct, quiz.answers && quiz.answers[i], ok);
    });
    var starsEarned = M.gradeQuiz(right, maxCombo);
    Store.state.stars = (Store.state.stars || 0) + starsEarned;
    Store.state.submits = (Store.state.submits || 0) + 1;
    // 今日答题数/题量上限统计(自动回写 usage[date])
    var us = Store.usageForToday ? Store.usageForToday() : null;
    if (us) { us.n = (us.n || 0) + quiz.items.length; us.count = (us.count || 0) + quiz.items.length; }
    Store.addStarLog(starsEarned);
    Store.saveState();
    window.Edu.Parent.renderStars();
    if (window.Edu.Legacy) window.Edu.Legacy.evalBadges(quiz.items.length - right, maxCombo);

    // 游戏化课程地图 / 激励结算: 评星(正确+用时短+首次尝试) + 通关解锁 + 积分 + 里程碑
    var triesUsed = 0;
    for (var ti in quiz.items) { if (wrongTries[ti]) triesUsed++; }
    var duration = (Date.now() - (quiz.startedAt || Date.now())) / 1000;
    Store.addDailySecs(duration);
    var fast = duration < 60;
    var courseRes = null;
    if (window.Edu && window.Edu.Course) {
      courseRes = window.Edu.Course.recordQuizResult(quizSubject, quiz.type || quizSubject, {
        right: right, total: quiz.items.length, triesUsed: triesUsed, fast: fast
      });
    }

    clearRestTimer();
    clearQuizState();
    if (window.renderNav) window.renderNav();
    var container = document.getElementById(quizContainerId);
    if (container) {
      var total = quiz.items.length || 1;
      var pct = Math.round((right / total) * 100);
      var passed = pct >= 60;
      var unlockTxt = '';
      if (passed) {
        var lv = Store.stateLevel ? Store.stateLevel(quizSubject) : 1;
        unlockTxt = '<div class="qd-unlock">🚀 已解锁 <b>难度档 '+Math.min(5, lv + 1)+'</b></div>';
      }
      // 关卡进度行: 显示本局评星 / 通关解锁 / 积分奖励
      var courseLine = '';
      if (courseRes) {
        if (courseRes.passedNow) {
          courseLine = '<div class="qd-course pass">' +
            '<span class="qc-stars">'+String('⭐'.repeat(courseRes.stars) || '')+'</span>' +
            '<span>恭喜通关「'+esc(courseRes.levelName)+'」</span>' +
            (courseRes.unlockedNext ? '<span class="qc-next">▶ 下一关：'+esc(courseRes.unlockedNext)+' 已解锁</span>' : '') +
            (courseRes.milestones && courseRes.milestones.length ? '<span class="qc-mil">🎖️ '+esc(courseRes.milestones[0].txt)+' 里程碑达成（+'+courseRes.milestones[0].pts+' 积分）</span>' : '') +
            '</div>';
        } else if (courseRes.tryAgain) {
          courseLine = '<div class="qd-course retry">' +
            '<span>还差一点点～正确率达到 80% 或拿到 3 星即可通关，再试一次吧！</span>' +
            '</div>';
        } else if (courseRes.dailyDone || courseRes.freePractice) {
          courseLine = '<div class="qd-course plain">' +
            '<span>继续加油，完成闯关关卡可解锁课程地图下一关 🗺️</span>' +
            '</div>';
        }
      }
      var encourag = passed
        ? (pct >= 90 ? '太棒了！全部拿下，继续加油！' : '不错哦，继续保持！')
        : '没关系，温习一下错题，再来一次肯定更棒！';
      container.innerHTML = '<div class="quiz-done qd-wrap">'+
        '<div class="qd-emoji">🎉</div>'+
        '<div class="qd-title">闯关完成！</div>'+
        '<div class="qd-stats">'+
          '<div class="qd-num"><b>'+right+'</b><span>答对</span></div>'+
          '<div class="qd-num"><b>'+pct+'%</b><span>正确率</span></div>'+
          '<div class="qd-num"><b>'+starsEarned+'</b><span>星星</span></div>'+
        '</div>'+
        '<div class="qd-enc">'+encourag+'</div>'+
        unlockTxt+
        courseLine+
        '<div class="qz-action-row qd-actions">'+
          '<button type="button" class="btn-home" onclick="window.Edu.Workbench&&window.Edu.Workbench.quickHome&&window.Edu.Workbench.quickHome()">🏠 返回首页</button>'+
          '<button type="button" class="btn-again" onclick="'+restartExpr()+'">🔁 再练一次</button>'+
        '</div></div>';
    }
  };

  function recordAnswer(subj, type, qid, prompt, correct, got, ok) {
    var rec = { t:Date.now(), subj:subj, type:type, qid:qid, prompt:prompt, correct:correct, got:got, ok:ok };
    Store.state.records = Store.state.records || [];
    Store.state.records.unshift(rec);
    if (Store.state.records.length > 500) Store.state.records.length = 500;
    if (!ok) {
      Store.state.wrong = Store.state.wrong || [];
      Store.state.wrong.unshift({ subj:subj, type:type, qid:qid, prompt:prompt, correct:correct, got:got, t:Date.now() });
      if (Store.state.wrong.length > 200) Store.state.wrong.length = 200;
    }
    Store.saveState();
    if (window.eduSync && window.eduSync.qbankLearn) {
      window.eduSync.qbankLearn({ subj:subj, type:type, prompt:prompt, correct:ok, difficulty:window.Edu.MathUtils.diffOf(subj) });
    }
  }

  function restartExpr() {
    if (quiz && quiz.type === 'daily') return 'window.startDaily()';
    if (quizSubject === 'par') return 'window.parPlay(\'' + (quiz && quiz.type) + '\')';
    if (quizSubject === 'en') return 'window.wbEn(\'' + (window.Edu.EnWorkbench.wbEnMode || 'word') + '\')';
    if (quizSubject === 'math') return 'window.wbMath(\'' + (window.Edu.MathWorkbench.wbMathMode || 'calc') + '\')';
    return 'window.wbZh(\'' + (window.Edu.ZhWorkbench.wbZhMode || 'zi') + '\')';
  }

  window.Edu.QuizEngine.restartQuiz = function () {
    if (!quiz) return;
    var subj = quizSubject, type = quiz.type, diff = quiz.difficulty;
    quiz = null;
    window.Edu.QuizEngine.quiz = null;
    if (type === 'daily') { window.startDaily(); return; }
    if (subj === 'math') window.wbMath(window.Edu.MathWorkbench.wbMathMode || 'calc');
    else if (subj === 'en') window.wbEn(window.Edu.EnWorkbench.wbEnMode || 'word');
    else window.wbZh(window.Edu.ZhWorkbench.wbZhMode || 'zi');
  };

  window.Edu.QuizEngine.regenQuiz = function () {
    if (!quiz) return;
    window.Edu.QuizEngine.restartQuiz();
  };

  window.Edu.QuizEngine.quizInputSubmit = function (idx, val) {
    window.Edu.QuizEngine.onQuizInput(idx, val);
    if (!quiz || quiz.submitted) return;
    var it = quiz.items[idx];
    if (it && it.input && String(quiz.answers[idx]||'').trim()) {
      var inp = document.getElementById('qi-in-'+idx);
      if (inp) inp.disabled = true;
      var ok = M.isCorrect(it, quiz.answers[idx]);
      // 输入题: 答对自动跳下一题(1.5s + 星星动画); 答错揭示正确答案并显示「下一题 ▶」, 不自动跳转
      if (ok) {
        showSingleFeedback(idx, true);
        scheduleNext(1500);
      } else {
        showSingleFeedback(idx, false, true);
        addNextButton();
      }
    }
  };

  window.Edu.QuizEngine.quizNext = function () {
    if (!quiz || quiz.submitted) return;
    if (quiz.view < quiz.items.length - 1) {
      quiz.view++;
      renderQuiz();
    } else {
      if (answeredCount() === quiz.items.length) {
        window.Edu.QuizEngine.submitQuiz();
      }
    }
  };

  window.Edu.QuizEngine.startQuiz = function (subj, type, items, levelInfo) {
    // 正在做同一套练习时再次进入(如再次点击该科目标签): 直接重新生成新题, 不弹续学遮罩
    var isLive = !!(quiz && !quiz.submitted && quizSubject === subj && quiz.type === type);
    if (!isLive) {
      // 存在上次未完成练习时：给出「继续上次 / 取消」交互提示, 不自动恢复也不自动开始
      if (hasResume(subj, type)) { showResumePrompt(); return; }
    }
    delete dismissedResume[subj + ':' + type];
    quizSubject = subj;
    quiz = { items: items, type: type, difficulty: levelInfo && levelInfo.difficulty, answers: {}, view: 0, submitted: false, _t: Date.now(), startedAt: Date.now() };
    window.Edu.QuizEngine.quiz = quiz;
    quizOrder = {};
    wrongTries = {};
    Store.state.courseIn = null;
    saveQuizState();
    if (type === 'daily' || subj === 'daily') quizContainerId = 'wb-daily';
    else if (subj === 'par') quizContainerId = 'parPlay';
    else if (subj === 'math') quizContainerId = 'wb-math-body';
    else if (subj === 'en') quizContainerId = 'wb-en-body';
    else quizContainerId = 'wb-zh-body';
    renderQuiz();
    if (window.renderNav) window.renderNav();
  };

  // 练习未完成时离开: 弹窗确认; 同时把最新作答实时写入 localStorage, 保证刷新/切后台不掉进度
  if (typeof window.addEventListener === 'function') {
    window.addEventListener('beforeunload', function (e) {
      if (quiz && !quiz.submitted) {
        saveQuizState();
        e.preventDefault();
        e.returnValue = '';
        return '';
      }
    });
  }

  // 切后台/切回前台: 隐藏时保存最新进度(刷新/退到桌面也不丢答案)
  if (typeof document.addEventListener === 'function') {
    document.addEventListener('visibilitychange', function () {
      if (document.hidden && quiz && !quiz.submitted) saveQuizState();
    });
  }

  // 考试模式: 切屏时记录提醒(简单实现: 监听可见性变化并在恢复时轻提示)
  if (typeof document.addEventListener === 'function') {
    document.addEventListener('visibilitychange', function () {
      if (document.hidden && quiz && !quiz.submitted && quiz.examMode && window.Edu && window.Edu.Speech) {
        window.Edu.Speech.toast('考试模式：请集中精力，不要切屏哦');
      }
    });
  }

  // ============ 护眼休息: 累计学习 ≥20 分钟弹出「休息一下 🌳」 ============
  var REST_KEY = 'edu_rest_v1_' + String((window.eduKids && window.eduKids.active ? (window.eduKids.active() || {}).id : null) || 'kk');
  function restLimit() {
    // 护眼时长(分钟/秒): 家长控制「护眼提醒」可调, 默认 20 分钟
    var m = parseInt((Store.curSettings() || {}).eyeMin, 10);
    if (!(m > 0)) m = C.REST_DEFAULT || 20;
    return m * 60;
  }
  var restAccum = 0;
  var restTimer = null;
  var restLastTick = 0;
  var restOverlay = null;

  function restLoad() {
    try { return parseInt(localStorage.getItem(REST_KEY), 10) || 0; } catch (e) { return 0; }
  }
  function restSave(v) {
    try { localStorage.setItem(REST_KEY, String(v)); } catch (e) {}
  }
  function restResetAccum() { if (restAccum >= restLimit()) restAccum = 0; }
  function isPageVisible() {
    // 浏览器里返回 document.visibilityState === 'visible'; node 测试环境为 undefined → 视为不可见, 不启动计时, 避免测试进程被 interval 挂起
    try { return document.visibilityState === 'visible'; } catch (e) { return false; }
  }
  function syncRestTimer() {
    if (isPageVisible() && quiz && !quiz.submitted) {
      restLoad();
      if (!restTimer) { restLastTick = Date.now(); restTimer = setInterval(restTick, 1000); }
    } else {
      if (restTimer) { clearInterval(restTimer); restTimer = null; }
      restLoad();
    }
  }

  function restTick() {
    var now = Date.now();
    if (restLastTick) restAccum += Math.round((now - restLastTick) / 1000);
    restLastTick = now;
    if (restAccum >= restLimit()) {
      stopRestTick();
      showRestOverlay();
      restAccum = 0;
      restSave(0);
    } else {
      restSave(restAccum);
    }
  }
  function startRestTick() {
    if (restTimer) return;
    restLastTick = Date.now();
    restTimer = setInterval(restTick, 1000);
  }
  function stopRestTick() {
    if (restTimer) { clearInterval(restTimer); restTimer = null; }
  }

  function showRestOverlay() {
    var old = document.getElementById('restOverlay');
    if (old && old.parentNode) old.parentNode.removeChild(old);
    var div = document.createElement('div');
    div.id = 'restOverlay';
    div.className = 'rest-overlay';
    div.innerHTML = '<div class="rest-card">'+
      '<div class="rest-emoji">🌳</div>'+
      '<div class="rest-title">休息一下</div>'+
      '<div class="rest-sub">眼睛累了，喝口水、望望远，休息片刻再来闯关吧～</div>'+
      '<button type="button" class="rest-ok" onclick="window.Edu.QuizEngine.dismissRest()">好的，继续</button>'+
      '</div>';
    document.body.appendChild(div);
    window.Edu.QuizEngine.restOverlay = div;
  }
  function dismissRest() {
    var old = document.getElementById('restOverlay');
    if (old && old.parentNode) old.parentNode.removeChild(old);
    restOverlay = null;
    restResetAccum();
    restSave(0);
  }

  // 公共钩子(声明提升, 供 submitQuiz 等引用): 答题进入启停护眼计时, 也便于测试
  function startRestTimer() {
    restLoad();
    startRestTick();
  }
  function clearRestTimer() {
    stopRestTick();
    restSave(restAccum);
  }
  window.Edu.QuizEngine.startRestTimer = startRestTimer;
  window.Edu.QuizEngine.clearRestTimer = clearRestTimer;
  window.Edu.QuizEngine.showRestOverlay = showRestOverlay;
  window.Edu.QuizEngine.dismissRest = dismissRest;
  window.Edu.QuizEngine.restAccum = function () { return restAccum; };
  window.Edu.QuizEngine.restLimit = restLimit;

  window.onQuizInput = window.Edu.QuizEngine.onQuizInput;
  window.pickOpt = window.Edu.QuizEngine.pickOpt;
  window.tapOrder = window.Edu.QuizEngine.tapOrder;
  window.clearOrder = window.Edu.QuizEngine.clearOrder;
  window.submitQuiz = window.Edu.QuizEngine.submitQuiz;
  window.quizInputSubmit = window.Edu.QuizEngine.quizInputSubmit;
  window.quizNext = window.Edu.QuizEngine.quizNext;
  window.startQuiz = window.Edu.QuizEngine.startQuiz;
  window.restartQuiz = window.Edu.QuizEngine.restartQuiz;
  window.renderQuiz = window.Edu.QuizEngine.renderQuiz;
  window.scheduleNext = window.Edu.QuizEngine.scheduleNext;
})();