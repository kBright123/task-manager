(function () {
  'use strict';
  var C = window.Edu.Constants;

  function numCn(n) {
    n = Math.floor(Math.abs(n));
    if (n === 0) return '零';
    var CN0 = '零一二三四五六七八九';
    if (n < 10) return CN0[n];
    if (n < 20) return '十' + (n % 10 ? CN0[n % 10] : '');
    if (n < 100) { return CN0[Math.floor(n/10)] + '十' + (n % 10 ? CN0[n%10] : ''); }
    if (n < 1000) { var b=Math.floor(n/100), r=n%100; return CN0[b]+'百' + (r ? (r<10?'零'+CN0[r]:numCn(r)) : ''); }
    var q=Math.floor(n/1000), r2=n%1000; return CN0[q]+'千' + (r2 ? (r2<100?'零'+numCn(r2):numCn(r2)) : '');
  }

  function mathToSpeak(text) {
    if (!text) return '';
    var s = String(text);
    if (!/[+\-×÷＝=]/.test(s)) return s;
    s = s.replace(/×/g, ' 乘 ').replace(/÷/g, ' 除以 ')
         .replace(/\s*-\s*/g, ' 减 ').replace(/\s*\+\s*/g, ' 加 ')
         .replace(/[＝=]\s*\?+(\s*,?\s*对吗)?/g, ' 等于多少')
         .replace(/[＝=]/g, ' 等于 ')
         .replace(/\?+/g, '多少')
         .replace(/\s+/g, ' ');
    return s.replace(/(\d+)/g, function(m){ return numCn(parseInt(m, 10)); });
  }

  function stripBlank(s) {
    return String(s||'').replace(/[_＿\s]*\_+[_＿\s]*/g,' ').replace(/\s*=\s*\?+\s*$/,'').replace(/\s+/g,' ').trim();
  }

  function isCorrect(it, my) {
    if (it.order) return String(my) === String(it.correct);
    if (it.input) return String(my).trim() === String(it.correct).trim();
    return String(my) === String(it.correct);
  }

  // 选项可能为普通字符串, 也可能是 {v,label} 对象：统一取出展示文本与作答值
  function optLabel(o) { return (o !== null && typeof o === 'object' && 'label' in o) ? o.label : o; }
  function optVal(o) { return (o !== null && typeof o === 'object' && 'v' in o) ? o.v : o; }

  function randInt(n) { return Math.floor(Math.random()*n); }

  function shuffle(a) {
    var b = a.slice();
    for (var i=b.length-1;i>0;i--){ var j=Math.floor(Math.random()*(i+1)); var t=b[i];b[i]=b[j];b[j]=t; }
    return b;
  }

  // 从 pool 中随机取 n 个, 排除 exclude 中的取值(避免正确项重复/作选项)
  function sampleExclude(pool, exclude, n) {
    var ex = exclude || [];
    var arr = pool.filter(function(x){ return ex.indexOf(x) < 0; });
    return shuffle(arr).slice(0, n);
  }

  // 20/50/100 以内的加减法, 结果落在该档位区间的下半段, 避免出 1+2 这类过浅题:
  // 20以内 → 10-20; 50以内 → 20-50; 100以内 → 50-100; 10以内 → 5-10; 5以内 → 2-5
  function bandLow(max) {
    if (max <= 2) return 1;
    if (max === 50) return 20;
    return Math.min(max - 1, Math.floor(max / 2));
  }

  // opts: {lo: 结果下界(默认 bandLow), usedKeys: 去重表}
  function makeCalc(max, nocarry, allowMult, rnd, ops, opts) {
    var randFn = rnd || function(){ return Math.random(); };
    var o = opts || {};
    var lo = (o.lo === undefined || o.lo === null) ? bandLow(Math.max(1, max)) : o.lo;
    var usedKeys = o.usedKeys || null;
    if (!ops || !ops.length) {
      ops = ['+','-'];
      if (allowMult) ops.push('×','÷');
    }
    var guard = 0;
    for (;;) {
      var op = ops[Math.floor(randFn() * ops.length)];
      var q;
      if (op === '+') {
        // 和落在 [lo, max]: a 取大数区, b 补足
        var aLo = Math.max(1, lo - 1);
        var aHi = Math.max(aLo, max - 1);
        var a = aLo + Math.floor(randFn() * (aHi - aLo + 1));
        var bLo = Math.max(1, lo - a);
        var bHi = max - a;
        if (bHi < bLo) { if (++guard > 25) { a = 1; b = 1; q = {a:a,b:b,op:'+',correct:a+b,expr:a+'+'+b}; break; } continue; }
        var b = bLo + Math.floor(randFn() * (bHi - bLo + 1));
        if (nocarry && (a%10 + b%10 >= 10)) continue;
        q = { a:a, b:b, op:'+', correct:a+b, expr:a+'+'+b };
      } else if (op === '-') {
        // 差落在 [lo, max-1]: 被减数 a 大数区, 减数 b 使差不低于 lo
        if (max <= lo) { q = { a:max, b:0, op:'-', correct:max, expr:max+'-0' }; }
        else {
          var a2 = lo + 1 + Math.floor(randFn() * (max - lo));
          var b2 = 1 + Math.floor(randFn() * (a2 - lo));
          if (nocarry && (a2%10 < b2%10)) continue;
          q = { a:a2, b:b2, op:'-', correct:a2-b2, expr:a2+'-'+b2 };
        }
      } else if (op === '×') {
        a = Math.floor(randFn() * 9) + 1; b = Math.floor(randFn() * 9) + 1;
        q = { a:a, b:b, op:'×', correct:a*b, expr:a+'×'+b };
      } else {  // ÷
        b = Math.floor(randFn() * 9) + 1; a = b * (Math.floor(randFn() * 9) + 1);
        q = { a:a, b:b, op:'÷', correct:a/b, expr:a+'÷'+b };
      }
      if (!usedKeys) return q;
      var key = q.a + q.op + q.b;
      if (!usedKeys[key]) { usedKeys[key] = true; return q; }
      if (++guard > 80) return q;  // 组合池已耗尽, 放行避免死循环
    }
    return q;
  }

  function calcCfg(d) {
    var s = window.Edu.Store ? window.Edu.Store.curSettings() : {};
    var lvl = C.LEVEL_RANGE[Math.max(0, Math.min(4, d - 1))];
    var nocarry = (s && s.nocarry) ? true : (d <= 1);
    var mult = (s && s.mult) ? (d >= 2) : (d >= 4);
    if (nocarry) mult = false;
    return {
      max: (s && s.range > 0) ? s.range : lvl,
      nocarry: nocarry,
      mult: mult
    };
  }

  function makeCalcItem(q) {
    var sym = { '+':'+', '-':'−', '×':'×', '÷':'÷' }[q.op] || q.op;
    return { prompt: q.a + sym + q.b + ' = ?', input:true, correct:String(q.correct), note:q.expr };
  }

  function makeJudgeItem(q, k) {
    var wrong = q.correct + (k % 2 === 0 ? 1 : -1);
    var showCorrect = randInt(2) === 0;
    return {
      prompt: q.a + (q.op==='+'?'+':q.op==='-'?'−':q.op==='×'?'×':'÷') + q.b + ' = ' + (showCorrect ? q.correct : wrong),
      options: [{v:'true',label:'✅ 对'},{v:'false',label:'❌ 错'}],
      correct: showCorrect ? 'true' : 'false',
      note: q.expr + ' = ' + q.correct
    };
  }

  function makeWordItem(q) {
    return { prompt: q.template.replace('{a}',q.a).replace('{b}',q.b), input:true, correct:String(q.answer), note:q.a+(q.template.includes('又飞来')||q.template.includes('给了')?'+':'-')+q.b+'='+q.answer };
  }

  // 程序化生成应用题: 从模板随机取款, 数值在 max 范围内随机, 避免固定题库重复
  function makeWordAuto(max, usedKeys) {
    var C = window.Edu.Constants;
    var plus = C.WORD_PLUS, minus = C.WORD_MINUS;
    var isPlus = Math.random() < 0.5;
    var pool = isPlus ? plus : minus;
    var t = pool[Math.floor(Math.random()*pool.length)];
    // 答案范围控制: 加法 max, 减法被减数<=max
    var a, b;
    if (isPlus) {
      a = Math.floor(Math.random()*Math.max(2, Math.round(max*0.6))) + 1;
      b = Math.floor(Math.random()*Math.max(2, max - a)) + 1;
      if (b > max - a) b = Math.max(1, max - a);
    } else {
      a = Math.floor(Math.random()*max) + Math.max(1, max);
      if (a > max) a = Math.max(2, max);
      b = Math.floor(Math.random()*Math.max(1, a-1)) + 1;
    }
    var key = t.template.replace('{a}','').replace('{b}','') + '_' + isPlus + '_' + a + '_' + b;
    var guard = 0;
    while (usedKeys && usedKeys[key] && guard < 20) {
      a = Math.floor(Math.random()*max) + 1;
      b = Math.floor(Math.random()*max) + 1;
      if (!isPlus && b >= a) b = Math.max(1, a-1);
      if (isPlus && a+b > max) { a = Math.floor(Math.random()*Math.round(max*0.5))+1; b = Math.floor(Math.random()*(max-a))+1; }
      key = t.template.replace('{a}','').replace('{b}','') + '_' + isPlus + '_' + a + '_' + b;
      guard++;
    }
    if (usedKeys) usedKeys[key] = true;
    var q = { template:t.template, a:a, b:b, answer: isPlus ? a+b : a-b };
    return makeWordItem(q);
  }

  function levelRange(subj) {
    var s = window.Edu.Store ? window.Edu.Store.curSettings() : {};
    var r = s.range || 0;
    if (r) return r;
    var lv = window.Edu.Store ? window.Edu.Store.stateLevel(subj) : 1;
    return C.LEVEL_RANGE[Math.min(lv-1, C.LEVEL_RANGE.length-1)];
  }

  function stateLevel(subj) {
    return window.Edu.Store ? window.Edu.Store.stateLevel(subj) : 1;
  }

  function setLevel(subj, v) {
    if (window.Edu.Store) window.Edu.Store.setLevel(subj, v);
  }

  function diffOf(subj) {
    return stateLevel(subj);
  }

  // 发星: 答对一题 +1 星; 连续答对(≥2连)的每一题再 +2 星
  // comboBonus 由调用方按连对段累加: 每段第二个起的答对题各 +2
  function gradeQuiz(count, comboBonus) {
    return (count || 0) + (comboBonus || 0);
  }

  function seedRand(seed) {
    var x = Math.sin(seed) * 10000;
    return x - Math.floor(x);
  }

  function shuffleSeeded(a, rnd) {
    var b = a.slice();
    for (var i=b.length-1;i>0;i--){ var j=Math.floor(rnd()*(i+1)); var t=b[i];b[i]=b[j];b[j]=t; }
    return b;
  }

  function makeOptions(correct, distractors, count, labelFn) {
    var opts = [{v:String(correct), label:labelFn?labelFn(correct):String(correct), correct:true}];
    // 去重干扰项, 并排除正确答案
    var seen = new Set([String(correct)]);
    var pool = [];
    for (var d of distractors) {
      var v = String(d);
      if (!seen.has(v)) { seen.add(v); pool.push(v); }
    }
    // 洗牌
    for (var i=pool.length-1;i>0;i--){ var j=Math.floor(Math.random()*(i+1)); var t=pool[i];pool[i]=pool[j];pool[j]=t; }
    for (var k=0;k<Math.min(count-1,pool.length);k++) opts.push({v:pool[k], label:labelFn?labelFn(pool[k]):pool[k], correct:false});
    for (var m=opts.length-1;m>0;m--){ var n=Math.floor(Math.random()*(m+1)); var t2=opts[m];opts[m]=opts[n];opts[n]=t2; }
    return opts;
  }

  function toneOf(py) {
    if (!py) return 0;
    var m = String(py).match(/[āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ]/);
    if (!m) return 0;
    var idx = C.TONE_MARKS.indexOf(m[0]);
    return idx >= 0 ? (idx % 4) + 1 : 0;
  }
  function toneName(n) { return C.TONES[n-1] ? C.TONES[n-1].name : '一声'; }
  function toneEmoji(n) { return C.TONES[n-1] ? C.TONES[n-1].emoji : '📶'; }

  window.Edu.MathUtils = {
    numCn: numCn,
    mathToSpeak: mathToSpeak,
    stripBlank: stripBlank,
    isCorrect: isCorrect,
    optLabel: optLabel,
    optVal: optVal,
    makeCalc: makeCalc,
    calcCfg: calcCfg,
    makeCalcItem: makeCalcItem,
    makeJudgeItem: makeJudgeItem,
    makeWordItem: makeWordItem,
    makeWordAuto: makeWordAuto,
    levelRange: levelRange,
    stateLevel: stateLevel,
    setLevel: setLevel,
    diffOf: diffOf,
    gradeQuiz: gradeQuiz,
    seedRand: seedRand,
    shuffledSeeded: shuffleSeeded,
    shuffle: shuffle,
    sampleExclude: sampleExclude,
    makeOptions: makeOptions,
    toneOf: toneOf,
    toneName: toneName,
    toneEmoji: toneEmoji,
    randInt: randInt
  };
})();