(function () {
  'use strict';
  var Store = window.Edu.Store;
  var Speech = window.Edu.Speech;
  var Kids = window.Edu.Kids;

  // 兑换区分区: 每个专区(e.g. 武器区/奥特曼区)互斥折叠, 选中的才展示
  var GIFT_SECTIONS = [
    { id: 'weapon', icon: '🗡️', title: '武器专区', intro: '武器宝库的收藏，喜欢就兑换，可重复收集!' },
    { id: 'hero', icon: '⚜️', title: '武将专区', intro: '三国、水浒、西游记的英雄豪杰名号，每位独一无二，只此一块牌匾!' },
    { id: 'ultra', icon: '🦸', title: '奥特曼专区', intro: '稀有的奥特曼英雄，每位只能兑换一次，独一无二!' }
  ];
  function sectionOf(id) { for (var i = 0; i < GIFT_SECTIONS.length; i++) if (GIFT_SECTIONS[i].id === id) return GIFT_SECTIONS[i]; return null; }

  // 礼物目录: sec 归属专区, unique 表示该礼物不可重复拥有(奥特曼)
  // voice: 详情自动朗读的名称/口播; slogan: 专属口号(朗读时附带)
  var GIFT_CATALOG = [
    // ===== 武器专区(可重复收集) =====
    { id: 'feidao', sec: 'weapon', emoji: '🗡️', name: '飞刀', price: 15, desc: '例无虚发的飞刀，又快又准！', voice: '飞刀' },
    { id: 'dao', sec: 'weapon', emoji: '🔪', name: '宝刀', price: 25, desc: '削铁如泥的宝刀，挥舞起来呼呼作响！', voice: '宝刀' },
    { id: 'dun', sec: 'weapon', emoji: '🛡️', name: '神盾', price: 30, desc: '坚固无比的神盾，守护你不受伤害！', voice: '神盾' },
    { id: 'gong', sec: 'weapon', emoji: '🏹', name: '长弓', price: 40, desc: '百步穿杨的长弓，射出一支神箭！', voice: '长弓' },
    { id: 'jian', sec: 'weapon', emoji: '⚔️', name: '宝剑', price: 40, desc: '寒光闪闪的宝剑，勇士的最爱！', voice: '宝剑' },
    { id: 'qiang', sec: 'weapon', emoji: '🔫', name: '亮枪', price: 45, desc: '一击必中的亮枪，火力十足！', voice: '亮枪' },
    { id: 'car', sec: 'weapon', emoji: '🏎️', name: '炫酷跑车', price: 50, desc: '风驰电掣的炫酷跑车，出发兜风吧！', voice: '炫酷跑车' },
    { id: 'cannon', sec: 'weapon', emoji: '💣', name: '大炮', price: 55, desc: '威力无穷的大炮，轰出一发炮火！', voice: '大炮' },
    { id: 'tank', sec: 'weapon', emoji: '💥', name: '坦克', price: 60, desc: '火力全开的坦克，铁甲护体所向披靡！', voice: '坦克' },
    { id: 'armor', sec: 'weapon', emoji: '🚗', name: '装甲战车', price: 65, desc: '铁甲护体的装甲战车，开进战场如履平地！', voice: '装甲战车' },
    { id: 'heli', sec: 'weapon', emoji: '🚁', name: '武装直升机', price: 75, desc: '展翅高飞的武装直升机，盘旋空中守护大地！', voice: '武装直升机' },
    { id: 'plane', sec: 'weapon', emoji: '✈️', name: '战斗机', price: 80, desc: '制霸天空的战斗机，呼啸着冲上云霄！', voice: '战斗机' },
    { id: 'ship', sec: 'weapon', emoji: '🚢', name: '航空母舰', price: 90, desc: '巡游四海的航空母舰，海上编队的指挥舰！', voice: '航空母舰' },
    { id: 'mech', sec: 'weapon', emoji: '🤖', name: '机甲英雄', price: 100, desc: '勇敢无畏的机甲英雄，拯救世界的超级卫士！', voice: '机甲英雄', slogan: '机甲英雄，出击！' },
    // ===== 奥特曼专区(独一无二, 不可重复) =====
    { id: 'diga', sec: 'ultra', unique: true, emoji: '🦸', name: '迪迦奥特曼', price: 180, desc: '光的继承者，把希望带给人类，化作光芒冲向未来！', voice: '迪迦奥特曼', slogan: '化作光，飞向未来！' },
    { id: 'zero', sec: 'ultra', unique: true, emoji: '🦸', name: '赛罗奥特曼', price: 170, desc: '正义的首席詹奈纳，武器大师，速度与力量并存的战士！', voice: '赛罗奥特曼', slogan: '拯救，不靠蛮力，靠这颗炽热的心！' },
    { id: 'zeta', sec: 'ultra', unique: true, emoji: '🦸', name: '泽塔奥特曼', price: 160, desc: '相信伙伴的年轻战士，把勇气化作光芒！', voice: '泽塔奥特曼', slogan: '奥特曼不是无所不能的，但它会拼尽全力！' },
    { id: 'triga', sec: 'ultra', unique: true, emoji: '🦸', name: '特利迦奥特曼', price: 160, desc: '三千年前的光之勇者，用笑容守护未来！', voice: '特利迦奥特曼', slogan: '笑容，就是力量！' },
    { id: 'taro', sec: 'ultra', unique: true, emoji: '🦸', name: '泰罗奥特曼', price: 150, desc: '勇猛的 V 字战士，拥有压倒性的力量！', voice: '泰罗奥特曼', slogan: '泰罗奥特曼，出击！' },
    { id: 'mebius', sec: 'ultra', unique: true, emoji: '🦸', name: '梦比优斯奥特曼', price: 130, desc: '年轻的守护者，相信大家的心连在一起的力量！', voice: '梦比优斯奥特曼', slogan: '我一直相信，爱能拯救宇宙！' },
    { id: 'dyna', sec: 'ultra', unique: true, emoji: '🦸', name: '戴拿奥特曼', price: 140, desc: '来自未来的战士，在无垠宇宙中自由飞翔！', voice: '戴拿奥特曼', slogan: '感受宇宙的力量吧！' },
    { id: 'gaia', sec: 'ultra', unique: true, emoji: '🦸', name: '盖亚奥特曼', price: 130, desc: '大地之子，与地球的意志同在，守护我们成长的大地！', voice: '盖亚奥特曼', slogan: '大地的力量，与我同在！' },
    { id: 'orb', sec: 'ultra', unique: true, emoji: '🦸', name: '欧布奥特曼', price: 150, desc: '融合了两个光之力量的全新勇者！', voice: '欧布奥特曼', slogan: '燃烧吧，圣光！' },
    { id: 'geed', sec: 'ultra', unique: true, emoji: '🦸', name: '捷德奥特曼', price: 140, desc: '背负命运的少年战士，守护自己的信念！', voice: '捷德奥特曼', slogan: '我只相信，我能守护的东西！' },
    // ===== 武将专区(独一无二, 名字篆刻 + 兵器动画) =====
    // book: 出处(三国/水浒/西游记); camp: 阵营; seal: 印章单字; epithet: 绰号; weapon: 兵器; anim: 动画风格
    { id: 'h_lvbu', sec: 'hero', unique: true, emoji: '🔱', name: '吕布', price: 220, book: '三国', camp: '群', seal: '武', epithet: '飞将', weapon: '🔱', weaponName: '方天画戟', anim: 'whirl', desc: '天下第一猛将，手持方天画戟，万军之中无人能挡！', voice: '吕布', slogan: '人中吕布，马中赤兔！' },
    { id: 'h_guan', sec: 'hero', unique: true, emoji: '⚔️', name: '关羽', price: 220, book: '三国', camp: '蜀', seal: '义', epithet: '武圣', weapon: '⚔️', weaponName: '青龙偃月刀', anim: 'slice', desc: '忠义千秋的武圣，大刀过处，敌军望风而逃。', voice: '关羽', slogan: '温酒斩华雄，青龙偃月刀！' },
    { id: 'h_zhaoyun', sec: 'hero', unique: true, emoji: '🗡️', name: '赵云', price: 200, book: '三国', camp: '蜀', seal: '勇', epithet: '常胜将军', weapon: '🗡️', weaponName: '龙胆亮银枪', anim: 'thrust', desc: '一身是胆的常山赵子龙，一杆亮银枪护主突围。', voice: '赵云', slogan: '长坂坡前，七进七出！' },
    { id: 'h_zhangfei', sec: 'hero', unique: true, emoji: '🔱', name: '张飞', price: 200, book: '三国', camp: '蜀', seal: '猛', epithet: '万人敌', weapon: '🔱', weaponName: '丈八蛇矛', anim: 'thrust', desc: '豹头环眼的猛张飞，丈八蛇矛横扫千军。', voice: '张飞', slogan: '当阳桥头，一声喝退百万兵！' },
    { id: 'h_caocao', sec: 'hero', unique: true, emoji: '⚔️', name: '曹操', price: 200, book: '三国', camp: '魏', seal: '枭', epithet: '乱世枭雄', weapon: '⚔️', weaponName: '倚天剑', anim: 'glow', desc: '挟天子以令诸侯的一代枭雄，倚天剑锋芒毕露。', voice: '曹操', slogan: '宁教我负天下人！' },
    { id: 'h_zhugeliang', sec: 'hero', unique: true, emoji: '🎐', name: '诸葛亮', price: 200, book: '三国', camp: '蜀', seal: '谋', epithet: '卧龙', weapon: '🎐', weaponName: '白羽扇', anim: 'glow', desc: '神机妙算的卧龙，轻摇羽扇，运筹帷幄千里之外。', voice: '诸葛亮', slogan: '鞠躬尽瘁，死而后已！' },
    { id: 'h_liubei', sec: 'hero', unique: true, emoji: '⚔️', name: '刘备', price: 190, book: '三国', camp: '蜀', seal: '仁', epithet: '仁德之君', weapon: '⚔️', weaponName: '雌雄双股剑', anim: 'slice', desc: '仁义为本的汉昭烈帝，雌雄双股剑护佑苍生。', voice: '刘备', slogan: '勿以善小而不为！' },
    { id: 'h_machao', sec: 'hero', unique: true, emoji: '🗡️', name: '马超', price: 180, book: '三国', camp: '蜀', seal: '威', epithet: '锦马超', weapon: '🗡️', weaponName: '虎头湛金枪', anim: 'thrust', desc: '英姿飒爽的锦马超，西凉铁骑杀得曹操割须弃袍。', voice: '马超', slogan: '锦马超，杀得曹操割须弃袍！' },
    { id: 'h_huangzhong', sec: 'hero', unique: true, emoji: '🏹', name: '黄忠', price: 180, book: '三国', camp: '蜀', seal: '弓', epithet: '老当益壮', weapon: '🏹', weaponName: '宝雕弓', anim: 'arc', desc: '老当益壮的神箭手，定军山一战立下奇功。', voice: '黄忠', slogan: '百步穿杨，箭无虚发！' },
    { id: 'h_dianwei', sec: 'hero', unique: true, emoji: '🔱', name: '典韦', price: 160, book: '三国', camp: '魏', seal: '烈', epithet: '古之恶来', weapon: '🔱', weaponName: '双铁戟', anim: 'whirl', desc: '曹操麾下第一猛士，双铁戟护主，威震八方。', voice: '典韦', slogan: '双戟在手，以一敌百！' },
    { id: 'h_wusong', sec: 'hero', unique: true, emoji: '🏏', name: '武松', price: 200, book: '水浒', camp: '梁山', seal: '虎', epithet: '行者', weapon: '🏏', weaponName: '哨棒', anim: 'swing', desc: '醉打猛虎的行者武松，哨棒挥舞鬼神惊。', voice: '武松', slogan: '景阳冈上，打虎英雄！' },
    { id: 'h_linchong', sec: 'hero', unique: true, emoji: '🔱', name: '林冲', price: 200, book: '水浒', camp: '梁山', seal: '枪', epithet: '豹子头', weapon: '🔱', weaponName: '丈八蛇矛', anim: 'thrust', desc: '八十万禁军教头，枪法出神入化。', voice: '林冲', slogan: '豹子头风雪上梁山！' },
    { id: 'h_lujunyi', sec: 'hero', unique: true, emoji: '🗡️', name: '卢俊义', price: 200, book: '水浒', camp: '梁山', seal: '义', epithet: '玉麒麟', weapon: '🗡️', weaponName: '丈二钢枪', anim: 'thrust', desc: '富甲一方却义字当先，枪棒打遍天下无对手。', voice: '卢俊义', slogan: '枪棒天下无双！' },
    { id: 'h_luzhishen', sec: 'hero', unique: true, emoji: '🏏', name: '鲁智深', price: 180, book: '水浒', camp: '梁山', seal: '侠', epithet: '花和尚', weapon: '🏏', weaponName: '水磨禅杖', anim: 'whirl', desc: '力大无穷的花和尚，禅杖挥舞如天神下凡。', voice: '鲁智深', slogan: '拳打镇关西，倒拔垂杨柳！' },
    { id: 'h_huarong', sec: 'hero', unique: true, emoji: '🏹', name: '花荣', price: 180, book: '水浒', camp: '梁山', seal: '箭', epithet: '小李广', weapon: '🏹', weaponName: '神箭弯弓', anim: 'arc', desc: '开弓如满月，箭去似流星，百发百中。', voice: '花荣', slogan: '小李广箭如流星！' },
    { id: 'h_likui', sec: 'hero', unique: true, emoji: '🪓', name: '李逵', price: 170, book: '水浒', camp: '梁山', seal: '风', epithet: '黑旋风', weapon: '🪓', weaponName: '双板斧', anim: 'swing', desc: '性如烈火的黑旋风，一对板斧开路无敌。', voice: '李逵', slogan: '黑旋风斧劈两半！' },
    { id: 'h_yangzhi', sec: 'hero', unique: true, emoji: '🗡️', name: '杨志', price: 160, book: '水浒', camp: '梁山', seal: '刀', epithet: '青面兽', weapon: '🗡️', weaponName: '祖传朴刀', anim: 'slice', desc: '杨家将后人的青面兽，一口朴刀走江湖。', voice: '杨志', slogan: '青面兽一口宝刀走天下！' },
    { id: 'h_huyan', sec: 'hero', unique: true, emoji: '🔱', name: '呼延灼', price: 160, book: '水浒', camp: '梁山', seal: '鞭', epithet: '双鞭将', weapon: '🔱', weaponName: '雌雄双鞭', anim: 'whirl', desc: '朝廷名将之后，双鞭使开如雷贯日。', voice: '呼延灼', slogan: '连环马阵双鞭开道！' },
    { id: 'h_qinming', sec: 'hero', unique: true, emoji: '🔨', name: '秦明', price: 160, book: '水浒', camp: '梁山', seal: '雷', epithet: '霹雳火', weapon: '🔨', weaponName: '狼牙棒', anim: 'swing', desc: '性如烈火的霹雳火，一根狼牙棒打得敌将胆寒。', voice: '秦明', slogan: '霹雳火狼牙棒扫敌阵！' },
    { id: 'h_yanqing', sec: 'hero', unique: true, emoji: '🏹', name: '燕青', price: 150, book: '水浒', camp: '梁山', seal: '巧', epithet: '浪子', weapon: '🏹', weaponName: '川弩青箭', anim: 'arc', desc: '聪明机警的浪子燕青，百步穿杨还精通相扑。', voice: '燕青', slogan: '浪子燕青一弩定乾坤！' },
    // ===== 三国·群英补充 =====
    { id: 'h_zhangliao', sec: 'hero', unique: true, emoji: '⚔️', name: '张辽', price: 190, book: '三国', camp: '魏', seal: '威', epithet: '五子良将', weapon: '⚔️', weaponName: '钩镰大刀', anim: 'slice', desc: '威震逍遥津的五子良将，八百破十万，令江东小儿不敢夜啼。', voice: '张辽', slogan: '逍遥津前，威震江东！' },
    { id: 'h_xuchu', sec: 'hero', unique: true, emoji: '🔨', name: '许褚', price: 160, book: '三国', camp: '魏', seal: '勇', epithet: '虎痴', weapon: '🔨', weaponName: '镔铁大刀', anim: 'swing', desc: '力大无穷的虎痴，赤膊上阵也敢斗马超。', voice: '许褚', slogan: '虎痴发威，千军辟易！' },
    { id: 'h_zhouyu', sec: 'hero', unique: true, emoji: '🎐', name: '周瑜', price: 190, book: '三国', camp: '吴', seal: '雅', epithet: '美周郎', weapon: '🎐', weaponName: '琴剑', anim: 'glow', desc: '雄姿英发的东吴大都督，一曲赤壁火，烧退百万兵。', voice: '周瑜', slogan: '谈笑间，樯橹灰飞烟灭！' },
    { id: 'h_simayi', sec: 'hero', unique: true, emoji: '🪶', name: '司马懿', price: 190, book: '三国', camp: '魏', seal: '忍', epithet: '冢虎', weapon: '🪶', weaponName: '羽扇纶巾', anim: 'glow', desc: '深藏不露的冢虎，隐忍十年，终成三晋之业。', voice: '司马懿', slogan: '宁可我负人，不可人负我！' },
    { id: 'h_huanggai', sec: 'hero', unique: true, emoji: '🏹', name: '黄盖', price: 160, book: '三国', camp: '吴', seal: '忠', epithet: '铁鞭黄盖', weapon: '🏹', weaponName: '铁皮舟', anim: 'arc', desc: '甘受皮肉苦肉计，一船火攻烧翻曹营。', voice: '黄盖', slogan: '周瑜打黄盖，一个愿打一个愿挨！' },
    // ===== 水浒·天罡补充 =====
    { id: 'h_songjiang', sec: 'hero', unique: true, emoji: '🌂', name: '宋江', price: 200, book: '水浒', camp: '梁山', seal: '义', epithet: '及时雨', weapon: '🌂', weaponName: '帅旗', anim: 'whirl', desc: '仗义疏财的及时雨，替天行道的梁山之主。', voice: '宋江', slogan: '梁山聚义，替天行道！' },
    { id: 'h_wuyong', sec: 'hero', unique: true, emoji: '🪶', name: '吴用', price: 190, book: '水浒', camp: '梁山', seal: '智', epithet: '智多星', weapon: '🪶', weaponName: '鹅毛扇', anim: 'glow', desc: '足智多谋的智多星，妙计安天下，绝不输古人。', voice: '吴用', slogan: '运筹帷幄，决胜千里！' },
    { id: 'h_shijin', sec: 'hero', unique: true, emoji: '🐉', name: '史进', price: 170, book: '水浒', camp: '梁山', seal: '纹', epithet: '九纹龙', weapon: '🗡️', weaponName: '朴刀', anim: 'slice', desc: '身上九条青龙纹身，少年英雄一条枪挑遍天下。', voice: '史进', slogan: '九纹龙出山，威风凛凛！' },
    { id: 'h_daizong', sec: 'hero', unique: true, emoji: '🦶', name: '戴宗', price: 160, book: '水浒', camp: '梁山', seal: '行', epithet: '神行太保', weapon: '🦶', weaponName: '神行符', anim: 'thrust', desc: '腿上绑着神行甲马，日行八百里的神行太保。', voice: '戴宗', slogan: '神行千里，日行八百！' },
    { id: 'h_gongsun', sec: 'hero', unique: true, emoji: '🔮', name: '公孙胜', price: 170, book: '水浒', camp: '梁山', seal: '道', epithet: '入云龙', weapon: '🔮', weaponName: '松文古定剑', anim: 'glow', desc: '道法高深的入云龙，呼风唤雨，撒豆成兵。', voice: '公孙胜', slogan: '入云龙作法，风雷齐动！' },
    // ===== 西游记·取经天团 =====
    { id: 'h_sunwukong', sec: 'hero', unique: true, emoji: '🐵', name: '孙悟空', price: 220, book: '西游记', camp: '取经', seal: '空', epithet: '齐天大圣', weapon: '🥢', weaponName: '如意金箍棒', anim: 'whirl', desc: '大闹天宫的齐天大圣，火眼金睛，一个筋斗十万八千里。', voice: '孙悟空', slogan: '俺老孙来也！妖怪哪里跑！' },
    { id: 'h_zhubajie', sec: 'hero', unique: true, emoji: '🐷', name: '猪八戒', price: 190, book: '西游记', camp: '取经', seal: '戒', epithet: '天蓬元帅', weapon: '🌾', weaponName: '九齿钉耙', anim: 'swing', desc: '原是天蓬元帅下凡的猪八戒，九齿钉耙能以一当十。', voice: '猪八戒', slogan: '俺老猪来也！' },
    { id: 'h_shaseng', sec: 'hero', unique: true, emoji: '👹', name: '沙悟净', price: 180, book: '西游记', camp: '取经', seal: '净', epithet: '卷帘大将', weapon: '🏏', weaponName: '降妖宝杖', anim: 'thrust', desc: '忠厚老实的卷帘大将，肩挑行囊，一路护师取经。', voice: '沙悟净', slogan: '师兄，我来帮你！' },
    { id: 'h_tangseng', sec: 'hero', unique: true, emoji: '🙏', name: '唐僧', price: 190, book: '西游记', camp: '取经', seal: '佛', epithet: '三藏法师', weapon: '🪄', weaponName: '九环锡杖', anim: 'glow', desc: '心怀慈悲的三藏法师，历九九八十一难，西天取回真经。', voice: '唐僧', slogan: '贫僧自东土大唐而来！' },
    { id: 'h_erlang', sec: 'hero', unique: true, emoji: '👁️', name: '二郎神', price: 190, book: '西游记', camp: '天庭', seal: '神', epithet: '显圣真君', weapon: '🗡️', weaponName: '三尖两刃刀', anim: 'slice', desc: '灌江口二郎真君，天眼一开，降妖伏魔手到擒来。', voice: '二郎神', slogan: '三尖两刃刀出鞘！' },
    { id: 'h_nezha', sec: 'hero', unique: true, emoji: '🔥', name: '哪吒', price: 180, book: '西游记', camp: '天庭', seal: '焰', epithet: '三太子', weapon: '🔥', weaponName: '火尖枪', anim: 'whirl', desc: '脚踩风火轮的哪吒三太子，乾坤圈出手百发百中。', voice: '哪吒', slogan: '乾坤圈，去！' },
    { id: 'h_niumowang', sec: 'hero', unique: true, emoji: '🐮', name: '牛魔王', price: 190, book: '西游记', camp: '妖魔', seal: '霸', epithet: '平天大圣', weapon: '🐮', weaponName: '混铁棍', anim: 'swing', desc: '力大无穷的平天大圣，与孙悟空大战三百回合不分胜负。', voice: '牛魔王', slogan: '俺老牛谁也不怕！' },
    { id: 'h_honghai', sec: 'hero', unique: true, emoji: '🔥', name: '红孩儿', price: 170, book: '西游记', camp: '妖魔', seal: '圣', epithet: '圣婴大王', weapon: '🔥', weaponName: '三昧真火', anim: 'glow', desc: '善使三昧真火的圣婴大王，一口火喷得大圣都逃。', voice: '红孩儿', slogan: '看我的三昧真火！' },
    // ===== 三国·群英扩充 =====
    { id: 'h_jiangwei', sec: 'hero', unique: true, emoji: '🦅', name: '姜维', price: 180, book: '三国', camp: '蜀', seal: '忠', epithet: '天水麒麟儿', weapon: '🗡️', weaponName: '麒麟铁枪', anim: 'thrust', desc: '诸葛亮传人，九伐中原，忠义日月可鉴。', voice: '姜维', slogan: '继丞相之志，兴复汉室！' },
    { id: 'h_dengai', sec: 'hero', unique: true, emoji: '⛰️', name: '邓艾', price: 170, book: '三国', camp: '魏', seal: '奇', epithet: '阴平奇袭', weapon: '🗡️', weaponName: '九环刀', anim: 'slice', desc: '偷渡阴平的奇将，一曲灭蜀，名震天下。', voice: '邓艾', slogan: '奇兵出阴平，蜀汉归晋！' },
    { id: 'h_luxun', sec: 'hero', unique: true, emoji: '🎐', name: '陆逊', price: 185, book: '三国', camp: '吴', seal: '儒', epithet: '书生都督', weapon: '🎐', weaponName: '朱雀羽扇', anim: 'glow', desc: '火烧连营八百里，一把火定三国之势。', voice: '陆逊', slogan: '书生亦可定天下！' },
    { id: 'h_lvmeng', sec: 'hero', unique: true, emoji: '🛶', name: '吕蒙', price: 180, book: '三国', camp: '吴', seal: '智', epithet: '白衣渡江', weapon: '🗡️', weaponName: '吴钩', anim: 'slice', desc: '士别三日刮目相看，白衣渡江智取荆州。', voice: '吕蒙', slogan: '士别三日，刮目相看！' },
    { id: 'h_ganning', sec: 'hero', unique: true, emoji: '🏴‍☠️', name: '甘宁', price: 160, book: '三国', camp: '吴', seal: '勇', epithet: '锦帆贼', weapon: '🔱', weaponName: '铁链流星', anim: 'whirl', desc: '百骑劫曹营的锦帆贼，江东第一猛将。', voice: '甘宁', slogan: '百骑夜袭，威震曹营！' },
    { id: 'h_taishici', sec: 'hero', unique: true, emoji: '🏹', name: '太史慈', price: 175, book: '三国', camp: '吴', seal: '信', epithet: '北海一箭', weapon: '🏹', weaponName: '画戟双弓', anim: 'arc', desc: '单骑救主的神射手，守信重诺的义士。', voice: '太史慈', slogan: '人生在世，当带三尺剑立不世之功！' },
    { id: 'h_sunce', sec: 'hero', unique: true, emoji: '🏇', name: '孙策', price: 190, book: '三国', camp: '吴', seal: '霸', epithet: '小霸王', weapon: '🗡️', weaponName: '霸王枪', anim: 'thrust', desc: '虎踞江东的江东猛虎，小霸王之名天下闻。', voice: '孙策', slogan: '江东子弟，何惧于天下！' },
    { id: 'h_zhanghe', sec: 'hero', unique: true, emoji: '🎯', name: '张郃', price: 170, book: '三国', camp: '魏', seal: '巧', epithet: '巧变将军', weapon: '🔱', weaponName: '玄铁矛', anim: 'thrust', desc: '临阵巧变的天才战将，街亭一战名动天下。', voice: '张郃', slogan: '用兵之道，在于巧变！' },
    { id: 'h_weiyan', sec: 'hero', unique: true, emoji: '🗡️', name: '魏延', price: 165, book: '三国', camp: '蜀', seal: '猛', epithet: '汉中太守', weapon: '🗡️', weaponName: '断魂大刀', anim: 'slice', desc: '智勇双全的汉中太守，子午谷奇谋未竟。', voice: '魏延', slogan: '谁敢拦我！' },
    { id: 'h_xiahoudun', sec: 'hero', unique: true, emoji: '👁️', name: '夏侯惇', price: 175, book: '三国', camp: '魏', seal: '刚', epithet: '独眼将军', weapon: '🔱', weaponName: '断蛟枪', anim: 'thrust', desc: '拔矢啖睛的刚烈猛将，曹操麾下一等忠臣。', voice: '夏侯惇', slogan: '父精母血，不可弃也！' },
    // ===== 水浒·天罡地煞扩充 =====
    { id: 'h_chaogai', sec: 'hero', unique: true, emoji: '🏹', name: '晁盖', price: 200, book: '水浒', camp: '梁山', seal: '义', epithet: '托塔天王', weapon: '🏹', weaponName: '七星宝刀', anim: 'slice', desc: '智取生辰纲的七星聚义之首，梁山的奠基人。', voice: '晁盖', slogan: '大丈夫行事，当光明磊落！' },
    { id: 'h_guansheng', sec: 'hero', unique: true, emoji: '⚔️', name: '关胜', price: 190, book: '水浒', camp: '梁山', seal: '义', epithet: '大刀', weapon: '⚔️', weaponName: '青龙偃月刀', anim: 'slice', desc: '关羽后裔，五虎上将之首，威震京师的名将。', voice: '关胜', slogan: '义字当头，刀下不斩无辜！' },
    { id: 'h_chaijin', sec: 'hero', unique: true, emoji: '🔥', name: '柴进', price: 175, book: '水浒', camp: '梁山', seal: '疏', epithet: '小旋风', weapon: '🗡️', weaponName: '龙泉宝剑', anim: 'slice', desc: '周世宗后人，仗义疏财的柴大官人。', voice: '柴进', slogan: '有钱能使鬼推磨！' },
    { id: 'h_liying', sec: 'hero', unique: true, emoji: '🦅', name: '李应', price: 170, book: '水浒', camp: '梁山', seal: '豪', epithet: '扑天雕', weapon: '🗡️', weaponName: '铁脊枪', anim: 'thrust', desc: '独龙岗的财主，一杆铁枪打遍四方。', voice: '李应', slogan: '一飞冲天，谁敢小觑！' },
    { id: 'h_zhutong', sec: 'hero', unique: true, emoji: '🧔', name: '朱仝', price: 175, book: '水浒', camp: '梁山', seal: '义', epithet: '美髯公', weapon: '🗡️', weaponName: '朴刀', anim: 'slice', desc: '重情重义的郓城县都头，三兄弟义薄云天。', voice: '朱仝', slogan: '兄弟有难，两肋插刀！' },
    { id: 'h_leihong', sec: 'hero', unique: true, emoji: '🐯', name: '雷横', price: 170, book: '水浒', camp: '梁山', seal: '威', epithet: '插翅虎', weapon: '🔨', weaponName: '朴刀', anim: 'swing', desc: '膂力过人的好汉，跳涧过渠如履平地。', voice: '雷横', slogan: '力大无穷，赛过猛虎！' },
    { id: 'h_liutang', sec: 'hero', unique: true, emoji: '👹', name: '刘唐', price: 165, book: '水浒', camp: '梁山', seal: '赤', epithet: '赤发鬼', weapon: '🗡️', weaponName: '朴刀', anim: 'slice', desc: '紫黑阔脸的赤发鬼，随七星聚义上梁山。', voice: '刘唐', slogan: '赤发鬼报仇，誓不罢休！' },
    { id: 'h_lijun', sec: 'hero', unique: true, emoji: '🌊', name: '李俊', price: 175, book: '水浒', camp: '梁山', seal: '水', epithet: '混江龙', weapon: '🌊', weaponName: '铁桨', anim: 'thrust', desc: '水军统帅中的龙头，翻江倒海无人能敌。', voice: '李俊', slogan: '混江龙入海，风浪再大也不怕！' },
    { id: 'h_ruanxiaosan', sec: 'hero', unique: true, emoji: '🎣', name: '阮小二', price: 160, book: '水浒', camp: '梁山', seal: '豪', epithet: '立地太岁', weapon: '🎣', weaponName: '铁枪', anim: 'thrust', desc: '阮氏三雄之首，水性天下无双的渔家好汉。', voice: '阮小二', slogan: '三阮聚义，水战无敌！' },
    { id: 'h_ruanxiaowu', sec: 'hero', unique: true, emoji: '🎣', name: '阮小五', price: 160, book: '水浒', camp: '梁山', seal: '勇', epithet: '短命二郎', weapon: '🎣', weaponName: '铁板叉', anim: 'swing', desc: '阮氏三雄之一，水里的好汉岸上的英雄。', voice: '阮小五', slogan: '在水我是龙，上岸我是虎！' },
    { id: 'h_ruanxiaoqi', sec: 'hero', unique: true, emoji: '🎣', name: '阮小七', price: 165, book: '水浒', camp: '梁山', seal: '侠', epithet: '活阎罗', weapon: '🎣', weaponName: '熟铜叉', anim: 'thrust', desc: '阮氏三雄中最小的一个，胆大心细的活阎罗。', voice: '阮小七', slogan: '天王老子来了，我也不怕！' },
    { id: 'h_zhangheng', sec: 'hero', unique: true, emoji: '⛵', name: '张横', price: 160, book: '水浒', camp: '梁山', seal: '浪', epithet: '船火儿', weapon: '⛵', weaponName: '渔叉', anim: 'thrust', desc: '浔阳江上的船夫杀手，得名船火儿。', voice: '张横', slogan: '风浪再急，我也敢行船！' },
    { id: 'h_zhangshun', sec: 'hero', unique: true, emoji: '🌊', name: '张顺', price: 170, book: '水浒', camp: '梁山', seal: '捷', epithet: '浪里白条', weapon: '🏹', weaponName: '川弩', anim: 'arc', desc: '水性极佳的白条好汉，在水里无人能捉住他。', voice: '张顺', slogan: '浪里白条，来去如风！' },
    { id: 'h_yangxiong', sec: 'hero', unique: true, emoji: '🗡️', name: '杨雄', price: 165, book: '水浒', camp: '梁山', seal: '烈', epithet: '病关索', weapon: '🗡️', weaponName: '朴刀', anim: 'slice', desc: '剑眉星目的刽子手，杀人不见血的好汉。', voice: '杨雄', slogan: '犯我兄弟者，刀下不留情！' },
    { id: 'h_shixiu', sec: 'hero', unique: true, emoji: '💥', name: '石秀', price: 175, book: '水浒', camp: '梁山', seal: '烈', epithet: '拼命三郎', weapon: '🗡️', weaponName: '朴刀', anim: 'slice', desc: '胆大心细的拼命三郎，赤手夺刀救主。', voice: '石秀', slogan: '拼命三郎，怕字怎么写！' },
    { id: 'h_xiezhen', sec: 'hero', unique: true, emoji: '🐍', name: '解珍', price: 160, book: '水浒', camp: '梁山', seal: '猎', epithet: '两头蛇', weapon: '🔱', weaponName: '虎叉', anim: 'thrust', desc: '登州山上最有名的猎户，猎虎本领天下无双。', voice: '解珍', slogan: '管你是虎是豹，见了我都怕！' },
    { id: 'h_xiebao', sec: 'hero', unique: true, emoji: '🐙', name: '解宝', price: 160, book: '水浒', camp: '梁山', seal: '猎', epithet: '双尾蝎', weapon: '🔱', weaponName: '虎叉', anim: 'thrust', desc: '解珍的弟弟，两兄弟上山打虎，比虎还猛。', voice: '解宝', slogan: '兄弟同心，上山打虎！' },
    { id: 'h_shiqian', sec: 'hero', unique: true, emoji: '🐀', name: '时迁', price: 170, book: '水浒', camp: '梁山', seal: '捷', epithet: '鼓上蚤', weapon: '🗡️', weaponName: '夜行匕首', anim: 'whirl', desc: '轻功天下无双的神偷，飞檐走壁探囊取物。', voice: '时迁', slogan: '来无影去无踪，鼓上蚤时迁！' },
    { id: 'h_baisheng', sec: 'hero', unique: true, emoji: '🐭', name: '白胜', price: 150, book: '水浒', camp: '梁山', seal: '义', epithet: '白日鼠', weapon: '🏹', weaponName: '毒箭', anim: 'arc', desc: '智取生辰纲的英雄，白日鼠白胜。', voice: '白胜', slogan: '白日鼠一到，桶里全变酒！' },
    { id: 'h_bailongma', sec: 'hero', unique: true, emoji: '🐎', name: '小白龙', price: 190, book: '西游记', camp: '取经', seal: '龙', epithet: '白龙马', weapon: '🐎', weaponName: '龙爪', anim: 'thrust', desc: '西海龙王三太子，化作白龙马驮师西行。', voice: '小白龙', slogan: '一声龙吟，万里行云！' },
    { id: 'h_guanyin', sec: 'hero', unique: true, emoji: '🌺', name: '观音菩萨', price: 200, book: '西游记', camp: '天庭', seal: '慈', epithet: '南海观音', weapon: '🌺', weaponName: '杨柳净瓶', anim: 'glow', desc: '大慈大悲的南海观音，普度众生点化取经人。', voice: '观音菩萨', slogan: '慈悲为怀，普度众生！' },
    { id: 'h_laozi', sec: 'hero', unique: true, emoji: '☯️', name: '太白金星', price: 185, book: '西游记', camp: '天庭', seal: '和', epithet: '太白金星', weapon: '☯️', weaponName: '拂尘', anim: 'glow', desc: '天庭的老好人，招安悟空的和事佬。', voice: '太白金星', slogan: '和为贵，忍为高！' },
    { id: 'h_tieshan', sec: 'hero', unique: true, emoji: '🌬️', name: '铁扇公主', price: 180, book: '西游记', camp: '妖魔', seal: '扇', epithet: '铁扇公主', weapon: '🌬️', weaponName: '芭蕉扇', anim: 'whirl', desc: '牛魔王之妻，一把芭蕉扇能扇灭火焰山。', voice: '铁扇公主', slogan: '芭蕉扇一出，火焰山也灭！' },
    { id: 'h_baigujing', sec: 'hero', unique: true, emoji: '💀', name: '白骨精', price: 175, book: '西游记', camp: '妖魔', seal: '妖', epithet: '白骨夫人', weapon: '💀', weaponName: '白骨爪', anim: 'glow', desc: '三次变化骗唐僧的白骨夫人，诡计多端。', voice: '白骨精', slogan: '三变白骨，专骗唐僧！' }
  ];
  var DEFAULT_PRICES = {};
  GIFT_CATALOG.forEach(function (g) { DEFAULT_PRICES[g.id] = g.price; });

  function esc(s) { return String(s === undefined || s === null ? '' : s).replace(/</g, '&lt;').replace(/&/g, '&amp;'); }
  function imgOf(id) {
    var g = giftOf(id);
    return (g && g.sec === 'ultra') ? '/static/edu/ultra/' + id + '.svg' : '/static/edu/weapons/' + id + '.svg';
  }
  function isImageGift(id) { var g = giftOf(id); return !!g && g.sec !== 'hero'; }
  function giftIcon(id) {
    return isImageGift(id)
      ? '<img class="gift-emoji" src="' + imgOf(id) + '" alt="" draggable="false">'
      : '<div class="gift-emoji">' + ((giftOf(id) || {}).emoji || '🎁') + '</div>';
  }
  function giftOf(id) {
    for (var i = 0; i < GIFT_CATALOG.length; i++) if (GIFT_CATALOG[i].id === id) return GIFT_CATALOG[i];
    return null;
  }
  // 文学武将牌匾: 兵器在名字上方, 印章字体细节 + 动画体现人物风格
  function heroPlaqueHtml(g, big) {
    var b = big ? ' hero-p-lg' : '';
    var anim = (g.anim && /^[a-z]+$/.test(g.anim)) ? g.anim : 'glow';
    return '<div class="hero-plaque' + b + '">' +
      '<span class="hero-seal">' + esc(g.seal || '') + '</span>' +
      '<div class="hero-weapon"><span class="hw-emoji">' + (g.weapon || '⚔️') + '</span><span class="hw-name">' + esc(g.weaponName || '') + '</span></div>' +
      '<div class="hero-camp"><span class="hc-book">' + esc(g.book || '') + '</span> · <span class="hc-camp">' + esc(g.camp || '') + '</span> · <span class="hc-epithet">' + esc(g.epithet || '') + '</span></div>' +
      '<div class="hero-name">' + esc(g.name) + '</div>' +
      '</div>';
  }
  function heroAnimCls(g) {
    return 'hero-card anim-' + ((g.anim && /^[a-z]+$/.test(g.anim)) ? g.anim : 'glow');
  }
  // 补全缺失的礼物数据（旧宝贝可能没有 redeemed/wishes），价格一律使用默认定价
  function ensureGiftData() {
    Store.state.redeemed = (Store.state.redeemed && Array.isArray(Store.state.redeemed)) ? Store.state.redeemed : [];
    Store.state.wishes = (Store.state.wishes && typeof Store.state.wishes === 'object' && !Array.isArray(Store.state.wishes)) ? [] : (Store.state.wishes || []);
  }
  function giftPriceOf(id) {
    var p = DEFAULT_PRICES[id];
    return (typeof p === 'number' && p >= 0) ? p : 20;
  }
  // 卖出返还: 比购入价少 5 颗星星(最低 0), 避免「买进卖出」零成本刷星
  function sellRefundOf(r) {
    var price = (r && typeof r.price === 'number' && r.price >= 0) ? r.price : giftPriceOf(r && r.id);
    return Math.max(0, price - 5);
  }
  function redeemedAll() {
    return (Store.state.redeemed && Array.isArray(Store.state.redeemed)) ? Store.state.redeemed : [];
  }
  function giftCount(id) {
    var c = 0, red = redeemedAll();
    for (var i = 0; i < red.length; i++) if (red[i] && red[i].id === id) c++;
    return c;
  }
  // 当前选中的专区(互斥折叠)
  function curTab() {
    var t = (Store.state && Store.state.giftTab);
    return sectionOf(t) ? t : 'weapon';
  }
  window.giftTab = function (sec) {
    Store.state.giftTab = sectionOf(sec) ? sec : 'weapon';
    Store.saveState();
    renderWish();
  };
  // 折叠/展开某个书的武将区域(默认展开)
  window.heroToggle = function (bk) {
    Store.state.heroCollapsed = Store.state.heroCollapsed || {};
    Store.state.heroCollapsed[bk] = !Store.state.heroCollapsed[bk];
    Store.saveState();
    var el = document.querySelector('.hero-book[data-book="' + bk + '"]');
    if (el) {
      el.classList.toggle('closed', !!Store.state.heroCollapsed[bk]);
    }
  };
  

  function renderWish() {
    var body = document.getElementById('eduWishBody');
    if (!body) return;
    renderWelcomeInto('wishWelcome', '攒星星，兑换你想要的小心愿');
    ensureGiftData();
    var wishes = Store.state.wishes || [];
    var stars = Store.state.stars || 0;
    var tab = curTab();
    var html = '<div class="wish-summary" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;padding:12px;background:linear-gradient(135deg,#fff3d6,#ffe1ae);border-radius:12px;border:1.5px solid #ffd9a8;">'+
      '<div style="display:flex;gap:8px;">'+
      '<button type="button" class="btn-soft" onclick="window.wishAdd()">+ 新增星愿</button>'+
      '<button type="button" class="btn-soft" onclick="window.parentAddStars()">👑 家长加星</button>'+
      '</div>'+
      '</div>';

    // ---- 互斥专区 Tab(武器区 / 奥特曼区): 选中的展开, 另一个自动折叠 ----
    html += '<div class="gift-tabs" role="tablist">' + GIFT_SECTIONS.map(function (s) {
      var on = s.id === tab;
      return '<button type="button" class="gift-tab' + (on ? ' on' : '') + '" onclick="window.giftTab(\'' + s.id + '\')">' +
        s.icon + ' ' + esc(s.title) + '</button>';
    }).join('') + '</div>';

    // ---- 当前专区的兑换区(已兑换并入同区, 按区折叠展示) ----
    html += renderGiftSection(tab, stars);

    // ---- 我的星愿 ----
    html += '<h3 class="gift-title">✨ 我的星愿</h3>';
    if (!wishes.length) {
      html += '<div style="text-align:center;padding:24px;color:var(--edu-muted);">暂无星愿，点击「新增星愿」添加心愿吧～</div>';
    } else {
      html += '<div class="wish-list">';
      wishes.forEach(function(w, i){
        var can = stars >= (w.cost || 10);
        html += '<div class="wish-item" style="display:flex;align-items:center;gap:12px;padding:12px;background:var(--edu-surface);border:1px solid var(--edu-border-2);border-radius:12px;margin-bottom:10px;">'+
          '<div style="flex:1;"><div style="font-weight:700;">'+esc(w.title)+'</div><div style="font-size:.85rem;color:var(--edu-muted);">价值 '+w.cost+' 颗星星</div></div>'+
          '<div style="display:flex;gap:8px;">'+
          '<button type="button" class="btn-soft '+(can?'':'')+'" '+(can?'':'disabled')+' onclick="window.wishRedeem('+i+')">兑换</button>'+
          '<button type="button" class="btn-ghost" onclick="window.wishRemove('+i+')">删除</button>'+
          '</div></div>';
      });
      html += '</div>';
    }
    body.innerHTML = html;
    renderWishKidPicker();
  }

  // 渲染一个专区的完整内容: 兑换卡片(卖出/兑换在卡片上直接操作)
  function renderGiftSection(sec, stars) {
    var secMeta = sectionOf(sec) || GIFT_SECTIONS[0];
    var html = '<div class="gift-section">' +
      '<h3 class="gift-title">' + secMeta.icon + ' 兑换区 · ' + esc(secMeta.title) + '</h3>' +
      '<div class="gift-intro">' + esc(secMeta.intro) + '</div>';
    if (sec === 'hero') {
      // 武将专区: 按书分组(三国 / 水浒 / 西游记), 每组可点击折叠, 默认全部展开
      var BOOKS = ['三国', '水浒', '西游记'];
      BOOKS.forEach(function (bk) {
        var list = GIFT_CATALOG.filter(function (g) { return g.sec === 'hero' && g.book === bk; });
        var got = list.filter(function (g) { return giftCount(g.id) > 0; }).length;
        var closed = (Store.state.heroCollapsed && Store.state.heroCollapsed[bk]) ? ' closed' : '';
        html += '<div class="hero-book' + closed + '" data-book="' + bk + '">' +
          '<div class="hero-book-h" onclick="window.heroToggle(\'' + bk + '\')">' +
          '<span class="hero-book-arr">▾</span>' +
          '<span class="hero-book-ic">' + (bk === '三国' ? '🏇' : bk === '水浒' ? '⚔️' : '🐒') + '</span>' +
          '<span class="hero-book-t">' + esc(bk) + (bk === '西游记' ? ' · 取经天团' : ' · 英雄豪杰') + '</span>' +
          '<span class="hero-book-n">' + got + ' / ' + list.length + ' 位</span></div>' +
          '<div class="gift-grid">' +
          list.map(function (g) { return giftCardHtml(g, stars); }).join('') +
          '</div></div>';
      });
    } else {
      html += '<div class="gift-grid">';
      GIFT_CATALOG.filter(function (g) { return g.sec === sec; }).forEach(function (g) {
        html += giftCardHtml(g, stars);
      });
      html += '</div>';
    }
    html += '</div>';
    return html;
  }

  function giftCardHtml(g, stars) {
    var price = giftPriceOf(g.id);
    var can = stars >= price;
    var cnt = giftCount(g.id);
    var owned = cnt > 0;
    var badge = '';
    if (owned) badge = g.unique
      ? '<span class="gift-owned">已拥有</span>'
      : '<span class="gift-count">×' + cnt + '</span>';
    var actions;
    if (g.unique) {
      if (owned) {
        actions = '<button type="button" class="gift-sell" onclick="event.stopPropagation();window.giftSellOf(\'' + g.id + '\')">卖出 ' + sellRefundOf({ id: g.id, price: price }) + '⭐</button>';
      } else {
        actions = '<button type="button" class="gift-buy" ' + (can ? '' : 'disabled') + ' onclick="event.stopPropagation();window.giftRedeem(\'' + g.id + '\')">兑换</button>';
      }
    } else {
      actions = '<button type="button" class="gift-buy" ' + (can ? '' : 'disabled') + ' onclick="event.stopPropagation();window.giftRedeem(\'' + g.id + '\')">兑换</button>' +
        (owned ? '<button type="button" class="gift-sell" onclick="event.stopPropagation();window.giftSellOf(\'' + g.id + '\')">卖出 ' + sellRefundOf({ id: g.id, price: price }) + '⭐</button>' : '');
    }
    return '<div class="' + (g.sec === 'hero' ? 'gift-card ' + heroAnimCls(g) : 'gift-card') + (can ? '' : ' off') + '" onclick="window.giftOpen(\'' + g.id + '\')">' +
      badge +
      (g.sec === 'hero'
        ? heroPlaqueHtml(g, false)
        : '<img class="gift-emoji" src="' + imgOf(g.id) + '" alt="' + esc(g.name) + '" draggable="false">') +
      '<div class="gift-info">' +
      (g.sec === 'hero' ? '' : '<span class="gift-name">' + esc(g.name) + '</span>') +
      '<span class="gift-price">' + price + ' ⭐</span>' +
      '</div>' +
      '<div class="gift-actions">' + actions + '</div>' +
      '</div>';
  }

  function renderWishKidPicker() {
    var picker = document.getElementById('wishKidPicker');
    if (!picker) return;
    var kids = window.eduKids ? window.eduKids.all() : [];
    if (kids.length <= 1) { picker.innerHTML = ''; return; }
    var act = window.eduKids ? window.eduKids.active() : (kids[0] || null);
    picker.innerHTML = '<div class="kp-label">切换宝贝：</div>' +
      '<div class="kp-list">' + kids.map(function(k){
        var on = act && k.id === act.id;
        return '<button type="button" class="kp-btn'+(on?' on':'')+'" onclick="window.switchKid(\''+k.id+'\')">'+
          (k.gender==='female'?'👧':'👦')+' '+esc(k.name)+'</button>';
      }).join('') + '</div>';
  }

  // 兑换礼物（二次确认后，家长验证后扣星入已兑换）; 奥特曼不可重复
  window.giftRedeem = function (id) {
    var g = giftOf(id);
    if (!g) { Speech.toast('没有这件礼物'); return; }
    if (g.unique && giftCount(id) > 0) { Speech.toast(g.name + ' 已拥有，不能重复兑换'); return; }
    var price = giftPriceOf(id);
    if ((Store.state.stars || 0) < price) { Speech.toast('星星不足'); return; }
    giftConfirmTarget = { id: id, price: price };
    var t = document.getElementById('gcTitle');
    var s = document.getElementById('gcSub');
    if (t) t.textContent = '确认兑换 ' + g.name;
    if (s) s.textContent = '将花费 ' + price + ' 颗星星，确定吗？';
    var m = document.getElementById('eduMaskGiftConfirm');
    if (m) m.style.display = 'flex';
  };
  var giftConfirmTarget = null;
  window.giftConfirmOk = function () {
    var m = document.getElementById('eduMaskGiftConfirm');
    if (m) m.style.display = 'none';
    var t = giftConfirmTarget;
    giftConfirmTarget = null;
    if (!t) return;
    var g = giftOf(t.id);
    if (!g) return;
    window.requireParent(function () {
      if (Store.awardStars) Store.awardStars(-t.price, '兑换·' + g.name);
      else Store.state.stars -= t.price;
      Store.state.redeemed = (Store.state.redeemed && Array.isArray(Store.state.redeemed)) ? Store.state.redeemed : [];
      Store.state.redeemed.push({ id: g.id, name: g.name, emoji: g.emoji, price: t.price, t: Date.now(), date: fmtDate(new Date()) });
      Store.saveState();
      Kids.renderStarBar();
      renderWish();
      Speech.toast('兑换成功！获得 ' + g.name + ' 💫');
    });
  };
  window.giftConfirmCancel = function () {
    var m = document.getElementById('eduMaskGiftConfirm');
    if (m) m.style.display = 'none';
    giftConfirmTarget = null;
  };

  // 家长手动加星（需备注）
  window.parentAddStars = function () {
    var m = document.getElementById('eduMaskParentAddStars');
    if (!m) return;
    var starsInput = document.getElementById('pasStars');
    var noteInput = document.getElementById('pasNote');
    if (starsInput) starsInput.value = '10';
    if (noteInput) noteInput.value = '';
    m.style.display = 'flex';
    setTimeout(function () { if (noteInput) noteInput.focus(); }, 100);
  };
  window.parentAddStarsCancel = function () {
    var m = document.getElementById('eduMaskParentAddStars');
    if (m) m.style.display = 'none';
  };
  window.parentAddStarsConfirm = function () {
    var starsInput = document.getElementById('pasStars');
    var noteInput = document.getElementById('pasNote');
    var stars = starsInput ? parseInt(starsInput.value, 10) : 0;
    var note = noteInput ? noteInput.value.trim() : '';
    if (!stars || stars < 1) { Speech.toast('请输入有效的星星数'); return; }
    if (!note) { Speech.toast('请填写备注说明'); if (noteInput) noteInput.focus(); return; }
    window.requireParent(function () {
      if (Store.awardStars) Store.awardStars(stars, '家长加星·' + note);
      else Store.state.stars = (Store.state.stars || 0) + stars;
      Store.saveState();
      Kids.renderStarBar();
      renderWish();
      Speech.toast('家长加星成功：+' + stars + ' ⭐');
      parentAddStarsCancel();
    });
  };

  function fmtDate(d) {
    return (d.getFullYear()) + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  // 打开礼物细节弹窗, 自动朗读名称与专属口号
  function openGiftDetail(g, extra) {
    var title = document.getElementById('detailTitle');
    var sub = document.getElementById('detailSub');
    var body = document.getElementById('detailBody');
    var price = giftPriceOf(g.id);
    if (title) title.textContent = '🎁 ' + g.name;
    if (sub) sub.textContent = extra || ('需要 ' + price + ' 颗星星兑换');
    var cnt = giftCount(g.id);
    var secName = sectionOf(g.sec) ? sectionOf(g.sec).title : '';
    var sloganHtml = '';
    // 播放按钮: 武将朗读完整内容(出处+阵营+绰号+简介+口号), 其它礼物朗读专属口号
    var fullTxt = (g.sec === 'hero') ? (heroSpeakText(g) || g.slogan || '') : (g.slogan || '');
    if (fullTxt) {
      var replay = (window.Edu.Speech && window.Edu.Speech.spkBtn) ? window.Edu.Speech.spkBtn(fullTxt, 'gdetail-play') : '';
      sloganHtml = '<div class="gdetail-slogan' + (g.sec === 'hero' ? ' hero' : '') + '">';
      if (g.slogan) sloganHtml += (g.sec === 'hero' ? '🎙️ 播放讲解 ' : '「' + esc(g.slogan) + '」');
      sloganHtml += replay + '</div>';
    }
    if (body) body.innerHTML =
      '<div class="gift-detail">' +
      (g.sec === 'hero'
        ? heroPlaqueHtml(g, true)
        : (isImageGift(g.id)
          ? '<img class="gdetail-emoji" src="' + imgOf(g.id) + '" alt="' + esc(g.name) + '" draggable="false">'
          : '<div class="gdetail-emoji">' + (g.emoji || '🎁') + '</div>')) +
      '<div class="gdetail-name">' + esc(g.name) + '<span class="gdetail-sec">' + esc(secName) + '</span></div>' +
      '<div class="gdetail-desc">' + esc(g.desc) + '</div>' +
      sloganHtml +
      '<div class="gdetail-meta">价格 ' + price + ' ⭐' + (cnt ? ' · 已拥有 ' + cnt + (g.unique ? ' 位' : ' 个') : '') + '</div>' +
      '</div>';
    var mask = document.getElementById('eduMaskDetail');
    if (mask) mask.style.display = 'flex';
    speakGift(g);
  }
  function speakGift(g) {
    try {
      if (!g || !window.Edu.Speech || !window.Edu.Speech.playSpeak) return;
      var txt = heroSpeakText(g) || (g.voice || g.name);
      window.Edu.Speech.playSpeak(txt);
      // 武将名号/简介/口号已由 heroSpeakText 合并为一段, 不再二次播报口号
      if (g.sec !== 'hero' && g.slogan) {
        setTimeout(function () { window.Edu.Speech.playSpeak(g.slogan); }, 2000);
      }
    } catch (e) {}
  }
  // 武将朗读: 名号(出处+阵营+绰号) + 简介 + 口号, 让宝贝了解更多武将信息
  function heroSpeakText(g) {
    if (!g || g.sec !== 'hero') return '';
    var head = g.name + '，' + (g.book || '') +
      (g.camp ? '，' + g.camp : '') +
      (g.epithet ? '，人称' + g.epithet : '') + '。';
    return head + (g.desc || '') + (g.slogan ? (g.desc && g.desc.slice(-1) === '。' ? '' : '。') + g.slogan : '');
  }
  window.giftDetail = function (id) {
    var g = giftOf(id);
    if (!g) return;
    openGiftDetail(g);
  };
  // 卡片/图片点击查看
  window.giftOpen = window.giftDetail;
  window.giftDetailByIdx = function (i) {
    var red = redeemedAll();
    var r = red[i];
    if (!r) return;
    var g = giftOf(r.id) || { id: r.id, sec: 'weapon', emoji: r.emoji || '🎁', name: r.name || '礼物', desc: '已兑换的礼物' };
    openGiftDetail(g, r.name ? '已拥有' : '');
  };

  window.wishAdd = function () {
    var m = document.getElementById('eduMaskWishAdd');
    if (!m) return;
    var titleInput = document.getElementById('waTitle');
    var costInput = document.getElementById('waCost');
    if (titleInput) titleInput.value = '';
    if (costInput) costInput.value = '30';
    m.style.display = 'flex';
    setTimeout(function () { if (titleInput) titleInput.focus(); }, 100);
  };
  window.wishAddCancel = function () {
    var m = document.getElementById('eduMaskWishAdd');
    if (m) m.style.display = 'none';
  };
  window.wishAddConfirm = function () {
    var titleInput = document.getElementById('waTitle');
    var costInput = document.getElementById('waCost');
    var title = titleInput ? titleInput.value.trim() : '';
    var cost = costInput ? parseInt(costInput.value, 10) : 0;
    if (!title) { Speech.toast('请输入星愿名称'); if (titleInput) titleInput.focus(); return; }
    if (!cost || cost < 1) { Speech.toast('星星数需大于0'); return; }
    Store.state.wishes = (Store.state.wishes && typeof Store.state.wishes === 'object' && !Array.isArray(Store.state.wishes)) ? [] : (Store.state.wishes || []);
    Store.state.wishes.push({ title: title, cost: cost, created: Date.now() });
    Store.saveState();
    renderWish();
    wishAddCancel();
    Speech.toast('新星愿已添加：' + title + ' 💫');
  };

  window.wishRedeem = function (i) {
    var wishes = (Store.state.wishes && Array.isArray(Store.state.wishes)) ? Store.state.wishes : [];
    var w = wishes[i];
    if (!w) return;
    if ((Store.state.stars || 0) < w.cost) { Speech.toast('星星不足'); return; }
    window.requireParent(function () {
      if (Store.awardStars) Store.awardStars(-w.cost, '心愿达成·' + w.title);
      else Store.state.stars -= w.cost;
      Store.state.wishLog = Store.state.wishLog || [];
      Store.state.wishLog.push({ title: w.title, cost: w.cost, t: Date.now() });
      Store.state.wishes = (Store.state.wishes && Array.isArray(Store.state.wishes)) ? Store.state.wishes : [];
      Store.state.wishes.splice(i, 1);
      Store.saveState();
      Kids.renderStarBar();
      renderWish();
      Speech.toast('兑换成功！'+w.title);
    });
  };

  // 卖出已兑换礼物: 按购入价减 5 星返还(防零成本刷星)
  window.giftSell = function (i) {
    var red = redeemedAll();
    var r = red[i];
    if (!r) return;
    var g = giftOf(r.id);
    var name = r.name || (g ? g.name : '礼物');
    var refund = sellRefundOf(r);
    window.requireParent(function () {
      if (Store.awardStars) Store.awardStars(refund, '卖出·' + name);
      else Store.state.stars = (Store.state.stars || 0) + refund;
      red.splice(i, 1);
      Store.saveState();
      Kids.renderStarBar();
      renderWish();
      Speech.toast('已卖出 ' + name + '，返还 ' + refund + ' 颗星星 💫');
    });
  };
  // 卡片上的卖出: 卖掉最近购入的一件该礼物
  window.giftSellOf = function (id) {
    var red = redeemedAll();
    for (var i = red.length - 1; i >= 0; i--) {
      if (red[i] && red[i].id === id) { window.giftSell(i); return; }
    }
    Speech.toast('没有可卖出的 ' + (giftOf(id) ? giftOf(id).name : '礼物'));
  };

  window.wishRemove = function (i) {
    window.requireParent(function(){
      Store.state.wishes = (Store.state.wishes && Array.isArray(Store.state.wishes)) ? Store.state.wishes : [];
      Store.state.wishes.splice(i, 1);
      Store.saveState();
      renderWish();
    });
  };

  window.wishRemoveP = function (i) {
    window.requireParent(function(){
      Store.state.wishLog = (Store.state.wishLog && Array.isArray(Store.state.wishLog)) ? Store.state.wishLog : [];
      Store.state.wishLog.splice(i, 1);
      Store.saveState();
      renderWish();
    });
  };

  window.Edu.Wish = {
    GIFT_SECTIONS: GIFT_SECTIONS,
    GIFT_CATALOG: GIFT_CATALOG,
    DEFAULT_PRICES: DEFAULT_PRICES,
    renderWish: renderWish,
    giftOf: giftOf,
    giftPriceOf: giftPriceOf,
    sellRefundOf: sellRefundOf,
    giftCount: giftCount,
    giftRedeem: window.giftRedeem,
    giftConfirmOk: window.giftConfirmOk,
    giftConfirmCancel: window.giftConfirmCancel,
    giftSell: window.giftSell,
    giftSellOf: window.giftSellOf,
    giftOpen: window.giftOpen,
    giftDetail: window.giftDetail,
    giftDetailByIdx: window.giftDetailByIdx,
    giftTab: window.giftTab,
    wishAdd: window.wishAdd,
    wishAddCancel: window.wishAddCancel,
    wishAddConfirm: window.wishAddConfirm,
    wishRedeem: window.wishRedeem,
    wishRemove: window.wishRemove,
    wishRemoveP: window.wishRemoveP,
    parentAddStars: window.parentAddStars,
    parentAddStarsCancel: window.parentAddStarsCancel,
    parentAddStarsConfirm: window.parentAddStarsConfirm
  };
})();