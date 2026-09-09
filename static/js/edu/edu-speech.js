(function () {
  'use strict';
  var C = window.Edu.Constants;
  var M = window.Edu.MathUtils;

  var zhVoice = null;
  var speakFBTimer = null;
  var lastSpeakText = '', lastSpeakAt = 0;
  var netAudio = null, netAudioUrl = '';
  var speakSeq = 0;   // 播放会话序号: 新增/停止播放时自增, 作废所有在途播放/重试回调

  function pickZhVoice() {
    if (typeof speechSynthesis === 'undefined') return;
    var vs = speechSynthesis.getVoices();
    zhVoice = vs.find(function(v){ return /zh.*CN/i.test(v.lang); }) || vs.find(function(v){ return /zh/i.test(v.lang); }) || null;
  }
  if (typeof speechSynthesis !== 'undefined') {
    speechSynthesis.onvoiceschanged = pickZhVoice;
    pickZhVoice();
  }

  function speakOn() {
    try { var v = localStorage.getItem(C.SPEAK_ON_KEY); return v !== 'false'; } catch(e){ return true; }
  }

  function setSpeakIcon() {
    var btn = document.getElementById('soundToggle');
    if (btn) btn.textContent = speakOn() ? '🔊' : '🔇';
  }

  // iOS/iPad 判定: 网络音频几乎只能在手势内同步 .play() 才出声, 兜底也需手势内调系统音。
  var isIos = (function () {
    if (typeof navigator === 'undefined') return false;
    return /iP(hone|ad|od)/.test(navigator.userAgent) ||
      (/Macintosh/.test(navigator.userAgent) && typeof navigator.maxTouchPoints === 'number' && navigator.maxTouchPoints > 1);
  })();

  // iOS/iPad Safari: 音频需在首个手势内激活, 否则 new Audio().play() 会被自动播放策略
  // 静默拒绝。首次 touch/click 时预热 AudioContext + 播放一段静音, 把页面标记为已交互。
  var audioUnlocked = false;
  var warmCtx = null;
  function unlockAudio() {
    if (audioUnlocked) return;
    audioUnlocked = true;
    try {
      var AC = window.AudioContext || window.webkitAudioContext;
      if (AC) {
        if (!warmCtx) warmCtx = new AC();
        if (warmCtx && warmCtx.state === 'suspended' && warmCtx.resume) warmCtx.resume();
        var buf = warmCtx.createBuffer(1, 1, 22050);
        var src = warmCtx.createBufferSource();
        src.buffer = buf;
        src.connect(warmCtx.destination);
        src.start(0);
      }
    } catch (e) {}
  }
  if (typeof document !== 'undefined' && document.addEventListener) {
    var _waitUnlock = function () { unlockAudio(); };
    ['pointerdown', 'touchstart', 'click'].forEach(function (ev) {
      document.addEventListener(ev, _waitUnlock, { once: true, capture: true, passive: true });
    });
  }

  window.Edu.Speech = window.Edu.Speech || {};
  window.Edu.Speech.unlockAudio = unlockAudio;

  window.Edu.Speech.toggleSpeak = function () {
    var on = !speakOn();
    try { localStorage.setItem(C.SPEAK_ON_KEY, on); } catch(e){}
    setSpeakIcon();
    if (on) window.Edu.Speech.playSpeak('声音已开启');
  };

  window.Edu.Speech.playSpeak = function (text, force) {
    if (!text) return;
    if (speakOn()) {
      if (force) playSpeakForceNet(text);  // 用户主动点击: 强制网络 TTS(有用户交互, 绕过自动播放拦截)
      else speak(text, force);            // 自动播放: 本地优先+兜底
    }
  };

  function ttLang(t) {
    var han = (t.match(/[\u4e00-\u9fff]/g)||[]).length;
    var lat = (t.match(/[a-zA-Z]/g)||[]).length;
    return han >= lat ? 'zh' : 'en';
  }

  function stopNetAudio() {
    speakSeq++;                       // 作废在途播放/重试回调, 杜绝旧音频晚到“再放一遍”
    if (netAudio) { netAudio.pause(); netAudio.src = ''; netAudio = null; }
    netAudioUrl = '';
  }

  // 停止一切语音: 网络音频 + 本地 speechSynthesis(切到下一题/退出答题时调用)
  function stopSpeech() {
    stopNetAudio();
    try {
      if (typeof speechSynthesis !== 'undefined' && speechSynthesis.cancel) speechSynthesis.cancel();
    } catch (e) {}
  }

  function playAudio(urls) {
    stopNetAudio();
    var i = 0;
    function tryNext() {
      if (i >= urls.length) return;
      netAudio = new Audio(urls[i]);
      netAudio.onerror = function(){ i++; tryNext(); };
      netAudio.onended = function(){ stopNetAudio(); };
      netAudio.play().catch(function(){ i++; tryNext(); });
    }
    tryNext();
  }

  // 音色清单(与后端 _TTS_VOICES 对应): id -> 中文名
  var TTS_VOICES = [
    { id: 'xiaoxiao', name: '晓晓 · 温暖女声' },
    { id: 'xiaoyi', name: '小艺 · 活泼' },
    { id: 'yunxi', name: '云希 · 清晰' },
    { id: 'yunyang', name: '云扬 · 沉稳' }
  ];

  function curVoice() {
    try {
      var s = window.Edu && window.Edu.Store && window.Edu.Store.curSettings ? window.Edu.Store.curSettings() : null;
      if (s && s.voice) return s.voice;
    } catch (e) {}
    return 'xiaoxiao';
  }

  function ttsUrl(text) {
    var le = ttLang(text);
    // cv: 缓存版本号。服务端音频编码格式变更(MPEG-2→MPEG-1)后, 浏览器可能仍用 immutable 旧缓存,
    // 升号强制重拉新字节。
    return '/edu/api/tts?text=' + encodeURIComponent(text) + '&lang=' + le + '&v=' + curVoice() + '&cv=1';
  }

  function playNetTTS(text) {
    playAudio([ttsUrl(text)]);
  }

  // 预加载 TTS 音频(浏览器走 HTTP 缓存), 缓解「语音首播 3 秒+ 延迟」
  function preloadTTS(text) {
    if (!text || typeof window === 'undefined' || typeof window.Audio === 'undefined') return;
    try {
      var a = new Audio(ttsUrl(text));
      if (typeof a.preload === 'string') a.preload = 'auto';
    } catch (e) {}
  }

  // 网络 TTS(edge-tts 高音质, 服务端缓存同源 mp3) 带超时: 仅在本地合成不可用/失败时兜底
  function playNetTimed(text, onFail, timeout) {
    var url = ttsUrl(text);
    var mySeq = speakSeq;             // 捕获当前会话; 一旦有新播放/停止即整体作废
    var attempts = 0, MAX_ATTEMPTS = 2, T_TIMEOUT = timeout || 12000;
    var done = false, played = false, started = false, current = null, cleanTimer = null;

    function finish(ok, err) {
      if (done || mySeq !== speakSeq) return;
      done = true;
      if (cleanTimer) clearTimeout(cleanTimer);
      if (current) { try { current.onerror = current.oncanplaythrough = current.onended = null; } catch (e) {} }
      if (!ok) { stopNetAudio(); if (onFail) onFail(err || 'network_error'); }
    }

    function attempt() {
      if (done || mySeq !== speakSeq) return;
      if (attempts >= MAX_ATTEMPTS) { if (!done && mySeq === speakSeq) finish(false, 'network_error'); return; }
      attempts++;
      var a = new Audio(url);
      current = a;
      function tryPlay() {
        if (started || done || mySeq !== speakSeq) return;
        played = true; started = true;
        if (cleanTimer) clearTimeout(cleanTimer);
        var p = a.play();
        if (p && p.catch) p.catch(function(){});
      }
      function failOnce(err) {
        if (done || mySeq !== speakSeq) return;
        try { a.onerror = a.oncanplaythrough = a.onended = a.onloadeddata = null; a.pause(); a.src = ''; } catch (e) {}
        a = null;
        if (attempts < MAX_ATTEMPTS) {
          if (cleanTimer) clearTimeout(cleanTimer);
          attempt();
        } else {
          finish(false, err);
        }
      }
      a.onerror = function(){ failOnce('network_error'); };
      a.onloadeddata = tryPlay;         // 首帧数据就绪即播放, 减小等待感
      a.oncanplaythrough = tryPlay;     // 缓冲充足后再兜底触发(幂等)
      a.onended = function(){
        if (done || mySeq !== speakSeq) return;
        finish(true);
        stopNetAudio();
      };
      if (cleanTimer) clearTimeout(cleanTimer);
      cleanTimer = setTimeout(function(){ if (mySeq === speakSeq) failOnce(played ? 'autoplay_blocked' : 'network_timeout'); }, T_TIMEOUT);
      try { a.load(); } catch (e) {}
      netAudio = a;
    }
    attempt();
  }

  // 用户点击触发的网络 TTS(有用户交互, 可绕过自动播放策略)
  // 强化: 超时 + 失败重试(重新建 Audio 元素); 网络迟迟不出声时回退本地合成(不干等)
  function playNetTTSUserGesture(text, onFail, onstart) {
    if (typeof window === 'undefined' || typeof window.Audio === 'undefined') return;
    var url = ttsUrl(text);
    stopNetAudio();                       // 停旧播放并自增会话, 作废在途回调
    var mySeq = speakSeq;                 // 本次点击独占本次会话
    var attempts = 0, MAX_ATTEMPTS = 2, T_TIMEOUT = 4500;
    var played = false, started = false, done = false, cleanTimer = null;

    function finish(ok, msg) {
      if (done || mySeq !== speakSeq) return;
      done = true;
      if (cleanTimer) clearTimeout(cleanTimer);
      if (!ok) { stopNetAudio(); if (onFail) onFail(msg || 'network_error'); }
    }

    function attempt() {
      if (done || mySeq !== speakSeq) return;
      if (attempts >= MAX_ATTEMPTS) { if (!done && mySeq === speakSeq) finish(false, played ? '' : 'network_error'); return; }
      attempts++;
      var a = new Audio(url);
      function tryPlay() {
        if (started || done || mySeq !== speakSeq) return;
        started = true; played = true;
        if (cleanTimer) clearTimeout(cleanTimer);
        var p = a.play();
        if (p && p.catch) p.catch(function(){});
      }
      function fail() {
        if (done || mySeq !== speakSeq) return;
        a.onerror = a.oncanplaythrough = a.onended = a.onloadeddata = null;
        try { a.pause(); a.src = ''; } catch (e) {}
        if (attempts < MAX_ATTEMPTS) {
          if (cleanTimer) clearTimeout(cleanTimer);
          attempt();
        } else {
          finish(false, played ? '' : '网络语音加载失败，请再点一次');
        }
      }
      a.onerror = fail;
      a.onplaying = function(){ if (!done && mySeq === speakSeq && onstart) onstart(); }; // 真正开始出声
      a.onended = function(){ if (done || mySeq !== speakSeq) return; finish(true); stopNetAudio(); };
      a.onloadeddata = tryPlay;           // 首帧数据就绪即播放, 减小等待感
      a.oncanplaythrough = tryPlay;       // 兜底触发(幂等)
      if (cleanTimer) clearTimeout(cleanTimer);
      cleanTimer = setTimeout(function(){ if (mySeq === speakSeq) fail(); }, T_TIMEOUT);
      try { a.load(); } catch (e) {}
      netAudio = a;
      // iOS: attempt() 此刻仍在点击手势内同步执行 —— 立即同步 .play() 满足
      // "手势内起播"要求, 数据就绪后自动续播; 异步回调里的 .play() 在 iOS 会被拦截。
      if (isIos) {
        try {
          var pr = a.play();
          if (pr && pr.catch) pr.catch(function(){});
        } catch (e) {}
      }
    }
    attempt();
  }

  // 预加载网络音频到缓存(不播放)
  function preloadNetTTS(text) {
    if (typeof window === 'undefined' || typeof window.Audio === 'undefined') return;
    try {
      var a = new Audio(ttsUrl(text));
      a.preload = 'auto';
      a.onerror = function(){}; // 静默忽略预加载错误
    } catch (e) {}
  }

  // 本地兜底: 网络 TTS 失败/被自动播放拦截时, 用系统 speechSynthesis(音色即系统音, 与设置不同)
  // —— 仅当无法通过 edge-tts 使用「我的」所选音色时的最后手段。
  function speakLocal(t) {
    try {
      var u = new SpeechSynthesisUtterance(t);
      u.lang = ttLang(t) === 'zh' ? 'zh-CN' : 'en-US';
      u.rate = 1.0;
      var vs = speechSynthesis.getVoices();
      var v = zhVoice || vs.find(function(x){ return /zh.*CN/i.test(x.lang); }) || vs.find(function(x){ return /zh/i.test(x.lang); });
      if (v) u.voice = v;
      speechSynthesis.cancel();
      speechSynthesis.speak(u);
    } catch (e) {}
  }

  // 主播放入口: 网络 TTS(edge-tts, 遵循「我的」选择的音色) 优先,
  // 失败/自动播放被拦时快速回退本地 speechSynthesis(网络不可用才用它, 保证音色与设置一致)。
  function speak(text, force) {
    if (!text || !speakOn() || typeof window === 'undefined' || typeof window.Audio === 'undefined') return;
    var t = M.mathToSpeak(String(text));
    var now = Date.now();
    if (!force && t === lastSpeakText && now - lastSpeakAt < 1200) return;
    lastSpeakText = t; lastSpeakAt = now;

    // 先预加载网络音频(后台缓存), 以便兜底时秒开
    preloadNetTTS(t);

    // 网络 TTS 失败/超时/被拦截 → 本地 speechSynthesis 兜底(短超时, 尽快出声)
    playNetTimed(t, function(){
      speakLocal(t);
    }, 2500);
  }

  // 供按钮点击调用: 强制走网络 TTS(有用户交互, 成功率最高)
  function playSpeakForceNet(text) {
    if (!text || !speakOn()) return;
    var t = M.mathToSpeak(String(text));
    lastSpeakText = t; lastSpeakAt = Date.now();
    if (isIos) {
      // 这台 iPad 实测: ① DOM <audio> 元素(http/blob 均)整条管线不工作; ② fetch+Web Audio
      // decodeAudioData→AudioContext 播 PCM 反而能出晓晓音色(独立管线, 首手势已解锁)。
      // 流程: 点击后只走 AC 解码晓晓(不先起系统音, 避免双音重叠); ~1.8s 未出声才补系统音兜底;
      // AC 一旦出声立即取消系统音。
      var url = ttsUrl(t);
      iOSProbeShow(url, t);
      var sysPending = true;
      setTimeout(function () {
        if (!sysPending) return;
        iOSProbeMark('系统音兜底');
        speakLocal(t);
      }, 1800);
      playIosAudio(url, function () {
        iOSProbeMark('AC解码已出声');
        sysPending = false;
        try { if (window.speechSynthesis) speechSynthesis.cancel(); } catch (e) {}
      }, function (err) {
        iOSProbeMark('iOS音频失败:' + err);
      });
      return;
    }
    playNetTTSUserGesture(t, function(){ speakLocal(t); });  // 网络慢/失败 → 本地兜底, 不干等
  }

  // iOS: AC decodeAudioData 解码播放(主) → blob <audio>(兜底)。若主路成功即停调系统音。
  function playIosAudio(url, onStart, onFail) {
    var mySeq = speakSeq, done = false;
    function finish(started, msg) {
      if (done || mySeq !== speakSeq) return;
      done = true;
      if (started) { if (onStart) onStart(); }
      else if (onFail) onFail(msg || '音频不出声');
    }
    tryAc();
    function tryAc() {
      try {
        var AC = window.AudioContext || window.webkitAudioContext;
        if (!AC) { tryBlob(); return; }
        if (!warmCtx) warmCtx = new AC();
        var ctx = warmCtx;
        var t = setTimeout(function () {
          clearTimeout(t);
          tryBlob();  // 解码迟迟不回调 → 改走 blob 兜底
        }, 4000);
        fetch(url).then(function (r) { return r.arrayBuffer(); }).then(function (ab) {
          return new Promise(function (res, rej) { ctx.decodeAudioData(ab, res, rej); });
        }).then(function (buf) {
          clearTimeout(t);
          if (!buf || done || mySeq !== speakSeq) return;
          if (ctx.state === 'suspended' && ctx.resume) ctx.resume();
          var src = ctx.createBufferSource();
          src.buffer = buf;
          var g = ctx.createGain(); g.gain.value = 1;
          src.connect(g); g.connect(ctx.destination);
          src.onended = function () { try { src.disconnect(); g.disconnect(); } catch (e) {} };
          src.start(0);
          finish(true);
        }, function (err) {
          clearTimeout(t);
          iOSProbeMark('AC解码失败:' + (err && err.message || err));
          tryBlob();
        });
      } catch (e) { tryBlob(); }
    }
    function tryBlob() {
      playBlobIos(url, function () {
        iOSProbeMark('blob已出声');
        finish(true);
      }, function (err) {
        finish(false, err || '媒体不出声');
      }, 5000);
    }
  }

  // iOS: 用 fetch 拿到 mp3 字节 → blob URL 播放(http 音频元素在该 iPad 渲染不出声)。
  function playBlobIos(url, onStart, onFail, timeout) {
    if (typeof fetch !== 'function' || typeof URL === 'undefined' || !URL.createObjectURL) { if (onFail) onFail('no_blob'); return; }
    var mySeq = speakSeq;
    var done = false, a = null, t = null;
    function finish(ok, msg) {
      if (done || mySeq !== speakSeq) return;
      done = true;
      if (t) clearTimeout(t);
      if (!ok) { if (onFail) onFail(msg || 'blob_err'); }
    }
    t = setTimeout(function () { if (mySeq === speakSeq) finish(false, '超时'); }, timeout || 6000);
    fetch(url).then(function (r) {
      if (!r.ok) throw new Error('http_' + r.status);
      return r.blob();
    }).then(function (blob) {
      if (done || mySeq !== speakSeq) return;
      var bu = URL.createObjectURL(blob);
      a = new Audio(bu);
      netAudio = a;                            // stopNetAudio 可停掉它
      a.onplaying = function () { if (onStart) onStart(); };
      a.onended = function () { finish(true); try { URL.revokeObjectURL(a.src); } catch (e) {} if (netAudio === a) netAudio = null; };
      a.onerror = function () { if (!done) { finish(false, '渲染失败'); } };
      var p = a.play();
      if (p && p.catch) p.catch(function () { finish(false, '被拦截'); });
    }).catch(function (e) {
      finish(false, (e && e.message) || '请求失败');
    });
  }

  // iOS 持久探针: 点 🔊 时同步 fetch TTS, 结果写进一个固定小条(不消失)+ console,
  // 用于定位「请求不通」还是「请求成功但渲染不出声」。
  var _probeEl = null;
  function probeEl() {
    if (_probeEl) return _probeEl;
    try {
      _probeEl = document.createElement('div');
      _probeEl.id = 'iosTtsProbe';
      _probeEl.style.cssText = 'position:fixed;left:8px;bottom:60px;z-index:99999;background:rgba(0,0,0,.72);color:#ffd;font:11px/1.4 monospace;padding:6px 9px;border-radius:6px;max-width:90vw;white-space:pre-wrap;';
      document.body.appendChild(_probeEl);
    } catch (e) {}
    return _probeEl;
  }
  function iOSProbeShow(url, t) {
    var el = probeEl(); if (!el) return;
    el.textContent = 'iOS TTS 探测中…\n' + String(t).slice(0, 24);
    try { window.__ttsProbe = {}; } catch (e) {}
    try {
      var st = Date.now();
      fetch(url).then(function (r) {
        r.arrayBuffer().then(function (ab) {
          var ver = mpegVerLabel(ab);
          el.textContent = 'iOS TTS: HTTP ' + r.status + ' ' + ab.byteLength + 'B ' + (Date.now() - st) + 'ms ' + ver + ' sv=' + (r.headers.get('X-TTS-V') || '?') + (r.headers.get('Content-Length') != null ? ' cl=' + r.headers.get('Content-Length') : '');
        }, function () {
          el.textContent = 'iOS TTS: HTTP ' + r.status + ' 读取响应失败';
        });
      }).catch(function () {
        el.textContent = 'iOS TTS: 网络不可达 (fetch failed)';
      });
    } catch (e) { el.textContent = 'iOS TTS: 探测异常 ' + e; }
  }
  function iOSProbeMark(m) {
    var el = probeEl(); if (!el) return;
    el.textContent = (el.textContent ? el.textContent + '\n' : '') + m;
    try { window.__ttsProbe = window.__ttsProbe || {}; window.__ttsProbe.playState = m; } catch (e) {}
  }

  // 从 mp3 首帧解析流版本, 用于探针显示 iPad 实际收到的音频格式
  function mpegVerLabel(ab) {
    try {
      var u8 = new Uint8Array(ab, 0, 4);
      if (u8[0] === 0x49 && u8[1] === 0x44 && u8[2] === 0x33) return 'MPEG1(cv)';
      if (u8[0] !== 0xFF || (u8[1] & 0xE0) !== 0xE0) return '?';
      var v = (u8[1] >> 3) & 3;
      var names = { 3: 'MPEG1', 2: 'MPEG2', 0: 'MPEG2.5' };
      return names[v] || '?';
    } catch (e) { return '?'; }
  }

  // 组装整题朗读文本: 题干(或听音词) + 每个选项的「序号、选项」(如 「。一、香蕉。二、苹果。」)
  function questionReadText(leadText, options) {
    var t = String(leadText === undefined || leadText === null ? '' : leadText);
    if (options && options.length) {
      var parts = [];
      for (var i = 0; i < options.length; i++) {
        parts.push(M.numCn(i + 1) + '、' + M.optLabel(options[i]));
      }
      t += '。' + parts.join('。');
    }
    return t;
  }

  function spkBtn(text, cls) {
    if (!text) return '';
    // 不安全: JSON.stringify 会产生双引号, 与 HTML 属性定界符冲突 => 用单引号定界并转义文本
    var arg = String(text).replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\n/g, ' ').replace(/"/g, '&quot;');
    // 用户点击: 有用户手势, 强制走网络 TTS(绕过自动播放拦截), 保证能出声
    return '<button type="button" class="qi-spk '+(cls||'')+'" onclick="window.Edu.Speech.playSpeakForceNet(\''+arg+'\')" aria-label="朗读">🔊</button>';
  }

  // 极速练习/闯关鼓励语音: 答对/答错随机一句, 每次一个; 避免连续两次相同
  var lastEnc = '';
  function encPick(list) {
    if (!list || !list.length) return '';
    var p = list[Math.floor(Math.random() * list.length)];
    if (p === lastEnc && list.length > 1) { p = list[(list.indexOf(p) + 1) % list.length]; }
    lastEnc = p;
    return p;
  }

  window.Edu.Speech.speak = speak;
  window.Edu.Speech.spkBtn = spkBtn;
  window.Edu.Speech.questionReadText = questionReadText;
  window.Edu.Speech.setSpeakIcon = setSpeakIcon;
  window.Edu.Speech.stopNetAudio = stopNetAudio;
  window.Edu.Speech.stopSpeech = stopSpeech;
  window.Edu.Speech.playNetTTS = playNetTTS;
  window.Edu.Speech.preloadTTS = preloadTTS;
  window.Edu.Speech.speakOn = speakOn;
  window.Edu.Speech.encPick = encPick;
  window.Edu.Speech.playSpeakForceNet = playSpeakForceNet;
  window.Edu.Speech.TTS_VOICES = TTS_VOICES;
  window.Edu.Speech.curVoice = curVoice;
  window.encPick = encPick;
  // 别名: 部分模块(practice 等)用 window.Speech 判读/调用语音
  window.Speech = window.Edu.Speech;
  window.toggleSpeak = window.Edu.Speech.toggleSpeak;

  // 轻量 toast 提示(供各模块统一调用)
  var spkToastT = null;
  window.Edu.Speech.toast = function (msg) {
    var el = document.getElementById('eduToast');
    if (!el) return;
    clearTimeout(spkToastT);
    el.textContent = msg;
    el.style.display = 'block';
    el.style.opacity = '1';
    spkToastT = setTimeout(function(){ el.style.opacity = '0'; setTimeout(function(){ el.style.display='none'; },300); }, 1800);
  };

  // Initialize icon on load (defer to avoid issues in non-browser environments)
  try {
    if (typeof document !== 'undefined' && document.readyState !== 'loading') setSpeakIcon();
    else if (typeof document !== 'undefined') document.addEventListener('DOMContentLoaded', setSpeakIcon);
  } catch(e) {}
})();