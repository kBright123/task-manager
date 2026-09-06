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
  var GO_QUIZ_DATA = {
    atari: [
      { id: 'atari_1', prompt: '黑棋下一手能吃掉白棋吗？', board: '9', moves: ['D4','D5','E4','E5','C4','C5','D3'], answer: 'D6', options: ['D6','C6','E6','F4'], type: 'atari', explain: '白棋在 D5 只有 1 气(D6)，黑棋落子 D6 提吃白棋' },
      { id: 'atari_2', prompt: '请找出白棋的唯一口气', board: '9', moves: ['D4','E4','E3','F3','D3','F4'], answer: 'E2', options: ['E2','D2','F2','E1'], type: 'atari', explain: '白棋三子连在一起，只剩 E2 一口气' },
      { id: 'atari_3', prompt: '黑棋如何吃掉角上的白棋？', board: '9', moves: ['A1','A2','B1','B2','A3'], answer: 'A4', options: ['A4','B3','C1','B4'], type: 'atari', explain: '白棋在角上只有 A4 一口气，黑棋落子 A4 提吃' },
      { id: 'atari_4', prompt: '白棋被围住了，黑棋下哪里提子？', board: '9', moves: ['E5','D5','E4','D4','F5','F4','E6','D6','E3'], answer: 'F6', options: ['F6','D3','G5','F3'], type: 'atari', explain: '白棋大龙只剩 F6 一口气' },
      { id: 'atari_5', prompt: '找出能让白棋只有 1 气的落子点', board: '9', moves: ['C3','C4','D3','D4','B3','E3'], answer: 'C2', options: ['C2','B4','D2','C5'], type: 'atari', explain: '黑棋落子 C2，白棋只剩 C5 一口气' }
    ],
    liberty: [
      { id: 'lib_1', prompt: '黑棋如何增加这组棋的气？', board: '9', moves: ['D4','E4','D5','E5','C4'], answer: 'C5', options: ['C5','D3','E3','F4'], type: 'liberty', explain: '黑棋落子 C5 连接 C4，增加气数' },
      { id: 'lib_2', prompt: '白棋要逃命，应该往哪个方向跑？', board: '9', moves: ['D4','D5','E5','E4','F4'], answer: 'E3', options: ['E3','D3','F3','E2'], type: 'liberty', explain: '白棋向 E3 方向跑能增加气' },
      { id: 'lib_3', prompt: '这组黑棋现在有几口气？', board: '9', moves: ['C3','C4','D3','D4'], answer: '8', options: ['6','7','8','9'], type: 'liberty', explain: '两子连接共有 8 口气' },
      { id: 'lib_4', prompt: '白棋被包围，还剩几口气？', board: '9', moves: ['E4','D4','E5','D5','E3','D3','F4'], answer: '2', options: ['1','2','3','4'], type: 'liberty', explain: '白棋只剩 E2 和 F3 两口气' },
      { id: 'lib_5', prompt: '黑棋下哪里能让自己的棋最多气？', board: '9', moves: ['D4','E4'], answer: 'D5', options: ['D5','C4','E3','F4'], type: 'liberty', explain: 'D5 能连接形成更大的气' }
    ],
    capture: [
      { id: 'cap_1', prompt: '黑棋打吃白棋一子', board: '9', moves: ['D4','D5','E4','E5','C4'], answer: 'C5', options: ['C5','D3','F5','C6'], type: 'capture', explain: '黑棋 C5 打吃白棋 D5' },
      { id: 'cap_2', prompt: '找出提吃白棋两子的落子点', board: '9', moves: ['D4','E4','D5','E5','C4','F4'], answer: 'C5', options: ['C5','D3','F3','C3'], type: 'capture', explain: '黑棋 C5 提吃白棋 D5、E5 两子' },
      { id: 'cap_3', prompt: '黑棋如何吃掉白棋三子？', board: '9', moves: ['C3','C4','D3','D4','B3','E3'], answer: 'C2', options: ['C2','B4','D2','C5'], type: 'capture', explain: '黑棋 C2 提吃白棋三子' },
      { id: 'cap_4', prompt: '这是打劫吗？黑棋能直接提吃吗？', board: '9', moves: ['D4','E4','D5','E5','C4','F4','C5','D3','E3','F3','C3'], answer: '是打劫', options: ['是打劫','能直接提吃','需要找劫材','以上都错'], type: 'capture', explain: '这是典型的打劫形状，黑棋不能直接提吃' },
      { id: 'cap_5', prompt: '角部打吃：黑棋怎么吃白棋？', board: '9', moves: ['A2','B2','A3','B3','A1'], answer: 'A4', options: ['A4','B1','C1','B4'], type: 'capture', explain: '黑棋 A4 打吃角部白棋' }
    ],
    connect: [
      { id: 'conn_1', prompt: '黑棋如何连接两组分离的棋？', board: '9', moves: ['C3','E3'], answer: 'D3', options: ['D3','C4','E4','D2'], type: 'connect', explain: 'D3 连接左右两子' },
      { id: 'conn_2', prompt: '白棋想分断黑棋，下哪里？', board: '9', moves: ['D4','D5','E4'], answer: 'E5', options: ['E5','C4','F4','D3'], type: 'connect', explain: '白棋 E5 分断黑棋上下连接' },
      { id: 'conn_3', prompt: '判断：黑棋这两组棋已经连接了吗？', board: '9', moves: ['C3','C4','D3','D4','E3','E4'], answer: '已连接', options: ['已连接','未连接','有一口气相连','需要再下一子'], type: 'connect', explain: '黑棋六子已形成坚固连接' },
      { id: 'conn_4', prompt: '黑棋下哪里既能连接又能攻击白棋？', board: '9', moves: ['D4','D5','E4','F4'], answer: 'E5', options: ['E5','C4','D3','F5'], type: 'connect', explain: 'E5 连接上下同时攻击白棋 D5' },
      { id: 'conn_5', prompt: '飞二连接：黑棋下哪里？', board: '9', moves: ['C3','F3'], answer: 'D3', options: ['D3','E3','C4','D4'], type: 'connect', explain: 'D3 是标准的飞二连接点' }
    ],
    life_death: [
      { id: 'ld_1', prompt: '这组黑棋是活棋吗？', board: '9', moves: ['C3','C4','D3','D4','C2','D2','B3','E3','C5','D5','B4'], answer: '活棋(二眼)', options: ['活棋(二眼)','死棋','只有假眼','打劫活'], type: 'life_death', explain: '黑棋在 C3 和 C5 形成两个真眼，绝对活棋' },
      { id: 'ld_2', prompt: '白棋如何杀死这组黑棋？', board: '9', moves: ['C3','C4','D3','D4','C2','D2','B3','E3','C5'], answer: '白棋下 D5', options: ['白棋下 D5','白棋下 B4','白棋下 C1','白棋下 E4'], type: 'life_death', explain: '白棋 D5 打入破坏第二只眼，黑棋死棋' },
      { id: 'ld_3', prompt: '角部弯四：黑棋先手能活吗？', board: '9', moves: ['A2','B2','A3','B3','A1','C1','A4'], answer: '先手活，后手死', options: ['先手活，后手死','绝对活','绝对死','打劫活'], type: 'life_death', explain: '弯四黑棋先手 A5 活，后手白棋 A5 杀死' },
      { id: 'ld_4', prompt: '这形状是真眼还是假眼？', board: '9', moves: ['C3','C4','D3','D4','C2','D2','B3','E3','B4'], answer: '真眼', options: ['真眼','假眼','共活','打劫眼'], type: 'life_death', explain: '黑棋 C3、C5 都是真眼，周围黑棋紧固' },
      { id: 'ld_5', prompt: '白棋怎么做假眼骗黑棋？', board: '9', moves: ['C3','C4','D3','D4','C2','D2','B3','E3'], answer: '白棋下 B4 做假眼', options: ['白棋下 B4 做假眼','白棋下 C5','白棋下 D5','白棋下 E4'], type: 'life_death', explain: 'B4 看似是眼，实则白棋可打入做假眼' }
    ],
    ko: [
      { id: 'ko_1', prompt: '这是什么形状？', board: '9', moves: ['D4','E4','D5','E5','C4','F4','C5','D3','E3','F3','C3'], answer: '打劫', options: ['打劫','双活','花六','角部弯四'], type: 'ko', explain: '标准的单劫形状' },
      { id: 'ko_2', prompt: '黑棋打劫后，白棋能马上回提吗？', board: '9', moves: ['D4','E4','D5','E5','C4','F4','C5','D3','E3','F3','C3','D6'], answer: '不能，打劫规则禁止', options: ['不能，打劫规则禁止','能，直接回提','要等两手','以上都错'], type: 'ko', explain: '打劫规则：打劫后对手不能马上回提，必须先找劫材' },
      { id: 'ko_3', prompt: '什么是劫材？', board: '9', moves: [], answer: '别处威胁对手大于劫价值的棋', options: ['别处威胁对手大于劫价值的棋','劫附近的棋','随便下一手棋','吃掉对手一子'], type: 'ko', explain: '劫材是指在别处下子，威胁对手的利益大于劫本身的价值' },
      { id: 'ko_4', prompt: '双打劫：这是活棋还是死棋？', board: '9', moves: [], answer: '活棋(双打劫无限循环)', options: ['活棋(双打劫无限循环)','死棋','打劫活','花六'], type: 'ko', explain: '双打劫双方都不愿先填，形成无限循环，判定为活棋' },
      { id: 'ko_5', prompt: '劫争最终结果取决于什么？', board: '9', moves: [], answer: '双方劫材大小比较', options: ['双方劫材大小比较','谁先下的','棋盘大小','运气'], type: 'ko', explain: '劫争胜负取决于双方劫材的总价值比较' }
    ],
    semeai: [
      { id: 'sem_1', prompt: '共活：双方都只有这一组棋，结果如何？', board: '9', moves: ['D4','D5','E4','E5','C4','F4','C5','D3','E3','F3','C3','D2','E2'], answer: '共活(双活)', options: ['共活(双活)','黑活白死','白活黑死','打劫'], type: 'semeai', explain: '双方都只有单眼，互相不敢先下，形成共活' },
      { id: 'sem_2', prompt: '黑棋有二眼，白棋只有单眼，谁赢？', board: '9', moves: [], answer: '黑棋赢(白棋死)', options: ['黑棋赢(白棋死)','白棋赢','共活','打劫'], type: 'semeai', explain: '有眼者胜，黑棋二眼绝对活，白棋单眼必死' },
      { id: 'sem_3', prompt: '外气相同，内气黑棋多 1 目，谁赢？', board: '9', moves: [], answer: '黑棋赢', options: ['黑棋赢','白棋赢','共活','看谁先手'], type: 'semeai', explain: '共活公式：外气相同时，内气多者胜' },
      { id: 'sem_4', prompt: '这是共活还是单方活？', board: '9', moves: ['D4','E4','D5','E5','C4','F4'], answer: '共活', options: ['共活','黑活','白活','打劫'], type: 'semeai', explain: '双方都只有单眼且外气相同，形成共活' },
      { id: 'sem_5', prompt: '共活时，这块区域归谁算地？', board: '9', moves: [], answer: '都不算地(或平分)', options: ['都不算地(或平分)','归黑棋','归白棋','按棋子数算'], type: 'semeai', explain: '共活区域通常不计地，或按规则平分' }
    ],
    opening: [
      { id: 'open_1', prompt: '星位小目最常见的拆二方式是？', board: '9', moves: ['D4'], answer: '低拆/高拆/飞拆', options: ['低拆/高拆/飞拆','尖顶','二间高拆','大飞'], type: 'opening', explain: '星位小目标准拆法：低拆 D6、高拆 D5、飞拆 E6' },
      { id: 'open_2', prompt: '小目低拆后，黑棋常见应对是？', board: '9', moves: ['D4','D6'], answer: '托/扳/飞压', options: ['托/扳/飞压','尖顶','跳','长'], type: 'opening', explain: '小目低拆后黑棋常托 C6、扳 C5、飞压 E5' },
      { id: 'open_3', prompt: '星位无忧角：黑棋怎么下？', board: '9', moves: ['D4'], answer: '小目', options: ['小目','高目','三三','天元'], type: 'opening', explain: '星位标准开局是小目 D4(D16/Q4/Q16)' },
      { id: 'open_4', prompt: '三三入角：白棋意图是什么？', board: '9', moves: ['D4'], answer: '实地/活棋', options: ['实地/活棋','外势','打劫','以上都错'], type: 'opening', explain: '三三入角追求角部实地和活棋，给对手外势' },
      { id: 'open_5', prompt: '中国流布局的特点是？', board: '9', moves: ['D4','Q4','D16','Q16'], answer: '厚实外势/模样大', options: ['厚实外势/模样大','实地多','只下角部','以上都错'], type: 'opening', explain: '中国流追求厚势和大模样，常见于星位小目配合' }
    ],
    endgame: [
      { id: 'end_1', prompt: '官子阶段：先手 10 目 vs 逆手 15 目，先下哪里？', board: '9', moves: [], answer: '先手 10 目', options: ['先手 10 目','逆手 15 目','都一样','看心情'], type: 'endgame', explain: '先手价值 = 10 × 2 = 20，逆手价值 = 15，先手大' },
      { id: 'end_2', prompt: '双方都想先手的地方叫？', board: '9', moves: [], answer: '双方急所', options: ['双方急所','单方急所','消极手','平常手'], type: 'endgame', explain: '双方都想先手占据的地方叫双方急所，价值最大' },
      { id: 'end_3', prompt: '贴目规则下，黑棋赢棋需要多少目？', board: '9', moves: [], answer: '185 目(3.75 子)', options: ['185 目(3.75 子)','180 目','190 目','看规则'], type: 'endgame', explain: '中国规则 3.75 子贴目，黑棋需 185 目才算赢' },
      { id: 'end_4', prompt: '收官时，边角大于中腹吗？', board: '9', moves: [], answer: '边角大于中腹', options: ['边角大于中腹','中腹大于边角','一样大','不固定'], type: 'endgame', explain: '围棋谚语：金角银边草肚皮，官子也按此顺序' },
      { id: 'end_5', prompt: '什么是"慢一手"？', board: '9', moves: [], answer: '原本先手变成逆手', options: ['原本先手变成逆手','下棋速度慢','思考时间长','以上都错'], type: 'endgame', explain: '慢一手指原本是先手的地方，因对手先下变成逆手，损失双倍价值' }
    ],
    quiz: [
      { id: 'q_1', prompt: '围棋棋盘标准路数是？', board: '9', moves: [], answer: '19×19', options: ['19×19','13×13','9×9','15×15'], type: 'quiz', explain: '标准围棋棋盘为 19 路，共 361 个交叉点' },
      { id: 'q_2', prompt: '黑白棋子各多少颗？', board: '9', moves: [], answer: '180/181', options: ['180/181','150/150','200/200','100/100'], type: 'quiz', explain: '黑棋 181 颗，白棋 180 颗，黑棋先行多一子' },
      { id: 'q_3', prompt: '围棋胜负判断：中国规则数什么？', board: '9', moves: [], answer: '目数(棋子+围地)', options: ['目数(棋子+围地)','只数围地','只数棋子','数吃子数'], type: 'quiz', explain: '中国规则数目法：棋子数 + 围地数 = 总目数' },
      { id: 'q_4', prompt: '贴目制下黑棋让几目？', board: '9', moves: [], answer: '3.75 子(7.5 目)', options: ['3.75 子(7.5 目)','5.5 子','2.5 子','不让目'], type: 'quiz', explain: '中国规则贴目 3.75 子，即 7.5 目' },
      { id: 'q_5', prompt: '围棋段位从低到高：业余几级到几段？', board: '9', moves: [], answer: '业余 30 级 ~ 专业 9 段', options: ['业余 30 级 ~ 专业 9 段','业余 10 级 ~ 专业 5 段','业余 20 级 ~ 专业 7 段','没有段位制'], type: 'quiz', explain: '业余从 30 级(入门)到 1 级，再到业余 1-7 段，专业 1-9 段' }
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

  function buildGoQuiz(subj, type) {
    var data = GO_QUIZ_DATA[type] || GO_QUIZ_DATA.atari;
    var items = shuffleArray(data).slice(0, C.QUIZ_LEN || 10).map(function (q, i) {
      var opts = q.options.map(function (o, oi) { return { v: o, label: o }; });
      return {
        id: q.id,
        prompt: q.prompt,
        options: opts,
        correct: q.answer,
        note: q.explain,
        wtype: type,
        board: q.board,
        moves: q.moves
      };
    });
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
    var W = 300, L = 26, S = (W - L) / (n - 1);
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
      stones += '<circle cx="' + cx.toFixed(1) + '" cy="' + cy.toFixed(1) + '" r="' + r.toFixed(1) + '" fill="url(#gb' + (black ? 'k' : 'w') + ')" stroke="' + (black ? '#1f1a12' : '#d8d3c8') + '" stroke-width="1.5"/>';
      if (black) stones += '<circle cx="' + (cx - r * 0.28).toFixed(1) + '" cy="' + (cy - r * 0.28).toFixed(1) + '" r="' + (r * 0.28).toFixed(1) + '" fill="rgba(255,255,255,0.16)"/>';
      else stones += '<circle cx="' + (cx - r * 0.3).toFixed(1) + '" cy="' + (cy - r * 0.3).toFixed(1) + '" r="' + (r * 0.18).toFixed(1) + '" fill="rgba(255,255,255,0.55)"/>';
      last = { cx: cx, cy: cy, r: r };
    });
    var lastMark = last ? '<circle cx="' + last.cx.toFixed(1) + '" cy="' + last.cy.toFixed(1) + '" r="' + (last.r * 0.24).toFixed(1) + '" fill="#e74c3c"/>' : '';
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + W + ' ' + W + '" width="100%" height="auto" role="img" aria-label="围棋棋盘">' +
      '<defs>' +
      '<linearGradient id="gwood" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#f2c878"/><stop offset="100%" stop-color="#d9a254"/></linearGradient>' +
      '<radialGradient id="gbk" cx="38%" cy="32%" r="70%"><stop offset="0%" stop-color="#4a4a4a"/><stop offset="100%" stop-color="#0a0a0a"/></radialGradient>' +
      '<radialGradient id="gbw" cx="38%" cy="32%" r="70%"><stop offset="0%" stop-color="#ffffff"/><stop offset="100%" stop-color="#c8c4b8"/></radialGradient>' +
      '</defs>' +
      '<rect x="2" y="2" width="' + (W - 4) + '" height="' + (W - 4) + '" rx="14" fill="url(#gwood)"/>' +
      lines + stars + labels + stones + lastMark +
      '</svg>';
  }

  function renderGoWorkbench(body) {
    if (!body) return;
    body.innerHTML = goSectionHtml();
    renderGoMode(body.querySelector('#wb-go-body'), wbGoMode);
  }

  // 工作台骨架 HTML(与模板 #wb-go 结构一致)
  function goSectionHtml() {
    var modeTabs = [
      { id: 'atari', label: '基本气与吃子', emoji: '💨' },
      { id: 'liberty', label: '找气与逃跑', emoji: '🏃' },
      { id: 'capture', label: '打吃与提子', emoji: '🎯' },
      { id: 'connect', label: '连接与分断', emoji: '🔗' },
      { id: 'life_death', label: '死活与二眼', emoji: '👁️' },
      { id: 'ko', label: '打劫与劫材', emoji: '♻️' },
      { id: 'semeai', label: '共活与双活', emoji: '⚖️' },
      { id: 'opening', label: '布局与定式', emoji: '📐' },
      { id: 'endgame', label: '官子与收官', emoji: '🏁' },
      { id: 'quiz', label: '围棋知识', emoji: '🏆' }
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
    parseGoCoord: parseGoCoord
  };
})();