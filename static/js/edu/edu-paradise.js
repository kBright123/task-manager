(function () {
  'use strict';
  var C = window.Edu.Constants;
  var M = window.Edu.MathUtils;
  var Store = window.Edu.Store;
  var Speech = window.Edu.Speech;
  var QuizEngine = window.Edu.QuizEngine;

  var PAR = { active: false, game: null, idx: 0, score: 0, items: [] };

  function parInit() {
    var grid = document.getElementById('parGameGrid');
    if (!grid) return;
    grid.innerHTML = C.PAR_GAMES.map(function(g){
      return '<button type="button" class="par-game" onclick="window.Edu.Paradise.parPlay(\''+g.key+'\')">'+
        '<div class="par-icon">'+g.icon+'</div>'+
        '<div class="par-name">'+g.name+'</div>'+
        '<div class="par-desc">'+g.desc+'</div>'+
        '</button>';
    }).join('');
    document.getElementById('parHome').style.display = '';
    document.getElementById('parPlay').style.display = 'none';
    PAR.active = false;
  }

  window.Edu.Paradise = {
    PAR: PAR,
    parInit: parInit
  };

  window.Edu.Paradise.parPlay = function (key) {
    var game = C.PAR_GAMES.find(function(g){ return g.key === key; });
    if (!game) return;
    PAR.active = true; PAR.game = key; PAR.idx = 0; PAR.score = 0; PAR.items = [];
    document.getElementById('parHome').style.display = 'none';
    var play = document.getElementById('parPlay');
    play.style.display = '';
    play.innerHTML = '<div class="par-hud" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">'+
      '<div>🎮 '+game.name+'</div>'+
      '<div id="parScore" style="font-weight:800;color:var(--edu-primary);">分数: 0</div>'+
      '</div><div id="parItem" style="min-height:200px;"></div>'+
      '<button type="button" class="btn-soft" style="width:100%;margin-top:12px;" onclick="window.Edu.Paradise.parBack()">返回</button>';
    parNextItem();
  };

  function parNextItem() {
    var item = document.getElementById('parItem');
    if (!item) return;
    if (PAR.idx >= 10) {
      item.innerHTML = '<div style="text-align:center;padding:30px;">🎉 游戏结束！<br>最终得分: <b>'+PAR.score+'</b>/100</div>';
      return;
    }
    var html = '';
    if (PAR.game === 'color') {
      var colors = ['红','黄','蓝','绿','紫','橙'];
      var correct = colors[Math.floor(Math.random()*colors.length)];
      var opts = colors.filter(function(c){return c!==correct;}).slice(0,3).concat(correct).sort(function(){return Math.random()-0.5;});
      PAR.items.push({prompt:'点击 '+correct, correct:correct, options:opts});
      html = '<div style="font-size:2.5rem;font-weight:800;text-align:center;margin-bottom:20px;color:var(--edu-ink);">请点击：'+correct+'</div>';
      html += '<div class="par-opts" style="display:flex;flex-wrap:wrap;gap:10px;justify-content:center;">'+opts.map(function(o){
        return '<button type="button" class="par-opt" style="border-radius:12px;border:3px solid var(--edu-border-2);font-size:1.5rem;font-weight:700;background:#fff;" onclick="window.Edu.Paradise.parAnswer(\''+o+'\')">'+o+'</button>';
      }).join('')+'</div>';
    } else if (PAR.game === 'shape') {
      var shapes = ['🔴','🔵','🟢','🟡','🟣','🟠'];
      var correct = shapes[Math.floor(Math.random()*shapes.length)];
      var opts = shapes.filter(function(s){return s!==correct;}).slice(0,3).concat(correct).sort(function(){return Math.random()-0.5;});
      PAR.items.push({prompt:'找出 '+correct, correct:correct, options:opts});
      html = '<div style="font-size:2rem;text-align:center;margin-bottom:20px;">请找出：'+correct+'</div>';
      html += '<div class="par-opts" style="display:flex;flex-wrap:wrap;gap:10px;justify-content:center;">'+opts.map(function(o){
        return '<button type="button" class="par-opt" style="border-radius:12px;border:3px solid var(--edu-border-2);font-size:2.5rem;background:#fff;" onclick="window.Edu.Paradise.parAnswer(\''+o.replace(/'/g,"\\'")+'\')">'+o+'</button>';
      }).join('')+'</div>';
    } else if (PAR.game === 'number') {
      var count = Math.floor(Math.random()*5)+1;
      var emojis = ['🍎','🍌','🍇','🍓','🥝','🍑'];
      var emoji = emojis[Math.floor(Math.random()*emojis.length)];
      var opts = Array.from({length:4},function(_,i){return i+1;}).sort(function(){return Math.random()-0.5;});
      if (!opts.includes(count)) opts[0] = count;
      PAR.items.push({prompt:'数一数有几个 '+emoji, correct:String(count), options:opts.map(String)});
      html = '<div style="font-size:3rem;text-align:center;margin-bottom:20px;">'+emoji.repeat(count)+'</div>';
      html += '<div style="text-align:center;margin-bottom:10px;color:var(--edu-muted);">上面有几个？</div>';
      html += '<div class="par-opts" style="display:flex;flex-wrap:wrap;gap:10px;justify-content:center;">'+opts.map(function(o){
        return '<button type="button" class="par-opt" style="border-radius:12px;border:3px solid var(--edu-border-2);font-size:1.8rem;font-weight:700;background:#fff;" onclick="window.Edu.Paradise.parAnswer(\''+o+'\')">'+o+'</button>';
      }).join('')+'</div>';
    } else if (PAR.game === 'animal') {
      var animals = [{name:'猫',sound:'喵喵',emoji:'🐱'},{name:'狗',sound:'汪汪',emoji:'🐶'},{name:'鸭',sound:'嘎嘎',emoji:'🦆'},{name:'牛',sound:'哞哞',emoji:'🐮'},{name:'羊',sound:'咩咩',emoji:'🐑'},{name:'猪',sound:'哼哼',emoji:'🐷'}];
      var correct = animals[Math.floor(Math.random()*animals.length)];
      var opts = animals.filter(function(a){return a.name!==correct.name;}).slice(0,3).concat(correct).sort(function(){return Math.random()-0.5;});
      PAR.items.push({prompt:'听声音找 '+correct.name, correct:correct.name, options:opts.map(function(a){return a.name;})});
      html = '<div style="font-size:2rem;text-align:center;margin-bottom:10px;">听：'+correct.sound+'</div>';
      html += '<div class="par-opts" style="display:flex;flex-wrap:wrap;gap:10px;justify-content:center;">'+opts.map(function(a){
        return '<button type="button" class="par-opt" style="border-radius:12px;border:3px solid var(--edu-border-2);font-size:2.5rem;background:#fff;" onclick="window.Edu.Paradise.parAnswer(\''+a.name+'\')">'+a.emoji+'</button>';
      }).join('')+'</div>';
    } else if (PAR.game === 'fruit') {
      var fruits = ['🍎','🍌','🍇','🍓','🥝','🍑','🍊','🍋'];
      var correct = fruits[Math.floor(Math.random()*fruits.length)];
      var opts = fruits.filter(function(f){return f!==correct;}).slice(0,3).concat(correct).sort(function(){return Math.random()-0.5;});
      PAR.items.push({prompt:'找出 '+correct, correct:correct, options:opts});
      html = '<div style="font-size:3rem;text-align:center;margin-bottom:20px;">哪个是水果？</div>';
      html += '<div class="par-opts" style="display:flex;flex-wrap:wrap;gap:10px;justify-content:center;">'+opts.map(function(o){
        return '<button type="button" class="par-opt" style="border-radius:12px;border:3px solid var(--edu-border-2);font-size:2.5rem;background:#fff;" onclick="window.Edu.Paradise.parAnswer(\''+o.replace(/'/g,"\\'")+'\')">'+o+'</button>';
      }).join('')+'</div>';
    }
    item.innerHTML = html;
  }

  window.Edu.Paradise.parAnswer = function (val) {
    if (!PAR.active || !PAR.items[PAR.idx]) return;
    var it = PAR.items[PAR.idx];
    var ok = val === it.correct;
    if (ok) { PAR.score += 10; Speech.playSpeak('答对了'); }
    else { Speech.playSpeak('再试一次'); }
    document.getElementById('parScore').textContent = '分数: ' + PAR.score;
    PAR.idx++;
    if (PAR.timer) clearTimeout(PAR.timer);
    PAR.timer = setTimeout(parNextItem, 600);
  };

  window.Edu.Paradise.parBack = function () {
    if (PAR.timer) { clearTimeout(PAR.timer); PAR.timer = null; }
    PAR.active = false;
    document.getElementById('parHome').style.display = '';
    document.getElementById('parPlay').style.display = 'none';
  };
  window.parPlay = window.Edu.Paradise.parPlay;
})();