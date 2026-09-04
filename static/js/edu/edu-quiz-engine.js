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

  function answeredCount() {
    if (!quiz || !quiz.items) return 0;
    return quiz.items.filter(function(it, i){ return quiz.answers && quiz.answers[i] !== undefined && quiz.answers[i] !== ''; }).length;
  }

  // 每题星星状态: done=答对(金), wrong=答错(黑), empty=未答(空心)
  function starState(i) {
    var it = quiz.items[i];
    if (it.order) {
      var o = (quiz.quizOrder && quiz.quizOrder[i]) || [];
      if (!o.length) return 'empty';
      return String(o.join('|')) === String(it.correct) ? 'done' : 'wrong';
    }
    var my = quiz.answers && quiz.answers[i];
    if (my === undefined || String(my).trim() === '') return 'empty';
    return M.isCorrect(it, my) ? 'done' : 'wrong';
  }

  function starRowHtml() {
    var s = '';
    for (var i = 0; i < quiz.items.length; i++) {
      var st = starState(i);
      s += '<span class="qstar ' + st + '">' + (st === 'empty' ? '☆' : '⭐') + '</span>';
    }
    return s;
  }

  function updateQuizProg() {
    if (!quiz) return;
    var total = quiz.items.length;
    var right = quizAnsweredRight();
    var pct = total ? Math.round((right / total) * 100) : 0;
    var starsEl = document.getElementById('qzProgStars');
    var bar = document.getElementById('qzProgBar');
    if (starsEl) starsEl.innerHTML = starRowHtml();
    if (bar) bar.style.width = pct + '%';
  }

  function quizAnsweredRight() {
    if (!quiz) return 0;
    return quiz.items.filter(function(it, i){ return quiz.answers && M.isCorrect(it, quiz.answers[i]); }).length;
  }

  function renderQuizProgTop() {
    if (!quiz) return '';
    var total = quiz.items.length;
    var right = quizAnsweredRight();
    var pct = total ? Math.round((right / total) * 100) : 0;
    return '<div class="qz-prog-top">'+
      '<div class="qz-stars" id="qzProgStars">'+ starRowHtml() +'</div>'+
      '<div class="qz-track"><div class="qz-fill" id="qzProgBar" style="width:'+pct+'%"></div></div>'+
      '</div>';
  }

  function renderQuizFooter() {
    if (!quiz) return '';
    var total = quiz.items.length;
    var allDone = (answeredCount() === total);
    // 累计获得的星星: 展示在底部操作栏左侧, 与「完成闯关」同一行, 不单独占行
    var cumStars = (Store.state && Store.state.stars) || 0;
    var cumHtml = cumStars > 0
      ? '<span class="qz-cumstars">⭐ 累计 '+cumStars+' 颗</span>'
      : '';
    // 全部答完才出现「完成闯关」按钮; 未答完不渲染占位按钮, 避免空按钮残留
    var btnHtml = allDone
      ? '<button type="button" class="qz-finish ready" onclick="window.Edu.QuizEngine.submitQuiz()">🎉 完成闯关</button>'
      : '';
    return '<div class="qz-footer">'+
      '<div class="qz-action-bar">'+ cumHtml +'<div class="qz-progress"></div>'+ btnHtml +'</div>'+
      '</div>';
  }

  // 听音选字: 重播按钮播放当前题目读音
  function replaySpeak() {
    var it = quiz && quiz.items && quiz.items[quiz.view];
    if (it && it.listen) Speech.playSpeak(it.listen, 1);
  }

  // 听音题自动播放: 渲染后播读音, 便于「听语音→选字」
  function autoplayListen(i) {
    var it = quiz.items[i];
    if (it && it.listen) {
      Speech.preloadTTS(it.listen);          // 预热音频, 缓解首播延迟
      setTimeout(function(){ Speech.playSpeak(it.listen); }, 60);
    }
  }

  function buildQuizCard(i) {
    var it = quiz.items[i];
    var isListen = !!it.listen;
    var spk = isListen ? '' : Speech.spkBtn(it.prompt, 'qi-spk');
    // 读物题(选项一个大字): 题干用大字展示目标字, 控制行用"看它不是"? 仍是"找出"引导
    var isCharPick = !it.order && !it.input && it.options && /^[\u4e00-\u9fa5]$/.test(String(it.prompt||''));
    var headPrompt = isCharPick ? '找一找：哪个是下面这个字？' : it.prompt;
    // 口算题: 题干即算式, 算式并入答案行与输入框同行展示, 题干区不再重复显示算式
    if (it.input) {
      var _pv = M.stripBlank(String(it.prompt));
      var _nv = String(it.note || it.prompt).replace(/\s*=\s*\?+\s*$/, '');
      var _nm = function(s){ return s.split(/\s+/).join('').replace(/−/g,'-').replace(/×/g,'*').replace(/÷/g,'/'); };
      if (_nm(_pv) === _nm(_nv)) headPrompt = '';
    }
    var h = '<div class="quiz-item" id="qi-'+i+'">';
    if (isListen) {
      // 听音选字: 🔊 重播按键内联到题干同一行(与其它题朗读键样式统一)
      h += '<div class="qi-head"><span class="qi-no">'+(i+1)+'</span><span class="qi-prompt">'+M.stripBlank(headPrompt)+'</span>' +
        '<button type="button" class="qi-listen-btn inline" onclick="window.Edu.QuizEngine.replaySpeak()" aria-label="再听一遍">🔊</button>' +
        '<span class="qi-listen-hint">再听一遍</span></div>';
    } else {
      h += '<div class="qi-head"><span class="qi-no">'+(i+1)+'</span><span class="qi-prompt">'+M.stripBlank(headPrompt)+'</span>'+spk+'</div>';
    }
    if (isCharPick) h += '<div class="qi-big">'+M.stripBlank(it.prompt)+'</div>';
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
      // 题干下方只展示与题干不同的「算式小结」(应用题模板→数字式); 口算题题干已是算式, 不重复显示
      var exprV = String(it.note || it.prompt).replace(/\s*=\s*\?+\s*$/, '');
      var pV = M.stripBlank(String(it.prompt));
      var norm = function(s){ return s.split(/\s+/).join('').replace(/−/g,'-').replace(/×/g,'*').replace(/÷/g,'/'); };
      if (norm(exprV) !== norm(pV)) {
        // 应用题: 题干文字保留, 数字式算式单独展示
        h += '<div class="qi-expr">'+M.stripBlank(exprV)+'</div>';
      }
      h += '<div class="qi-ans">'+
        (norm(exprV) === norm(pV) ? '<span class="qi-eq-text">'+M.stripBlank(exprV)+'</span><span class="qi-eq">＝</span>' : (/\s*=\s*\?+\s*$/.test(String(it.prompt)) ? '<span class="qi-eq">＝</span>' : ''))+
      '<input id="qi-in-'+i+'" class="qi-in" data-idx="'+i+'" type="number" inputmode="numeric" autocomplete="off" placeholder="?" aria-label="答案" oninput="window.Edu.QuizEngine.onQuizInput('+i+',this.value)" onkeydown="if(event.key===\'Enter\'){event.preventDefault();window.Edu.QuizEngine.quizInputSubmit('+i+',this.value)}">';
      h += '<button type="button" class="qi-submit" onclick="window.Edu.QuizEngine.quizInputSubmit('+i+',document.getElementById(\'qi-in-'+i+'\').value)">确认</button>';
      h += '</div></div>';
    } else {
      // 选项题: 题干用大字突出展示(拼音/笔顺等带 big 的), 建立"看图字→选"的清晰对应
      if (it.big != null && it.big !== '') {
        h += '<div class="qi-big">'+M.stripBlank(String(it.big))+'</div>';
      }
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
    document.body && document.body.classList && document.body.classList.remove('quiz-complete');
    window.Edu.FAB.quickFabSet(false);
    document.body && document.body.classList && document.body.classList.add('quiz-live');
    if (quiz.view === undefined) quiz.view = 0;
    var container = document.getElementById(quizContainerId);
    if (!container) return;
    var bannerHtml = '';
    if (quizSubject !== 'par' && quizSubject) {
      bannerHtml = '<div id="quizHeader">' + window.Edu.Header.quizHeaderHtml('quiz', quizSubject, quiz.type) + '</div>';
    }
    container.innerHTML = '<div class="qz-card">' + bannerHtml + renderQuizProgTop() + buildQuizCard(quiz.view) + renderQuizFooter() + '</div>';
    if (quiz.items[quiz.view].input) {
      var inp = document.getElementById('qi-in-'+quiz.view);
      if (inp) setTimeout(function(){ inp.focus(); }, 100);
    }
    updateQuizProg();
    syncRestTimer();
    autoplayListen(quiz.view);
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
    replaySpeak: replaySpeak,
    restartExpr: restartExpr,
    get advTimer() { return advTimer; },
    set advTimer(v) { advTimer = v; }
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

  window.Edu.QuizEngine.onQuizInput = function (idx, val) {
    if (!quiz) return;
    quiz.answers = quiz.answers || [];
    quiz.answers[idx] = val;
    updateQuizProg();
    saveQuizState();
    if (window.Edu.Header) window.Edu.Header.refreshQuizHeader();
  };

  // 每道选择题是否已完成判定(点选即判后, 避免重复判题/重复计时跳转)
  var judged = {};

  window.Edu.QuizEngine.pickOpt = function (idx, v) {
    if (!quiz || quiz.submitted) return;
    // 点选即判: 点选项立即套用正确答案 → 自动进下一题; 点错的先给「再试一次」, 第二次错才揭示
    if (judged[idx]) return;
    var it = quiz.items[idx];
    window.Edu.QuizEngine.onQuizInput(idx, v);
    var item = document.getElementById('qi-'+idx);
    if (item) {
      item.querySelectorAll('.qi-opts .qo-pick').forEach(function(b){
        b.classList.remove('picked-wrong');
        b.classList.toggle('selected', b.getAttribute('data-v') === v);
      });
    }
    if (it && it.options && it.type !== 'order') {
      judgeChoice(idx);
    } else if (it && it.options && it.type === 'order') {
      // 排序题需选满全部后才判定(原有逻辑保留)
      var joined = (quizOrder[idx]||[]).map(function(i){ return M.stripBlank(String(M.optVal(it.options[i]))); }).join('');
      if (quizOrder[idx] && quizOrder[idx].length === it.options.length) {
        window.Edu.QuizEngine.onQuizInput(idx, joined);
        judgeChoice(idx);
      }
    }
  };

  // 提交选择题判定: 点选即判, 答对锁定+自动进下一题; 答错给「再试一次」, 第二次才揭示正确答案
  function judgeChoice(idx) {
    if (!quiz || quiz.submitted || judged[idx]) return;
    var it = quiz.items[idx];
    if (!it || !it.options) return;
    judged[idx] = true;
    var val = quiz.answers && quiz.answers[idx];
    if (val === undefined || val === '') return;
    var ok = M.isCorrect(it, val);
    var cbtn = document.getElementById('qzConfirm');
    var item = document.getElementById('qi-'+idx);
    if (it.type === 'order') {
      // 排序题: 答对锁定并自动进下一题, 答错第二次才揭示
      if (ok) {
        lockOptions(idx, cbtn, '下一题 ▶');
        showSingleFeedback(idx, true);
        scheduleNext(1500);
      } else {
        wrongTries[idx] = (wrongTries[idx] || 0) + 1;
        judged[idx] = wrongTries[idx] >= 2;
        if (wrongTries[idx] >= 2) { lockOptions(idx, cbtn); showSingleFeedback(idx, false, true); addNextButton(); }
        else { judged[idx] = false; showSingleFeedback(idx, false, false); if (cbtn) cbtn.disabled = true; }
      }
      return;
    }
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
        judged[idx] = false;   // 首次答错: 保留可再试, 允许下次点选重新判定
        showSingleFeedback(idx, false, false);
      }
    }
  }

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
    // 兼容旧流程: 选择题已点选即判, 这里仅为排序/输入题兜底; 已判定则跳过避免重复
    if (it.options && judged[idx]) return;
    if (!it.options) {
      lockOptions(idx, null, '下一题 ▶');
      var ok2 = M.isCorrect(it, val);
      showSingleFeedback(idx, ok2);
      scheduleNext(1400);
      return;
    }
    judgeChoice(idx);
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
      var wordTxt = it.listen && it.word ? String(it.word) : '';
      feed.innerHTML = '<span>💡</span><span>正确答案是 <b>'+esc(correctTxt)+'</b>' +
        (wordTxt ? '（听的是「<b>'+esc(wordTxt)+'</b>」）' : '') + '</span>';
      Speech.playSpeak((wordTxt ? wordTxt : '正确答案是 ') + correctTxt);
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
      if (ok) {
        right++; combo++; maxCombo = Math.max(maxCombo, combo);
      }
      else { combo = 0; }
      recordAnswer(quizSubject, it.type || quizSubject, it.id, it.prompt, it.correct, quiz.answers && quiz.answers[i], ok);
    });
    var starsEarned = M.gradeQuiz(right);
    Store.state.stars = (Store.state.stars || 0) + starsEarned;
    Store.state.submits = (Store.state.submits || 0) + 1;
    // 今日答题数/题量上限统计(自动回写 usage[date])
    var us = Store.usageForToday ? Store.usageForToday() : null;
    if (us) { us.n = (us.n || 0) + quiz.items.length; us.count = (us.count || 0) + quiz.items.length; }
    Store.addStarLog(starsEarned);
    Store.saveState();
    window.Edu.Parent.renderStars();
    if (window.Edu.Legacy) window.Edu.Legacy.evalBadges(quiz.items.length - right, maxCombo);

    // 游戏化课程地图 / 激励结算: 评星(正确+用时短+首次尝试) + 通关解锁 + 星星奖励 + 里程碑
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
    document.body && document.body.classList && document.body.classList.remove('quiz-live');
    document.body && document.body.classList && document.body.classList.add('quiz-complete');
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
      // 关卡进度行: 显示本局评星 / 通关解锁 / 星星奖励
      var courseLine = '';
      if (courseRes) {
        if (courseRes.passedNow) {
          courseLine = '<div class="qd-course pass">' +
            '<span class="qc-stars">'+String('⭐'.repeat(courseRes.stars) || '')+'</span>' +
            '<span>恭喜通关「'+esc(courseRes.stageName || courseRes.levelName)+'」</span>' +
            (courseRes.unlockedNext ? '<span class="qc-next">▶ 下一关：'+esc(courseRes.unlockedNext)+' 已解锁</span>' : '') +
            (courseRes.bigDone ? '<span class="qc-next">🏁 第'+(courseRes.levelIdx+1)+'大关全部通关</span>' : '') +
            (courseRes.milestones && courseRes.milestones.length ? '<span class="qc-mil">🎖️ '+esc(courseRes.milestones[0].txt)+' 里程碑达成（+'+courseRes.milestones[0].bonus+' 星星）</span>' : '') +
            '</div>';
        } else if (courseRes.tryAgain) {
          courseLine = '<div class="qd-course retry">' +
            '<span>还差一点点～达到该小关正确率即可通关，再试一次吧！</span>' +
            '</div>';
        } else if (courseRes.dailyDone || courseRes.freePractice) {
          courseLine = '<div class="qd-course plain">' +
            '<span>继续加油，完成闯关关卡可解锁课程地图下一小关 🗺️</span>' +
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
          (courseRes && courseRes.passedNow && courseRes.next
            ? '<button type="button" class="btn-next" onclick="window.Edu.Course&&window.Edu.Course.launchLevel&&window.Edu.Course.launchLevel(\''+quizSubject+'\','+courseRes.next.big+','+courseRes.next.stage+')">▶ 下一关</button>'
            : '')+
          '<button type="button" class="btn-again" onclick="'+restartExpr()+'">🔁 再练一次</button>'+
        '</div></div>';
    }
  };

  function recordAnswer(subj, type, qid, prompt, correct, got, ok) {
    var now = new Date();
    var dkey = now.getFullYear() + '-' + ('0' + (now.getMonth()+1)).slice(-2) + '-' + ('0'+now.getDate()).slice(-2);
    var rec = { t:Date.now(), date:dkey, subj:subj, type:type, qid:qid, prompt:prompt, correct:correct, got:got, ok:ok };
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
    document.body && document.body.classList && document.body.classList.remove('quiz-complete');
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

  function startFresh(subj, type, items, levelInfo) {
    quizSubject = subj;
    quiz = { items: items, type: type, difficulty: levelInfo && levelInfo.difficulty, answers: {}, view: 0, submitted: false, _t: Date.now(), startedAt: Date.now() };
    window.Edu.QuizEngine.quiz = quiz;
    quizOrder = {};
    wrongTries = {};
    judged = {};
    // 一套新题开始即视为离开上一个闯关上下文(结算靠 recordQuizResult 的 curPos 回退即可);
    // 关卡难度 cfg 已在 launchLevel(eduNav 之后)写入并由 wbRenderMath 在 startQuiz 前读取, 故此处可安全置空.
    Store.state.courseIn = null;
    saveQuizState();
    if (type === 'daily' || subj === 'daily') quizContainerId = 'wb-daily';
    else if (subj === 'par') quizContainerId = 'parPlay';
    else if (subj === 'math') quizContainerId = 'wb-math-body';
    else if (subj === 'en') quizContainerId = 'wb-en-body';
    else quizContainerId = 'wb-zh-body';
    renderQuiz();
    if (window.renderNav) window.renderNav();
  }

  window.Edu.QuizEngine.startQuiz = function (subj, type, items, levelInfo) {
    // 正在做同一套练习时再次进入(如再次点击该科目标签): 直接重新生成新题
    var isLive = !!(quiz && !quiz.submitted && quizSubject === subj && quiz.type === type);
    if (isLive) { startFresh(subj, type, items, levelInfo); return; }
    // 清掉可能残留的上次未完练习快照, 始终起一套新题(不再弹「续学」提示)
    clearQuizState();
    startFresh(subj, type, items, levelInfo);
  };

  // 离开页面时做最后一次保存(不弹「离开此页?」提示): 进度已随每次作答实时落盘 + 切后台时保存,
  // 因此刷新/关闭不再需要阻塞确认; 去掉 preventDefault 即不再触发浏览器「留在此页」弹窗
  if (typeof window.addEventListener === 'function') {
    window.addEventListener('beforeunload', function () {
      if (quiz && !quiz.submitted) saveQuizState();
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