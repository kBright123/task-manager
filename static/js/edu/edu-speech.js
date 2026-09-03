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
    if (!text || typeof window === 'undefined' || typeof window.Audio === 'undefined') return;
    try {
      var a = new Audio(ttsUrl(text));
      if (typeof a.preload === 'string') a.preload = 'auto';
    } catch (e) {}
  }

  // 网络 TTS(edge-tts 高音质, 服务端缓存同源 mp3) 带超时: 仅在本地合成不可用/失败时兜底
  function playNetTimed(text, onFail) {
    if (typeof window === 'undefined' || typeof window.Audio === 'undefined') { onFail && onFail('not_browser'); return; }
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
    var timer2 = setTimeout(function(){ finish(function(){ stopNetAudio(); onFail && onFail(); }); }, 5000);
    a.oncanplaythrough = function(){ finish(function(){ stopNetAudio(); }); };
    a.onerror = function(){ finish(function(){ stopNetAudio(); onFail && onFail(); }); };
    a.onended = function(){ clearTimeout(timer2); stopNetAudio(); };
    var p = a.play();
    if (p && p.catch) p.catch(function(){ finish(function(){ stopNetAudio(); onFail && onFail(); }); });
    netAudio = a;
    if (typeof netAudioUrl === 'string') netAudioUrl = url;
  }

  function hasAnyVoice() {
    if (typeof speechSynthesis === 'undefined') return false;
    try { return speechSynthesis.getVoices().length > 0; } catch (e) { return false; }
  }

  // 网络 TTS: 仅在本地合成失败时兜底
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
    var timer2 = setTimeout(function(){ finish(function(){ stopNetAudio(); onFail && onFail('network_timeout'); }); }, 10000);
    a.oncanplaythrough = function(){ finish(function(){ stopNetAudio(); }); };
    a.onerror = function(){ finish(function(){ stopNetAudio(); onFail && onFail('network_error'); }); };
    a.onended = function(){ clearTimeout(timer2); stopNetAudio(); };
    var p = a.play();
    if (p && p.catch) p.catch(function(){ finish(function(){ stopNetAudio(); onFail && onFail('autoplay_blocked'); }); });
    netAudio = a;
    if (typeof netAudioUrl === 'string') netAudioUrl = url;
  }

  // 用户点击触发的网络 TTS(有用户交互, 可绕过自动播放策略)
  function playNetTTSUserGesture(text) {
    if (typeof window === 'undefined' || typeof window.Audio === 'undefined') return;
    var url = ttsUrl(text);
    stopNetAudio();
    var a = new Audio(url);
    var played = false;
    a.oncanplaythrough = function(){ played = true; };
    a.onerror = function(){ stopNetAudio(); if (!played) window.Edu.Speech.toast('网络语音加载失败'); };
    a.onended = function(){ stopNetAudio(); };
    var p = a.play();
    if (p && p.catch) p.catch(function(){
      stopNetAudio();
      if (!played) window.Edu.Speech.toast('浏览器拦截播放, 请再次点击');
    });
    netAudio = a;
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

  // 主播放入口: 本地合成优先, 失败/超时自动切网络 TTS
  function speak(text, force) {
    if (!text || !speakOn() || typeof window === 'undefined' || typeof window.Audio === 'undefined') return;
    var t = M.mathToSpeak(String(text));
    var now = Date.now();
    if (!force && t === lastSpeakText && now - lastSpeakAt < 1200) return;
    lastSpeakText = t; lastSpeakAt = now;

    // 先预加载网络音频(后台缓存), 以便兜底时秒开
    preloadNetTTS(t);

    // 尝试本地合成: 给足 3 秒让 speechSynthesis 启动(桌面端冷启动较慢)
    var started = false;
    var fb;
    function fallback(reason) {
      if (fb) clearTimeout(fb);
      // 自动兜底网络 TTS(可能被自动播放策略拦截)
      playNetTimed(t, function(err){
        if (err === 'autoplay_blocked') {
          // 静默失败, 留给用户点按钮时的 user-gesture 重试
        } else if (err === 'network_timeout') {
          window.Edu.Speech.toast('网络语音超时');
        } else {
          window.Edu.Speech.toast('语音暂时不可用');
        }
      });
    }
    try {
      fb = setTimeout(function(){ if (!started) fallback('local_timeout'); }, 3000);
      var u = new SpeechSynthesisUtterance(t);
      u.lang = ttLang(t) === 'zh' ? 'zh-CN' : 'en-US';
      u.rate = 1.0;
      var vs = speechSynthesis.getVoices();
      var v = zhVoice || vs.find(function(x){ return /zh.*CN/i.test(x.lang); }) || vs.find(function(x){ return /zh/i.test(x.lang); });
      if (v) u.voice = v;
      u.onstart = function(){ started = true; if (fb) clearTimeout(fb); stopNetAudio(); };
      u.onerror = function(e){ if (fb) clearTimeout(fb); fallback('local_error'); };
      speechSynthesis.cancel();
      speechSynthesis.speak(u);
    } catch (e) {
      if (fb) clearTimeout(fb);
      fallback('local_exception');
    }
  }

  // 供按钮点击调用: 强制走网络 TTS(有用户交互, 成功率最高)
  function playSpeakForceNet(text) {
    if (!text || !speakOn()) return;
    var t = M.mathToSpeak(String(text));
    lastSpeakText = t; lastSpeakAt = Date.now();
    playNetTTSUserGesture(t);
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
  window.Edu.Speech.playSpeakForceNet = playSpeakForceNet;
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