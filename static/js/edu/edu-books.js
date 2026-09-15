(function () {
  'use strict';
  // =====================================================
  // 绘本阅读 (简约开源绘本引擎, 独立于 React 系项目):
  // 每本绘本由「主题渐变背景 + 大号场景 emoji 插画 + 短句旁白」组成,
  // 语音使用本应用已有的 /edu/api/tts (edge-tts) 同源有声朗读。
  // 功能: 点击/键盘/滑动翻页 · 全屏阅读 · 每页自动朗读。
  // 故事内容为公共领域经典寓言/童话 + 原创短篇, 无版权风险。
  // =====================================================
  var Speech = window.Edu.Speech;

var BOOKS = [
    // === 龟兔赛跑（伊索寓言）—— 坚持不懈、胜不骄 ===
    {
      id: 'gui-tu-sai-pao', title: '龟兔赛跑', tag: '寓言 · 坚持', color: '#7fce78',
      pages: [
        { k: 'hare', bg: 'meadow', ems: ['🌳','🌳','🐦'], text: '龟兔赛跑' },
        { k: 'hare', bg: 'meadow', ems: ['🐢','🐰','🌲'], text: '森林里，小兔子跑得飞快，总爱笑话小乌龟走得慢。' },
        { k: 'hare', bg: 'meadow', ems: ['🐰','💪','😤'], text: '小兔子拍拍胸脯说：“哼，谁也没我跑得快！”' },
        { k: 'race', bg: 'meadow', ems: ['🐢','😊','🐰'], text: '小乌龟不急不慢地说：“我们来赛跑，比比看谁先到山顶。”' },
        { k: 'race', bg: 'sunny', ems: ['🏁','🐰','🐢'], text: '发令枪一响，小兔子"嗖"地一下冲了出去。' },
        { k: 'run', bg: 'sunny', ems: ['🐰','💨','🏃'], text: '它跑得真快呀，一眨眼就跑到了半山腰。' },
        { k: 'turtle', bg: 'meadow', ems: ['🐢','💪','💨'], text: '小乌龟还在起点附近，一步一步稳稳地爬。' },
        { k: 'turtle', bg: 'sunny', ems: ['🐢','😊','💪'], text: '它对自己说：“没关系，只要不停下来，就一定能到。”' },
        { k: 'hare', bg: 'sunny', ems: ['🐰','回头看','🐢'], text: '小兔子回头一看，乌龟连山脚都还没到呢。' },
        { k: 'nap', bg: 'forest', ems: ['🌳','🐰','💡'], text: '它得意地想：我先睡一觉，醒来再跑也来得及。' },
        { k: 'sleep', bg: 'forest', ems: ['😴','🌳','💤'], text: '小兔子靠着大树，呼呼地睡着了。' },
        { k: 'turtle', bg: 'meadow', ems: ['🐢','💨','💪'], text: '小乌龟从睡着的兔子身边经过，它没有停下来。' },
        { k: 'mountain', bg: 'sunny', ems: ['🐢','💪','⛰️'], text: '太阳快落山了，小乌龟终于爬到了山顶。' },
        { k: 'finish', bg: 'sunny', ems: ['🏁','🐢','🎉'], text: '小乌龟到了终点！全场都为它欢呼！' },
        { k: 'surprise', bg: 'forest', ems: ['😱','🐰','🏃'], text: '小兔子醒来一看——呀，乌龟已经到了终点！' },
        { k: 'run', bg: 'sunny', ems: ['😫','🐰','😔'], text: '它拼命往山上跑，可是已经来不及了。' },
        { k: 'turtle', bg: 'sunny', ems: ['🐢','🐰','🤝'], text: '小乌龟说：“你跑得比我快，但你太骄傲了。”' },
        { k: 'winner', bg: 'dawn', ems: ['🌅','💡','⭐'], text: '小朋友，坚持到底才能赢，骄傲会让人落后哦！' }
      ]
    },
    // === 狼来了（伊索寓言）—— 诚实守信 ===
    {
      id: 'lang-lai-le', title: '狼来了', tag: '寓言 · 诚实', color: '#b0a68f',
      pages: [
        { k: 'sheep', bg: 'meadow', ems: ['⛰️','🐑','☁️'], text: '狼来了' },
        { k: 'shepherd', bg: 'meadow', ems: ['👦','🐑','⛰️'], text: '从前有个放羊的小男孩，每天在山坡上看着羊群吃草。' },
        { k: 'boy', bg: 'sunny', ems: ['👦','😮‍💨','🐑'], text: '山坡上只有他一个人，日子久了，他觉得特别无聊。' },
        { k: 'boy', bg: 'meadow', ems: ['👦','💡','😈'], text: '有一天他眼珠一转，想到了一个"好玩"的主意。' },
        { k: 'wolf', bg: 'meadow', ems: ['📢','🐺','😱'], text: '他扯着嗓子喊：“狼来啦！狼来啦！大家快来呀！”' },
        { k: 'farmer', bg: 'farm', ems: ['👨‍🌾','🏃','🎣'], text: '山下的农民们听到喊声，赶紧放下手里的活儿跑上山。' },
        { k: 'farmer', bg: 'sunny', ems: ['👨‍🌾','❓','👦'], text: '大家气喘吁吁跑上来，可是连狼的影子都没看到。' },
        { k: 'laugh', bg: 'sunny', ems: ['😂','👦','😡'], text: '小男孩哈哈大笑：“哈哈哈，真好玩！你们上当啦！”' },
        { k: 'farmer', bg: 'farm', ems: ['👨‍🌾','😤','🚶'], text: '大人们很生气，摇摇头说：“这孩子真不像话！”' },
        { k: 'wolf', bg: 'meadow', ems: ['📢','🐺','😱'], text: '过了几天，他又喊：“狼来啦！狼来啦！快来人哪！”' },
        { k: 'farmer', bg: 'farm', ems: ['👨‍🌾','🤷','🚶'], text: '大人们又被骗了，这次更生气了。' },
        { k: 'wolf', bg: 'meadow', ems: ['🐺','🐺','😠'], text: '有一天，狼真的来了！两只大灰狼扑向羊群！' },
        { k: 'sheep', bg: 'meadow', ems: ['🐺','🐑','😱'], text: '羊群吓得四处乱跑，小男孩吓得脸都白了。' },
        { k: 'boy', bg: 'meadow', ems: ['👦','📢','😰'], text: '他拼命喊：“狼来啦！狼来啦！这次是真的！”' },
        { k: 'wolf', bg: 'farm', ems: ['👨‍🌾','🤷','🚶'], text: '可是大人们都不相信了，没有人跑上来帮忙。' },
        { k: 'farmer', bg: 'meadow', ems: ['🐺','🐑','😢'], text: '大灰狼叼走了好几只小羊，小男孩哭了起来。' },
        { k: 'sheep', bg: 'dusk', ems: ['😢','👦','🐑'], text: '他后悔极了：原来撒谎的人，说真话也没人信了。' },
        { k: 'shepherd', bg: 'dawn', ems: ['💡','👦','⭐'], text: '小朋友，诚实是最重要的品质，撒谎会失去别人的信任！' }
      ]
    },
    // === 乌鸦喝水（伊索寓言）—— 动脑解决问题 ===
    {
      id: 'wu-ya-he-shui', title: '乌鸦喝水', tag: '寓言 · 智慧', color: '#7ec5ff',
      pages: [
        { k: 'crow', bg: 'sky', ems: ['☀️','☁️','🐦'], text: '乌鸦喝水' },
        { k: 'sun', bg: 'sunny', ems: ['☀️','🐦','😅'], text: '炎热的夏天，一只乌鸦在天空中飞了很久，口渴极了。' },
        { k: 'crow', bg: 'sky', ems: ['🐦','🌳','🔍'], text: '它找啊找，嗓子干得快冒烟了。' },
        { k: 'water', bg: 'meadow', ems: ['🐦','🍶','💧'], text: '终于，它看到草地上有一个玻璃瓶，里面有小半瓶水！' },
        { k: 'bottle', bg: 'sunny', ems: ['🍶','💧','🐦'], text: '可是瓶口太细了，乌鸦的嘴巴怎么也伸不进去。' },
        { k: 'crow', bg: 'sunny', ems: ['🐦','😫','💧'], text: '它试了好几种办法：倒过来、推瓶子，水就是喝不到。' },
        { k: 'crow', bg: 'meadow', ems: ['🐦','💡','✨'], text: '乌鸦安静下来想了想，突然眼睛一亮：有办法了！' },
        { k: 'stone', bg: 'meadow', ems: ['🐦','🪨','🍶'], text: '它找来一颗小石子，对准瓶口，"咚"地丢了进去。' },
        { k: 'stone', bg: 'meadow', ems: ['🐦','🪨','🪨'], text: '一颗、两颗、三颗……乌鸦一颗接一颗地往瓶里放石子。' },
        { k: 'water', bg: 'meadow', ems: ['🍶','💧','⬆️'], text: '奇妙的事情发生了——瓶子里的水面慢慢升高了！' },
        { k: 'crow', bg: 'sunny', ems: ['🍶','💧','💫'], text: '水面升到了瓶口，乌鸦终于喝到清凉的水了！' },
        { k: 'crow', bg: 'sunny', ems: ['🐦','😋','☀️'], text: '乌鸦开心极了，喝了一大口，再也不口渴了。' },
        { k: 'water', bg: 'dawn', ems: ['💡','🐦','🌟'], text: '遇到困难别着急，动脑筋就能想到好办法！' }
      ]
    },
    // === 三只小猪（英国童话）—— 勤劳踏实 ===
    {
      id: 'san-zhi-xiao-zhu', title: '三只小猪', tag: '童话 · 勤劳', color: '#f5b83d',
      pages: [
        { k: 'pig', bg: 'farm', ems: ['🏠','🌻','☀️'], text: '三只小猪' },
        { k: 'pig', bg: 'home', ems: ['🐷','🐷','🐷'], text: '猪妈妈有三个孩子，它们渐渐长大了，该自己出去生活了。' },
        { k: 'pig', bg: 'farm', ems: ['🐷','👋','🏠'], text: '妈妈叮嘱说：“孩子们，记得盖一间结实的房子，保护好自己。”' },
        { k: 'straw', bg: 'farm', ems: ['🐷','🌾','🏃'], text: '猪大哥贪玩，跑到田里抱了一大堆稻草。' },
        { k: 'house', bg: 'farm', ems: ['🏠','🌾','⏱️'], text: '不到半天，它就盖好了一间草房子。' },
        { k: 'wood', bg: 'forest', ems: ['🐷','🪵','💪'], text: '猪二哥找来一些木板，叮叮当当地敲了两天。' },
        { k: 'house', bg: 'forest', ems: ['🏠','🪵','✨'], text: '木房子比草房子好看多了，猪二哥很满意。' },
        { k: 'brick', bg: 'sunny', ems: ['🐷','🧱','💪'], text: '猪小弟最勤劳，它去山脚搬来一块一块的砖头。' },
        { k: 'brick', bg: 'sunny', ems: ['🧱','🧱','🐷'], text: '它搬了七天七夜，累得满头大汗，手都磨红了。' },
        { k: 'house', bg: 'sunny', ems: ['🏠','🧱','✨'], text: '终于，一间漂亮的砖房子盖好了，又结实又好看。' },
        { k: 'wolf', bg: 'meadow', ems: ['🐺','😈','👀'], text: '有一天，一只大灰狼溜到了村子里。' },
        { k: 'straw', bg: 'meadow', ems: ['🐺','💨','🏠','🌾'], text: '大灰狼深吸一口气——呼！草房子一下子就被吹塌了。' },
        { k: 'pig', bg: 'farm', ems: ['🐷','😱','🏃'], text: '猪大哥吓得拔腿就跑，跑进了猪二哥的木房子里。' },
        { k: 'wood', bg: 'forest', ems: ['🐺','💨','🏠','🪵'], text: '大灰狼又使劲吹——呼！木房子也哗啦啦地倒了。' },
        { k: 'brick', bg: 'forest', ems: ['🐷','🐷','😱','🏃'], text: '两只小猪吓得直哆嗦，赶紧跑到猪小弟的砖房子里。' },
        { k: 'brick', bg: 'sunny', ems: ['🐺','💨','🏠','🧱'], text: '大灰狼吹呀吹、撞呀撞，砖房子纹丝不动。' },
        { k: 'wolf', bg: 'sunny', ems: ['🐺','😫','💨'], text: '大灰狼累得气喘吁吁，只好灰溜溜地走了。' },
        { k: 'house', bg: 'dusk', ems: ['🏠','🧱','✅'], text: '三只小猪抱在一起，猪小弟的砖房子保护了大家。' },
        { k: 'pig', bg: 'dawn', ems: ['💡','🏠','⭐'], text: '做事情不能偷懒偷快，认真踏实才能做得长久！' }
      ]
    },
    // === 小红帽（格林童话）—— 安全意识 ===
    {
      id: 'xiao-hong-mao', title: '小红帽', tag: '童话 · 安全', color: '#ff8a8a',
      pages: [
        { k: 'girl', bg: 'rose', ems: ['🏠','🌸','☀️'], text: '小红帽' },
        { k: 'girl', bg: 'rose', ems: ['👧','🧺','❤️'], text: '从前有个可爱的小姑娘，大家都叫她小红帽。' },
        { k: 'basket', bg: 'rose', ems: ['👩','👧','🧺'], text: '妈妈对她说：“把这些点心给外婆送去吧，外婆生病了。”' },
        { k: 'forest', bg: 'rose', ems: ['👧','🧺','🌳'], text: '小红帽戴上心爱的红帽子，提着篮子出发了。' },
        { k: 'flowers', bg: 'forest', ems: ['🌳','🌺','🦋'], text: '路上开满了鲜花，小红帽停下来摘了几朵。' },
        { k: 'wolf', bg: 'forest', ems: ['🐺','🌸','😈'], text: '一只大灰狼从树后钻出来，假装友好地问：“小姑娘，你要去哪里呀？”' },
        { k: 'girl', bg: 'forest', ems: ['👧','😊','🐺'], text: '小红帽不知道大灰狼是坏人，告诉它外婆住在林子那边。' },
        { k: 'grandmother', bg: 'forest', ems: ['🐺','🏃','💨'], text: '大灰狼飞快地跑到外婆家，把外婆藏在了柜子里。' },
        { k: 'grandmother', bg: 'home', ems: ['🐺','👗','🛏️'], text: '大灰狼穿上外婆的衣服，戴上外婆的眼镜，躺在床上。' },
        { k: 'girl', bg: 'home', ems: ['👧','🚪','🧺'], text: '小红帽到了外婆家，推开门说：“外婆，我来啦！”' },
        { k: 'girl', bg: 'home', ems: ['👧','🤔','🐺'], text: '小红帽觉得好奇怪：“外婆，您的耳朵怎么这么大呀？”' },
        { k: 'wolf', bg: 'home', ems: ['🐺','😡','👧'], text: '大灰狼露出了真面目，一把抓住了小红帽。' },
        { k: 'hunter', bg: 'forest', ems: ['👨‍🌾','🪓','💪'], text: '幸好一个猎人路过，听到了奇怪的声音，冲了进去。' },
        { k: 'hunter', bg: 'home', ems: ['👨‍🌾','🪓','🚪'], text: '猎人用斧头劈开柜子，救出了小红帽和外婆。' },
        { k: 'girl', bg: 'sunny', ems: ['👧','👩','🤗'], text: '小红帽扑进妈妈怀里，以后再也不跟陌生人说话了。' },
        { k: 'girl', bg: 'dawn', ems: ['💡','👧','⭐'], text: '不要轻信陌生人的话，要学会保护自己！' }
      ]
    },
    // === 丑小鸭（安徒生童话）—— 自信坚持 ===
    {
      id: 'chou-xiao-ya', title: '丑小鸭', tag: '童话 · 自信', color: '#ffd28a',
      pages: [
        { k: 'duckling', bg: 'river', ems: ['☀️','🌊','🌿'], text: '丑小鸭' },
        { k: 'duck', bg: 'river', ems: ['🦆','🥚','🥚'], text: '鸭妈妈孵了一窝蛋，小鸭子们一个个破壳而出。' },
        { k: 'duckling', bg: 'river', ems: ['🐤','🐤','🦆'], text: '小鸭子们毛茸茸的，黄黄的，特别可爱。' },
        { k: 'duckling', bg: 'river', ems: ['🐣','😔','🐤'], text: '可是有一只鸭子又大又灰，长得和大家都不一样。' },
        { k: 'duckling', bg: 'river', ems: ['🐤','😤','🐣'], text: '其他小鸭子都嘲笑它：“你好丑呀！离我们远一点！”' },
        { k: 'duck', bg: 'farm', ems: ['🐔','🐔','🐣'], text: '连院子里的鸡鸭们也欺负它，用嘴啄它。' },
        { k: 'duckling', bg: 'sunny', ems: ['🐣','😢','🌧️'], text: '丑小鸭难过极了，它决定离开这个让它伤心的家。' },
        { k: 'snow', bg: 'snow', ems: ['🦆','❄️','🌑'], text: '冬天来了，丑小鸭又冷又饿，差点冻死在雪地里。' },
        { k: 'farm', bg: 'snow', ems: ['👨‍🌾','🏠','❤️'], text: '幸好一个好心的老爷爷把它带回了家，喂它食物。' },
        { k: 'spring', bg: 'river', ems: ['☀️','🌸','🌳'], text: '春天来了，花开了，草绿了，到处生机勃勃。' },
        { k: 'swan', bg: 'river', ems: ['🦢','🦢','✨'], text: '丑小鸭来到湖边，看到几只美丽的白天鹅在游泳。' },
        { k: 'swan', bg: 'river', ems: ['🦢','💓','🏊'], text: '它鼓起勇气游过去，想跟天鹅做朋友。' },
        { k: 'swan', bg: 'river', ems: ['🦢','😊','✨'], text: '天鹅们围着它说：“你真漂亮呀！跟我们一起玩吧！”' },
        { k: 'water', bg: 'river', ems: ['🦢','😱','💧'], text: '丑小鸭低头一看——湖面倒映着一只美丽的白天鹅！' },
        { k: 'swan', bg: 'river', ems: ['🦢','💃','🌟'], text: '原来它不是丑小鸭，它是一只漂亮的白天鹅呀！' },
        { k: 'swan', bg: 'sunny', ems: ['🦢','🦢','🦢'], text: '丑小鸭和天鹅们一起快乐地在湖面上跳起了舞。' },
        { k: 'swan', bg: 'dawn', ems: ['🌟','💖','🦢'], text: '不要因为暂时的困难就放弃，你终会绽放自己的光芒！' }
      ]
    },
    // === 猴子捞月（中国民间故事）—— 冷静思考 ===
    {
      id: 'hou-zi-lao-yue', title: '猴子捞月', tag: '民间 · 思考', color: '#8f9ce8',
      pages: [
        { k: 'monkey', bg: 'night', ems: ['🌙','⭐','🌲'], text: '猴子捞月' },
        { k: 'monkey', bg: 'night', ems: ['🐒','🐒','🐒'], text: '一天晚上，一群猴子在树林里玩耍打闹。' },
        { k: 'well', bg: 'night', ems: ['🐒','🌳','🌊'], text: '小猴子跑到井边，低头往井里一看。' },
        { k: 'moon', bg: 'night', ems: ['😱','🌙','💧'], text: '它吓了一跳：“不好啦！月亮掉进井里啦！”' },
        { k: 'monkey', bg: 'night', ems: ['🐒','📢','😱'], text: '小猴子大声喊：“快来呀！月亮掉进井里啦！”' },
        { k: 'monkey', bg: 'night', ems: ['🐒','🐒','🐒'], text: '猴子们全都围过来了，大家叽叽喳喳地讨论。' },
        { k: 'monkey', bg: 'night', ems: ['🐒','🤔','🌙'], text: '老猴子说：“月亮是我们的好朋友，我们得把它捞上来！”' },
        { k: 'tree', bg: 'night', ems: ['🐒','🐒','🌳'], text: '猴子们爬上井边的大树，一个接一个倒挂下来。' },
        { k: 'water', bg: 'night', ems: ['🐒','🐒','💧'], text: '最小的猴子伸出手去捞水里的月亮。' },
        { k: 'water', bg: 'river', ems: ['💧','💫','😠'], text: '可是手一碰到水面，月亮就碎成了好多好多片。' },
        { k: 'monkey', bg: 'night', ems: ['🐒','😤','💧'], text: '猴子们换了个办法又试，还是捞不上来。' },
        { k: 'moon', bg: 'night', ems: ['🐒','☝️','🌕'], text: '这时老猴子抬起头，看到了天上的月亮。' },
        { k: 'moon', bg: 'night', ems: ['🌕','😊','🐒'], text: '咦？月亮好好地挂在天上呢，根本没有掉下来！' },
        { k: 'moon', bg: 'night', ems: ['🐒','😂','💧'], text: '原来井里只是月亮的影子呀，猴子们都笑起来了。' },
        { k: 'monkey', bg: 'night', ems: ['🐒','🐒','🏠'], text: '猴子们高高兴兴地回家了，以后遇到事情要先想一想。' },
        { k: 'moon', bg: 'dawn', ems: ['💡','🌙','⭐'], text: '遇事不要着急，仔细观察、认真思考，才能找到答案！' }
      ]
    },
    // === 司马光砸缸（中国历史故事）—— 临危不乱 ===
    {
      id: 'si-ma-guang-za-gang', title: '司马光砸缸', tag: '历史 · 勇敢', color: '#82b4f5',
      pages: [
        { k: 'boy', bg: 'sunny', ems: ['☀️','🏠','🌳'], text: '司马光砸缸' },
        { k: 'boy', bg: 'sky', ems: ['👦','📖','💡'], text: '古时候有个聪明的孩子叫司马光，他爱动脑筋。' },
        { k: 'children', bg: 'sunny', ems: ['👦','👦','👧'], text: '有一天，他和好朋友们在花园里捉迷藏。' },
        { k: 'jug', bg: 'home', ems: ['🏞️','💧','🏺'], text: '花园角落有一口大水缸，里面装满了清水。' },
        { k: 'boy', bg: 'home', ems: ['👦','🧗','💀'], text: '有个小朋友爬到缸沿上，想看看里面有什么。' },
        { k: 'water', bg: 'river', ems: ['😱','💦','👦'], text: '不好！他脚一滑，"扑通"一声掉进了大水缸里！' },
        { k: 'water', bg: 'river', ems: ['💦','😱','👦'], text: '水缸太高了，小朋友在里面拼命挣扎，水快没过头顶了。' },
        { k: 'children', bg: 'sunny', ems: ['👧','😭','👦'], text: '其他小朋友都吓坏了，有的坐在地上大哭。' },
        { k: 'boy', bg: 'sunny', ems: ['👦','🏃','💪'], text: '司马光没有哭，他飞快地跑到水缸旁边。' },
        { k: 'boy', bg: 'sunny', ems: ['👦','🤔','💡'], text: '他冷静地想了一秒钟：水太多，人太小，喊大人来不及！' },
        { k: 'stone', bg: 'sunny', ems: ['💪','🪨','👦'], text: '司马光抱起一块大石头，用尽全身力气砸向水缸。' },
        { k: 'water', bg: 'river', ems: ['🪨','💥','💦'], text: '"啪！"水缸被砸了一个大洞，水哗哗地流了出来。' },
        { k: 'water', bg: 'river', ems: ['💦','⬇️','👦'], text: '水慢慢流光了，小朋友终于可以站起来呼吸了。' },
        { k: 'family', bg: 'sunny', ems: ['👦','😊','👩'], text: '小朋友的爸爸妈妈赶来，连声感谢司马光。' },
        { k: 'boy', bg: 'sunny', ems: ['👦','👍','🌟'], text: '大家都夸他：你真是个又聪明又勇敢的孩子！' },
        { k: 'stone', bg: 'dawn', ems: ['💡','🪨','⭐'], text: '遇到紧急情况不要慌，冷静思考就能想出好办法！' }
      ]
    },
    // === 孔融让梨（中华传统美德）—— 分享谦让 ===
    {
      id: 'kong-rong-rang-li', title: '孔融让梨', tag: '美德 · 谦让', color: '#a7d98a',
      pages: [
        { k: 'pear', bg: 'home', ems: ['🏠','☀️','🌳'], text: '孔融让梨' },
        { k: 'boy', bg: 'sunny', ems: ['👦','📖','🏠'], text: '古时候有个孩子叫孔融，他从小就很懂事。' },
        { k: 'family', bg: 'home', ems: ['👨','👩','👧','👦'], text: '孔融有五个哥哥和一个弟弟，一家人住在一起。' },
        { k: 'pear', bg: 'sunny', ems: ['👨','🍐','🧺'], text: '有一天，爸爸买回来一大筐新鲜的梨子。' },
        { k: 'pear', bg: 'home', ems: ['🍐','🍐','🍐'], text: '梨子黄澄澄的，闻起来香甜极了。' },
        { k: 'pear', bg: 'home', ems: ['👨','👦','👧'], text: '爸爸说：“孩子们，快来吃梨吧，每人挑一个。”' },
        { k: 'pear', bg: 'home', ems: ['👧','🍐','😊'], text: '哥哥姐姐们纷纷跑过来，每人挑了一个又大又黄的。' },
        { k: 'pear', bg: 'home', ems: ['👦','🍐','🔍'], text: '轮到孔融了，他却拿了一个最小的梨子。' },
        { k: 'pear', bg: 'home', ems: ['👨','❓','👦'], text: '爸爸好奇地问：“融儿，你为什么拿最小的梨呀？”' },
        { k: 'pear', bg: 'home', ems: ['👦','😊','🍐'], text: '孔融说：“我年纪最小，应该吃最小的。大的留给哥哥们。”' },
        { k: 'pear', bg: 'home', ems: ['👦','🍐','😊'], text: '他又说：“弟弟比我更小，我要把大的留给弟弟。”' },
        { k: 'pear', bg: 'home', ems: ['👧','🍐','😢'], text: '哥哥弟弟们听了，都很感动。' },
        { k: 'family', bg: 'home', ems: ['👨','👩','😊'], text: '爸爸妈妈高兴地笑了：我们的融儿真是个懂事的好孩子。' },
        { k: 'family', bg: 'sunny', ems: ['👨','👩','👦'], text: '从那以后，孔融的哥哥弟弟们也都学会了互相谦让。' },
        { k: 'pear', bg: 'dawn', ems: ['🌟','🍐','❤️'], text: '分享和谦让，能让大家都感到温暖和快乐！' }
      ]
    },
    // === 守株待兔（中国成语故事）—— 勤劳致富 ===
    {
      id: 'shou-zhu-dai-tu', title: '守株待兔', tag: '成语 · 勤劳', color: '#a8c786',
      pages: [
        { k: 'farmer', bg: 'farm', ems: ['☀️','🌾','🏠'], text: '守株待兔' },
        { k: 'field', bg: 'farm', ems: ['👨‍🌾','🧎','🌾'], text: '从前有个农夫，每天天不亮就到田里干活。' },
        { k: 'sun', bg: 'farm', ems: ['👨‍🌾','🥵','💧'], text: '太阳火辣辣地晒着，汗水顺着脸颊不停地流。' },
        { k: 'tree', bg: 'farm', ems: ['🌳','🪵','🌳'], text: '田边有棵老树桩，农夫累的时候就坐在树桩旁休息。' },
        { k: 'rabbit', bg: 'farm', ems: ['🐇','💨','💫'], text: '突然，一只野兔子飞快地跑过来，"砰"地撞在树桩上！' },
        { k: 'rabbit', bg: 'farm', ems: ['🐇','😵','💫'], text: '兔子撞得晕了过去，一动也不动了。' },
        { k: 'rabbit', bg: 'farm', ems: ['👨‍🌾','😊','🐇'], text: '农夫捡起兔子，高兴极了：“白捡了一只大肥兔！”' },
        { k: 'food', bg: 'farm', ems: ['🍖','🍷','😋'], text: '晚上，农夫美美地吃了一顿兔子肉，真是太香了。' },
        { k: 'rabbit', bg: 'sunny', ems: ['💭','👨‍🌾','🐇'], text: '他躺在床上想：“要是天天都能捡到兔子，那多好呀！”' },
        { k: 'field', bg: 'sunny', ems: ['👨‍🌾','🌳','🌾'], text: '第二天开始，农夫不再种田了，天天坐在树桩旁等兔子。' },
        { k: 'field', bg: 'sunny', ems: ['👨‍🌾','😊','🔍'], text: '他等啊等，从早到晚盯着树桩，连饭都忘了吃。' },
        { k: 'field', bg: 'meadow', ems: ['🌾','😢','🌾'], text: '日子一天天过去，田里的庄稼都枯死了。' },
        { k: 'rabbit', bg: 'meadow', ems: ['👨‍🌾','😭','🌾'], text: '可是，再也没有兔子来撞树桩了。' },
        { k: 'farmer', bg: 'sunny', ems: ['👨‍🌾','🌾','🐛'], text: '农夫什么也没等到，还错过了种田的时节。' },
        { k: 'farmer', bg: 'dawn', ems: ['💪','🌾','💡'], text: '天上不会掉馅饼，只有靠自己勤劳的双手才能有收获！' }
      ]
    },
    // === 小马过河（中国经典故事）—— 勇于尝试 ===
    {
      id: 'xiao-ma-guo-he', title: '小马过河', tag: '故事 · 勇敢', color: '#f5a623',
      pages: [
        { k: 'horse', bg: 'meadow', ems: ['🐴','🌾','🏠'], text: '小马过河' },
        { k: 'river', bg: 'home', ems: ['🐴','👩','🌾'], text: '小马和妈妈住在美丽的小河边，每天都过得很开心。' },
        { k: 'horse', bg: 'farm', ems: ['🐴','👩','📦'], text: '有一天，妈妈对小马说：“你长大了，帮妈妈送袋粮食到河对面吧。”' },
        { k: 'horse', bg: 'meadow', ems: ['🐴','💪','📦'], text: '小马驮着粮食，高高兴兴地出发了。' },
        { k: 'river', bg: 'river', ems: ['🐴','🌊','😰'], text: '走着走着，一条哗啦啦的小河挡住了去路。' },
        { k: 'river', bg: 'river', ems: ['🐴','🤔','💧'], text: '小马不知道河水有多深，该不该过呢？' },
        { k: 'cow', bg: 'meadow', ems: ['🐂','🐴','💡'], text: '老牛伯伯走过来说：“水很浅，才到我的小腿，放心过吧！”' },
        { k: 'squirrel', bg: 'meadow', ems: ['🐿️','🐴','😱'], text: '小松鼠急急忙忙跑过来说：“千万别过河！水很深，会淹死人的！”' },
        { k: 'horse', bg: 'river', ems: ['🐴','🤔','❓'], text: '小马犯难了：牛伯伯说浅，小松鼠说深，到底听谁的？' },
        { k: 'horse', bg: 'river', ems: ['🐴','💬','👩'], text: '它跑回去问妈妈：“妈妈，我该听谁的呀？”' },
        { k: 'horse', bg: 'home', ems: ['🐴','👩','💡'], text: '妈妈温柔地说：“光听别人说不行，你要自己去试一试。”' },
        { k: 'river', bg: 'river', ems: ['🐴','💪','🌊'], text: '小马鼓起勇气，一步一步小心地走进了小河里。' },
        { k: 'river', bg: 'river', ems: ['🐴','💧','😊'], text: '河水不深也不浅，刚刚好到小马的肚子。' },
        { k: 'river', bg: 'river', ems: ['🐴','📦','🎉'], text: '小马安全地过了河，把粮食送到了河对面。' },
        { k: 'river', bg: 'river', ems: ['🐴','😊','☀️'], text: '它开心地想：原来河水没有牛伯伯说的那么浅，也没有小松鼠说的那么深。' },
        { k: 'horse', bg: 'dawn', ems: ['💡','🐴','⭐'], text: '别人说的不一定对，勇敢地去试一试，答案就在你脚下！' }
      ]
    },
    // === 曹冲称象（中国历史故事）—— 善于观察 ===
    {
      id: 'cao-chong-cheng-xiang', title: '曹冲称象', tag: '历史 · 智慧', color: '#9b59b6',
      pages: [
        { k: 'elephant', bg: 'sunny', ems: ['☀️','🏯','🌳'], text: '曹冲称象' },
        { k: 'boy', bg: 'sky', ems: ['👦','📖','💡'], text: '古时候有个聪明的孩子叫曹冲，是曹操的儿子。' },
        { k: 'elephant', bg: 'sunny', ems: ['🐘','👦','👥'], text: '有一天，有人送给曹操一头大象，大家都来观看。' },
        { k: 'elephant', bg: 'sunny', ems: ['🐘','😮','👀'], text: '大象好大呀，比房子还高，腿像大柱子一样粗。' },
        { k: 'elephant', bg: 'sunny', ems: ['👨','❓','🐘'], text: '曹操问：“这头大象有多重？谁能称出来？”' },
        { k: 'elephant', bg: 'sunny', ems: ['👥','🤔','⚖️'], text: '大臣们议论纷纷：这么大的象，哪有那么大的秤呀？' },
        { k: 'boy', bg: 'sunny', ems: ['👦','💡','✨'], text: '小曹冲眨眨眼睛说：“我有办法！”' },
        { k: 'boat', bg: 'river', ems: ['🐘','🚣','💧'], text: '他让人把大象牵到一艘大船上，船稳稳地浮在水面。' },
        { k: 'boat', bg: 'river', ems: ['船','💧','✏️'], text: '小曹冲在水面和船身相交的地方画了一条线。' },
        { k: 'stone', bg: 'river', ems: ['🐘','⬇️','💧'], text: '然后让人把大象牵下船，往船里放石头。' },
        { k: 'stone', bg: 'river', ems: ['🪨','🪨','⚖️'], text: '石头放啊放，水面慢慢升到了刚才画线的位置。' },
        { k: 'scale', bg: 'sunny', ems: ['⚖️','🪨','💡'], text: '小曹冲说：“现在只要称一称石头有多重就好了！”' },
        { k: 'scale', bg: 'sunny', ems: ['⚖️','🪨','👦'], text: '大臣们把石头搬上秤，终于知道了大象的重量。' },
        { k: 'father', bg: 'sunny', ems: ['👨','😊','👦'], text: '曹操高兴地笑了：我儿子比你们这些大人还聪明！' },
        { k: 'elephant', bg: 'dawn', ems: ['💡','🐘','⭐'], text: '遇到难题别放弃，换个角度想一想，办法总会有的！' }
      ]
    },
  ];

  function esc(s) {
    return String(s === undefined || s === null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function bookById(id) {
    for (var i = 0; i < BOOKS.length; i++) {
      if (BOOKS[i].id === id) return BOOKS[i];
    }
    return null;
  }

function picUrl(bid, idx) {
    return '/static/img/books/' + bid + '/p' + ('0' + (idx + 1)).slice(-2) + '.jpg';
  }

function imgFallback(el) {
    var parent = el && el.parentNode;
    if (!parent) return;
    if (el) el.style.display = 'none';
    var fb = parent.querySelector('.pb-emoji-fb');
    if (fb) fb.style.display = '';
  }

  function coverFallback(el, bid) {
    var parent = el && el.parentNode;
    if (!parent) return;
    if (el) el.style.display = 'none';
    var fb = parent.querySelector('.bk-fb');
    if (fb) fb.style.display = '';
  }

  // ---------- 首页「绘本阅读」区 ----------
  function renderBooksSection() {
    var cards = BOOKS.map(function (b) {
      return '<button type="button" class="book-card" data-bk="' + b.id + '" ' +
        'onclick="window.Edu.Books.openBook(\'' + b.id + '\')" ' +
        'title="' + esc(b.title) + '" aria-label="阅读《' + esc(b.title) + '》">' +
        '<span class="bk-cover" style="--bk:' + b.color + ';">' +
        '<img class="bk-img" src="' + picUrl(b.id, 0) + '" alt="" loading="lazy" ' +
        'onerror="window.Edu.Books.coverFallback(this, \'' + b.id + '\')">' +
        '<span class="bk-fb">' + (b.pages[0].ems || []).slice(0, 2).join('') + '</span>' +
        '</span>' +
        '<span class="bk-name">' + esc(b.title) + '</span>' +
        '<span class="bk-tag">' + esc(b.tag) + ' · ' + ((b.pages || []).length - 1) + '页</span>' +
        '</button>';
    }).join('');
    return '<section class="home-books-sec">' +
      '<div class="home-sec-head">' +
      '<span class="home-continue-head">📚 绘本阅读</span>' +
      '<span class="pb-sec-sub">有声 · 全屏 · 点开即读</span>' +
      '</div>' +
      '<div class="home-books-scroll">' + cards + '</div>' +
      '</section>';
  }

  // ---------- 阅读器状态 ----------
  var curBook = null, curPage = 0, curTotal = 0;
  var autoSay = true;
  var waitingDbl = false;

  function readerEl() { return document.getElementById('eduReader'); }

  function openBook(id) {
    var b = bookById(id);
    if (!b) return;
    curBook = b;
    curPage = 0;
    curTotal = b.pages.length;
    var wrap = readerEl();
    if (!wrap) return;
    wrap.style.display = 'flex';
    document.body.style.overflow = 'hidden';
    document.getElementById('pbTitle').textContent = b.title;
    renderPage();
    renderDots();
    if (autoSay) window.setTimeout(playPage, 350);
  }

  function closeReader() {
    stopSay();
    var wrap = readerEl();
    if (wrap) {
      wrap.style.display = 'none';
      if (document.fullscreenElement === wrap && document.exitFullscreen) {
        document.exitFullscreen().catch(function () {});
      }
    }
    document.body.style.overflow = '';
    curBook = null;
  }

  function renderPage() {
    if (!curBook) return;
    var p = curBook.pages[curPage];
    if (!p) return;
    var stage = document.getElementById('pbStage');
    var n = curPage + 1;
    var isCover = curPage === 0;
    var sceneHtml = (p.ems || []).map(function (e) { return '<span class="pb-emo">' + e + '</span>'; }).join('');
    var art = '<div class="pb-art">' +
      '<img class="pb-img" src="' + picUrl(curBook.id, curPage) + '" alt="" loading="lazy" ' +
      'onerror="window.Edu.Books.imgFallback(this)">' +
      '<div class="pb-emoji-fb pb-scene' + ((p.ems||[]).length >= 4 ? ' pb-scene-4' : (p.ems||[]).length === 3 ? ' pb-scene-3' : '') + '" style="display:none;">' + sceneHtml + '</div>' +
      '</div>';
    stage.innerHTML =
      '<div class="pb-page pb-' + esc(p.bg) + (isCover ? ' pb-cover' : '') + '">' +
      art +
      '<div class="pb-text-card">' +
      '<p class="pb-text">' + esc(p.text) + '</p>' +
      '<button type="button" class="pb-speak" onclick="window.Edu.Books.playPage()">🔊 读一读</button>' +
      '</div>' +
      '<div class="pb-page-no">' + n + ' / ' + curTotal + '</div>' +
      '</div>';
  }

  function renderDots() {
    var box = document.getElementById('pbDots');
    if (!box || !curBook) return;
    box.innerHTML = '';
    for (var i = 0; i < curTotal; i++) {
      var d = document.createElement('span');
      d.className = 'pb-dot' + (i === curPage ? ' on' : '');
      box.appendChild(d);
    }
  }

  function nextPage() {
    if (!curBook) return;
    if (curPage + 1 >= curTotal) {
      if (curTotal === 1) return;
      closeReader();
      return;
    }
    curPage++;
    renderPage();
    renderDots();
    if (autoSay) window.setTimeout(playPage, 380);
  }

  function prevPage() {
    if (!curBook) return;
    if (curPage <= 0) return;
    curPage--;
    renderPage();
    renderDots();
    if (autoSay) window.setTimeout(playPage, 380);
  }

  function playPage() {
    if (!curBook || !Speech) return;
    var p = curBook.pages[curPage];
    if (!p || !p.text) return;
    Speech.playSpeakForceNet(p.text);
  }
  function stopSay() {
    if (Speech && Speech.stopSpeech) Speech.stopSpeech();
  }

  function toggleAuto() {
    autoSay = !autoSay;
    var btn = document.getElementById('pbAuto');
    if (btn) btn.classList.toggle('off', !autoSay);
    if (autoSay) playPage();
  }

  function toggleFull() {
    var wrap = readerEl();
    if (!wrap) return;
    if (document.fullscreenElement) {
      if (document.exitFullscreen) document.exitFullscreen().catch(function () {});
    } else {
      var el = wrap;
      if (el.requestFullscreen) {
        el.requestFullscreen().catch(function () {
          wrap.classList.add('pb-fs-fallback');
        });
      }
    }
  }

  // ---------- 事件绑定(翻页: 点击左右区 / 键盘 / 滑动) ----------
  function bindReader() {
    var stage = document.getElementById('pbStage');
    if (!stage) return;
    stage.addEventListener('click', function (e) {
      if (!curBook) return;
      if (e.target.closest('button')) return;
      var rect = stage.getBoundingClientRect();
      var x = e.clientX - rect.left;
      var third = rect.width / 3;
      if (x > rect.width - third) {
        nextPage();
      } else if (x < third) {
        prevPage();
      }
    });
    document.addEventListener('keydown', function (e) {
      if (!curBook || readerEl().style.display !== 'flex') return;
      if (e.key === 'Escape') { closeReader(); return; }
      if (e.key === 'ArrowRight') nextPage();
      if (e.key === 'ArrowLeft') prevPage();
      if (e.key === ' ') { e.preventDefault(); playPage(); }
    });
    var startX = 0, startY = 0, tracking = false;
    stage.addEventListener('touchstart', function (e) {
      var t = e.touches[0];
      startX = t.clientX; startY = t.clientY; tracking = true;
    }, { passive: true });
    stage.addEventListener('touchend', function (e) {
      if (!tracking) return;
      tracking = false;
      var t = e.changedTouches[0];
      var dx = t.clientX - startX, dy = t.clientY - startY;
      if (Math.abs(dx) < 40 || Math.abs(dy) > Math.abs(dx) * 1.4) return;
      if (dx < 0) nextPage(); else prevPage();
    }, { passive: true });
    var back = document.getElementById('pbBack');
    if (back) back.addEventListener('click', closeReader);
    var auto = document.getElementById('pbAuto');
    if (auto) auto.addEventListener('click', toggleAuto);
    var full = document.getElementById('pbFull');
    if (full) full.addEventListener('click', toggleFull);
    var prevBtn = document.getElementById('pbPrev');
    if (prevBtn) prevBtn.addEventListener('click', prevPage);
    var nextBtn = document.getElementById('pbNext');
    if (nextBtn) nextBtn.addEventListener('click', nextPage);
    if (window.Edu && window.Edu.Speech && window.Edu.Speech.unlockAudio) {
      window.Edu.Speech.unlockAudio();
    }
  }

  // 延迟到 DOM 就绪后再绑定(模板中容器可能尚未渲染)
  function ensureInit() {
    if (window.__pbBound) return;
    if (document.getElementById('eduReader')) {
      window.__pbBound = true;
      bindReader();
    }
  }
  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', ensureInit);
    } else {
      ensureInit();
    }
    // 容错: 某些模板轮询几次确保绑定成功
    var _tries = 0;
    (function waitBind() {
      if (!window.__pbBound && _tries < 20) {
        _tries++;
        setTimeout(function () { ensureInit(); waitBind(); }, 120);
      }
    })();
  }

  window.Edu.Books = {
    list: BOOKS,
    openBook: openBook,
    closeReader: closeReader,
    nextPage: nextPage,
    prevPage: prevPage,
    playPage: playPage,
    toggleAuto: toggleAuto,
    toggleFull: toggleFull,
    renderBooksSection: renderBooksSection,
    imgFallback: imgFallback,
    coverFallback: coverFallback,
    autoSay: function () { return autoSay; }
  };
  window.openPicBook = openBook;
})();