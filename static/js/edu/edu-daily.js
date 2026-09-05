(function () {
  'use strict';
  var C = window.Edu.Constants;
  var M = window.Edu.MathUtils;
  var Store = window.Edu.Store;
  var Speech = window.Edu.Speech;
  var QuizEngine = window.Edu.QuizEngine;
  var ZhWorkbench = window.Edu.ZhWorkbench;
  var MathWorkbench = window.Edu.MathWorkbench;
  var EnWorkbench = window.Edu.EnWorkbench;

  function seedRand(seed) {
    // Mulberry32 PRNG - deterministic, fast, good distribution
    var t = (seed += 0x6D2B79F5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }

  function shuffleSeeded(a, rnd) {
    var b = a.slice();
    for (var i=b.length-1;i>0;i--){ var j=Math.floor(rnd()*(i+1)); var t=b[i];b[i]=b[j];b[j]=t; }
    return b;
  }

  function buildDaily() {
    var today = new Date().toISOString().slice(0,10);
    var daySeed = Date.parse(today); // deterministic per day
    // Closure-based PRNG to maintain seed state
    var rnd = (function(){
      var seed = daySeed;
      return function(){
        var t = (seed += 0x6D2B79F5);
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
      };
    })();
    var plan = shuffleSeeded(C.DAILY_PLAN.slice(), rnd);
    var items = [];
    var usedMath = {};
    plan.forEach(function(subj){
      var diff = M.diffOf(subj);
      var range = M.levelRange(subj);
      var s = Store.curSettings();
      var nocarry = s.nocarry || (subj==='math' && diff <= 2);
      var allowMult = s.mult || diff >= 5;
      if (subj === 'zh') {
        var q = C.ZI[Math.floor(rnd()*C.ZI.length)];
        items.push({ id:q.id, isubj:'zh', type:'zi', prompt:q.prompt, options:['天','地','人','大','小','上','下','中','日','月'].filter(function(x){return x!==q.prompt;}).slice(0,3).concat(q.prompt).sort(function(){return rnd()-0.5;}), correct:q.prompt });
      } else if (subj === 'math') {
        var q2 = M.makeCalc(range, nocarry, allowMult, rnd, null, { usedKeys: usedMath });
        var item = M.makeCalcItem(q2);
        item.isubj = 'math';
        item.type = 'calc';
        items.push(item);
      } else if (subj === 'en') {
        var w = C.WORDS[Math.floor(rnd()*C.WORDS.length)];
        items.push({ id:w.id, isubj:'en', type:'word', prompt:w.cn, options:C.WORDS.filter(function(x){return x.id!==w.id;}).slice(0,3).map(function(x){return x.word;}).concat(w.word).sort(function(){return rnd()-0.5;}), correct:w.word });
      }
    });
    return items.slice(0, C.QUIZ_LEN);
  }

  window.buildDaily = buildDaily;

  window.startDaily = function () {
    var items = buildDaily();
    var subj = (items && items[0] && items[0].isubj) || 'zh';
    if (window.Edu.Workbench && window.Edu.Workbench.showSubjectSection) window.Edu.Workbench.showSubjectSection('daily');
    QuizEngine.startQuiz(subj, 'daily', items, { difficulty: 1 });
  };

  window.Edu.Daily = {
    buildDaily: buildDaily,
    startDaily: startDaily,
    seedRand: seedRand,
    shuffleSeeded: shuffleSeeded
  };
})();