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
    q('sg', 'sg_12', '赤壁之战中献计“连环计”、借东风的军师是？', '诸葛亮', ['庞统', '周瑜', '黄盖'], '借东风'),
    q('sg', 'sg_13', '温酒斩华雄，一战成名的是哪位刘备麾下名将？', '关羽', ['张飞', '赵云', '黄忠'], '温酒斩华雄'),
    q('sg', 'sg_14', '白帝城托孤，刘备将儿子刘禅托付给了谁？', '诸葛亮', ['赵云', '关羽', '张飞'], '白帝托孤'),
    q('sg', 'sg_15', '失街亭后，诸葛亮空城抚琴骗退了谁？', '司马懿', ['曹操', '孙权', '曹仁'], '空城计'),
    q('sg', 'sg_16', '建立魏国、废汉献帝自己称帝的是谁？', '曹丕', ['刘备', '曹操', '孙坚'], '曹丕称帝'),
    q('sg', 'sg_17', '火烧连营七百里、大破刘备的是哪位东吴将领？', '陆逊', ['鲁肃', '吕蒙', '周瑜'], '火烧连营'),
    q('sg', 'sg_18', '关羽败走麦城，被哪位东吴都督趁势擒获？', '吕蒙', ['陆逊', '周瑜', '甘宁'], '败走麦城'),
    q('sg', 'sg_19', '“乐不思蜀”这个成语说的是谁？', '刘禅', ['刘备', '孙权', '曹丕'], '乐不思蜀'),
    q('sg', 'sg_20', '“身在曹营心在汉”，心里始终想着刘备的名将是？', '关羽', ['张飞', '赵云', '马超'], '身在曹营心在汉'),
    q('sg', 'sg_21', '常山赵子龙——赵云，他的“字”是什么？', '子龙', ['子敬', '子明', '士元'], '常山赵子龙'),
    q('sg', 'sg_22', '蜀国五虎上将中，年过七旬仍老当益壮的是？', '黄忠', ['马超', '赵云', '张飞'], '老将黄忠'),
    q('sg', 'sg_23', '“挟天子以令诸侯”的曹操，字什么？', '孟德', ['玄德', '奉先', '仲达'], '魏武曹操'),
    q('sg', 'sg_24', '赤壁之战，刘备与谁结盟共同对抗曹操？', '孙权', ['袁绍', '刘表', '刘璋'], '孙刘联盟'),
    q('sg', 'sg_25', '长坂坡大战，赵云在乱军中救出了谁的幼子？', '刘备', ['曹操', '孙权', '诸葛亮'], '长坂坡救主'),
    q('sg', 'sg_26', '“六出祁山”、北伐魏国的是哪位蜀汉丞相？', '诸葛亮', ['庞统', '蒋琬', '费祎'], '六出祁山'),
    q('sg', 'sg_27', '长坂坡上，赵云夺走了谁家的青釭剑？', '曹操', ['袁绍', '孙权', '董卓'], '青釭剑'),
    q('sg', 'sg_28', '马超为报父仇猛攻曹操，打得曹军割须弃袍的是哪里的猛将？', '西凉', ['江东', '河北', '荆襄'], '锦马超'),
    q('sg', 'sg_29', '西凉名将“锦马超”的父亲是谁？', '马腾', ['马岱', '马良', '马谡'], '锦马超父子'),
    q('sg', 'sg_30', '“三英战吕布”，其中的“三英”不包括谁？', '曹操', ['刘备', '关羽', '张飞'], '三英战吕布')
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
    q('xy', 'xy_12', '天蓬元帅转世、错投猪胎的是？', '猪八戒', ['沙僧', '白龙马', '红孩儿'], '错投猪胎'),
    q('xy', 'xy_13', '火焰山挡住了取经路，孙悟空去找谁借芭蕉扇？', '铁扇公主', ['白骨精', '蜘蛛精', '玉兔精'], '火焰山'),
    q('xy', 'xy_14', '会让观音菩萨心头发紧的“圣婴大王”红孩儿，他的父亲是谁？', '牛魔王', ['孙悟空', '猪八戒', '沙僧'], '圣婴大王'),
    q('xy', 'xy_15', '通天河里，驮着唐僧师徒过河的是一只什么？', '大老鼋', ['大乌龟', '大螃蟹', '大白鹅'], '通天河'),
    q('xy', 'xy_16', '三打白骨精，白骨精第一次变成了谁？', '村姑', ['老翁', '老妇', '青牛精'], '三打白骨精'),
    q('xy', 'xy_17', '大闹天宫后，孙悟空被如来佛祖压在了哪座山下？', '五行山', ['花果山', '火焰山', '灵山'], '五行山'),
    q('xy', 'xy_18', '猪八戒的法名（法号）是什么？', '悟能', ['悟净', '悟空', '悟真'], '八戒法名'),
    q('xy', 'xy_19', '沙和尚的法名（法号）是什么？', '悟净', ['悟能', '悟空', '悟明'], '沙僧法名'),
    q('xy', 'xy_20', '“女儿国”的国王想招谁做驸马？', '唐僧', ['孙悟空', '猪八戒', '沙僧'], '女儿国'),
    q('xy', 'xy_21', '盘丝洞里的妖怪，原来是什么变的？', '蜘蛛精', ['蝎子精', '狐狸精', '蜈蚣精'], '盘丝洞'),
    q('xy', 'xy_22', '真假美猴王里，假扮孙悟空的是谁？', '六耳猕猴', ['通臂猿猴', '赤尻马猴', '金丝猴'], '六耳猕猴'),
    q('xy', 'xy_23', '车迟国斗法，和虎力、鹿力、羊力大仙比试的是谁？', '孙悟空', ['猪八戒', '沙僧', '唐僧'], '车迟国斗法'),
    q('xy', 'xy_24', '大闹天宫时，和孙悟空打得难分难解、也会七十二变的是谁？', '二郎神', ['哪吒', '巨灵神', '李天王'], '二郎神'),
    q('xy', 'xy_25', '孙悟空的如意金箍棒，原本是东海的什么宝贝？', '定海神针', ['降妖宝杖', '紫金铃铛', '珊瑚玉树'], '定海神针'),
    q('xy', 'xy_26', '孙悟空在天庭当“弼马温”，他的工作是什么？', '养马', ['放牛', '守桃园', '炼丹'], '弼马温'),
    q('xy', 'xy_27', '人参果树的主人、号称“地仙之祖”的是谁？', '镇元大仙', ['太上老君', '观音菩萨', '太白金星'], '人参果树'),
    q('xy', 'xy_28', '金角大王和银角大王，是哪位仙人的弟子？', '太上老君', ['玉皇大帝', '如来佛祖', '观音菩萨'], '金角银角'),
    q('xy', 'xy_29', '观音身边的“善财童子”，原本是谁？', '红孩儿', ['哪吒', '金童', '土地公'], '善财童子'),
    q('xy', 'xy_30', '西天取经成功后，猪八戒被封为什么？', '净坛使者', ['金身罗汉', '斗战胜佛', '旃檀功德佛'], '八戒封号')
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
    q('sh', 'sh_12', '“醉打蒋门神、血溅鸳鸯楼”的是？', '武松', ['石秀', '武大郎', '燕青'], '行者武松'),
    q('sh', 'sh_13', '绰号“小旋风”、专门仗义疏财的大乡绅是？', '柴进', ['卢俊义', '林冲', '杨志'], '小旋风'),
    q('sh', 'sh_14', '绰号“玉麒麟”、枪棒天下无双的梁山好汉是？', '卢俊义', ['燕青', '关胜', '呼延灼'], '玉麒麟'),
    q('sh', 'sh_15', '梁山上最精通相扑、绰号“浪子”的是谁？', '燕青', ['石秀', '张顺', '花荣'], '浪子燕青'),
    q('sh', 'sh_16', '杨志卖刀时，一刀砍死的地痞无赖叫什么？', '牛二', ['周瑾', '郑屠', '西门庆'], '杨志卖刀'),
    q('sh', 'sh_17', '绰号“鼓上蚤”、最擅长飞檐走壁偷东西的是谁？', '时迁', ['戴宗', '石秀', '燕青'], '鼓上蚤时迁'),
    q('sh', 'sh_18', '吴用“智取生辰纲”，那么押送生辰纲的是哪位好汉？', '杨志', ['刘唐', '公孙胜', '阮小七'], '智取生辰纲'),
    q('sh', 'sh_19', '绰号“没羽箭”、一双飞石百发百中的是？', '张清', ['索超', '董平', '徐宁'], '没羽箭张清'),
    q('sh', 'sh_20', '绰号“拼命三郎”的是哪一位好汉？', '石秀', ['杨雄', '史进', '焦挺'], '拼命三郎'),
    q('sh', 'sh_21', '绰号“神行太保”、日行八百里的是谁？', '戴宗', ['李逵', '武松', '鲁智深'], '神行太保'),
    q('sh', 'sh_22', '绰号“九纹龙”、身上纹着九条龙的是？', '史进', ['李俊', '张横', '穆春'], '九纹龙史进'),
    q('sh', 'sh_23', '绰号“双鞭”、使两根水磨钢鞭的名将是？', '呼延灼', ['秦明', '索超', '关胜'], '双鞭呼延灼'),
    q('sh', 'sh_24', '绰号“急先锋”的是哪一位好汉？', '索超', ['秦明', '董平', '花荣'], '急先锋索超'),
    q('sh', 'sh_25', '“豹子头”林冲是中了谁的计、被刺配沧州？', '高俅', ['蔡京', '童贯', '王伦'], '逼上梁山'),
    q('sh', 'sh_26', '鲁智深拳打镇关西，是为了救哪一位落难的女子？', '金翠莲', ['潘金莲', '李师师', '阎婆惜'], '拳打镇关西'),
    q('sh', 'sh_27', '武松醉打快活林，帮谁夺回了被强占的酒店？', '施恩', ['卢俊义', '柴进', '李忠'], '快活林'),
    q('sh', 'sh_28', '阮氏三雄兄弟三人，在水泊梁山担任什么？', '水军头领', ['马军头领', '步兵头领', '探马首领'], '阮氏三雄'),
    q('sh', 'sh_29', '宋江在浔阳楼题下“反诗”，被哪个地方官下令捉拿？', '黄文炳', ['高俅', '西门庆', '蒋门神'], '浔阳楼题诗'),
    q('sh', 'sh_30', '梁山泊忠义堂前杏黄旗上，写着哪四个大字？', '替天行道', ['劫富济贫', '安民济世', '替天行善'], '替天行道')
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

  // 抽取一整套题(10 题, 选项随机排序); zong=三国/西游/水浒 混合.
  // 按最近出题记录(QuizEngine.recentExclude)避开刚刚考过的题, 减少重复.
  function buildLitQuiz(mode) {
    var pool = (mode === 'zong')
      ? SG.concat(XY, SH)
      : (LIT_QUIZ_DATA[mode] || SG);
    var n = QUIZ_LEN;
    var rec = (window.Edu.QuizEngine && window.Edu.QuizEngine.recentExclude) || [];
    var fresh = pool.filter(function (x) { return rec.indexOf(x.id) < 0; });
    // 恰够 10 题就全用“没考过”的; 不够时退回全池(保证题目能凑齐)
    var source = (fresh.length >= n) ? fresh : pool;
    var chosen = shuffle(source).slice(0, n);
    if (window.Edu.QuizEngine) window.Edu.QuizEngine.recentExclude =
      (window.Edu.QuizEngine.recentExclude || []).concat(chosen.map(function (x) { return x.id; })).slice(-40);
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

  // 极速练习: 单题即时抽取, 也避开刚练过的题
  function sampleItem(mode) {
    var pool = (mode === 'zong') ? SG.concat(XY, SH) : (LIT_QUIZ_DATA[mode] || SG);
    var rec = (window.Edu.QuizEngine && window.Edu.QuizEngine.recentExclude) || [];
    var cand = pool.filter(function (x) { return rec.indexOf(x.id) < 0; });
    if (cand.length === 0) cand = pool;
    var x = cand[Math.floor(Math.random() * cand.length)];
    if (window.Edu.QuizEngine) window.Edu.QuizEngine.recentExclude =
      (window.Edu.QuizEngine.recentExclude || []).concat(x.id).slice(-40);
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