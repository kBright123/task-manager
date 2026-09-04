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
      // 不重复取样: 打乱词库逐题取正确词, 干扰项从全词库随机抽(不含该正确词)
      var wordPool = M.shuffle(C.WORDS);
      var allWords = C.WORDS.map(function(x){ return x.word; });
      for (var i=0;i<n;i++) {
        var w = wordPool[i % wordPool.length];
        items.push({ id:w.id, type:'word', prompt:w.cn,
          options:M.makeOptions(w.word, M.sampleExclude(allWords, [w.word], 3), 4), correct:w.word });
      }
    } else if (type === 'dialogue') {
      var diaPool = M.shuffle(C.DIALOGUES);
      var allEn = C.DIALOGUES.map(function(x){ return x.en; });
      for (var j=0;j<n;j++) {
        var d = diaPool[j % diaPool.length];
        items.push({ id:d.id, type:'dialogue', prompt:d.cn,
          options:M.makeOptions(d.en, M.sampleExclude(allEn, [d.en], 3), 4), correct:d.en });
      }
    } else if (type === 'match') {
      renderMatch(body);
      return;
    } else if (type === 'listen') {
      // 听力/词义识别: 播放单词读音(可再次点听), 不重复取样, 从全词库随机干扰项
      var lPool = M.shuffle(C.WORDS);
      var lCns = C.WORDS.map(function(x){ return x.cn; });
      // 本轮题组内已用过的选项值(含各题正确项与干扰项), 避免同一选项在多次题目里反复出现
      var usedOpts = {};
      for (var k2=0;k2<n;k2++) {
        var wl = lPool[k2 % lPool.length];
        var used = [wl.cn].concat(Object.keys(usedOpts));
        var dist = M.sampleExclude(lCns, used, 3);
        // 词库有限时放宽: 兜底从全池(仅排除本项正确词)补足 3 个干扰项, 尽量降低但不杜绝跨题重复
        if (dist.length < 3) {
          dist = M.sampleExclude(lCns, [wl.cn], 3 - dist.length).concat(dist);
        }
        usedOpts[wl.cn] = 1;
        for (var di=0; di<dist.length; di++) usedOpts[dist[di]] = 1;
        items.push({
          id: wl.id, type:'listen', listen: wl.word, word: wl.word, emoji: wl.emoji,
          prompt: wl.emoji + ' 听一听，选出正确的意思',
          big: wl.word, note: wl.word + ' = ' + wl.cn,
          options: M.makeOptions(wl.cn, dist, 4), correct: wl.cn
        });
        if (Speech && Speech.preloadTTS) Speech.preloadTTS(wl.word);
      }
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
    if (msg) msg.textContent = matchedN === matchL.length ? '全部配对完成！' : '点击左右两边配对';
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