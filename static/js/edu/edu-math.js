(function () {
  'use strict';
  var C = window.Edu.Constants;
  var M = window.Edu.MathUtils;
  var Store = window.Edu.Store;
  var Speech = window.Edu.Speech;
  var QuizEngine = window.Edu.QuizEngine;

  var wbMathMode = 'calc';
  var wbWrongActive = false;

  function wbRenderMath() {
    var body = document.getElementById('wb-math-body');
    if (!body) return;
    if (wbMathMode === 'wrong') { renderWrongList(body); return; }
    var type = (wbMathMode === 'order') ? 'order' : wbMathMode;
    var diff = M.diffOf('math');
    var range = M.levelRange('math');
    var s = Store.curSettings();
    var nocarry = s.nocarry || (wbMathMode === 'calc' && diff <= 2);
    var allowMult = s.mult || diff >= 5;
    var ops = null;
    // 闯关模式: 难度由关卡主题 + 小关进度自动决定(无需家长手动设置)
    var courseIn = Store.state.courseIn;
    if (courseIn && courseIn.cfg && Store.state.courseInflight) {
      range = courseIn.cfg.max;
      nocarry = !!courseIn.cfg.nocarry;
      ops = courseIn.cfg.ops;
      allowMult = ops.indexOf('×') >= 0 || ops.indexOf('÷') >= 0;
    }
    var items = [];
    var n = C.QUIZ_LEN;
    if (type === 'calc') {
      for (var i=0;i<n;i++) { var q = M.makeCalc(range, nocarry, allowMult, null, ops); items.push(M.makeCalcItem(q)); }
    } else if (type === 'judge') {
      for (var j=0;j<n;j++) { var q2 = M.makeCalc(range, nocarry, allowMult, null, ops); items.push(M.makeJudgeItem(q2, j)); }
    } else if (type === 'word') {
      var usedKeys = {};
      var wRange = Math.max(10, range || 20);
      for (var k=0;k<n;k++) { items.push(M.makeWordAuto(wRange, usedKeys)); }
    } else if (type === 'order') {
      for (var m=0;m<n;m++) {
        var arr = [M.randInt(10)+1, M.randInt(10)+1, M.randInt(10)+1, M.randInt(10)+1];
        var sorted = arr.slice().sort(function(a,b){return a-b;});
        items.push({ id:'ord_'+m, type:'order', order:true, prompt:'从小到大排序', options:arr, correct:sorted.join('') });
      }
    }
    QuizEngine.startQuiz('math', type, items, { difficulty: diff });
  }

  window.wbMath = function (k) {
    wbMathMode = k;
    if (window.Edu.Workbench && window.Edu.Workbench.showSubjectSection) window.Edu.Workbench.showSubjectSection('math');
    document.getElementById('wb-math').querySelectorAll('.sm-tab').forEach(function(b){ b.classList.toggle('active', b.dataset.s === k); });
    wbRenderMath();
    Store.saveWb();
  };

  function renderWrongList(body) {
    var wrongs = (Store.state.wrong || []).filter(function(w){ return w.subj === 'math'; });
    if (!wrongs.length) { body.innerHTML = '<div style="text-align:center;padding:30px;color:var(--edu-muted);">没有错题啦 🎉</div>'; return; }
    body.innerHTML = '<div class="wrong-list">'+wrongs.map(function(w, i){
      return '<div class="wrong-item" style="padding:12px;border-bottom:1px solid var(--edu-border-2);">'+
        '<div style="font-weight:700;">'+w.prompt+'</div>'+
        '<div style="font-size:.85rem;color:var(--edu-muted);">你的答案：'+w.got+'  正确：'+w.correct+'</div>'+
        '<button type="button" class="btn-soft" style="margin-top:8px;font-size:.8rem;padding:4px 10px;" onclick="window.Edu.MathWorkbench.wbWrongQuiz('+i+')">重练此题</button>'+
        '</div>';
    }).join('')+'</div>';
    wbWrongActive = true;
  }

  window.Edu.MathWorkbench = {
    wbMathMode: wbMathMode,
    wbWrongActive: wbWrongActive,
    wbRenderMath: wbRenderMath,
    renderWrongList: renderWrongList
  };

  window.Edu.MathWorkbench.wbWrongQuiz = function (idx) {
    var wrongs = (Store.state.wrong || []).filter(function(w){ return w.subj === 'math'; });
    var w = wrongs[idx];
    if (!w) return;
    var items = [{ id:w.qid, type:w.type, prompt:w.prompt, options:w.options, input:w.input, correct:w.correct }];
    QuizEngine.startQuiz('math', w.type, items, { difficulty: M.diffOf('math') });
    wbWrongActive = false;
  };
})();