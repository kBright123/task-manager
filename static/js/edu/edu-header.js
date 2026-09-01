(function () {
  'use strict';
  var C = window.Edu.Constants;
  var M = window.Edu.MathUtils;
  var Store = window.Edu.Store;
  var QuizEngine = window.Edu.QuizEngine;
  var Speech = window.Edu.Speech;

  function quizAnsweredRight() {
    var quiz = QuizEngine.quiz;
    if (!quiz || !quiz.items) return 0;
    var n = 0;
    quiz.items.forEach(function(it, i){
      if (it.order) {
        if (String((QuizEngine.quizOrder && QuizEngine.quizOrder[i] || []).join('|')) === String(it.correct)) n++;
        return;
      }
      var my = QuizEngine.quiz.answers && QuizEngine.quiz.answers[i];
      if (my !== undefined && String(my).trim() !== '' && M.isCorrect(it, my)) n++;
    });
    return n;
  }

  // active: 'guan'|'su'(历史) 或 'quiz'|'practice'(新标志)
  function quizHeaderHtml(active, subj, type){
    subj = subj || 'zh'; type = type || 'zi';
    var isSu = (active === 'su' || active === 'practice');
    var isQuiz = (active === 'guan' || active === 'quiz');
    var lv = window.eduEngine ? window.eduEngine.diffOf(subj) : 3;
    var state = Store.state;
    var passed = (state.adv && state.adv[subj] && state.adv[subj][type] && state.adv[subj][type].passed);
    var itemName = ({zh:{poem:'古诗',zi:'识字',stroke:'笔顺',pinyin:'拼音',yun:'拼音',read:'拼音',tone:'拼音',fan:'词语',liang:'词语',daily:'每日挑战'},
                     math:{calc:'口算',judge:'判断',word:'应用题',order:'排序',daily:'每日挑战'},
                     en:{word:'单词',dialogue:'对话',daily:'每日挑战'}}[subj]||{})[type] || type;
    var modeTxt = isSu ? '极速练习' : '闯关';
    var nRight;
    if (isSu) {
      nRight = (window.PRACTICE && window.PRACTICE.active) ? (window.PRACTICE.right || 0) : 0;
    } else {
      nRight = quizAnsweredRight();
    }
    var html = '<div class="qz-ctl">' +
      '<button type="button" class="qc-exit" onclick="quitAsk()"><i class="bi bi-x-lg"></i> 退出</button>' +
      '<button type="button" class="qc-sound" id="soundToggle" onclick="toggleSpeak()" aria-label="声音">🔊</button>' +
      '</div>' +
      '<div class="lv-banner">'+
      '<div class="lv-left"><span class="lv-badge">🗺️ '+modeTxt+' · '+esc(itemName)+'</span>'+
      '<span class="lv-sub" id="lvSub">已答对 <b>'+nRight+'</b> 题</span></div>'+
      '<div class="lv-right">'+(passed?'<span class="lv-passed">✅ 已通过本关</span>':'<span class="lv-notyet">⏳ 待通关</span>')+
      '<span class="lv-at">难度档 '+lv+'/5</span>';
    if (type !== 'daily'){
      html += '<span class="pb-mini-group">'+
        '<button type="button" class="pb-mini'+(isQuiz?' active':'')+'" onclick="window.restartQuiz()">🗺️ 闯关</button>'+
        '<button type="button" class="pb-mini'+(isSu?' active':'')+'" onclick="window.startPractice(\''+esc(subj)+'\',\''+esc(type)+'\')">⚡ 极速练习</button></span>';
    }
    html += '</div></div>';
    return html;
  }

  // 闯关卷作答时实时刷新横幅里的"已答对 N 题"
  function refreshQuizHeader() {
    var el = document.getElementById('lvSub');
    if (el) el.innerHTML = '已答对 <b>' + quizAnsweredRight() + '</b> 题';
  }

  // 兼容旧引用: 仅按钮一行(练习历史/测试), 委托给统一页头
  function modeBarHtml(active){
    return quizHeaderHtml(active);
  }

  window.Edu.Header = {
    quizHeaderHtml: quizHeaderHtml,
    quizAnsweredRight: quizAnsweredRight,
    refreshQuizHeader: refreshQuizHeader,
    modeBarHtml: modeBarHtml
  };

  window.quizHeaderHtml = quizHeaderHtml;
  window.quizAnsweredRight = quizAnsweredRight;
  window.refreshQuizHeader = refreshQuizHeader;
  window.modeBarHtml = modeBarHtml;
  window.ENC_OK = C.ENC_OK;
  window.ENC_WRONG = C.ENC_WRONG;
  window.encPick = Speech.encPick;
})();
