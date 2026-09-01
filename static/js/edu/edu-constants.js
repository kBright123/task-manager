(function () {
  'use strict';
  window.Edu = window.Edu || {};
  var C = window.Edu.Constants = {};

  C.QUIZ_LEN = 10;
  C.LS_BASE = 'edu_record_v1';
  C.STR_BASE = 'edu_workbench_v1';
  C.DEFAULT_SET = { range: 0, nocarry: false, mult: false, dailyQ: 20, dailyMin: 0, show: { trace: true, par: true }, eyeMin: 20, font: 'm', sound: true };
  C.REST_DEFAULT = 20;   // 护眼时长默认(分钟)
  C.SPEAK_ON_KEY = 'edu_speak_v1';
  C.PWD_KEY = 'edu_parent_pwd_v1';
  C.PRACTICE_SECS = 20;

  C.LEITNER_DAYS = [1, 3, 7, 14, 30];
  C.LEVEL_RANGE = [5, 10, 20, 50, 100];

  C.DAILY_PLAN = ['zh','zh','zh','zh','math','math','math','en','en','en'];
  C.DAILY_LABEL = { zh: '语文', math: '数学', en: '英语' };
  C.SUBJ_LABEL = { zh: '语文', math: '数学', en: '英语', par: '乐园' };

  C.PRAISE_MSGS = ['真棒！','答对啦，太厉害！','好聪明呀～','漂亮！','你越来越棒咯！','太赞了！'];
  C.WRONG_MSGS = ['没关系，再想想','差一点，再试一次','别灰心，再数一数','不小心走神啦，再看一看'];

  C.ENC_OK = ['你真棒！','答对啦，太厉害了！','好聪明呀～','漂亮！','你越来越棒咯！','太赞了！','加油，就这样！'];
  C.ENC_WRONG = ['打错了～ 继续加油！','没关系，再想想！','别灰心，再试一次！','差一点点，加油！','再想想，你可以的！'];

  C.POEMS = [
    { id:'p1', title:'《静夜思》', author:'李白', lines:['床前明月光','疑是地上霜','举头望明月','低头思故乡'] },
    { id:'p2', title:'《春晓》', author:'孟浩然', lines:['春眠不觉晓','处处闻啼鸟','夜来风雨声','花落知多少'] },
    { id:'p3', title:'《悯农》', author:'李绅', lines:['锄禾日当午','汗滴禾下土','谁知盘中餐','粒粒皆辛苦'] },
    { id:'p4', title:'《咏鹅》', author:'骆宾王', lines:['鹅鹅鹅','曲项向天歌','白毛浮绿水','红掌拨清波'] },
    { id:'p5', title:'《登鹳雀楼》', author:'王之涣', lines:['白日依山尽','黄河入海流','欲穷千里目','更上一层楼'] },
  ];

  C.ZI = [
    {id:'zi1', prompt:'天', pinyin:'tiān', strokes:4, audio:'zi1'},
    {id:'zi2', prompt:'地', pinyin:'dì', strokes:6, audio:'zi2'},
    {id:'zi3', prompt:'人', pinyin:'rén', strokes:2, audio:'zi3'},
    {id:'zi4', prompt:'大', pinyin:'dà', strokes:3, audio:'zi4'},
    {id:'zi5', prompt:'小', pinyin:'xiǎo', strokes:3, audio:'zi5'},
    {id:'zi6', prompt:'上', pinyin:'shàng', strokes:3, audio:'zi6'},
    {id:'zi7', prompt:'下', pinyin:'xià', strokes:3, audio:'zi7'},
    {id:'zi8', prompt:'中', pinyin:'zhōng', strokes:4, audio:'zi8'},
    {id:'zi9', prompt:'日', pinyin:'rì', strokes:4, audio:'zi9'},
    {id:'zi10', prompt:'月', pinyin:'yuè', strokes:4, audio:'zi10'},
  ];

  C.STROKES = [
    {id:'str1', char:'一', name:'横', order:['一']},
    {id:'str2', char:'二', name:'二', order:['一','一']},
    {id:'str3', char:'三', name:'三', order:['一','一','一']},
    {id:'str4', char:'十', name:'十', order:['横','竖']},
    {id:'str5', char:'人', name:'人', order:['撇','捺']},
    {id:'str6', char:'入', name:'入', order:['撇','捺']},
    {id:'str7', char:'八', name:'八', order:['撇','捺']},
    {id:'str8', char:'上', name:'上', order:['竖','横','横']},
    {id:'str9', char:'下', name:'下', order:['横','竖','点']},
    {id:'str10', char:'大', name:'大', order:['横','撇','捺']},
    {id:'str11', char:'小', name:'小', order:['竖钩','撇','点']},
    {id:'str12', char:'口', name:'口', order:['竖','横折','横']},
  ];

  C.P_SHENG = [
    { id:'p1', s:'b', zi:'八', py:'bā', e:'8️⃣' }, { id:'p2', s:'p', zi:'皮', py:'pí', e:'🧒' },
    { id:'p3', s:'m', zi:'妈', py:'mā', e:'👩' }, { id:'p4', s:'f', zi:'飞', py:'fēi', e:'✈️' },
    { id:'p5', s:'d', zi:'大', py:'dà', e:'🅰️' }, { id:'p6', s:'t', zi:'天', py:'tiān', e:'☁️' },
    { id:'p7', s:'n', zi:'牛', py:'niú', e:'🐮' }, { id:'p8', s:'l', zi:'六', py:'liù', e:'6️⃣' },
    { id:'p9', s:'g', zi:'瓜', py:'guā', e:'🍉' }, { id:'p10', s:'k', zi:'口', py:'kǒu', e:'👄' },
    { id:'p11', s:'h', zi:'花', py:'huā', e:'🌸' }, { id:'p12', s:'j', zi:'鸡', py:'jī', e:'🐔' },
    { id:'p13', s:'q', zi:'七', py:'qī', e:'7️⃣' }, { id:'p14', s:'x', zi:'小', py:'xiǎo', e:'🐭' },
    { id:'p15', s:'zh', zi:'猪', py:'zhū', e:'🐷' }, { id:'p16', s:'ch', zi:'车', py:'chē', e:'🚗' },
    { id:'p17', s:'sh', zi:'书', py:'shū', e:'📖' }, { id:'p18', s:'r', zi:'日', py:'rì', e:'☀️' },
    { id:'p19', s:'z', zi:'子', py:'zǐ', e:'👶' }, { id:'p20', s:'c', zi:'菜', py:'cài', e:'🥬' },
    { id:'p21', s:'s', zi:'三', py:'sān', e:'3️⃣' }, { id:'p22', s:'y', zi:'鱼', py:'yú', e:'🐟' },
    { id:'p23', s:'w', zi:'我', py:'wǒ', e:'🧑' }
  ];
  C.P_YUN = [
    { id:'y1', u:'a', zi:'爸', py:'bà', e:'👨' }, { id:'y2', u:'o', zi:'喔', py:'ō', e:'😯' },
    { id:'y3', u:'e', zi:'鹅', py:'é', e:'🦢' }, { id:'y4', u:'i', zi:'衣', py:'yī', e:'👕' },
    { id:'y5', u:'u', zi:'乌', py:'wū', e:'🐦' }, { id:'y6', u:'ü', zi:'鱼', py:'yú', e:'🐟' },
    { id:'y7', u:'ai', zi:'爱', py:'ài', e:'❤️' }, { id:'y8', u:'ei', zi:'杯', py:'bēi', e:'🥤' },
    { id:'y9', u:'ui', zi:'水', py:'shuǐ', e:'💧' }, { id:'y10', u:'ao', zi:'猫', py:'māo', e:'🐱' },
    { id:'y11', u:'ou', zi:'口', py:'kǒu', e:'👄' }, { id:'y12', u:'iu', zi:'六', py:'liù', e:'6️⃣' },
    { id:'y13', u:'ie', zi:'姐', py:'jiě', e:'👧' }, { id:'y14', u:'an', zi:'山', py:'shān', e:'⛰️' },
    { id:'y15', u:'en', zi:'门', py:'mén', e:'🚪' }, { id:'y16', u:'in', zi:'心', py:'xīn', e:'💖' },
    { id:'y17', u:'ang', zi:'羊', py:'yáng', e:'🐑' }, { id:'y18', u:'ong', zi:'虫', py:'chóng', e:'🐛' }
  ];
  C.P_READ = [
    { id:'r1', zi:'马', py:'mǎ', e:'🐴' }, { id:'r2', zi:'树', py:'shù', e:'🌳' },
    { id:'r3', zi:'火', py:'huǒ', e:'🔥' }, { id:'r4', zi:'门', py:'mén', e:'🚪' },
    { id:'r5', zi:'羊', py:'yáng', e:'🐑' }, { id:'r6', zi:'雨', py:'yǔ', e:'🌧️' },
    { id:'r7', zi:'手', py:'shǒu', e:'✋' }, { id:'r8', zi:'金', py:'jīn', e:'💰' },
    { id:'r9', zi:'鸟', py:'niǎo', e:'🐦' }, { id:'r10', zi:'狗', py:'gǒu', e:'🐶' },
    { id:'r11', zi:'花', py:'huā', e:'🌸' }
  ];
  C.TONES = [
    { n:1, name:'一声', mark:'ˉ', emoji:'📶', desc:'平平高高，像喊远处的人' },
    { n:2, name:'二声', mark:'ˊ', emoji:'↗️', desc:'像爬山，声音往上升' },
    { n:3, name:'三声', mark:'ˇ', emoji:'↘↗', desc:'先低沉再扬起，拐个弯' },
    { n:4, name:'四声', mark:'ˋ', emoji:'⬇️', desc:'像滑滑梯，重重落下' }
  ];
  C.TONE_MARKS = 'āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ';

  C.MOUTH = {
    b:'双唇轻轻一碰 👄', p:'双唇闭拢，送出一口气 💨', m:'双唇相闭，鼻子出声 🤫',
    f:'上牙轻轻咬住下嘴唇 🦷', d:'舌尖顶住上牙床 ☝️', t:'舌尖顶住上牙床，送气 💨',
    n:'舌尖顶上牙床，鼻子出气 👃', l:'舌尖抵上牙床，翘起 👅',
    g:'舌根抬起顶软腭 🗣️', k:'舌根抬起，轻轻送气 💨', h:'舌根抬起，喉咙出气 🗣️',
    j:'舌面贴住上颚，嘴角扁平 😬', q:'舌面贴住上颚，送气 💨', x:'舌面靠近上颚，轻轻摩擦 🤫',
    zh:'舌尖翘起抵住上颚 😛', ch:'舌尖翘起抵住上颚，送气 💨', sh:'舌尖翘起，摩擦出气 💨',
    r:'舌尖翘起，喉咙出声 🗣️', z:'舌尖抵住上牙背，摩擦 🤫', c:'舌尖抵住上牙背，送气 💨',
    s:'舌尖靠近上牙背，摩擦出气 💨', y:'像读 i，嘴角向两边咧开 😁', w:'像读 u，嘴巴噘圆 😙',
    a:'张大嘴巴 😮', o:'嘴巴圆圆，像惊讶 😯', e:'嘴巴微张，先微笑 😄',
    i:'嘴角向两边咧开 😁', u:'嘴巴噘圆 😙', ü:'嘴巴噘圆，像吹口哨 🌬️',
    ai:'从 a 滑向 i，嘴巴由大到小 😮→😁', ei:'从 e 滑向 i，保持微笑 😄→😁',
    ui:'从 u 滑向 i，噘嘴到咧嘴 😙→😁', ao:'从 a 滑向 o，嘴巴逐渐变圆 🔄',
    ou:'从 o 滑向 u，嘴巴越收越小 😮→😙', iu:'从 i 滑向 u，咧嘴到噘嘴 😁→😙',
    ie:'从 i 滑向 e，咧嘴到微笑 😁→😄', an:'从 a 滑向 n，尾巴舌尖抵上牙床 🔚',
    en:'从 e 滑向 n，舌头尖尖顶上去 🔚', in:'从 i 滑向 n，微笑收尾 →鼻音 👃',
    ang:'从 a 滑向 ng，尾巴舌根抬起 🦴', ong:'从 o 滑向 ng，舌根抬起 🦴'
  };
  function mouthOf(k){ return C.MOUTH[k] || ''; }
  C.mouthOf = mouthOf;
  var TONE_MAP = { 'ā':'a','á':'a','ǎ':'a','à':'a','ē':'e','é':'e','ě':'e','è':'e','ī':'i','í':'i','ǐ':'i','ì':'i','ō':'o','ó':'o','ǒ':'o','ò':'o','ū':'u','ú':'u','ǔ':'u','ù':'u','ǖ':'ü','ǘ':'ü','ǚ':'ü','ǜ':'ü' };
  C.stripTone = function (py){ return String(py||'').replace(/[āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ]/g, function(m){ return TONE_MAP[m] || m; }); };
  C.readMouth = function (py){
    var plain = C.stripTone(py);
    var keys = Object.keys(C.MOUTH).sort(function(a,b){ return b.length - a.length; });
    for (var i=0;i<keys.length;i++){ if (plain.length >= keys[i].length && plain.indexOf(keys[i], plain.length - keys[i].length) === plain.length - keys[i].length) return C.MOUTH[keys[i]]; }
    return '';
  };

  C.FANCI = [
    {prompt:'天 _ 地', correct:'和', options:['和','与','跟','同']},
    {prompt:'大 _ 小', correct:'和', options:['和','与','跟','同']},
    {prompt:'上 _ 下', correct:'下', options:['下','上','中','左']},
    {prompt:'日 _ 月', correct:'明', options:['明','亮','光','早']},
    {prompt:'高 _ 矮', correct:'矮', options:['矮','高','低','短']},
    {prompt:'多 _ 少', correct:'少', options:['少','多','大','小']},
    {prompt:'长 _ 短', correct:'短', options:['短','长','小','矮']},
    {prompt:'黑 _ 白', correct:'白', options:['白','黑','灰','亮']},
    {prompt:'快 _ 慢', correct:'慢', options:['慢','快','急','缓']},
    {prompt:'冷 _ 热', correct:'热', options:['热','冷','温','凉']},
    {prompt:'前 _ 后', correct:'后', options:['后','前','左','右']},
    {prompt:'开 _ 关', correct:'关', options:['关','开','合','启']},
  ];
  C.LIANGCI = [
    {prompt:'量词：一 ____ 书', correct:'本', options:['本','张','个','支']},
    {prompt:'量词：一 ____ 纸', correct:'张', options:['本','张','个','支']},
    {prompt:'量词：一 ____ 铅笔', correct:'支', options:['本','张','个','支']},
    {prompt:'量词：一 ____ 苹果', correct:'个', options:['本','张','个','支']},
    {prompt:'量词：一 ____ 猫', correct:'只', options:['只','个','条','头']},
    {prompt:'量词：一 ____ 花', correct:'朵', options:['朵','棵','支','片']},
    {prompt:'量词：一 ____ 树', correct:'棵', options:['棵','棵','朵','支']},
    {prompt:'量词：一 ____ 鱼', correct:'条', options:['条','只','个','尾']},
    {prompt:'量词：一 ____ 车', correct:'辆', options:['辆','台','条','个']},
    {prompt:'量词：一 ____ 鞋', correct:'双', options:['双','只','对','个']},
  ];

  C.TR_CHARS = [
    {id:'tr1', char:'一', name:'横', strokes:[[{x:40,y:80},{x:160,y:80}]]},
    {id:'tr2', char:'十', name:'十', strokes:[[{x:100,y:40},{x:100,y:160}], [{x:40,y:100},{x:160,y:100}]]},
    {id:'tr3', char:'人', name:'人', strokes:[[{x:100,y:40},{x:40,y:160}], [{x:100,y:40},{x:160,y:160}]]},
    {id:'tr4', char:'大', name:'大', strokes:[[{x:100,y:30},{x:40,y:170}], [{x:100,y:30},{x:160,y:170}], [{x:60,y:120},{x:140,y:120}]]},
  ];

  C.WORDS = [
    {id:'w1', word:'apple', cn:'苹果', audio:'w1', emoji:'🍎'},
    {id:'w2', word:'banana', cn:'香蕉', audio:'w2', emoji:'🍌'},
    {id:'w3', word:'cat', cn:'猫', audio:'w3', emoji:'🐱'},
    {id:'w4', word:'dog', cn:'狗', audio:'w4', emoji:'🐶'},
    {id:'w5', word:'elephant', cn:'大象', audio:'w5', emoji:'🐘'},
    {id:'w6', word:'fish', cn:'鱼', audio:'w6', emoji:'🐟'},
    {id:'w7', word:'bird', cn:'鸟', audio:'w7', emoji:'🐦'},
    {id:'w8', word:'book', cn:'书', audio:'w8', emoji:'📖'},
    {id:'w9', word:'school', cn:'学校', audio:'w9', emoji:'🏫'},
    {id:'w10', word:'milk', cn:'牛奶', audio:'w10', emoji:'🥛'},
    {id:'w11', word:'water', cn:'水', audio:'w11', emoji:'💧'},
    {id:'w12', word:'sun', cn:'太阳', audio:'w12', emoji:'☀️'},
  ];

  C.DIALOGUES = [
    {id:'d1', en:'Hello!', cn:'你好！', audio:'d1'},
    {id:'d2', en:'How are you?', cn:'你好吗？', audio:'d2'},
    {id:'d3', en:'Good morning.', cn:'早上好。', audio:'d3'},
    {id:'d4', en:'Thank you.', cn:'谢谢。', audio:'d4'},
    {id:'d5', en:'Goodbye.', cn:'再见。', audio:'d5'},
    {id:'d6', en:'I love you.', cn:'我爱你。', audio:'d6'},
    {id:'d7', en:'Nice to meet you.', cn:'很高兴认识你。', audio:'d7'},
    {id:'d8', en:'See you tomorrow.', cn:'明天见。', audio:'d8'},
    {id:'d9', en:'Excuse me.', cn:'打扰一下。', audio:'d9'},
    {id:'d10', en:'May I come in?', cn:'我可以进来吗？', audio:'d10'},
    {id:'d11', en:'What time is it?', cn:'现在几点了？', audio:'d11'},
    {id:'d12', en:'Good night.', cn:'晚安。', audio:'d12'},
  ];

  C.PAR_GAMES = [
    {key:'color', name:'🌈 认颜色', desc:'点击听到的颜色', icon:'🎨'},
    {key:'shape', name:'🔷 认形状', desc:'找出相同形状', icon:'🔷'},
    {key:'number', name:'🔢 数数字', desc:'数一数有几个', icon:'🔢'},
    {key:'animal', name:'🐶 认动物', desc:'听声音找动物', icon:'🐶'},
    {key:'fruit', name:'🍎 认水果', desc:'看图选水果', icon:'🍎'},
  ];

  C.WORD_PLUS = [
    {a:3, b:2, template:'有{a}只小鸟，又飞来{b}只，一共有几只？', answer:5},
    {a:4, b:1, template:'小红有{a}颗糖，妈妈给了{b}颗，一共几颗？', answer:5},
    {a:2, b:3, template:'树上有{a}个苹果，树下有{b}个，一共几个？', answer:5},
    {a:3, b:4, template:'篮子里有{a}个球，又放进{b}个，一共几个？', answer:7},
    {a:5, b:2, template:'小明有{a}本书，又买来{b}本，一共有几本？', answer:7},
  ];
  C.WORD_MINUS = [
    {a:5, b:2, template:'有{a}个桃子，吃了{b}个，还剩几个？', answer:3},
    {a:6, b:1, template:'小明有{a}张纸，用了{b}张，还剩几张？', answer:5},
    {a:4, b:3, template:'篮子里有{a}个球，拿走了{b}个，还剩几个？', answer:1},
    {a:7, b:2, template:'盘子里有{a}个苹果，吃掉{b}个，还剩几个？', answer:5},
    {a:8, b:3, template:'车上有{a}人，下去了{b}人，还剩几人？', answer:5},
  ];
})();