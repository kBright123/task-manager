(function () {
  'use strict';
  var M = window.Edu.MathUtils;
  var Store = window.Edu.Store;
  var QuizEngine = window.Edu.QuizEngine;

  // =====================================================================
  // 文学名著: 《三国演义》《西游记》《水浒传》
  // 题型以「人物名字」为主: 绰号→人物 / 兵器→人物 / 事迹→人物
  // 每题 options 含答案字串 + 3 个同书干扰项; TTS 会朗读题干与每个选项
  // =====================================================================

  function q(book, id, prompt, answer, distractors, note) {
    return { id: id, book: book, prompt: prompt, answer: answer, note: note || '',
      options: [answer].concat(distractors) };
  }

  var SG = [
    q('sg', 'sg_1', '三国里绰号“卧龙”的军师是？', '诸葛亮', ['庞统', '周瑜', '司马懿'], '卧龙·诸葛亮'),
    q('sg', 'sg_2', '三国里被称作“凤雏”的是？', '庞统', ['诸葛亮', '关羽', '张飞'], '凤雏·庞统'),
    q('sg', 'sg_3', '武圣关羽使用的兵器是？', '青龙偃月刀', ['丈八蛇矛', '方天画戟', '双股剑'], '青龙偃月刀'),
    q('sg', 'sg_4', '手持丈八蛇矛、“燕人张翼德”指的是？', '张飞', ['赵云', '马超', '黄忠'], '燕人张飞'),
    q('sg', 'sg_5', '长坂坡单骑救阿斗、七进七出的是？', '赵云', ['关羽', '张飞', '吕布'], '常山赵子龙'),
    q('sg', 'sg_6', '千里走单骑、过五关斩六将的是？', '关羽', ['赵云', '张飞', '马超'], '武圣关羽'),
    q('sg', 'sg_7', '“宁教我负天下人，休教天下人负我”是谁说的？', '曹操', ['刘备', '孙权', '司马懿'], '曹操'),
    q('sg', 'sg_8', '“挟天子以令诸侯”的是谁？', '曹操', ['袁绍', '董卓', '刘备'], '曹操'),
    q('sg', 'sg_9', '刘备三顾茅庐请出山的是？', '诸葛亮', ['庞统', '徐庶', '司马懿'], '三顾茅庐'),
    q('sg', 'sg_10', '火烧赤壁、赔了夫人又折兵的东吴都督是？', '周瑜', ['鲁肃', '陆逊', '孙权'], '周瑜'),
    q('sg', 'sg_11', '“桃园三结义”的三兄弟不包括谁？', '赵云', ['刘备', '关羽', '张飞'], '桃园三结义'),
    q('sg', 'sg_12', '赤壁之战中献计“连环计”、借东风的军师是？', '诸葛亮', ['庞统', '周瑜', '黄盖'], '借东风')
  ];

  var XY = [
    q('xy', 'xy_1', '大闹天宫、偷吃蟠桃的是？', '孙悟空', ['猪八戒', '沙僧', '白龙马'], '齐天大圣'),
    q('xy', 'xy_2', '孙悟空的金箍棒又叫什么？', '如意金箍棒', ['九齿钉耙', '降妖宝杖', '紫金铃'], '如意金箍棒'),
    q('xy', 'xy_3', '唐僧骑的白马，其实是龙王三太子？', '小白龙', ['红孩儿', '牛魔王', '金翅大鹏'], '白龙马'),
    q('xy', 'xy_4', '在高老庄抢亲、后来护送唐僧的是？', '猪八戒', ['孙悟空', '沙僧', '白龙马'], '天蓬元帅'),
    q('xy', 'xy_5', '沙僧下凡前，在天庭做过什么官？', '卷帘大将', ['弼马温', '天蓬元帅', '托塔天王'], '卷帘大将'),
    q('xy', 'xy_6', '孙悟空大闹天宫之前，在天庭当过什么官？', '弼马温', ['卷帘大将', '天蓬元帅', '御马监'], '弼马温'),
    q('xy', 'xy_7', '唐僧师徒最终在哪里取得真经？', '大雷音寺', ['小雷音寺', '观音禅院', '五庄观'], '西天雷音'),
    q('xy', 'xy_8', '三打白骨精、被唐僧错怪赶走的徒弟是？', '孙悟空', ['猪八戒', '沙僧', '白龙马'], '三打白骨精'),
    q('xy', 'xy_9', '“三借芭蕉扇”讲述的是谁借扇子？', '孙悟空', ['猪八戒', '沙僧', '牛魔王'], '三借芭蕉扇'),
    q('xy', 'xy_10', '有七十二变、一个筋斗十万八千里的是？', '孙悟空', ['猪八戒', '沙僧', '白龙马'], '七十二变'),
    q('xy', 'xy_11', '让孙悟空头疼的紧箍咒，是观音送给谁的？', '唐僧', ['猪八戒', '沙僧', '白龙马'], '紧箍咒'),
    q('xy', 'xy_12', '天蓬元帅转世、错投猪胎的是？', '猪八戒', ['沙僧', '白龙马', '红孩儿'], '错投猪胎')
  ];

  var SH = [
    q('sh', 'sh_1', '绰号“及时雨”、坐上梁山第一把交椅的是？', '宋江', ['晁盖', '卢俊义', '林冲'], '及时雨'),
    q('sh', 'sh_2', '绰号“智多星”、出谋划策的军师是？', '吴用', ['宋江', '公孙胜', '花荣'], '智多星'),
    q('sh', 'sh_3', '景阳冈上赤手空拳打死猛虎的是？', '武松', ['李逵', '鲁智深', '杨志'], '行者武松'),
    q('sh', 'sh_4', '绰号“黑旋风”、使两把板斧的是？', '李逵', ['鲁智深', '武松', '杨志'], '黑旋风'),
    q('sh', 'sh_5', '倒拔垂杨柳、绰号“花和尚”的是？', '鲁智深', ['李逵', '武松', '林冲'], '花和尚'),
    q('sh', 'sh_6', '风雪山神庙、绰号“豹子头”的是？', '林冲', ['卢俊义', '柴进', '杨志'], '豹子头'),
    q('sh', 'sh_7', '“智取生辰纲”的谋划者是？', '吴用', ['宋江', '公孙胜', '卢俊义'], '智取生辰纲'),
    q('sh', 'sh_8', '绰号“小李广”、百发百中的神箭手是？', '花荣', ['燕青', '史进', '董平'], '小李广'),
    q('sh', 'sh_9', '绰号“浪里白条”的水军头领是？', '张顺', ['李俊', '阮小七', '张横'], '浪里白条'),
    q('sh', 'sh_10', '绰号“母夜叉”、开黑店的梁山女将是？', '孙二娘', ['顾大嫂', '扈三娘', '金翠莲'], '母夜叉'),
    q('sh', 'sh_11', '梁山第二任寨主、绰号“托塔天王”的是？', '晁盖', ['宋江', '吴用', '卢俊义'], '托塔天王'),
    q('sh', 'sh_12', '“醉打蒋门神、血溅鸳鸯楼”的是？', '武松', ['石秀', '武大郎', '燕青'], '行者武松')
  ];

  var LIT_QUIZ_DATA = { sg: SG, xy: XY, sh: SH };

  var LIT_MODES = [
    { id: 'sg', label: '三国演义', emoji: '🏇' },
    { id: 'xy', label: '西游记', emoji: '🐒' },
    { id: 'sh', label: '水浒传', emoji: '⚔️' },
    { id: 'zong', label: '名著综合', emoji: '📚' }
  ];

  var wbLitMode = 'sg';
  var QUIZ_LEN = Math.min((window.Edu.Constants.QUIZ_LEN || 10), 12);

  function shuffle(a) {
    var arr = (a || []).slice();
    for (var i = arr.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var t = arr[i]; arr[i] = arr[j]; arr[j] = t;
    }
    return arr;
  }

  // 抽取一整套题(10 题, 选项随机排序); zong=三国/西游/水浒 混合
  function buildLitQuiz(mode) {
    var pool = (mode === 'zong')
      ? SG.concat(XY, SH)
      : (LIT_QUIZ_DATA[mode] || SG);
    var chosen = shuffle(pool).slice(0, QUIZ_LEN);
    return chosen.map(function (x) {
      return {
        id: 'lit_' + x.id,
        type: mode,
        prompt: x.prompt,
        options: shuffle(x.options),
        correct: x.answer,
        note: x.note
      };
    });
  }

  // 极速练习: 单题即时抽取
  function sampleItem(mode) {
    var pool = (mode === 'zong') ? SG.concat(XY, SH) : (LIT_QUIZ_DATA[mode] || SG);
    var x = pool[Math.floor(Math.random() * pool.length)];
    return {
      id: 'lit_' + x.id,
      type: mode, wtype: mode,
      prompt: x.prompt,
      options: shuffle(x.options),
      correct: x.answer,
      note: x.note
    };
  }

  // 工作台骨架 HTML(与围棋模式一致的动态注入, 兼容模板缺失)
  function litSectionHtml() {
    var html = '<div id="wb-lit">';
    html += '<div class="sm-tabs" style="overflow-x:auto;white-space:nowrap;margin-bottom:12px;">';
    LIT_MODES.forEach(function (m) {
      html += '<button type="button" class="sm-tab' + (wbLitMode === m.id ? ' active' : '') + '" data-s="' + m.id + '" onclick="wbLit(\'' + m.id + '\')">' + m.emoji + ' ' + m.label + '</button>';
    });
    html += '</div>';
    html += '<div id="wb-lit-body"></div>';
    html += '</div>';
    return html;
  }

  function setLitTab(mode) {
    document.querySelectorAll('#wb-lit .sm-tab').forEach(function (t) {
      t.classList.toggle('active', t.dataset.s === mode);
    });
  }

  function renderLitMode(container, mode) {
    if (!container) return;
    var items = buildLitQuiz(mode);
    QuizEngine.startQuiz('lit', mode, items, { difficulty: M.diffOf('lit') });
  }

  window.wbLit = function (mode) {
    mode = String(mode || 'sg');
    if (['sg', 'xy', 'sh', 'zong'].indexOf(mode) === -1) mode = 'sg';
    wbLitMode = mode;
    if (window.Edu.Workbench && window.Edu.Workbench.showSubjectSection) window.Edu.Workbench.showSubjectSection('lit');
    var body = document.getElementById('wb-lit-body');
    if (body) {
      setLitTab(mode);
      renderLitMode(body, mode);
    } else {
      // 兜底: 模板缺失 #wb-lit 时动态注入工作台骨架(与围棋模式一致), 不覆盖其余栏目
      var sec = document.getElementById('eduWorkbench');
      if (sec && !document.getElementById('wb-lit')) {
        var d = document.createElement('div');
        d.innerHTML = litSectionHtml();
        var litSec = d.firstElementChild;
        if (litSec) {
          sec.appendChild(litSec);
          litSec.style.display = '';
          renderLitMode(document.getElementById('wb-lit-body'), mode);
        }
      }
    }
    Store.saveWb();
  };

  window.Edu.LitWorkbench = {
    wbLitMode: wbLitMode,
    LIT_QUIZ_DATA: LIT_QUIZ_DATA,
    LIT_MODES: LIT_MODES,
    buildLitQuiz: buildLitQuiz,
    sampleItem: sampleItem,
    litSectionHtml: litSectionHtml,
    wbLit: wbLit
  };
})();