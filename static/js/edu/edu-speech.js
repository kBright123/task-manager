(function () {
  'use strict';
  var C = window.Edu.Constants;
  var M = window.Edu.MathUtils;

  var zhVoice = null;
  var speakFBTimer = null;
  var lastSpeakText = '', lastSpeakAt = 0;
  var netAudio = null, netAudioUrl = '';

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
    try { return localStorage.getItem(C.SPEAK_ON_KEY) === 'true'; } catch(e){ return false; }
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
    if (speakOn()) speak(text, force);
  };

  function ttLang(t) {
    var han = (t.match(/[\u4e00-\u9fff]/g)||[]).length;
    var lat = (t.match(/[a-zA-Z]/g)||[]).length;
    return han >= lat ? 'zh' : 'en';
  }

  function stopNetAudio() {
    if (netAudio) { netAudio.pause(); netAudio.src = ''; netAudio = null; }
    netAudioUrl = '';
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

  function ttsUrl(text) {
    var le = ttLang(text);
    return '/edu/api/tts?text=' + encodeURIComponent(text) + '&lang=' + le;
  }

  function playNetTTS(text) {
    playAudio([ttsUrl(text)]);
  }

  // 预加载 TTS 音频(浏览器走 HTTP 缓存), 缓解「语音首播 3 秒+ 延迟」
  function preloadTTS(text) {
    if (!text) return;
    try {
      var a = new Audio(ttsUrl(text));
      if (typeof a.preload === 'string') a.preload = 'auto';
    } catch (e) {}
  }

  // 网络 TTS(edge-tts 高音质, 服务端缓存同源 mp3) 带超时: 仅在本地合成不可用/失败时兜底
  function playNetTimed(text, onFail) {
    var url = ttsUrl(text);
    stopNetAudio();
    var a = new Audio(url);
    var done = false;
    function finish(fn) {
      if (done) return;
      done = true;
      clearTimeout(timer2);
      fn();
    }
    var timer2 = setTimeout(function(){ finish(function(){ stopNetAudio(); onFail && onFail(); }); }, 1800);
    a.oncanplaythrough = function(){ finish(function(){ stopNetAudio(); }); };
    a.onerror = function(){ finish(function(){ stopNetAudio(); onFail && onFail(); }); };
    a.onended = function(){ clearTimeout(timer2); stopNetAudio(); };
    var p = a.play();
    if (p && p.catch) p.catch(function(){ finish(function(){ stopNetAudio(); onFail && onFail(); }); });
    netAudio = a;
    if (typeof netAudioUrl === 'string') netAudioUrl = url;
  }

  function hasZhVoice() {
    if (typeof speechSynthesis === 'undefined') return 'none';
    try {
      var vs = speechSynthesis.getVoices();
      return (zhVoice || vs.some(function(x){ return /zh/i.test(x.lang); })) ? 'yes' : 'no';
    } catch (e) { return 'no'; }
  }

  // 纯本地合成(即时、离线): 有可用语音时近乎零延迟
  function speechSynthNow(text) {
    if (typeof speechSynthesis === 'undefined') { window.Edu.Speech.toast('无法播放语音'); return false; }
    var u = new SpeechSynthesisUtterance(text);
    u.lang = ttLang(text) === 'zh' ? 'zh-CN' : 'en-US';
    u.rate = 1.0;
    var v = zhVoice || (function(){
      var a=speechSynthesis.getVoices(); return a.find(function(x){ return /zh.*CN/i.test(x.lang); }) || a.find(function(x){ return /zh/i.test(x.lang); }) || null;
    })();
    if (v) u.voice = v;
    speechSynthesis.cancel();
    speechSynthesis.speak(u);
    return true;
  }

  // 主播放入口: 本地合成优先(即时低延时), 网络高音质 TTS 兜底
  function speak(text, force) {
    if (!text || !speakOn()) return;
    var t = M.mathToSpeak(String(text));
    var now = Date.now();
    // force=1 用于「🔊 再听一遍」等显式重播: 忽略去重, 用户点了就该重放
    if (!force && t === lastSpeakText && now - lastSpeakAt < 1200) return;
    lastSpeakText = t; lastSpeakAt = now;
    // 先尝试本地合成: 冷启动/无语音引擎时可能在几百毫秒内不触发 onstart, 再转网络 TTS
    if (hasZhVoice() !== 'yes') { playNetTimed(t, function(){ window.Edu.Speech.toast('网络语音不可用, 且本机无语音引擎'); }); return; }
    var started = false;
    var fb;
    try {
      fb = setTimeout(function(){ if (!started) playNetTimed(t, function(){}); }, 800);
      var u = new SpeechSynthesisUtterance(t);
      u.lang = 'zh-CN';
      u.rate = 1.0;
      var v = zhVoice || (speechSynthesis.getVoices() || []).find(function(x){ return /zh/i.test(x.lang); });
      if (v) u.voice = v;
      u.onstart = function(){ started = true; if (fb) clearTimeout(fb); stopNetAudio(); };
      u.onerror = function(){ if (fb) clearTimeout(fb); playNetTimed(t, function(){}); };
      speechSynthesis.cancel();
      speechSynthesis.speak(u);
    } catch (e) {
      if (fb) clearTimeout(fb);
      playNetTimed(t, function(){});
    }
  }

  function spkBtn(text, cls) {
    if (!text) return '';
    // 不安全: JSON.stringify 会产生双引号, 与 HTML 属性定界符冲突 => 用单引号定界并转义文本
    var arg = String(text).replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\n/g, ' ').replace(/"/g, '&quot;');
    return '<button type="button" class="qi-spk '+(cls||'')+'" onclick="window.Edu.Speech.playSpeak(\''+arg+'\')" aria-label="朗读"><i class="bi bi-volume-up"></i></button>';
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
  window.Edu.Speech.setSpeakIcon = setSpeakIcon;
  window.Edu.Speech.stopNetAudio = stopNetAudio;
  window.Edu.Speech.playNetTTS = playNetTTS;
  window.Edu.Speech.preloadTTS = preloadTTS;
  window.Edu.Speech.speakOn = speakOn;
  window.Edu.Speech.encPick = encPick;
  window.encPick = encPick;
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