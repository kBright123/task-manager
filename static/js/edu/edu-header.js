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
    // 关卡标签: 闯关时使用课程进度(第几大关第几小关), 而非难度档, 避免误显示难度
    var lvTxt;
    var Course = window.Edu && window.Edu.Course;
    var pos = null;
    if (isQuiz) {
      pos = (Course && Course.curPos) ? Course.curPos(subj) : null;
      if (pos) {
        lvTxt = '第 ' + (Number(pos.big) + 1) + ' 大关';
        if (pos.stage > 0) lvTxt += ' · 第 ' + (Number(pos.stage) + 1) + ' 小关';
      } else {
        var _lv = window.eduEngine ? window.eduEngine.diffOf(subj) : 3;
        lvTxt = (_lv === '' || _lv == null) ? '第 1 关' : ('第 ' + Number(_lv) + ' 关');
      }
    } else {
      var lv = window.eduEngine ? window.eduEngine.diffOf(subj) : 3;
      lvTxt = (lv === '' || lv == null) ? '第 1 关' : ('第 ' + Number(lv) + ' 关');
    }
    var state = Store.state;
    var passed = (state.adv && state.adv[subj] && state.adv[subj][type] && state.adv[subj][type].passed);
    var itemName = ({zh:{poem:'古诗',zi:'识字',stroke:'笔顺',pinyin:'拼音',yun:'拼音',read:'拼音',tone:'拼音',fan:'词语',liang:'词语',daily:'每日挑战'},
                     math:{calc:'口算',judge:'判断',word:'应用题',order:'排序',daily:'每日挑战'},
                     en:{word:'单词',dialogue:'对话',daily:'每日挑战'}}[subj]||{})[type] || type;
    // 答题页不提供模式切换入口(模式在首页选择), 仅以只读标签展示当前关卡
    var modeChip = '<span class="lv-badge">' + (isSu ? '⚡ 极速练习' : ('🗺️ ' + lvTxt + ' · ' + esc(itemName))) + '</span>';
    var html = '<div class="qc-ctl">' +
      '<div class="qc-side">' + modeChip + (passed ? '<span class="lv-passed">✅ 已通过</span>' : '') + '</div>' +
      '<button type="button" class="qc-exit" onclick="quitAsk()"><i class="bi bi-x-lg"></i>' + (isSu ? '退出' : '返回') + '</button>' +
      '</div>';
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
