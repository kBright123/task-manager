(function () {
  'use strict';
  var C = window.Edu.Constants;
  var M = window.Edu.MathUtils;
  var Store = window.Edu.Store;
  var Speech = window.Edu.Speech;
  var QuizEngine = window.Edu.QuizEngine;

  var PRACTICE_SECS = C.PRACTICE_SECS;
  var PRACTICE = { active: false };
  window.PRACTICE = PRACTICE;

  function practiceItem() {
    if (!PRACTICE.active) return null;
    var subj = PRACTICE.subj, type = PRACTICE.type;
    var diff = M.diffOf(subj);
    var range = M.levelRange(subj);
    var s = Store.curSettings();
    var nocarry = s.nocarry || (subj==='math' && diff <= 2);
    var allowMult = s.mult || diff >= 5;
    if (type === 'calc') { var q = M.makeCalc(range, nocarry, allowMult); return M.makeCalcItem(q); }
    if (type === 'judge') { var q2 = M.makeCalc(range, nocarry, allowMult); return M.makeJudgeItem(q2, PRACTICE.idx); }
    if (type === 'word') { var q3 = C.WORD_PLUS[Math.floor(Math.random()*C.WORD_PLUS.length)]; if (Math.random()<0.5) q3 = C.WORD_MINUS[Math.floor(Math.random()*C.WORD_MINUS.length)]; return M.makeWordItem(q3); }
    if (type === 'zi') {
      // 与闯关「识字」一致: 2000 常用字池 + 听音选词(播放词语语音, 隐藏目标词)
      var pool = C.ZI_2000 || C.ZI;
      var z = pool[Math.floor(Math.random()*pool.length)];
      var word = z.ex || z.prompt;
      var wordPool = pool.map(function(x){ return x.ex || x.prompt; });
      var otherWords = wordPool.filter(function(w){ return w !== word; });
      // 预合成语音
      if (window.Speech && Speech.preloadTTS) Speech.preloadTTS(word);
      return { id:z.id, type:'zi', prompt:'听一听，是哪个词？', listen:word, word:word, pinyin:z.pinyin,
        options:M.makeOptions(word, otherWords, 4), correct:word };
    }
    if (type === 'pinyin') { var p = C.P_READ[Math.floor(Math.random()*C.P_READ.length)]; return { id:'read_'+p.id, type:'pinyin', prompt:'「'+p.zi+'」这个字怎么读？', big:p.e+' '+p.zi, options:M.makeOptions(p.py, C.P_READ.map(function(t){return t.py;}), 3), correct:p.py, note:p.py }; }
    if (type === 'word_en') { var w = C.WORDS[Math.floor(Math.random()*C.WORDS.length)]; return { id:w.id, type:'word_en', prompt:w.cn, options:C.WORDS.filter(function(x){return x.id!==w.id;}).slice(0,3).map(function(x){return x.word;}).concat(w.word).sort(function(){return Math.random()-0.5;}), correct:w.word }; }
    return null;
  }

  function practiceHud() {
    return '<div class="pr-hud" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">'+
      '<div id="prTimer" style="font-size:1.2rem;font-weight:800;color:var(--edu-primary);">⏱ '+PRACTICE_SECS+'s</div>'+
      '<div id="prScore" style="font-weight:700;">连击: <b id="prStreak">0</b>  正确: <b id="prRight">0</b>  错误: <b id="prWrong">0</b></div>'+
      '</div>';
  }

  function practiceRenderItem() {
    var it = PRACTICE.cur;
    if (!it) return '';
    var spk = Speech.spkBtn(it.prompt, 'qi-spk');
    var h = '<div class="quiz-item active" style="margin-top:10px;">';
    if (it.listen) {
      // 听音选字(识字极速/闯关同款): 不显示目标字, 🔊 重播 + 自动播放词语语音
      h += '<div class="qi-head"><span class="qi-no">'+(PRACTICE.idx+1)+'</span><span class="qi-prompt">'+M.stripBlank(it.prompt)+'</span></div>';
      h += '<div class="qi-listen"><button type="button" class="qi-listen-btn" onclick="window.Edu.Practice.replaySpeak()" aria-label="再听一遍">🔊</button><div class="qi-listen-hint">再听一遍</div></div>';
    } else {
      h += '<div class="qi-head"><span class="qi-no">'+(PRACTICE.idx+1)+'</span><span class="qi-prompt">'+M.stripBlank(it.prompt)+'</span>'+spk+'</div>';
    }
    if (it.input) {
      h += '<div class="qi-ans">'+(/\s*=\s*\?+\s*$/.test(String(it.prompt)) ? '<span class="qi-eq">＝</span>' : '')+'';
      h += '<input id="pqi" class="qi-in" type="number" inputmode="numeric" autocomplete="off" placeholder="?" aria-label="答案" oninput="window.Edu.Practice.practiceInput(this.value)" onkeydown="if(event.key===\'Enter\'){event.preventDefault();window.Edu.Practice.practiceAnswer(this.value)}">';
      h += '</div>';
    } else {
      h += '<div class="qi-opts">';
      (it.options||[]).forEach(function(o){
        var v = String(M.optVal(o));
        h += '<button type="button" class="qo-pick" onclick="window.Edu.Practice.practiceAnswer(\''+M.stripBlank(v).replace(/'/g,"\\'")+'\')">'+M.optLabel(o)+'</button>';
      });
      h += '</div>';
    }
    h += '<div class="qi-feed" style="margin-top:10px;font-weight:600;min-height:20px;"></div></div>';
    return h;
  }

  function practiceRenderTimer() {
    var t = document.getElementById('prTimer');
    if (!t) return;
    var s = Math.ceil(PRACTICE.leftMs / 1000);
    t.textContent = '⏱ ' + s + 's';
    t.style.color = s <= 3 ? '#d94c4c' : 'var(--edu-primary)';
  }

  function practiceTick() {
    if (!PRACTICE.active || PRACTICE.lock) return;
    PRACTICE.leftMs -= 250;
    practiceRenderTimer();
    if (PRACTICE.leftMs <= 0) practiceTimeout();
  }

  function practiceTimeout() {
    if (!PRACTICE.active || PRACTICE.lock) return;
    var it = PRACTICE.cur;
    PRACTICE.lock = true;
    if (PRACTICE.timer) clearInterval(PRACTICE.timer);
    if (PRACTICE.lockTimer) clearTimeout(PRACTICE.lockTimer);
    PRACTICE.pending = '';
    PRACTICE.streak = 0; PRACTICE.wrong++;
    var _now = new Date();
    var _dkey = _now.getFullYear() + '-' + ('0' + (_now.getMonth()+1)).slice(-2) + '-' + ('0'+_now.getDate()).slice(-2);
    var rec = { t:Date.now(), date:_dkey, subj:PRACTICE.subj, type:it.wtype || PRACTICE.type, qid:it.id, prompt:it.prompt, correct:it.correct, got:'⏱ 超时', ok:false };
    Store.state.records = Store.state.records || [];
    Store.state.records.unshift(rec);
    if (Store.state.records.length > 500) Store.state.records.length = 500;
    Store.state.wrong = Store.state.wrong || [];
    Store.state.wrong.unshift({ subj:PRACTICE.subj, type:it.wtype || PRACTICE.type, qid:it.id, prompt:it.prompt, correct:it.correct, got:'⏱ 超时', t:Date.now() });
    if (Store.state.wrong.length > 200) Store.state.wrong.length = 200;
    Store.saveState();
    if (window.eduSync && window.eduSync.qbankLearn) {
      window.eduSync.qbankLearn({ subj:PRACTICE.subj, type:it.wtype || PRACTICE.type, prompt:it.prompt, correct:false, difficulty:M.diffOf(PRACTICE.subj) });
    }
    var _pqi = document.getElementById('pqi'); var feed = (_pqi && _pqi.parentElement) ? _pqi.parentElement.querySelector('.qi-feed') : null;
    if (feed) { feed.className = 'qi-feed no'; feed.textContent = '⏱ 时间到～'; }
    practiceRenderTimer();
    PRACTICE.lockTimer = setTimeout(practiceNext, 650);
  }

  function practiceContainer() {
    // 模块化架构下题目渲染进对应学科面板(而非不存在的 #quizShell); 与闯关容器保持一致
    var subj = PRACTICE ? PRACTICE.subj : 'zh';
    if (subj === 'daily') return 'wb-daily';
    if (subj === 'math') return 'wb-math-body';
    if (subj === 'en') return 'wb-en-body';
    return 'wb-zh-body';
  }

  function practiceNext() {
    if (!PRACTICE.active) return;
    var it = practiceItem();
    if (!it) return;
    PRACTICE.cur = it; PRACTICE.idx++; PRACTICE.lock = false; PRACTICE.leftMs = PRACTICE_SECS * 1000;
    var box = document.getElementById(practiceContainer());
    if (!box) return;
    box.innerHTML = window.quizHeaderHtml('su', PRACTICE.subj, PRACTICE.type) + practiceHud() +
      '<div class="quiz-item pratica qi-p-in" id="pqi">'+practiceRenderItem()+'</div>';
    practiceRenderTimer();
    if (PRACTICE.timer) clearInterval(PRACTICE.timer);
    PRACTICE.timer = setInterval(practiceTick, 250);
    var inp = document.getElementById('pqi');
    if (inp && inp.querySelector) { var inn = inp.querySelector('.qi-in'); if (inn) setTimeout(function(){ inn.focus(); }, 100); }
    if (it.listen && window.Speech && Speech.playSpeak) {
      if (Speech.preloadTTS) Speech.preloadTTS(it.listen);
      setTimeout(function(){ if (window.Speech && Speech.playSpeak) Speech.playSpeak(it.listen); }, 60);
    }
  }

  window.Edu.Practice = {
    PRACTICE: PRACTICE,
    PRACTICE_SECS: PRACTICE_SECS,
    practiceItem: practiceItem,
    practiceHud: practiceHud,
    practiceRenderItem: practiceRenderItem,
    practiceRenderTimer: practiceRenderTimer,
    practiceTick: practiceTick,
    practiceTimeout: practiceTimeout,
    practiceNext: practiceNext
  };

  window.Edu.Practice.replaySpeak = function () {
    var it = window.Edu.Practice && window.Edu.Practice.PRACTICE && window.Edu.Practice.PRACTICE.cur;
    if (it && it.listen && window.Speech && Speech.playSpeak) Speech.playSpeak(it.listen, 1);
  };

  window.Edu.Practice.practiceInput = function (v) {
    if (!PRACTICE.active || PRACTICE.lock) return;
    PRACTICE.pending = v;
  };

  window.Edu.Practice.practiceAnswer = function (got) {
    if (!PRACTICE.active || PRACTICE.lock) return;
    var it = PRACTICE.cur;
    var val = String(got == null ? '' : got).trim();
    if (PRACTICE.pending && val !== '⏱ 超时') { val = PRACTICE.pending; PRACTICE.pending = ''; }
    PRACTICE.lock = true;
    if (PRACTICE.timer) clearInterval(PRACTICE.timer);
    var ok = String(it.correct) === String(val) || M.isCorrect(it, val);
    var _now = new Date();
    var _dkey = _now.getFullYear() + '-' + ('0' + (_now.getMonth()+1)).slice(-2) + '-' + ('0'+_now.getDate()).slice(-2);
    var rec = { t:Date.now(), date:_dkey, subj:PRACTICE.subj, type:it.wtype || PRACTICE.type, qid:it.id, prompt:it.prompt, correct:it.correct, got:val, ok:ok };
    Store.state.records = Store.state.records || [];
    Store.state.records.unshift(rec);
    if (Store.state.records.length > 500) Store.state.records.length = 500;
    if (ok) {
      PRACTICE.streak++; PRACTICE.maxStreak = Math.max(PRACTICE.maxStreak, PRACTICE.streak); PRACTICE.right++; PRACTICE.score += PRACTICE.streak;
      Speech.playSpeak('答对了');
    } else {
      PRACTICE.streak = 0; PRACTICE.wrong++;
      Store.state.wrong = Store.state.wrong || [];
      Store.state.wrong.unshift({ subj:PRACTICE.subj, type:it.wtype || PRACTICE.type, qid:it.id, prompt:it.prompt, correct:it.correct, got:val, t:Date.now() });
      if (Store.state.wrong.length > 200) Store.state.wrong.length = 200;
      Speech.playSpeak('再试一次');
    }
    Store.saveState();
    if (window.eduSync && window.eduSync.qbankLearn) {
      window.eduSync.qbankLearn({ subj:PRACTICE.subj, type:it.wtype || PRACTICE.type, prompt:it.prompt, correct:ok, difficulty:M.diffOf(PRACTICE.subj) });
    }
    // 温和反馈: 正确→正激励, 错误→再试一次✨(不用 ❌)
    var _pqi = document.getElementById('pqi'); var feed = (_pqi && _pqi.parentElement) ? _pqi.parentElement.querySelector('.qi-feed') : null;
    if (feed) {
      if (ok) { feed.className = 'qi-feed offer'; feed.innerHTML = '<span class="pr-emoji">⭐</span><span>'+Speech.encPick(C.ENC_OK)+'</span>'; }
      else { feed.className = 'qi-feed gentle'; feed.innerHTML = '<span>🌱</span><span>'+Speech.encPick(C.ENC_WRONG)+' 再试一次✨</span>'; }
    }
    practiceRenderTimer();
    PRACTICE.lockTimer = setTimeout(practiceNext, 650);
  };

  function centerView(id) {
    try { var el = document.getElementById(id); if (el && el.scrollIntoView) el.scrollIntoView({behavior:'smooth',block:'center'}); } catch(e){}
  }

  window.startPractice = function (subj, type) {
    if (window.Edu.QuizEngine.quiz) window.Edu.QuizEngine.quiz.submitted = true;
    if (window.Edu.QuizEngine.advTimer) { clearTimeout(window.Edu.QuizEngine.advTimer); window.Edu.QuizEngine.advTimer = null; }
    PRACTICE = { active:true, subj:subj, type:type, idx:0, score:0, streak:0, maxStreak:0,
      right:0, wrong:0, leftMs:PRACTICE_SECS*1000, timer:null, lockTimer:null, lock:false, pending:'', _t:Date.now() };
    window.PRACTICE = PRACTICE;
    window.Edu.Practice.PRACTICE = PRACTICE;
    window.Edu.FAB.quickFabSet(false);
    practiceNext();
    centerView('practiceBox');
    if (window.renderNav) window.renderNav();
  };

  window.stopPractice = function () {
    if (!PRACTICE.active) return;
    var n = PRACTICE.right + PRACTICE.wrong;
    if (n === 0) { Speech.toast('还没有作答哦'); return; }
    PRACTICE.active = false;
    if (PRACTICE.timer) clearInterval(PRACTICE.timer);
    if (PRACTICE.lockTimer) clearTimeout(PRACTICE.lockTimer);
    var secs = Math.max(1, Math.round((Date.now() - (PRACTICE._t || Date.now())) / 1000));
    var usage = Store.usageForToday();
    usage.n += n; usage.count = (usage.count || 0) + n; usage.secs += secs;
    Store.addDailySecs(secs);
    Store.state.submits = (Store.state.submits || 0) + 1;
    Store.state.maxCombo = Math.max(Store.state.maxCombo || 0, PRACTICE.maxStreak);
    Store.wb.done = Store.wb.done || [];
    var doneKey = PRACTICE.subj + ':' + PRACTICE.type;
    if (Store.wb.done.indexOf(doneKey) < 0) Store.wb.done.push(doneKey);
    if (window.Edu.Legacy) window.Edu.Legacy.evalBadges([], PRACTICE.maxStreak);
    Store.saveState(); Store.saveWb();
    var shell = document.getElementById(practiceContainer());
    if (shell) {
      var medal = PRACTICE.score >= 30 ? '🏆' : (PRACTICE.score >= 15 ? '🌟' : '💪');
      var praise = PRACTICE.wrong === 0 ? '一题未失，超强手感！' : (PRACTICE.right > PRACTICE.wrong ? '状态很好，继续加油！' : '多练几次就更稳啦～');
      shell.innerHTML =
        '<div class="qs-result practice-result">'+
        '<div class="big">'+medal+' ⚡'+PRACTICE.score+' 分</div>'+
        '<p>'+praise+' 共 '+n+' 题 · 答对 '+PRACTICE.right+' · 答错 '+PRACTICE.wrong+'</p>'+
        '<p style="margin-bottom:8px;">🔥 最高连对 '+PRACTICE.maxStreak+' 题 · 用时 '+Math.max(1, Math.round(secs/60*10)/10)+' 分</p>'+
        '<button type="button" class="btn-soft" onclick="'+window.Edu.QuizEngine.restartExpr()+'">继续学习</button></div>';
    }
    window.PRACTICE = PRACTICE;
    if (window.renderNav) window.renderNav();
  };

  window.practiceInput = window.Edu.Practice.practiceInput;
  window.practiceAnswer = window.Edu.Practice.practiceAnswer;
})();