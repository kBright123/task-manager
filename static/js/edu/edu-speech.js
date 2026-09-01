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

  window.Edu.Speech.playSpeak = function (text) {
    if (!text) return;
    if (speakOn()) M.speak(text);
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

  function playNetTTS(text) {
    var le = ttLang(text);
    var url = '/edu/api/tts?text=' + encodeURIComponent(text) + '&lang=' + le;
    playAudio([url]);
  }

  function speak(text) {
    if (!text || !speakOn()) return;
    var t = M.mathToSpeak(String(text));
    var now = Date.now();
    if (t === lastSpeakText && now - lastSpeakAt < 1200) return;
    lastSpeakText = t; lastSpeakAt = now;
    if (typeof speechSynthesis !== 'undefined') {
      var u = new SpeechSynthesisUtterance(t);
      u.lang = ttLang(t) === 'zh' ? 'zh-CN' : 'en-US';
      u.rate = 1.0;
      var vs = speechSynthesis.getVoices();
      var v = zhVoice || vs.find(function(x){ return /zh.*CN/i.test(x.lang); });
      if (v) u.voice = v;
      speechSynthesis.cancel();
      speechSynthesis.speak(u);
    } else {
      playNetTTS(t);
    }
  }

  function spkBtn(text, cls) {
    return '<button type="button" class="qi-spk '+(cls||'')+'" onclick="window.Edu.Speech.playSpeak('+JSON.stringify(text)+')" aria-label="朗读"><i class="bi bi-volume-up"></i></button>';
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