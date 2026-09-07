(function () {
  'use strict';
  var C = window.Edu.Constants;
  var M = window.Edu.MathUtils;
  var Store = window.Edu.Store;
  var Speech = window.Edu.Speech;
  var Kids = window.Edu.Kids;
  var QuizEngine = window.Edu.QuizEngine;

  var wbGoMode = 'atari';
  var wbGoBoard = null;
  var wbGoBoardSize = 9;

  // 预设棋谱/题目数据
  // 说明: 所有带棋盘的题目均已用规则引擎逐一手动核对过(目标棋子气数=答案、落子后恰好整体被提);
  // 概念题(打劫/共活/布局/收官/知识/死活原理)不摆子, 避免出现错误的棋形误导孩子。
  var GO_QUIZ_DATA = {
    "atari": [
      { id: "atari_1", prompt: "角上的白棋只剩一口气，黑棋下一手提掉它！", board: "9", moves: ["H8", "I2", "H9", "A1", "A2", "H1", "H7", "I1"], answer: "B1", options: ["B1", "A3", "C1", "B2"], type: "atari", explain: "白棋 A1 在角里只剩 B1 一口气，黑棋落 B1 直接提掉" },
      { id: "atari_2", prompt: "底边的白棋气快没了，黑棋打吃它？", board: "9", moves: ["H8", "I2", "D2", "H1", "C1", "I1", "H9", "D1"], answer: "E1", options: ["E1", "F1", "D3", "C2"], type: "atari", explain: "白棋 D1 被 C1、D2 夹住，只剩 E1 一口气" },
      { id: "atari_3", prompt: "中间这颗白棋被围，黑棋从哪边打吃？", board: "9", moves: ["D4", "I2", "H8", "I3", "E5", "A9", "G7", "D5", "H9", "H1", "C5", "I1"], answer: "D6", options: ["D6", "C6", "E6", "D7"], type: "atari", explain: "白棋 D5 三面都是黑棋，只剩 D6 一口气" },
      { id: "atari_4", prompt: "黑棋下一手吃掉连着的两颗白棋！", board: "9", moves: ["H8", "D4", "E5", "A8", "D3", "D5", "C4", "H1", "G8", "I2", "E4", "I3", "H9", "A9", "C5", "I1"], answer: "D6", options: ["D6", "C6", "E6", "D7"], type: "atari", explain: "白棋 D4、D5 两子只剩 D6 一口气，黑落 D6 提两子" },
      { id: "atari_5", prompt: "黑棋妙手：一手同时打吃两组白棋！", board: "9", moves: ["E5", "C4", "A2", "A1", "F4", "I2", "B4", "E4", "C3", "B2", "C5", "A4", "E3", "I1"], answer: "D4", options: ["D4", "C3", "E3", "C2"], type: "atari", explain: "黑落 D4，C4 和 E4 两组白棋同时只剩一口气被提（双吃）" },
      { id: "atari_6", prompt: "边上的白棋快没气了，黑棋点住它！", board: "9", moves: ["B5", "I2", "A4", "I1", "C4", "B4"], answer: "B3", options: ["B3", "C3", "B2", "C5"], type: "atari", explain: "白棋 B4 被 A4、C4、B5 三面夹住，只剩 B3 一口气，黑落 B3 提掉" },
      { id: "atari_7", prompt: "中间的白棋被围成铁桶，黑棋一指点住！", board: "9", moves: ["D4", "I2", "D3", "C3", "C4", "I3", "H9", "H1", "B3", "I1"], answer: "C2", options: ["C2", "B2", "C1", "D2"], type: "atari", explain: "白棋 C3 四周都是黑棋，只剩 C2 一口气，黑落 C2 提掉" },
      { id: "atari_8", prompt: "角上两颗白棋只剩最后一口气，黑棋提掉它们！", board: "9", moves: ["G8", "A1", "B1", "A2", "B2", "I1"], answer: "A3", options: ["A3", "B3", "A4", "C3"], type: "atari", explain: "白棋 A1、A2 在角里只剩 A3 一口气，黑落 A3 提两子" },
      { id: "atari_9", prompt: "中间两颗白棋被团团围住，黑棋定点击破！", board: "9", moves: ["D7", "I2", "E5", "I3", "D5", "E6", "F5", "I1", "F6", "H1", "E7", "D6"], answer: "C6", options: ["C6", "C5", "B6", "D6"], type: "atari", explain: "白棋 D6、E6 被黑棋围死，只剩 C6 一口气，黑落 C6 提两子" },
      { id: "atari_10", prompt: "黑棋一手同时打吃两颗白棋，下哪里？", board: "9", moves: ["D4", "I2", "A3", "I3", "A5", "C4", "C3", "H1", "H9", "A4", "C5", "I1"], answer: "B4", options: ["B4", "B3", "B5", "C4"], type: "atari", explain: "黑落 B4，A4 和 C4 两颗白棋同时只剩一口气（双吃）" },
      { id: "atari_11", prompt: "中间的白棋被围住只差一口气，黑棋从上边点！", board: "9", moves: ["D7", "I2", "C6", "I1", "E6", "D6"], answer: "D5", options: ["D5", "C5", "E5", "D4"], type: "atari", explain: "白棋 D6 被三面包围，只剩 D5 一口气，黑落 D5 提掉" },
      { id: "atari_12", prompt: "右上角两颗白棋抱在一起，黑棋点住出口！", board: "9", moves: ["H8", "H9", "G9", "I9"], answer: "I8", options: ["I8", "G8", "H8", "I7"], type: "atari", explain: "白棋 H9、I9 在角里只剩 I8 一口气，黑落 I8 提两子" },
      { id: "atari_13", prompt: "黑棋一手双吃：边上两颗白棋一起打！", board: "9", moves: ["A7", "I2", "D6", "A6", "A5", "H1", "C7", "C6", "C5", "I1"], answer: "B6", options: ["B6", "B5", "B7", "C6"], type: "atari", explain: "黑落 B6，A6 和 C6 两颗白棋同时只剩一口气（双吃）" },
      { id: "atari_14", prompt: "两颗白棋挤在三路，黑棋点破！", board: "9", moves: ["D2", "C2", "B1", "I2", "A2", "B2", "B3", "H1", "C1", "I1"], answer: "C3", options: ["C3", "B3", "D3", "C4"], type: "atari", explain: "白棋 B2、C2 被围，只剩 C3 一口气，黑落 C3 提两子" }
    ],
    "liberty": [
      { id: "lib_1", prompt: "黑棋被打吃了，往哪里逃才安全？", board: "9", moves: ["H8", "C5", "D5", "E5", "H9", "D4"], answer: "D6", options: ["D6", "C6", "E6", "D7"], type: "liberty", explain: "黑落 D6 向上连出来，气变多，白棋吃不动了", subject: "D5" },
      { id: "lib_2", prompt: "黑棋只剩一口气了，往哪里逃，气才越来越多？", board: "9", moves: ["I2", "C2", "D2", "E2", "I1", "D3"], answer: "D1", options: ["D1", "C1", "E1", "D4"], type: "liberty", explain: "往底线 D1 跑，之后 C1、E1 还是出口，越跑气越多", subject: "D2" },
      { id: "lib_3", prompt: "黑棋只剩一口气了，往哪个方向逃才更有气？", board: "9", moves: ["I2", "D4", "I1", "C3", "D3", "E3"], answer: "D2", options: ["D2", "C2", "E2", "D5"], type: "liberty", explain: "黑落 D2 逃出，之后 C2、E2、D1 都是出口，气越来越多", subject: "D3" },
      { id: "lib_4", prompt: "这颗黑棋被三面夹住，往中间跑才活！", board: "9", moves: ["I1", "G5", "H1", "F4", "G4", "H4"], answer: "G3", options: ["G3", "F3", "H3", "G2"], type: "liberty", explain: "黑落 G3，F3、H3、G2 一下子多出三个出口", subject: "G4" },
      { id: "lib_5", prompt: "黑棋在二路上被夹，往底线跑出一口气！", board: "9", moves: ["C2", "D2", "I2", "C3", "I1", "B2"], answer: "C1", options: ["C1", "B1", "D1", "C4"], type: "liberty", explain: "黑落 C1 逃到边上，B1、D1 都是新出口", subject: "C2" },
      { id: "lib_6", prompt: "上面的黑棋被围住，往边线一伸就活了！", board: "9", moves: ["I2", "F6", "I1", "E5", "E6", "D6"], answer: "E7", options: ["E7", "D7", "F7", "E8"], type: "liberty", explain: "黑落 E7，D7、F7、E8 三个出口全打开", subject: "E6" },
      { id: "lib_7", prompt: "左边黑棋被追到只剩一口气，往角里挤一挤！", board: "9", moves: ["I2", "B6", "I1", "A7", "B7", "C7"], answer: "B8", options: ["B8", "A8", "C8", "B9"], type: "liberty", explain: "黑落 B8，A8、C8、B9 都是新出口，逃出生天", subject: "B7" },
      { id: "lib_8", prompt: "右边的黑棋被围，往下跳一步保平安！", board: "9", moves: ["H3", "G3", "A9", "I3", "G9", "H4"], answer: "H2", options: ["H2", "G2", "I2", "H1"], type: "liberty", explain: "黑落 H2，G2、H2 附近的出口全都有气", subject: "H3" },
      { id: "lib_9", prompt: "中间这颗黑棋被团团围住，往上冲一个口！", board: "9", moves: ["I2", "D4", "E4", "F4", "I1", "E3"], answer: "E5", options: ["E5", "D5", "F5", "E6"], type: "liberty", explain: "黑落 E5，D5、F5、E6 三个方向全活了", subject: "E4" },
      { id: "lib_10", prompt: "上边的黑棋后退就死，往角上腰里一挤！", board: "9", moves: ["G8", "H8", "I2", "G7", "I1", "F8"], answer: "G9", options: ["G9", "F9", "H9", "E9"], type: "liberty", explain: "黑落 G9 顶到边角，F9、H9 都是新出口", subject: "G8" },
      { id: "lib_11", prompt: "左边中腹的黑棋被夹死，往中间逃！", board: "9", moves: ["I2", "B6", "C6", "D6", "I1", "C7"], answer: "C5", options: ["C5", "B5", "D5", "C4"], type: "liberty", explain: "黑落 C5，B5、D5、C4 三个出口全打开", subject: "C6" },
      { id: "lib_12", prompt: "底边黑棋气仅一口，往下一跑反而安全！", board: "9", moves: ["G9", "E2", "A9", "G2", "F2", "F3"], answer: "F1", options: ["F1", "E1", "G1", "F4"], type: "liberty", explain: "黑落 F1 抢到底线，E1、G1 还是出口", subject: "F2" },
      { id: "lib_13", prompt: "最左路的黑棋只剩一囗，沿边往上爬！", board: "9", moves: ["I1", "A6", "A5", "B5"], answer: "A4", options: ["A4", "B4", "A3", "C5"], type: "liberty", explain: "黑落 A4，B4、A3 两个新出口，黑棋逃掉", subject: "A5" },
      { id: "lib_14", prompt: "黑棋在板上被追，往右上方探出一手！", board: "9", moves: ["I2", "G6", "H6", "I6", "I1", "H7"], answer: "H5", options: ["H5", "G5", "I5", "H4"], type: "liberty", explain: "黑落 H5，G5、I5、H4 全是新出口，脱离危险", subject: "H6" }
    ],
    "capture": [
      { id: "cap_1", prompt: "黑棋一次提掉边上两颗白棋，下哪里？", board: "9", moves: ["H8", "I2", "F1", "I1", "D2", "D1", "C1", "E1"], answer: "E2", options: ["E2", "D3", "F2", "D2"], type: "capture", explain: "白棋 D1、E1 只剩 E2 一口气，黑落 E2 全部提掉" },
      { id: "cap_2", prompt: "角上的白棋看着不少，黑棋一手全吃掉！", board: "9", moves: ["A3", "A1", "H8", "B1", "C1", "A2", "H9", "I1"], answer: "B2", options: ["B2", "A4", "C2", "B3"], type: "capture", explain: "黑落 B2，角上三颗白棋最后一口气被堵死，全部被提" },
      { id: "cap_3", prompt: "角上三颗白棋连在一起，黑棋一手全提掉！", board: "9", moves: ["H8", "A1", "G6", "B1", "C1", "A2", "B2", "I1"], answer: "A3", options: ["A3", "A4", "B3", "C2"], type: "capture", explain: "黑落 A3，角上三颗白棋只剩的一口气被堵死，全部被提" },
      { id: "cap_4", prompt: "黑棋一口气提掉三颗连着的白棋！", board: "9", moves: ["H8", "E1", "D2", "F1", "G1", "A9", "E2", "D1", "C1", "A8"], answer: "F2", options: ["F2", "E3", "D3", "F3"], type: "capture", explain: "白棋 D1、E1、F1 只剩 F2 一口气，黑落 F2 全部提掉" },
      { id: "cap_5", prompt: "白棋大龙被团团围住，黑棋最后一提在哪？", board: "9", moves: ["D4", "I2", "B6", "I3", "D5", "C4", "D6", "C5", "B4", "H1", "C3", "C6", "B5", "I1"], answer: "C7", options: ["C7", "B3", "D3", "C8"], type: "capture", explain: "黑棋 D 路、B 路和 C3 把白棋围死，白棋只剩 C7 一口气" },
      { id: "cap_6", prompt: "右上角的两颗白棋想逃，黑棋点住哪一口？", board: "9", moves: ["G8", "I2", "H8", "I1", "G6", "G9", "I9", "H9"], answer: "F9", options: ["F9", "F8", "E9", "G8"], type: "capture", explain: "白棋 G9、H9 被黑棋夹住，只剩 F9 一口气，黑落 F9 全提" },
      { id: "cap_7", prompt: "中间两颗白棋快没气了，黑棋从上边补上一口！", board: "9", moves: ["H8", "I2", "E6", "E5", "D5", "F5", "F4", "A8", "G5", "A9", "H9", "H1", "F6", "I1"], answer: "E4", options: ["E4", "D4", "E3", "F4"], type: "capture", explain: "白棋 E5、F5 只剩 E4 一口气，黑落 E4 提两子" },
      { id: "cap_8", prompt: "黑棋一口气提掉底边四颗白棋！", board: "9", moves: ["D2", "G1", "G2", "E1", "F2", "F1", "E2", "A9", "C1", "D1"], answer: "H1", options: ["H1", "H2", "G2", "I1"], type: "capture", explain: "底边四颗白棋连成一排，只剩 H1 一口气，黑落 H1 全提" },
      { id: "cap_9", prompt: "左上角两颗白棋，黑棋堵死出口！", board: "9", moves: ["A9", "B8", "A7", "I1", "B9", "I2", "B7", "A8"], answer: "C8", options: ["C8", "B9", "C7", "A9"], type: "capture", explain: "白棋 A8、B8 只剩 C8 一口气，黑落 C8 提两子" },
      { id: "cap_10", prompt: "角上三颗白棋，黑棋最后堵哪一口？", board: "9", moves: ["G8", "A1", "B3", "B1", "C1", "I1", "A2", "B2"], answer: "C2", options: ["C2", "D2", "C3", "B3"], type: "capture", explain: "白棋 A1、B1、B2 只剩 C2 一口气，黑落 C2 全提" },
      { id: "cap_11", prompt: "左路三颗白棋站成一队，黑棋从前面封口！", board: "9", moves: ["B3", "A3", "B1", "A1", "B2", "A2"], answer: "A4", options: ["A4", "B4", "A5", "C4"], type: "capture", explain: "白棋 A1、A2、A3 被 B 路堵住，只剩 A4 一口气，黑落 A4 全提" },
      { id: "cap_12", prompt: "黑棋围住底边三颗白棋，最后的出口在哪？", board: "9", moves: ["B1", "C2", "A2", "I2", "D3", "D2", "D1", "I3", "C3", "B2", "B3", "H1", "C1", "I1"], answer: "E2", options: ["E2", "D3", "E3", "E1"], type: "capture", explain: "白棋 B2、C2、D2 被围，只剩 E2 一口气，黑落 E2 全提" },
      { id: "cap_13", prompt: "四颗白棋抱成小方块，黑棋把它一锅端！", board: "9", moves: ["D2", "C2", "A1", "B1", "D1", "B2", "C3", "C1", "B3", "I1"], answer: "A2", options: ["A2", "A3", "A1", "D2"], type: "capture", explain: "白棋 2×2 方块只剩 A2 一口气，黑落 A2 四子全提" },
      { id: "cap_14", prompt: "上面两颗白棋贴着边，黑棋从下面收口！", board: "9", moves: ["F9", "E9", "E8", "I1", "C9", "D9"], answer: "D8", options: ["D8", "D7", "C8", "E9"], type: "capture", explain: "白棋 D9、E9 被夹住，只剩 D8 一口气，黑落 D8 全提" }
    ],
    "connect": [
      { id: "conn_1", prompt: "黑棋两组棋被分开，下一手连起来！", board: "9", moves: ["D4", "I2", "F4", "H1", "C4", "I1"], answer: "E4", options: ["E4", "E3", "E5", "D3"], type: "connect", explain: "黑落 E4，把左右两组黑棋接在一起" },
      { id: "conn_2", prompt: "白棋想连在一起，黑棋在哪里切断连线？", board: "9", moves: ["H8", "C5", "H6", "C6", "H9", "E6", "H7", "C4"], answer: "D6", options: ["D6", "C7", "E5", "D5"], type: "connect", explain: "黑落 D6，白棋 C6 和 E6 从此各奔东西", kind: "block", kpts: ["C6", "E6", "D6"] },
      { id: "conn_3", prompt: "黑棋斜着分成了两组，下一手连起来！", board: "9", moves: ["C5", "I2", "C3", "H1", "B5", "I1"], answer: "C4", options: ["C4", "B4", "D4", "C6"], type: "connect", explain: "黑落 C4，把 C5 和 C3 两组黑棋连成一串" },
      { id: "conn_4", prompt: "顺底边走：黑棋怎么把三颗子连成一串？", board: "9", moves: ["F1", "I2", "C1", "I3", "D1", "I1"], answer: "E1", options: ["E1", "E2", "D2", "F2"], type: "connect", explain: "黑落 E1，把 C、D、F 三颗黑棋连成一条龙" },
      { id: "conn_5", prompt: "白棋急着用 D1 连棋，黑棋抢先占下哪里？", board: "9", moves: ["H8", "I2", "H6", "C1", "H9", "I1", "H7", "E1"], answer: "D1", options: ["D1", "D2", "C2", "E2"], type: "connect", explain: "D1 是白棋上下连通的唯一要点，黑棋先下就切断", kind: "block", kpts: ["C1", "E1", "D1"] },
      { id: "conn_6", prompt: "底边的两组黑棋，下一手连成一条龙！", board: "9", moves: ["C2", "I2", "E2", "H1", "C1", "I1"], answer: "D2", options: ["D2", "C3", "E1", "D1"], type: "connect", explain: "黑落 D2，把 C1、C2 和 E2 接在一起" },
      { id: "conn_7", prompt: "中间两颗黑棋中间差一点，补在哪里才连上？", board: "9", moves: ["C5", "I2", "E5", "I1"], answer: "D5", options: ["D5", "D4", "C6", "E6"], type: "connect", explain: "D5 一落，C5-E5-D5 手拉手连成一条直线" },
      { id: "conn_8", prompt: "白棋想从底边连手，黑棋抢下哪个要点？", board: "9", moves: ["G8", "B1", "G9", "I1", "G7", "D1"], answer: "C1", options: ["C1", "C2", "B2", "D2"], type: "connect", explain: "C1 在 B1、D1 中间，黑棋抢先占住，白棋连不上", kind: "block", kpts: ["B1", "D1", "C1"] },
      { id: "conn_9", prompt: "角上的黑棋伸出一只手，接应外面那颗兄弟！", board: "9", moves: ["A1", "I2", "C1", "H1", "A2", "I1"], answer: "B1", options: ["B1", "B2", "A3", "C2"], type: "connect", explain: "黑落 B1，把角上的 A 路两子与 C1 连成一条龙" },
      { id: "conn_10", prompt: "黑棋被分成两半，下一手把它们接起来！", board: "9", moves: ["C5", "I2", "E4", "H1", "C4", "I1"], answer: "D4", options: ["D4", "D5", "C6", "E3"], type: "connect", explain: "黑落 D4，两组黑棋由此连成一体" },
      { id: "conn_11", prompt: "两个黑棋小组在等着搭桥，桥点在哪里？", board: "9", moves: ["D7", "I2", "B6", "H1", "B7", "I1"], answer: "C7", options: ["C7", "C6", "C8", "B8"], type: "connect", explain: "黑落 C7，把 B7 和 D7 两组连起来" },
      { id: "conn_12", prompt: "白棋想从中间连手，黑棋抢先占领要害！", board: "9", moves: ["I2", "D7", "I1", "F7"], answer: "E7", options: ["E7", "E6", "E8", "D8"], type: "connect", explain: "E7 是 D7、F7 两边的连接点，黑棋占住就切断了白棋", kind: "block", kpts: ["D7", "F7", "E7"] },
      { id: "conn_13", prompt: "黑棋斜斜的两小组，下一手连成一个大团！", board: "9", moves: ["D4", "I2", "B3", "H1", "C3", "I1"], answer: "C4", options: ["C4", "B4", "D4", "E4"], type: "connect", explain: "黑落 C4，把 C3 和 D4 两大组接在一起" },
      { id: "conn_14", prompt: "角里的黑棋派出一手，接住上面的兄弟！", board: "9", moves: ["A9", "I2", "C9", "H1", "A8", "I1"], answer: "B9", options: ["B9", "C9", "B8", "A9"], type: "connect", explain: "黑落 B9，把 A9 和 C9 连成一条线" }
    ],
    "life_death": [
      { id: "ld_1", prompt: "角上黑棋只剩一口气，白棋怎么提掉它？", board: "9", moves: ["A1", "A2"], answer: "B1", options: ["B1", "A3", "B2", "C1"], type: "life_death", explain: "白落 B1，黑棋 A1 只剩下的 B1 口也被堵，A1 被提" },
      { id: "ld_2", prompt: "两颗黑棋被围在边上，白棋最后一手在哪？", board: "9", moves: ["I1", "F1", "D1", "D2", "E1", "C1"], answer: "E2", options: ["E2", "C2", "F2", "D3"], type: "life_death", explain: "白落 E2，把黑棋 D1、E1 两颗子一起提掉" },
      { id: "ld_3", prompt: "角上两颗黑棋只剩一个口，白棋点追！", board: "9", moves: ["A1", "A2", "B1", "B2"], answer: "C1", options: ["C1", "A3", "C2", "B3"], type: "life_death", explain: "白落 C1，A1、B1 两颗黑棋最后的出口被堵，全部被提" },
      { id: "ld_4", prompt: "两颗黑棋靠在第二路，白棋一指点破！", board: "9", moves: ["C2", "D1", "I2", "C3", "D2", "B2", "H1", "E2", "I1", "C1"], answer: "D3", options: ["D3", "B3", "D4", "C4"], type: "life_death", explain: "白落 D3，C2、D2 两颗黑棋的唯一出口被盖死，全被提" },
      { id: "ld_5", prompt: "两颗黑棋竖直站在角上，白棋一网打尽！", board: "9", moves: ["A1", "B1", "A2", "B2"], answer: "A3", options: ["A3", "B3", "A4", "C3"], type: "life_death", explain: "白落 A3，A 路两颗黑棋被提得一干二净" },
      { id: "ld_6", prompt: "底边两颗黑棋被围住，白棋最后一击在哪？", board: "9", moves: ["B1", "A1", "C1", "D1", "I1", "B2"], answer: "C2", options: ["C2", "A2", "B3", "C3"], type: "life_death", explain: "白落 C2，B1、C1 两颗黑棋最后的气也被堵死" },
      { id: "ld_7", prompt: "三颗黑棋连成一排堵在底边，白棋点哪一口？", board: "9", moves: ["C1", "C2", "I1", "F1", "D1", "B1", "E1", "E2"], answer: "D2", options: ["D2", "B2", "D3", "F2"], type: "life_death", explain: "白落 D2，三颗黑棋连起的墙只有这一个口，堵上全提" },
      { id: "ld_8", prompt: "再长一排：四颗？不，三颗堵底边，白棋从右边堵死！", board: "9", moves: ["F1", "G1", "A9", "E2", "D1", "C1", "E1", "D2"], answer: "F2", options: ["F2", "D3", "E3", "G2"], type: "life_death", explain: "白落 F2，D1、E1、F1 三颗黑棋的最后一口气被堵死" },
      { id: "ld_9", prompt: "两颗黑棋竖在第二条线上，白棋从下往上堵！", board: "9", moves: ["I2", "C2", "B1", "A1", "I1", "C1", "B2", "A2"], answer: "B3", options: ["B3", "A3", "C3", "B4"], type: "life_death", explain: "白落 B3，B 路两颗黑棋的最后一个口被封，全被提" },
      { id: "ld_10", prompt: "右边一颗黑棋孤立无援，白棋怎么提它？", board: "9", moves: ["G1", "F1", "A9", "H1"], answer: "G2", options: ["G2", "F2", "H2", "G3"], type: "life_death", explain: "白落 G2，黑棋 G1 上下左右全无气，被提" },
      { id: "ld_11", prompt: "右上角两颗黑棋抱团，白棋从里边拆散！", board: "9", moves: ["I8", "H8", "I9", "H9"], answer: "I7", options: ["I7", "H7", "I6", "J9"], type: "life_death", explain: "白落 I7，I8、I9 两颗黑棋最后的气被堵，全被提" },
      { id: "ld_12", prompt: "左边三颗黑棋排着队，白棋从下面断后！", board: "9", moves: ["A9", "B8", "A7", "B9", "A8", "B7"], answer: "A6", options: ["A6", "B6", "A5", "B5"], type: "life_death", explain: "白落 A6，三颗黑棋上方唯一出口被堵，全被提" },
      { id: "ld_13", prompt: "中间两颗黑棋被围住，白棋补上致命一击！", board: "9", moves: ["I2", "D2", "C3", "C4", "D3", "C2", "H1", "B3", "I1", "E3"], answer: "D4", options: ["D4", "B4", "E4", "D5"], type: "life_death", explain: "白落 D4，C3、D3 两颗黑棋最后的气被封，全被提" },
      { id: "ld_14", prompt: "一颗黑棋被白棋包围，白棋点在哪就赢？", board: "9", moves: ["I2", "D7", "B7", "B6", "B8", "A7", "H1", "A8", "I1", "C8", "C7", "C6"], answer: "B9", options: ["B9", "A9", "C9"], type: "life_death", explain: "白落 B9，黑棋最后的一口气被堵死，三子全灭" }
    ]
  };

  function shuffleArray(arr) {
    var a = arr.slice();
    for (var i = a.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var tmp = a[i]; a[i] = a[j]; a[j] = tmp;
    }
    return a;
  }

  function goRecentKey(type) {
    return 'edu_go_qrecent_' + type;
  }

  // 选项顺序打乱: 正确答案不再固定在第一格
  function shuffleOptions(q) {
    var opts = q.options.map(function (o) { return { v: o, label: o }; });
    return shuffleArray(opts);
  }

  function buildGoQuiz(subj, type) {
    var data = GO_QUIZ_DATA[type] || GO_QUIZ_DATA.atari;
    // 跨场次去重: 优先出「最近没出过」的题, 进一步降低重复感
    var seen = [];
    try { seen = JSON.parse(localStorage.getItem(goRecentKey(type)) || '[]') || []; } catch (e) { seen = []; }
    var seenSet = {};
    seen.forEach(function (id) { seenSet[id] = 1; });
    var fresh = [], recalled = [];
    data.forEach(function (q) { (seenSet[q.id] ? recalled : fresh).push(q); });
    var ordered = shuffleArray(fresh).concat(shuffleArray(recalled));
    var picked = ordered.slice(0, C.QUIZ_LEN || 10);
    var items = picked.map(function (q) {
      // 坐标类题目(答案为棋盘交叉点): 改为「在棋盘上点选作答」, 不再展示文字选项
      var goTap = !!parseGoCoord(q.answer);
      return {
        id: q.id,
        prompt: q.prompt,
        options: shuffleOptions(q),
        correct: q.answer,
        note: q.explain,
        wtype: type,
        board: q.board,
        moves: q.moves,
        goTap: goTap
      };
    });
    // 记录本次出过的题, 只记住上一轮, 下次能稳定出一批没见过的
    var next = picked.map(function (q) { return q.id; }).concat(seen).slice(0, C.QUIZ_LEN || 10);
    try { localStorage.setItem(goRecentKey(type), JSON.stringify(next)); } catch (e) {}
    return items;
  }

  // 坐标解析: "D4" → { col:4, rank:4 }(A1 起步)
  function parseGoCoord(s) {
    if (s == null) return null;
    var m = String(s).trim().match(/^([A-Za-z])(\d{1,2})$/);
    if (!m) return null;
    return { col: m[1].toUpperCase().charCodeAt(0) - 64, rank: parseInt(m[2], 10) };
  }
  function starPoints(n) {
    if (n === 9) return [[3, 3], [3, 7], [5, 5], [7, 3], [7, 7]];
    if (n === 13) return [[4, 4], [4, 10], [7, 7], [10, 4], [10, 10]];
    if (n === 19) return [[4, 4], [4, 10], [4, 16], [10, 4], [10, 10], [10, 16], [16, 4], [16, 10], [16, 16]];
    var c = Math.ceil(n / 2); return [[c, c]];
  }

  // 渲染围棋棋盘: moves 按黑先白后交替落子, size 为路数(默认 9)
  function boardSvg(moves, size) {
    var n = parseInt(size, 10);
    if (!n || isNaN(n) || n < 2) n = 9;
    if (n > 19) n = 19;
    var W = 300, L = 26, R = 26, S = (W - L - R) / (n - 1);
    var px = function (c) { return L + (c - 1) * S; };
    var py = function (r) { return L + (n - r) * S; };
    var lines = '', i;
    for (i = 0; i < n; i++) {
      lines += '<line x1="' + px(1).toFixed(1) + '" y1="' + py(i + 1).toFixed(1) + '" x2="' + px(n).toFixed(1) + '" y2="' + py(i + 1).toFixed(1) + '" stroke="#8a5a20" stroke-width="2" stroke-linecap="round"/>';
      lines += '<line x1="' + px(i + 1).toFixed(1) + '" y1="' + py(1).toFixed(1) + '" x2="' + px(i + 1).toFixed(1) + '" y2="' + py(n).toFixed(1) + '" stroke="#8a5a20" stroke-width="2" stroke-linecap="round"/>';
    }
    var stars = starPoints(n).map(function (p) {
      return '<circle cx="' + px(p[0]).toFixed(1) + '" cy="' + py(p[1]).toFixed(1) + '" r="4" fill="#7a4a16"/>';
    }).join('');
    var labels = '';
    for (i = 1; i <= n; i++) {
      labels += '<text x="' + px(i).toFixed(1) + '" y="' + (W - 7) + '" text-anchor="middle" font-size="11" fill="#9a6a28">' + String.fromCharCode(64 + i) + '</text>';
      labels += '<text x="9" y="' + py(i).toFixed(1) + '" text-anchor="middle" dominant-baseline="central" font-size="11" fill="#9a6a28">' + i + '</text>';
    }
    var stones = '';
    var last = null;
    (moves || []).forEach(function (mv, idx) {
      var p = parseGoCoord(mv);
      if (!p || p.col < 1 || p.col > n || p.rank < 1 || p.rank > n) return;
      var cx = px(p.col), cy = py(p.rank), black = (idx % 2 === 0);
      var r = S * 0.46;
      stones += '<circle cx="' + cx.toFixed(1) + '" cy="' + cy.toFixed(1) + '" r="' + r.toFixed(1) + '" fill="url(#gb' + (black ? 'k' : 'w') + ')" stroke="' + (black ? '#1f1a12' : '#c4c8cc') + '" stroke-width="1.5"/>';
      if (black) stones += '<circle cx="' + (cx - r * 0.28).toFixed(1) + '" cy="' + (cy - r * 0.28).toFixed(1) + '" r="' + (r * 0.28).toFixed(1) + '" fill="rgba(255,255,255,0.16)"/>';
      else stones += '<circle cx="' + (cx - r * 0.3).toFixed(1) + '" cy="' + (cy - r * 0.3).toFixed(1) + '" r="' + (r * 0.18).toFixed(1) + '" fill="rgba(255,255,255,0.55)"/>';
      last = { cx: cx, cy: cy, r: r };
    });
    var lastMark = last ? '<circle cx="' + last.cx.toFixed(1) + '" cy="' + last.cy.toFixed(1) + '" r="' + (last.r * 0.24).toFixed(1) + '" fill="#e74c3c"/>' : '';
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + W + ' ' + W + '" width="100%" height="auto" role="img" aria-label="围棋棋盘">' +
      '<defs>' +
      '<linearGradient id="gwood" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#faf6ea"/><stop offset="100%" stop-color="#efe4cd"/></linearGradient>' +
      '<radialGradient id="gbk" cx="38%" cy="32%" r="70%"><stop offset="0%" stop-color="#4a4a4a"/><stop offset="100%" stop-color="#0a0a0a"/></radialGradient>' +
      '<radialGradient id="gbw" cx="38%" cy="32%" r="70%"><stop offset="0%" stop-color="#ffffff"/><stop offset="100%" stop-color="#e7e9ec"/></radialGradient>' +
      '</defs>' +
      '<rect x="2" y="2" width="' + (W - 4) + '" height="' + (W - 4) + '" rx="14" fill="url(#gwood)"/>' +
      lines + stars + labels + stones + lastMark +
      '</svg>';
  }

  function renderGoWorkbench(body) {
    if (!body) return;
    // 旧版可能存过文字题模式, 回退到安全的基本玩法
    if (['atari', 'liberty', 'capture', 'connect', 'life_death'].indexOf(wbGoMode) === -1) wbGoMode = 'atari';
    body.innerHTML = goSectionHtml();
    renderGoMode(body.querySelector('#wb-go-body'), wbGoMode);
  }

  // 交互式棋盘: 坐标题可点击交叉点作答. o 可含 { idx, tapped, reveal, correct }
  //  - idx: 题目索引(用于回调 goTap)
  //  - tapped: 当前已点选的坐标
  //  - reveal: 是否已揭示正确答案(答错两次后锁定)
  //  - correct: 正确答案坐标(揭示时高亮)
  function boardSvgTap(moves, size, o) {
    o = o || {};
    var n = parseInt(size, 10);
    if (!n || isNaN(n) || n < 2) n = 9;
    if (n > 19) n = 19;
    var W = 300, L = 26, R = 26, S = (W - L - R) / (n - 1);
    var px = function (c) { return L + (c - 1) * S; };
    var py = function (r) { return L + (n - r) * S; };
    var lines = '', i;
    for (i = 0; i < n; i++) {
      lines += '<line x1="' + px(1).toFixed(1) + '" y1="' + py(i + 1).toFixed(1) + '" x2="' + px(n).toFixed(1) + '" y2="' + py(i + 1).toFixed(1) + '" stroke="#8a5a20" stroke-width="2" stroke-linecap="round"/>';
      lines += '<line x1="' + px(i + 1).toFixed(1) + '" y1="' + py(1).toFixed(1) + '" x2="' + px(i + 1).toFixed(1) + '" y2="' + py(n).toFixed(1) + '" stroke="#8a5a20" stroke-width="2" stroke-linecap="round"/>';
    }
    var stars = starPoints(n).map(function (p) {
      return '<circle cx="' + px(p[0]).toFixed(1) + '" cy="' + py(p[1]).toFixed(1) + '" r="4" fill="#7a4a16"/>';
    }).join('');
    var labels = '';
    for (i = 1; i <= n; i++) {
      labels += '<text x="' + px(i).toFixed(1) + '" y="' + (W - 7) + '" text-anchor="middle" font-size="11" fill="#9a6a28">' + String.fromCharCode(64 + i) + '</text>';
      labels += '<text x="9" y="' + py(i).toFixed(1) + '" text-anchor="middle" dominant-baseline="central" font-size="11" fill="#9a6a28">' + i + '</text>';
    }
    var stones = '';
    var occupied = {};
    var last = null;
    (moves || []).forEach(function (mv, idx) {
      var p = parseGoCoord(mv);
      if (!p || p.col < 1 || p.col > n || p.rank < 1 || p.rank > n) return;
      var cx = px(p.col), cy = py(p.rank), black = (idx % 2 === 0);
      var r = S * 0.46;
      occupied[p.col + '_' + p.rank] = true;
      stones += '<circle cx="' + cx.toFixed(1) + '" cy="' + cy.toFixed(1) + '" r="' + r.toFixed(1) + '" fill="url(#gb' + (black ? 'k' : 'w') + ')" stroke="' + (black ? '#1f1a12' : '#c4c8cc') + '" stroke-width="1.5"/>';
      if (black) stones += '<circle cx="' + (cx - r * 0.28).toFixed(1) + '" cy="' + (cy - r * 0.28).toFixed(1) + '" r="' + (r * 0.28).toFixed(1) + '" fill="rgba(255,255,255,0.16)"/>';
      else stones += '<circle cx="' + (cx - r * 0.3).toFixed(1) + '" cy="' + (cy - r * 0.3).toFixed(1) + '" r="' + (r * 0.18).toFixed(1) + '" fill="rgba(255,255,255,0.55)"/>';
      last = { cx: cx, cy: cy, r: r };
    });
    var lastMark = '';
    var marks = '';
    // 下一次落子的颜色: 黑先白后, 依据已有手数取偶数列
    var blackMove = ((moves || []).length % 2 === 0);
    var stoneAt = function (coord) {
      var p = parseGoCoord(coord);
      if (!p || p.col < 1 || p.col > n || p.rank < 1 || p.rank > n) return '';
      var cx = px(p.col), cy = py(p.rank);
      return '<circle cx="' + cx.toFixed(1) + '" cy="' + cy.toFixed(1) + '" r="' + (S * 0.46).toFixed(1) + '" fill="' + (blackMove ? 'url(#gbk)' : 'url(#gbw)') + '" stroke="' + (blackMove ? '#1f1a12' : '#c4c8cc') + '" stroke-width="1.5"/>';
    };
    // 环状高亮某坐标
    var ringAt = function (coord, color, r) {
      var p = parseGoCoord(coord);
      if (!p || p.col < 1 || p.col > n || p.rank < 1 || p.rank > n) return '';
      var cx = px(p.col), cy = py(p.rank);
      return '<circle cx="' + cx.toFixed(1) + '" cy="' + cy.toFixed(1) + '" r="' + (r || 9) + '" fill="none" stroke="' + color + '" stroke-width="5" stroke-linecap="round"/>';
    };
    // 已点选的位置: 落下一枚星标, 便于确认自己点到的交叉点
    if (o.tapped) {
      lastMark = stoneAt(o.tapped);
      // 答对已锁定显示绿环, 未判定中的点选显示蓝环
      marks += ringAt(o.tapped, o.ok ? '#37b24d' : '#1c7ed6');
    }
    // 揭示正确答案: 正确点绿环, 点错的位置红环
    if (o.reveal) {
      if (o.correct) {
        lastMark = stoneAt(o.correct);
        marks += ringAt(o.correct, '#37b24d', 11);
      }
      if (o.tapped && o.tapped !== o.correct) marks += ringAt(o.tapped, '#f03e3e');
    }
    // 可点击交叉点(空点): 点选后回调 QuizEngine.goTap
    var hits = '';
    if (o.idx !== undefined) {
      for (var c = 1; c <= n; c++) {
        for (var r = 1; r <= n; r++) {
          if (occupied[c + '_' + r]) continue;
          var hc = String.fromCharCode(64 + c) + '' + r;
          var hx = px(c), hy = py(r);
          hits += '<circle cx="' + hx.toFixed(1) + '" cy="' + hy.toFixed(1) + '" r="' + (S * 0.62).toFixed(1) + '" fill="rgba(0,0,0,0.01)" data-coord="' + hc + '" style="cursor:pointer" onclick="window.Edu.QuizEngine.goTap(' + o.idx + ',\'' + hc + '\')"/>';
        }
      }
    }
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + W + ' ' + W + '" width="100%" height="auto" role="img" aria-label="围棋棋盘(点击作答)">' +
      '<defs>' +
      '<linearGradient id="gwood" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#faf6ea"/><stop offset="100%" stop-color="#efe4cd"/></linearGradient>' +
      '<radialGradient id="gbk" cx="38%" cy="32%" r="70%"><stop offset="0%" stop-color="#4a4a4a"/><stop offset="100%" stop-color="#0a0a0a"/></radialGradient>' +
      '<radialGradient id="gbw" cx="38%" cy="32%" r="70%"><stop offset="0%" stop-color="#ffffff"/><stop offset="100%" stop-color="#e7e9ec"/></radialGradient>' +
      '</defs>' +
      '<rect x="2" y="2" width="' + (W - 4) + '" height="' + (W - 4) + '" rx="14" fill="url(#gwood)"/>' +
      lines + stars + labels + stones + lastMark + marks + hits +
      '</svg>';
  }

  // 工作台骨架 HTML(与模板 #wb-go 结构一致)
  function goSectionHtml() {
    var modeTabs = [
      { id: 'atari', label: '基本气与吃子', emoji: '💨' },
      { id: 'liberty', label: '找气与逃跑', emoji: '🏃' },
      { id: 'capture', label: '打吃与提子', emoji: '🎯' },
      { id: 'connect', label: '连接与分断', emoji: '🔗' },
      { id: 'life_death', label: '死活与二眼', emoji: '👁️' }
    ];
    var html = '<div id="wb-go">';
    html += '<div class="sm-tabs" style="overflow-x:auto;white-space:nowrap;margin-bottom:12px;">';
    modeTabs.forEach(function (m) {
      html += '<button type="button" class="sm-tab' + (wbGoMode === m.id ? ' active' : '') + '" data-s="' + m.id + '" onclick="wbGo(\'' + m.id + '\')">' + m.emoji + ' ' + m.label + '</button>';
    });
    html += '</div>';
    html += '<div id="wb-go-body"></div>';
    html += '</div>';
    return html;
  }

  function setGoTab(mode) {
    document.querySelectorAll('#wb-go .sm-tab').forEach(function (t) {
      t.classList.toggle('active', t.dataset.s === mode);
    });
  }

  function renderGoMode(container, mode) {
    if (!container) return;
    var items = buildGoQuiz('go', mode);
    QuizEngine.startQuiz('go', mode, items, { difficulty: 1 });
  }

  window.wbGo = function (mode) {
    // 兼容闯关关卡的 go_xxx 与工作台 tab 的 xxx 两种 mode 写法
    mode = String(mode || 'atari').replace(/^go_/, '') || 'atari';
    // 只保留「点选棋盘」的 5 种玩法; 旧版存下的文字题模式回退到基本玩法
    if (['atari', 'liberty', 'capture', 'connect', 'life_death'].indexOf(mode) === -1) mode = 'atari';
    wbGoMode = mode;
    if (window.Edu.Workbench && window.Edu.Workbench.showSubjectSection) window.Edu.Workbench.showSubjectSection('go');
    var body = document.getElementById('wb-go-body');
    if (body) {
      setGoTab(mode);
      renderGoMode(body, mode);
    } else {
      // 兜底: 模板缺失 #wb-go 时动态注入工作台骨架(旧页面兼容), 不覆盖工作台其余栏目
      var sec = document.getElementById('eduWorkbench');
      if (sec && !document.getElementById('wb-go')) {
        var d = document.createElement('div');
        d.innerHTML = goSectionHtml();
        var goSec = d.firstElementChild;
        if (goSec) {
          sec.appendChild(goSec);
          goSec.style.display = '';
          renderGoMode(document.getElementById('wb-go-body'), mode);
        }
      }
    }
    Store.saveWb();
  };

  window.Edu.GoWorkbench = {
    wbGoMode: wbGoMode,
    renderGoWorkbench: renderGoWorkbench,
    wbGo: wbGo,
    GO_QUIZ_DATA: GO_QUIZ_DATA,
    boardSvg: boardSvg,
    boardSvgTap: boardSvgTap,
    parseGoCoord: parseGoCoord
  };
})();