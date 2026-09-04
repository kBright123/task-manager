(function () {
  'use strict';
  var Store = window.Edu.Store;

  function esc(s) { return String(s === undefined || s === null ? '' : s).replace(/</g, '<').replace(/&/g, '&'); }

  function avaOf(k) {
    if (!k) return '🧒';
    return k.gender === 'female' ? '👧' : '👦';
  }
  function levelOf(k) {
    if (!k) return 1;
    var s = Store.curSettings();
    return s && s.lv ? s.lv : 1;
  }

  function renderMine() {
    var body = document.getElementById('eduMineBody');
    if (!body) return;
    renderWelcomeInto('mineWelcome', '管理宝贝与个性化设置');
    var kids = window.eduKids ? window.eduKids.all() : [];
    var act = window.eduKids ? window.eduKids.active() : (kids[0] || null);
    var s = Store.curSettings();
    var name = act ? (act.name || '宝贝') : '宝贝';

    // 宝贝管理入口：有宝贝显示"管理宝贝"，无宝贝显示"添加宝贝"
    var kidsHtml = kids.length > 0
      ? '<button type="button" class="mine-kid-link" onclick="openKidsMgr()">' +
          '<span class="mkl-ava">' + avaOf(act) + '</span>' +
          '<div class="mkl-info">' +
            '<span class="mkl-title">管理宝贝</span>' +
            '<span class="mkl-sub">' + kids.length + ' 个宝贝 · 当前 ' + esc(name) + '</span>' +
          '</div>' +
          '<span class="mkl-chevron"><i class="bi bi-chevron-right"></i></span>' +
        '</button>'
      : '<button type="button" class="mine-kid-link empty" onclick="openKidsMgr()">' +
          '<span class="mkl-ava">🧒</span>' +
          '<div class="mkl-info">' +
            '<span class="mkl-title">添加宝贝</span>' +
            '<span class="mkl-sub">点击添加第一个宝贝</span>' +
          '</div>' +
          '<span class="mkl-plus">+</span>' +
        '</button>';

    // 护眼提醒 / 朗读与音效 为单字段设置 → 在我的页就地修改, 不弹框
    var eyeVal = s && s.eyeMin ? s.eyeMin : 20;
    var REST = [5, 10, 15, 20, 30, 45, 60];
    var eyeOpts = REST.map(function (m) {
      return '<option value="' + m + '"' + (m === eyeVal ? ' selected' : '') + '>' + m + ' 分钟' + (m === 20 ? '（推荐）' : '') + '</option>';
    }).join('');
    var soundOn = !s || s.sound !== false;
    var soundToggle =
      '<button type="button" class="ms-toggle" aria-pressed="' + (soundOn ? 'true' : 'false') + '" onclick="toggleSoundInline(' + (soundOn ? 'false' : 'true') + ')">' +
        '<span class="ms-toggle-knob"></span>' +
        '<span class="ms-toggle-label">' + (soundOn ? '已开启' : '已关闭') + '</span>' +
      '</button>';
    // 音色选择: 与后端 edge-tts 音色一致; 可选择 + 试听
    var Voice = window.Edu.Speech;
    var voices = (Voice && Voice.TTS_VOICES) || [];
    var curV = (Voice && Voice.curVoice) ? Voice.curVoice() : 'xiaoxiao';
    var voiceOpts = '<option value="">（默认 · 晓晓）</option>' + voices.map(function (v) {
      return '<option value="' + v.id + '"' + (v.id === curV ? ' selected' : '') + '>' + v.name + '</option>';
    }).join('');
    var voiceRow = '<div class="ms-item ms-inline-row">' +
      '<span class="ms-icon">🎙️</span><span>朗读音色</span>' +
      '<span class="ms-inline-ctl">' +
        '<select class="ms-select" id="mineVoice" aria-label="朗读音色" onchange="setVoiceInline(this.value)">' + voiceOpts + '</select>' +
        '<button type="button" class="ms-voice-preview" aria-label="试听音色" onclick="previewVoice()"><i class="bi bi-play-circle"></i></button>' +
      '</span>' +
    '</div>';

    // 设置分组
    var settingsHtml = '<div class="mine-settings">' +
      '<div class="ms-group">' +
        '<h4>学习设置</h4>' +
        '<button type="button" class="ms-item" onclick="openParentMode(\'course\')">' +
          '<span class="ms-icon">📚</span><span>课程与难度</span><i class="bi bi-chevron-right"></i>' +
        '</button>' +
        '<div class="ms-item ms-inline-row">' +
          '<span class="ms-icon">👁️</span><span>护眼提醒</span>' +
          '<span class="ms-inline-ctl"><select class="ms-select" id="mineEyeMin" aria-label="护眼提醒间隔" onchange="setEyeInline(this.value)">' + eyeOpts + '</select></span>' +
        '</div>' +
      '</div>' +
      '<div class="ms-group">' +
        '<h4>声音与显示</h4>' +
        '<div class="ms-item ms-inline-row">' +
          '<span class="ms-icon">🔊</span><span>朗读与音效</span>' +
          '<span class="ms-inline-ctl">' + soundToggle + '</span>' +
        '</div>' +
        voiceRow +
      '</div>' +
      '<div class="ms-group">' +
        '<h4>账号与数据</h4>' +
        '<button type="button" class="ms-item danger" onclick="openResetConfirm()">' +
          '<span class="ms-icon">🗑️</span><span>重置所有数据</span><i class="bi bi-chevron-right"></i>' +
        '</button>' +
      '</div>' +
    '</div>';

    body.innerHTML =
      kidsHtml +
      settingsHtml +
      '<p class="mine-foot">幼小衔接 · 快乐学习乐园</p>';
  }

  window.Edu.Mine = { renderMine: renderMine, avaOf: avaOf, levelOf: levelOf };
  window.renderMine = renderMine;
  window.setVoiceInline = function (val) {
    var s = Store.curSettings();
    s.voice = val || 'xiaoxiao';
    Store.mergeSet(s);
    Store.saveState();
    if (window.renderMine) window.renderMine();
    var nm = '默认';
    var voices = (window.Edu.Speech && window.Edu.Speech.TTS_VOICES) || [];
    for (var i = 0; i < voices.length; i++) if (voices[i].id === (val || 'xiaoxiao')) nm = voices[i].name;
    if (window.Edu.Speech && window.Edu.Speech.toast) window.Edu.Speech.toast('已选择音色：' + nm);
  };
  window.previewVoice = function () {
    var S = window.Edu.Speech;
    if (!S || !S.playSpeakForceNet) return;
    if (!Store.curSettings().sound) { S.toast && S.toast('请先开启朗读与音效'); return; }
    S.playSpeakForceNet('小朋友，你好呀！');
    if (S.toast) S.toast('试听当前音色');
  };
})();
