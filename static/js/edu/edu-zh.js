(function () {
  'use strict';
  var C = window.Edu.Constants;
  var M = window.Edu.MathUtils;
  var Store = window.Edu.Store;
  var Speech = window.Edu.Speech;
  var QuizEngine = window.Edu.QuizEngine;
  var Legacy = window.Edu.Legacy;

  var wbZhMode = 'zi';
  var wbPinyinMode = 'sheng';
  var wbCiyuMode = 'fan';
  var trIdx = 0, trCi = 0, trTick = Date.now();
  var trBase = null, trInk = null, trBaseCtx = null, trInkCtx = null, trDrawing = false;
  var matchL = [], matchR = [], selL = -1, selR = -1, matchedN = 0, matchedMap = {}, matchT = Date.now();

  function wbShowPanel(id) {
    // 只隐藏「子标签页栏」(如拼音的声母/韵母), 不能隐藏答题主体 #wb-zh-body——
    // 它 id 以 wb- 开头会被(id^=wb-)兜住并置为 display:none, 导致题目写进隐藏容器「不显示」
    document.querySelectorAll('#wb-zh .sm-tabs-sub').forEach(function(d){ d.style.display = 'none'; });
    var el = document.getElementById(id);
    if (el) el.style.display = '';
    var body = document.getElementById('wb-zh-body');
    if (body) body.style.display = '';
  }

  function setTab(containerId, k) {
    var container = document.getElementById(containerId);
    if (!container) return;
    container.querySelectorAll('.sm-tab').forEach(function(b){
      b.classList.toggle('active', b.dataset.s === k);
    });
  }

  function toneOf(py) {
    if (!py) return 0;
    var m = py.match(/[āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ]/);
    if (!m) return 0;
    var idx = C.TONE_MARKS.indexOf(m[0]);
    return idx >= 0 ? (idx % 4) + 1 : 0;
  }

  function toneName(n) { return C.TONES[n-1] ? C.TONES[n-1].name : '一声'; }
  function toneEmoji(n) { return C.TONES[n-1] ? C.TONES[n-1].emoji : '📶'; }
  function mouthOf(k) { return C.MOUTH[k] || ''; }
  function stripVowel(py) { return py.replace(/[āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ]/g, function(m){ return C.TONE_MARKS[C.TONE_MARKS.indexOf(m) % 6]; }); }
  function mouthKeyOf(py) {
    var base = stripVowel(py).replace(/[0-9]/g,'');
    return base;
  }

  function traceCur() { return C.TR_CHARS[trIdx]; }
  function linePath(ctx, pts, s) { ctx.beginPath(); ctx.moveTo(pts[0].x, pts[0].y); for (var i=1;i<pts.length;i++) ctx.lineTo(pts[i].x, pts[i].y); ctx.strokeStyle=s; ctx.lineWidth=4; ctx.lineCap='round'; ctx.lineJoin='round'; ctx.stroke(); }
  function traceSetup() {
    var wrap = document.getElementById('traceWrap');
    if (!wrap) return;
    trBase = document.createElement('canvas');
    trInk = document.createElement('canvas');
    trBase.width = trInk.width = wrap.clientWidth;
    trBase.height = trInk.height = wrap.clientHeight;
    trBaseCtx = trBase.getContext('2d');
    trInkCtx = trInk.getContext('2d');
    wrap.innerHTML = '';
    wrap.appendChild(trBase);
    wrap.appendChild(trInk);
    trInk.style.position = 'absolute'; trInk.style.left = '0'; trInk.style.top = '0'; trInk.style.pointerEvents = 'none';
    traceDrawBase();
    trInk.addEventListener('touchstart', trDown);
    trInk.addEventListener('touchmove', trMove);
    trInk.addEventListener('touchend', trUp);
    trInk.addEventListener('mousedown', trDown);
    trInk.addEventListener('mousemove', trMove);
    trInk.addEventListener('mouseup', trUp);
    trInk.addEventListener('mouseleave', trUp);
  }

  function traceResetInk() { if (trInkCtx) trInkCtx.clearRect(0,0,trInk.width,trInk.height); }
  function traceDrawBase() {
    if (!trBaseCtx) return;
    trBaseCtx.clearRect(0,0,trBase.width,trBase.height);
    var ch = traceCur();
    if (!ch) return;
    trBaseCtx.font = 'bold 180px Noto Serif SC, serif';
    trBaseCtx.textAlign = 'center'; trBaseCtx.textBaseline = 'middle';
    trBaseCtx.fillStyle = 'rgba(0,0,0,0.08)';
    trBaseCtx.fillText(ch.char, trBase.width/2, trBase.height/2 + 10);
    ch.strokes.forEach(function(stroke){ linePath(trBaseCtx, stroke, 'rgba(0,0,0,0.15)'); });
  }

  function updateTrHint() {
    var el = document.getElementById('trHint');
    if (el) el.textContent = '描红：' + traceCur().name;
  }

  function trPos(e) {
    var rect = trInk.getBoundingClientRect();
    var ct = e.touches ? e.touches[0] : e;
    return { x: ct.clientX - rect.left, y: ct.clientY - rect.top };
  }

  function trDown(e) { e.preventDefault(); trDrawing = true; trInkCtx.beginPath(); var p = trPos(e); trInkCtx.moveTo(p.x, p.y); }
  function trMove(e) { if (!trDrawing) return; e.preventDefault(); var p = trPos(e); trInkCtx.lineTo(p.x, p.y); trInkCtx.strokeStyle = '#e74c3c'; trInkCtx.lineWidth = 4; trInkCtx.lineCap = 'round'; trInkCtx.stroke(); }
  function trUp(e) { if (!trDrawing) return; trDrawing = false; trCheckDone(); }

  function trCheckDone() {
    var imgData = trInkCtx.getImageData(0,0,trInk.width,trInk.height).data;
    var inkPx = 0;
    for (var i=3;i<imgData.length;i+=4) if (imgData[i] > 50) inkPx++;
    var baseData = trBaseCtx.getImageData(0,0,trBase.width,trBase.height).data;
    var basePx = 0;
    for (var j=3;j<baseData.length;j+=4) if (baseData[j] > 10) basePx++;
    var ratio = basePx ? inkPx / basePx : 0;
    if (ratio > 0.45) { traceDone(); }
  }

  function traceDone() {
    Speech.playSpeak('写得真好');
    trCi++;
    if (trCi >= 3) { trCi = 0; trIdx = (trIdx + 1) % C.TR_CHARS.length; }
    traceDrawBase();
    traceResetInk();
    updateTrHint();
  }

  function traceRender(body) {
    body.innerHTML = '<div class="trace-wrap" id="traceWrap" style="width:100%;aspect-ratio:1;background:linear-gradient(135deg,#fffdf5,#fef3e2);border-radius:16px;border:2px solid var(--edu-border-2);touch-action:none;"></div>' +
      '<div style="margin-top:12px;text-align:center;"><span id="trHint" style="font-size:1rem;font-weight:700;color:var(--edu-ink);"></span></div>' +
      '<div class="trace-actions" style="display:flex;gap:8px;justify-content:center;margin-top:12px;">' +
      '<button type="button" class="btn-soft" onclick="window.Edu.ZhWorkbench.traceRedo()">重写</button>' +
      '<button type="button" class="btn-soft" onclick="window.Edu.ZhWorkbench.traceSkip()">跳过</button>' +
      '<button type="button" class="btn-soft" onclick="window.Edu.ZhWorkbench.traceNext()">下一个</button>' +
      '</div>';
    setTimeout(function(){ traceSetup(); updateTrHint(); }, 0);
  }

  window.Edu.ZhWorkbench = {
    wbZhMode: wbZhMode,
    wbPinyinMode: wbPinyinMode,
    wbCiyuMode: wbCiyuMode,
    trIdx: trIdx,
    trCi: trCi,
    traceCur: traceCur,
    traceSetup: traceSetup,
    traceResetInk: traceResetInk,
    traceDrawBase: traceDrawBase,
    updateTrHint: updateTrHint,
    trPos: trPos,
    trDown: trDown,
    trMove: trMove,
    trUp: trUp,
    trCheckDone: trCheckDone,
    traceDone: traceDone,
    traceRender: traceRender,
    toneOf: toneOf,
    toneName: toneName,
    toneEmoji: toneEmoji,
    mouthOf: mouthOf,
    stripVowel: stripVowel,
    mouthKeyOf: mouthKeyOf,
    setTab: setTab,
    wbShowPanel: wbShowPanel
  };

  window.Edu.ZhWorkbench.traceRedo = function () { traceResetInk(); };
  window.Edu.ZhWorkbench.traceSkip = function () { trCi = 3; traceDone(); };
  window.Edu.ZhWorkbench.traceNext = function () { trCi = 3; traceDone(); };

  window.wbZh = function (k) {
    wbZhMode = k;
    if (window.Edu.Workbench && window.Edu.Workbench.showSubjectSection) window.Edu.Workbench.showSubjectSection('zh');
    setTab('wb-zh', k);
    wbShowPanel('wb-zh');
    var pinyinTab = document.getElementById('wb-pinyin');
    if (pinyinTab) pinyinTab.style.display = (k === 'pinyin') ? '' : 'none';
    var pinyinBody = document.getElementById('wb-pinyin-body');
    if (pinyinBody) pinyinBody.style.display = (k === 'pinyin') ? '' : 'none';
    wbRenderZh();
    Store.saveWb();
  };

  window.wbPinyin = function (k) {
    wbPinyinMode = k;
    setTab('wb-pinyin', k);
    wbRenderZh();
    Store.saveWb();
  };

  window.wbCiyu = function (k) {
    wbCiyuMode = k;
    setTab('wb-ciyu', k);
    wbRenderZh();
    Store.saveWb();
  };

  function wbRenderZh() {
    var body = document.getElementById('wb-zh-body');
    if (!body) return;
    var type, title, items;
    if (wbZhMode === 'trace') { traceRender(body); return; }
    if (wbZhMode === 'poem' || wbZhMode === 'zi' || wbZhMode === 'stroke' || wbZhMode === 'pinyin' || wbZhMode === 'ciyu') {
      type = wbZhMode;
      if (wbZhMode === 'pinyin') type = (wbPinyinMode === 'yun') ? 'yun' : ((wbPinyinMode === 'read') ? 'read' : ((wbPinyinMode === 'tone') ? 'tone' : 'pinyin'));
      if (wbZhMode === 'ciyu') type = (wbCiyuMode === 'liang') ? 'liang' : 'fan';
      title = { zi:'识字', pinyin:'拼音', ciyu:'词语', poem:'古诗', stroke:'笔顺' }[wbZhMode] || type;
    }
    if (type === 'zi') {
      // 听音选词: 题干不显示目标词, 播放词语读音→从选项中选出听到的词
      // 选项使用 2000 常用字的例词, 而非单字, 更贴合真实听音场景
      var pool = C.ZI_2000 || C.ZI;
      var rec = window.Edu.QuizEngine && (window.Edu.QuizEngine.recentExclude || []);
      var n = Math.min(C.QUIZ_LEN || 10, pool.length);
      var chosen = [];
      if (pool.length && n > 0) {
        var scored = pool.map(function(z, i){
          var weight = (1000 - i) / 1000;
          if (rec && rec.indexOf(z.id) >= 0) weight -= 3;
          weight += Math.random();
          return { z: z, w: weight };
        });
        scored.sort(function(a, b){ return b.w - a.w; });
        for (var k = 0; k < n && k < scored.length; k++) chosen.push(scored[k].z);
      }
      if (chosen.length === 0) chosen = pool.slice(0, n);
      // 词语池: 用于生成干扰项
      var wordPool = chosen.map(function(z){ return z.ex || z.prompt; });
      items = chosen.map(function(z){
        var word = z.ex || z.prompt;
        // 预合成语音(后台请求 TTS API, 利用浏览器/服务端缓存), 游戏时秒开
        if (window.Speech && Speech.preloadTTS) Speech.preloadTTS(word);
        // 选项从词语池抽取(去重), 确保是词语而非单字
        var otherWords = wordPool.filter(function(w){ return w !== word; });
        return { id:z.id, type:'zi', prompt:'听一听，是哪个词？', big:'', listen:word, word:word, pinyin:z.pinyin, note:word,
          correct:word, options:M.makeOptions(word, otherWords, 4) };
      });
      if (window.Edu.QuizEngine) window.Edu.QuizEngine.recentExclude =
        (window.Edu.QuizEngine.recentExclude || []).concat(chosen.map(function(z){ return z.id; })).slice(-40);
    } else if (type === 'pinyin' || type === 'yun' || type === 'read' || type === 'tone') {
      if (type === 'pinyin') {
        items = C.P_SHENG.map(function(s){ return { id:'sh_'+s.id, type:'pinyin', prompt:'「'+s.zi+'（'+s.py+'）」的声母是？', big:s.e+' '+s.zi, options:M.makeOptions(s.s, C.P_SHENG.map(function(t){return t.s;}), 4), correct:s.s, note:'声母 '+s.s }; });
      } else if (type === 'yun') {
        items = C.P_YUN.map(function(y){ return { id:'yun_'+y.id, type:'pinyin', prompt:'「'+y.zi+'（'+y.py+'）」的韵母是？', big:y.e+' '+y.zi, options:M.makeOptions(y.u, C.P_YUN.map(function(t){return t.u;}), 4), correct:y.u, note:'韵母 '+y.u }; });
      } else if (type === 'read') {
        items = C.P_READ.map(function(p){ return { id:'read_'+p.id, type:'pinyin', prompt:'「'+p.zi+'」这个字怎么读？', big:p.e+' '+p.zi, options:M.makeOptions(p.py, C.P_READ.map(function(t){return t.py;}), 4), correct:p.py, note:p.py }; });
      } else if (type === 'tone') {
        items = C.P_READ.map(function(p){ var t = toneOf(p.py); return { id:'tone_'+p.id, type:'pinyin', prompt:'「'+p.zi+'」读「'+p.py+'」，它是第几声呀？', big:p.e+' '+p.zi, options:C.TONES.map(function(tt){return tt.name;}), correct:toneName(t), note:p.py }; });
      }
    } else if (type === 'fan' || type === 'liang') {
      var src2 = (type === 'liang') ? C.LIANGCI : C.FANCI;
      items = src2.map(function(c){ return { id:c.prompt.replace(/\s/g,''), type:'ciyu', prompt:c.prompt, options:c.options, correct:c.correct }; });
    } else if (type === 'stroke') {
      items = C.STROKES.map(function(s){ return { id:s.id, type:'stroke', prompt:s.char, options:['横','竖','撇','点','折'], correct:s.name }; });
    } else if (type === 'poem') {
      items = C.POEMS.map(function(p){
        var lines = p.lines.slice();
        var idx = Math.floor(Math.random()*lines.length);
        var blank = lines[idx];
        lines[idx] = '____';
        return { id:p.id, type:'poem', prompt:p.title + '：' + lines.join('，'), input:true, correct:blank, note:p.title + ' - ' + p.author };
      });
    }
    if (items && items.length > C.QUIZ_LEN) items = items.slice(0, C.QUIZ_LEN);
    if (items) QuizEngine.startQuiz('zh', type, items, { difficulty: M.diffOf('zh') });
  }

  function renderMatch(body) {
    var n = 5;
    matchL = C.WORDS.slice(0,n).map(function(w){ return {id:w.id, text:w.word, cn:w.cn}; });
    matchR = C.WORDS.slice(0,n).map(function(w){ return {id:w.id, text:w.cn, cn:w.word}; });
    for (var i=matchR.length-1;i>0;i--){ var j=Math.floor(Math.random()*(i+1)); var t=matchR[i]; matchR[i]=matchR[j]; matchR[j]=t; }
    selL = selR = -1; matchedN = 0; matchedMap = {}; matchT = Date.now();
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
      return '<button type="button" class="match-btn '+(done?'done':'')+' '+(selL===i?'sel':'')+'" onclick="window.Edu.ZhWorkbench.matchLpick('+i+')">'+(done?'✅ ':'')+m.text+'</button>';
    }).join('');
    r.innerHTML = matchR.map(function(m, i){
      var done = matchedMap[m.id];
      return '<button type="button" class="match-btn '+(done?'done':'')+' '+(selR===i?'sel':'')+'" onclick="window.Edu.ZhWorkbench.matchRpick('+i+')">'+(done?'✅ ':'')+m.text+'</button>';
    }).join('');
    if (msg) msg.textContent = matchedN === n ? '全部配对完成！' : '点击左右两边配对';
  }

  window.Edu.ZhWorkbench.matchLpick = function (i) {
    if (matchedMap[matchL[i].id]) return;
    selL = i;
    if (selR >= 0) { checkMatch(); }
    matchDraw();
  };

  window.Edu.ZhWorkbench.matchRpick = function (i) {
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

  window.Edu.ZhWorkbench.matchDraw = matchDraw;
  window.Edu.ZhWorkbench.checkMatch = checkMatch;
})();