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

  window.Edu.Speech = window.Edu.Speech || {};

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
    return '/edu/api/tts?text=' + encodeURIComponent(text) + '&lang=' + le + '&v=' + curVoice();
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
  function playNetTTSUserGesture(text, onFail) {
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
      a.onended = function(){ if (done || mySeq !== speakSeq) return; finish(true); stopNetAudio(); };
      a.onloadeddata = tryPlay;           // 首帧数据就绪即播放, 减小等待感
      a.oncanplaythrough = tryPlay;       // 兜底触发(幂等)
      if (cleanTimer) clearTimeout(cleanTimer);
      cleanTimer = setTimeout(function(){ if (mySeq === speakSeq) fail(); }, T_TIMEOUT);
      try { a.load(); } catch (e) {}
      netAudio = a;
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
    playNetTTSUserGesture(t, function(){ speakLocal(t); });  // 网络慢/失败 → 本地秒开兜底, 不干等
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