(function () {
  'use strict';
  var C = window.Edu.Constants;
  var M = window.Edu.MathUtils;
  var Store = window.Edu.Store;
  var Speech = window.Edu.Speech;
  var QuizEngine = window.Edu.QuizEngine;

  var wbEnMode = 'word';

  function wbRenderEn() {
    var body = document.getElementById('wb-en-body');
    if (!body) return;
    var type = (wbEnMode === 'match') ? 'match' : wbEnMode;
    var diff = M.diffOf('en');
    var items = [];
    var n = C.QUIZ_LEN;
    if (type === 'word') {
      for (var i=0;i<n;i++) {
        var w = C.WORDS[Math.floor(Math.random()*C.WORDS.length)];
        items.push({ id:w.id, type:'word', prompt:w.cn, options:C.WORDS.filter(function(x){return x.id!==w.id;}).slice(0,3).map(function(x){return x.word;}).concat(w.word).sort(function(){return Math.random()-0.5;}), correct:w.word });
      }
    } else if (type === 'dialogue') {
      for (var j=0;j<n;j++) {
        var d = C.DIALOGUES[Math.floor(Math.random()*C.DIALOGUES.length)];
        items.push({ id:d.id, type:'dialogue', prompt:d.cn, options:C.DIALOGUES.filter(function(x){return x.id!==d.id;}).slice(0,3).map(function(x){return x.en;}).concat(d.en).sort(function(){return Math.random()-0.5;}), correct:d.en });
      }
    } else if (type === 'match') {
      renderMatch(body);
      return;
    }
    QuizEngine.startQuiz('en', type, items, { difficulty: diff });
  }

  window.wbEn = function (k) {
    wbEnMode = k;
    if (window.Edu.Workbench && window.Edu.Workbench.showSubjectSection) window.Edu.Workbench.showSubjectSection('en');
    document.getElementById('wb-en').querySelectorAll('.sm-tab').forEach(function(b){ b.classList.toggle('active', b.dataset.s === k); });
    wbRenderEn();
    Store.saveWb();
  };

  var matchL = [], matchR = [], selL = -1, selR = -1, matchedN = 0, matchedMap = {};

  function renderMatch(body) {
    var n = 5;
    matchL = C.WORDS.slice(0,n).map(function(w){ return {id:w.id, text:w.word, cn:w.cn}; });
    matchR = C.WORDS.slice(0,n).map(function(w){ return {id:w.id, text:w.cn, cn:w.word}; });
    for (var i=matchR.length-1;i>0;i--){ var j=Math.floor(Math.random()*(i+1)); var t=matchR[i]; matchR[i]=matchR[j]; matchR[j]=t; }
    selL = selR = -1; matchedN = 0; matchedMap = {};
    body.innerHTML = '<div class="match-wrap"><div class="match-cols"><div class="match-col" id="matchL"></div><div class="match-col" id="matchR"></div></div><div id="matchMsg" style="text-align:center;margin-top:10px;font-weight:700;"></div></div>';
    matchDraw();
  }

  function matchDraw() {
    var l = document.getElementById('matchL');
    var r = document.getElementById('matchR');
    var msg = document.getElementById('matchMsg');
    if (!l || !r) return;
    l.innerHTML = matchL.map(function(m, i){
      var done = matchedMap[m.id];
      return '<button type="button" class="match-btn '+(done?'done':'')+' '+(selL===i?'sel':'')+'" onclick="window.Edu.EnWorkbench.matchLpick('+i+')">'+(done?'✅ ':'')+m.text+'</button>';
    }).join('');
    r.innerHTML = matchR.map(function(m, i){
      var done = matchedMap[m.id];
      return '<button type="button" class="match-btn '+(done?'done':'')+' '+(selR===i?'sel':'')+'" onclick="window.Edu.EnWorkbench.matchRpick('+i+')">'+(done?'✅ ':'')+m.text+'</button>';
    }).join('');
    if (msg) msg.textContent = matchedN === n ? '全部配对完成！' : '点击左右两边配对';
  }

  window.Edu.EnWorkbench = {
    wbEnMode: wbEnMode,
    wbRenderEn: wbRenderEn,
    renderMatch: renderMatch,
    matchDraw: matchDraw,
    matchL: matchL,
    matchR: matchR,
    selL: selL,
    selR: selR,
    matchedN: matchedN,
    matchedMap: matchedMap
  };

  window.Edu.EnWorkbench.matchLpick = function (i) {
    if (matchedMap[matchL[i].id]) return;
    selL = i;
    if (selR >= 0) { checkMatch(); }
    matchDraw();
  };

  window.Edu.EnWorkbench.matchRpick = function (i) {
    if (matchedMap[matchR[i].id]) return;
    selR = i;
    if (selL >= 0) { checkMatch(); }
    matchDraw();
  };

  function checkMatch() {
    if (matchL[selL].id === matchR[selR].id) {
      matchedMap[matchL[selL].id] = true;
      matchedN++;
      Speech.playSpeak('配对成功');
    } else {
      Speech.playSpeak('再试一次');
    }
    selL = selR = -1;
    matchDraw();
    if (matchedN === matchL.length) {
      Speech.playSpeak('全部配对完成');
    }
  }

  window.Edu.EnWorkbench.checkMatch = checkMatch;
})();