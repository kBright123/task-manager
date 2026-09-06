(function () {
  'use strict';
  var C = window.Edu.Constants;
  var Store = window.Edu.Store;
  var Speech = window.Edu.Speech;

  // 繁体大写数字: 题目用「繁体字」编写, 需要把中文数字转为阿拉伯数字作答
  var TRAD = ['零', '壹', '贰', '叁', '肆', '伍', '陆', '柒', '捌', '玖'];

  function tradN(n) {
    n = Math.max(0, Math.floor(n));
    if (n < 10) return TRAD[n];
    if (n < 20) return '拾' + (n % 10 ? TRAD[n % 10] : '');
    var t = Math.floor(n / 10), o = n % 10;
    return (t === 1 ? '拾' : TRAD[t] + '拾') + (o ? TRAD[o] : '');
  }

  var block = false;        // 是否正处于拦截中(拦截期间暂停答题推进)
  var pendingAdvance = false;  // 拦截时被挂起的自动进下一题
  var ticker = null;
  var lastTick = 0;
  var problem = null;

  function isBlocking() { return block; }

  function over() {
    return !!(Store && Store.usageOver && Store.usageOver());
  }

  // 每 15 秒累计一次页面学习时长, 达到上限即弹出验证弹框
  function tick() {
    if (!Store || !Store.addUsageSecs) return;
    var now = Date.now();
    if (!lastTick) lastTick = now;
    var secs = Math.round((now - lastTick) / 1000);
    lastTick = now;
    if (secs > 0) {
      // 弹框拦截期间不计入学习时长, 否则等待解答也会被算作已学时间
      if (!block) Store.addUsageSecs(secs);
      if (over()) showGate();
    }
  }

  function start() {
    if (ticker) return;
    // 页面不可见(后台/node 测试环境)时不启动计时, 避免长期占用/挂起事件循环
    try { if (document.visibilityState !== 'visible') { lastTick = Date.now(); return; } } catch (e) { lastTick = Date.now(); return; }
    lastTick = Date.now();
    ticker = setInterval(tick, 15000);
    if (typeof window.addEventListener === 'function') {
      var onVis = function () {
        if (document.hidden) {
          // 离开页面期间不算学习时长
          lastTick = Date.now();
          return;
        }
        if (!ticker) { lastTick = Date.now(); ticker = setInterval(tick, 15000); }
        else lastTick = Date.now();
        // 刷新/切回都会重新检查, 满足超时则再次拦截
        if (over()) showGate();
      };
      window.addEventListener('visibilitychange', onVis);
      window.addEventListener('focus', onVis);
    }
    if (over()) showGate();
  }

  function buildProblem() {
    var op = Math.random() < 0.5 ? '＋' : '－';
    var a = 1 + Math.floor(Math.random() * 50);
    var b = 1 + Math.floor(Math.random() * 50);
    if (op === '－' && a < b) { var t = a; a = b; b = t; }
    problem = { a: a, b: b, op: op, ans: (op === '＋') ? a + b : a - b };
  }

  function mask() {
    var el = document.getElementById('eduGateMask');
    if (!el || !el.parentNode) {
      el = document.createElement('div');
      el.id = 'eduGateMask';
      el.className = 'edu-gate-mask';
      el.style = el.style || {};
      document.body.appendChild(el);
    }
    return el;
  }

  function starV() {
    return (Store && Store.state && Store.state.stars) || 0;
  }

  function renderGate() {
    var el = mask();
    var usedMin = Math.max(1, Math.round(Store.usageUsedSec() / 60));
    var errTxt = '';
    el.innerHTML =
      '<div class="edu-gate-card">' +
        '<div class="eg-icon">⏰</div>' +
        '<div class="eg-title">学习时间到啦</div>' +
        '<div class="eg-sub">今天已经学了 ' + usedMin + ' 分钟，休息一下吧～<br>解锁后可以再学 ' + C.USAGE_UNLOCK_MIN + ' 分钟哦</div>' +
        '<button type="button" class="eg-btn eg-star" onclick="window.eduGateUnlockStars()">⭐ 用 ' + C.USAGE_UNLOCK_STARS + ' 颗星星解锁 ' + C.USAGE_UNLOCK_MIN + ' 分钟</button>' +
        '<div class="eg-divider">· 或 ·</div>' +
        '<div class="eg-math-title">答对下面的繁体数学题也能解锁：</div>' +
        '<div class="eg-problem"><span class="eg-p-trad">' + tradN(problem.a) + '</span><span class="eg-p-op">' + problem.op + '</span><span class="eg-p-trad">' + tradN(problem.b) + '</span><span class="eg-p-eq">＝</span><span class="eg-p-q">?</span></div>' +
        '<div class="eg-ans-row"><input id="eduGateAns" class="eg-input" type="number" inputmode="numeric" placeholder="?" aria-label="答案" autocomplete="off"></input>' +
        '<button type="button" class="eg-btn eg-go" onclick="window.eduGateCheck()">确认</button></div>' +
        '<div class="eg-err" id="eduGateErr">' + errTxt + '</div>' +
        '<div class="eg-fine">答错的话还不能继续哦，要答对才能解锁～</div>' +
      '</div>';
    el.style.display = 'flex';
  }

  function showGate() {
    if (block) return;
    block = true;
    pendingAdvance = false;
    buildProblem();
    renderGate();
  }

  function closeGate(needAdvance) {
    var el = document.getElementById('eduGateMask');
    if (el) { el.style.display = 'none'; el.innerHTML = ''; }
    block = false;
    pendingAdvance = false;
    lastTick = Date.now();
    if (needAdvance && window.Edu && window.Edu.QuizEngine) {
      window.Edu.QuizEngine.quizNext();
    }
  }

  // 扣 100 星星解锁: 星星不足不可选
  window.eduGateUnlockStars = function () {
    if (!block) return;
    if (starV() < C.USAGE_UNLOCK_STARS) {
      var err = document.getElementById('eduGateErr');
      if (err) { err.textContent = '星星不足 ' + C.USAGE_UNLOCK_STARS + ' 颗，答对题目也能解锁哦'; }
      return;
    }
    Store.state.stars = starV() - C.USAGE_UNLOCK_STARS;
    Store.addUsageUnlock();
    var adv = pendingAdvance;
    closeGate(adv);
    if (Speech && Speech.toast) Speech.toast('已扣 ' + C.USAGE_UNLOCK_STARS + ' 颗星星，再学 ' + C.USAGE_UNLOCK_MIN + ' 分钟 💫');
  };

  // 繁体数学题校验: 答对方可解锁, 打错无法继续
  window.eduGateCheck = function () {
    if (!block) return;
    var inp = document.getElementById('eduGateAns');
    var ans = inp ? String(inp.value).trim() : '';
    if (ans === '') return;
    if (String(ans).replace(/^0+(?=\d)/, '') === String(problem.ans)) {
      Store.addUsageUnlock();
      var adv = pendingAdvance;
      closeGate(adv);
      if (Speech && Speech.toast) Speech.toast('答对啦！再学 ' + C.USAGE_UNLOCK_MIN + ' 分钟，到点记得休息哦 🌈');
    } else {
      var err = document.getElementById('eduGateErr');
      if (err) err.textContent = '答错啦，还不能继续哦～再想想';
      if (inp) { inp.value = ''; try { inp.focus(); } catch (e) {} }
    }
  };

  window.Edu.UsageGate = {
    start: start,
    showGate: showGate,
    isBlocking: isBlocking,
    get pendingAdvance() { return pendingAdvance; },
    set pendingAdvance(v) { pendingAdvance = !!v; },
    tradN: tradN,
    _setBlock: function (v) { block = !!v; },
    _buildProblem: buildProblem,
    _getProblem: function () { return problem; },
    _setProblem: function (p) { problem = p; }
  };
})();