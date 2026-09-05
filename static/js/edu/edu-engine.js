(function () {
  'use strict';
  var C = window.Edu.Constants;
  var M = window.Edu.MathUtils;
  var Store = window.Edu.Store;

  // 内部状态引用
  var state = Store.state;

  // PASS_Q = 7; // 10题答对7题算过关

  function diffOf(subj) { return M.diffOf(subj); }

  var GEN = {
    zh_poem: function(d){ var w = C.POEMS[M.randInt(C.POEMS.length)]; var v = w.lines;
      var idx = M.randInt(v.length);
      var blank = v[idx];
      var lines = v.slice();
      lines[idx] = '____';
      var p = w.title + '：' + lines.join('，');
      return { id:'poem_'+w.id+'_'+blank, prompt:p, big:blank,
        options:M.makeOptions(blank, v.filter(function(x){return x!==blank;}).slice(0,2).concat(blank).sort(function(){return Math.random()-0.5;}), 3), correct:blank, note:w.title + ' - ' + w.author }; },
    zh_zi: function(d){ var z = C.ZI[M.randInt(C.ZI.length)];
      return { id:'zi_'+z.id, prompt:'“'+z.prompt+'”对应的汉字是？', big:z.prompt,
        options:M.makeOptions(z.prompt, C.ZI.map(function(x){return x.prompt;}), d>=4?4:3), correct:z.prompt, note:z.prompt+'（'+z.pinyin+'）' }; },
    zh_stroke: function(d){ var s = C.STROKES[M.randInt(C.STROKES.length)]; var c = s.order.length;
      return { id:'stroke_'+s.id, prompt:'「'+s.char+'」这个字一共有几笔？', big:s.char,
        options:M.makeOptions(c, [Math.max(2,c-1), c-2, c+1].filter(function(x){return x>0;}), d>=4?4:3), correct:c, note:c+' 笔' }; },
    zh_pinyin: function(d){ var x = C.P_SHENG[M.randInt(C.P_SHENG.length)];
      return { id:'pinyin_'+x.id, prompt:'「'+x.zi+'（'+x.py+'）」的声母是？', big:x.e+' '+x.zi, mouth:C.mouthOf(x.s),
        options:M.makeOptions(x.s, C.P_SHENG.map(function(t){return t.s;}).filter(function(t){return t!==x.s;}).slice(0,2).concat(x.s).sort(function(){return Math.random()-0.5;}), d>=4?4:3), correct:x.s, note:'声母 '+x.s+' · 口型：'+C.mouthOf(x.s) }; },
    zh_yun: function(d){ var x = C.P_YUN[M.randInt(C.P_YUN.length)];
      return { id:'yun_'+x.id, prompt:'「'+x.zi+'（'+x.py+'）」的韵母是？', big:x.e+' '+x.zi, mouth:C.mouthOf(x.u),
        options:M.makeOptions(x.u, C.P_YUN.map(function(t){return t.u;}).filter(function(t){return t!==x.u;}).slice(0,2).concat(x.u).sort(function(){return Math.random()-0.5;}), d>=4?4:3), correct:x.u, note:'韵母 '+x.u+' · 口型：'+C.mouthOf(x.u) }; },
    zh_read: function(d){ var x = C.P_READ[M.randInt(C.P_READ.length)];
      return { id:'read_'+x.id, prompt:'「'+x.zi+'」这个字怎么读？', big:x.e+' '+x.zi, mouth:C.readMouth(x.py),
        options:M.makeOptions(x.py, C.P_READ.map(function(t){return t.py;}), d>=4?4:3), correct:x.py, note:x.py+' · 口型：'+C.readMouth(x.py) }; },
    zh_tone: function(d){ var x = C.P_READ[M.randInt(C.P_READ.length)];
      var t = M.toneOf(x.py);
      return { id:'tone_'+x.id, prompt:'「'+x.zi+'」读「'+x.py+'」，它是第几声呀？', big:x.e+' '+x.zi,
        options:M.makeOptions(t, [1,2,3,4], 4, function(n){ return M.toneName(n)+'（'+M.toneEmoji(n)+'）'; }),
        correct:t, note:x.py+' · '+M.toneName(t) }; },
    zh_fan: function(d){ var x = C.FANCI[M.randInt(C.FANCI.length)];
      return { id:'fan_'+x.id, prompt:x.prompt, big:x.correct,
        options:M.makeOptions(x.correct, C.FANCI.map(function(t){return t.correct;}), d>=4?4:3), correct:x.correct, note:x.prompt.replace('_',x.correct) }; },
    zh_liang: function(d){ var x = C.LIANGCI[M.randInt(C.LIANGCI.length)];
      return { id:'liang_'+x.id, prompt:x.prompt, big:x.correct,
        options:M.makeOptions(x.correct, C.LIANGCI.map(function(t){return t.correct;}), 4), correct:x.correct, note:x.prompt.replace('____',x.correct) }; },
    math_calc: function(d){ var c = M.calcCfg(d); return M.makeCalcItem(M.makeCalc(c.max, c.nocarry, c.mult)); },
    math_judge: function(d){ var c = M.calcCfg(d); return M.makeJudgeItem(M.makeCalc(c.max, c.nocarry, c.mult), M.randInt(10)); },
    math_word: function(d){ var q3 = (Math.random()<0.5) ? C.WORD_PLUS[Math.floor(Math.random()*C.WORD_PLUS.length)] : C.WORD_MINUS[Math.floor(Math.random()*C.WORD_MINUS.length)]; return M.makeWordItem(q3); },
    math_order: function(d){ var max = C.LEVEL_RANGE[Math.max(0, Math.min(4, d-1))];
      var pool = []; for (var n=1;n<=max;n++) pool.push(n);
      pool.sort(function(){ return Math.random()-0.5; });
      var nums = pool.slice(0,5).sort(function(a,b){ return a-b; });
      return { id:'order_'+nums.join(','), order:true, prompt:'从小到大排一排：'+nums.join('、'),
        expected:nums, correct:nums.join('|'), note:'从小到大：'+nums.join(' → ') }; },
    en_word: function(d){ var w = C.WORDS[M.randInt(C.WORDS.length)];
      return { id:'enword_'+w.id, prompt:(w.cn ? '“'+w.cn+'”的英文是？' : '看图画，选对应的英文单词'), big:w.emoji,
        options:M.makeOptions(w.word, C.WORDS.map(function(x){return x.word;}), d>=4?4:3), correct:w.word, note:w.word+'（'+w.cn+'）' }; },
    en_dialogue: function(d){ var x = C.DIALOGUES[M.randInt(C.DIALOGUES.length)];
      return { id:'endia_'+x.id, prompt:'“'+x.cn+'”用英语怎么说？', big:x.emoji+' '+x.cn,
        options:M.makeOptions(x.en, C.DIALOGUES.map(function(t){return t.en;}), d>=4?4:3), correct:x.en, note:x.en }; }
  };

  function genOne(subj, type, diff) {
    var f = GEN[subj+'_'+type];
    return f ? f(diff||3) : null;
  }

  function qbToItem(q) {
    var it = { id:'qb_'+q.id, prompt:q.prompt,
      options:(q.options && q.options.length) ? q.options : undefined,
      input:(q.options && q.options.length) ? undefined : true,
      correct:String(q.correct), note:q.note||'' , wtype:q.type };
    // 从内容池重建 big
    if (q.subj === 'zh'){
      if (q.type === 'zi'){
        var m = (q.prompt||'').match(/“(.+?)”对应的汉字是？/);
        var zs = m && C.ZI.find(function(x){ return x.word === m[1]; });
        if (zs){ it.big = zs.emoji+' '+zs.word; it.options = M.makeOptions(zs.zi, C.ZI.map(function(x){return x.zi;}), 3); }
      } else if (q.type === 'read'){
        m = (q.prompt||'').match(/「(.+?)」这个字怎么读？/);
        var rs = m && C.P_READ.find(function(x){ return x.zi === m[1]; });
        if (rs) it.big = rs.e+' '+rs.zi;
      } else if (q.type === 'pinyin' || q.type === 'yun' || q.type === 'tone'){
        m = (q.prompt||'').match(/「(.+?)（(.+?)）」/);
        var ps = m && C.P_SHENG.find(function(x){ return x.py === m[2]; }) && { e:C.P_SHENG.find(function(x){ return x.py === m[2]; }).e, zi:C.P_SHENG.find(function(x){ return x.py === m[2]; }).zi }
                 || (m && C.P_YUN.find(function(x){ return x.py === m[2]; })) && { e:C.P_YUN.find(function(x){ return x.py === m[2]; }).e, zi:C.P_YUN.find(function(x){ return x.py === m[2]; }).zi }
                 || (m && C.P_READ.find(function(x){ return x.py === m[2]; }));
        if (ps) it.big = ps.e+' '+(ps.zi||'');
      } else if (q.type === 'fan'){
        m = (q.prompt||'').match(/「(.+?)」的反义词是？/);
        var fs = m && C.FANCI.find(function(x){ return x.zi === m[1]; });
        if (fs) it.big = fs.e+' '+fs.zi;
      }
    }
    return it;
  }

  function isLegacyPrompt(p){
    var s = p || '';
    return /(《.+?》里，空格处填什么？|这个词语对应的汉字是？|这个字怎么读？|看图画，选对应的英文单词|这句话用英语怎么说？|把数字按从小到大排好|补全《.+?》|……)/.test(s);
  }

  function poemTitle(p){ var m = (p||'').match(/《(.+?)》/); return m ? m[1] : ''; }

  function rebuildWrong(subj, type, w, diff){
    var d = diff || 3;
    var out = function(it){ return it || genOne(subj, type, d); };
    var m;
    var zs, rs, fs, ls, ws, ds;
    if (subj === 'zh'){
      if (type === 'poem'){
        var t = poemTitle(w.prompt);
        var src = t && C.POEMS.find(function(x){ return x.title === t; });
        if (src){
          var v = src.lines;
          var idx = M.randInt(v.length);
          var blank = v[idx];
          var lines = v.slice();
          lines[idx] = '____';
          var hd = lines.slice(0,idx).join('，');
          var tl = lines.slice(idx+1).join('，');
          return out({ id:w.q, prompt:(hd ? '《'+src.title+'》'+hd+'，____，'+tl : '《'+src.title+'》____，'+tl), big:blank,
            options:M.makeOptions(blank, v.filter(function(x){return x!==blank;}).slice(0,2).concat(blank).sort(function(){return Math.random()-0.5;}), 3), correct:blank, note:src.title + ' - ' + src.author });
        }
      } else if (type === 'zi'){
        m = (w.prompt||'').match(/“(.+?)”对应的汉字是？/);
        zs = m && C.ZI.find(function(x){ return x.word === m[1]; });
        if (zs) return out({ id:w.q, prompt:'“'+zs.word+'”对应的汉字是？', big:zs.emoji+' '+zs.word,
          options:M.makeOptions(zs.zi, C.ZI.map(function(x){ return x.zi; }), 3), correct:zs.zi, note:zs.zi+'（'+zs.pinyin+'）' });
      } else if (type === 'read'){
        m = (w.prompt||'').match(/「(.+?)」这个字怎么读？/);
        rs = m && C.P_READ.find(function(x){ return x.zi === m[1]; });
        if (rs) return out({ id:w.q, prompt:'「'+rs.zi+'」这个字怎么读？', big:rs.e+' '+rs.zi,
          options:M.makeOptions(rs.py, C.P_READ.map(function(x){ return x.py; }), 3), correct:rs.py, note:rs.py });
      } else if (type === 'fan'){
        m = (w.prompt||'').match(/「(.+?)」的反义词是？/);
        fs = m && C.FANCI.find(function(x){ return x.zi === m[1]; });
        if (fs) return out({ id:w.q, prompt:'「'+fs.zi+'”的反义词是？', big:fs.e+' '+fs.zi,
          options:M.makeOptions(fs.fan, C.FANCI.map(function(x){ return x.fan; }), 3), correct:fs.fan, note:fs.zi+'——'+fs.fan });
      } else if (type === 'liang'){
        m = (w.prompt||'').match(/「(.+?)\s*__\s*(.+?)」填哪个量词？/);
        ls = m && C.LIANGCI.find(function(x){ return x.n === (m[2]||''); });
        if (ls) return out({ id:w.q, prompt:'「'+ls.zi+' __ '+ls.n+'」填哪个量词？', big:ls.zi+' __',
          options:M.makeOptions(ls.m, ['个','只','朵','条','棵','本','辆','双','支','张'], 4), correct:ls.m, note:ls.zi+ls.m+ls.n });
      }
    } else if (subj === 'en'){
      if (type === 'word'){
        m = (w.prompt||'').match(/"(.+?)"的英文是？/);
        ws = m && C.WORDS.find(function(x){ return x.cn === m[1]; });
        if (ws) return out({ id:w.q, prompt:'“'+ws.cn+'”的英文是？', big:ws.emoji,
          options:M.makeOptions(ws.word, C.WORDS.map(function(x){ return x.word; }), 3), correct:ws.word, note:ws.word+'（'+ws.cn+'）' });
      } else if (type === 'dialogue'){
        m = (w.prompt||'').match(/"(.+?)"用英语怎么说？/);
        ds = m && C.DIALOGUES.find(function(x){ return x.cn === m[1]; });
        if (ds) return out({ id:w.q, prompt:'“'+ds.cn+'”用英语怎么说？', big:ds.emoji+' '+ds.cn,
          options:M.makeOptions(ds.en, C.DIALOGUES.map(function(x){ return x.en; }), 3), correct:ds.en, note:ds.en });
      }
    } else if (subj === 'math'){
      if (type === 'calc'){
        m = (w.prompt||'').match(/(\d+)\s*([+\-])\s*(\d+)\s*=\s*\?/);
        if (m){
          var a=+m[1], b=+m[3], ans = m[2]==='+' ? a+b : a-b;
          return out({ id:w.q, prompt:w.prompt, input:true, correct:String(ans), note:w.prompt.replace(/=\s*\?/, '= '+ans) });
        }
      } else if (type === 'judge'){
        m = (w.prompt||'').match(/(\d+)\s*([+\-])\s*(\d+)\s*＝\s*(\d+)/);
        if (m){
          var ja=+m[1], jb=+m[3], real = m[2]==='+' ? ja+jb : ja-jb, shown = +m[4];
          var tf = real === shown ? '对' : '错';
          return out({ id:w.q, prompt:w.prompt, options:[{v:'对',label:'✅ 对'},{v:'错',label:'❌ 错'}],
            correct:tf, note:w.prompt.replace('，对吗？','')+'（答：'+tf+'）' });
        }
      } else if (type === 'order'){
        var nums = String(w.correct||'').split('|').map(function(x){ return +x; }).sort(function(x,y){ return x-y; });
        if (nums.length) return out({ id:w.q, order:true, prompt:'从小到大排一排：'+nums.join('、'),
          expected:nums, correct:nums.join('|'), note:'从小到大：'+nums.join(' → ') });
      }
    }
    return out(null);
  }

  function assemble(subj, type){
    var diff = diffOf(subj);
    return new Promise(function(resolve){
      var items = [];
      var seen = {};
      function add(it){ if (it && it.prompt && !seen[it.prompt] && items.length < C.QUIZ_LEN){ seen[it.prompt]=1; items.push(it); } }
      // 1) 错题优先(~一半): 到期/逾期的排在前面(间隔复习), 其余随机
      var nowT = Date.now();
      var wrongs = (state.wrong||[]).filter(function(w){ return w.subj===subj && w.type===type; })
        .slice().sort(function(a, b){
          var da = (a.nextDue === undefined || a.nextDue <= nowT) ? 0 : 1;
          var db = (b.nextDue === undefined || b.nextDue <= nowT) ? 0 : 1;
          if (da !== db) return da - db;
          return Math.random()-0.5;
        }).slice(0, Math.ceil(C.QUIZ_LEN/2));
      wrongs.forEach(function(w){
        var it2 = rebuildWrong(subj, type, w, diff);
        if (!it2) return;
        it2.id = 'wg_'+w.q;
        it2.note = (it2.note||'') + ' · 巩固';
        add(it2);
      });
      var exclude = items.map(function(i){ return i.prompt; }).concat((Store.recentExclude || []).slice(0, 60));
      // 2) 若该关卡已通关, 排除已答对的题目(避免重复出题)
      var adv = state.adv && state.adv[subj] && state.adv[subj][type];
      var isPassed = !!(adv && adv.passed);
      if (isPassed && state.passedQuestions) {
        var pKey = subj + '::' + type;
        var passedList = state.passedQuestions[pKey] || [];
        exclude = exclude.concat(passedList);
      }
      function finish(list){
        (list||[]).forEach(function(i){ if (i && i.prompt){ (Store.recentExclude = Store.recentExclude || []).push(i.prompt); } });
        while ((Store.recentExclude || []).length > 80) (Store.recentExclude || []).shift();
        resolve(list);
      }
      var fresh = [];
      function fillToLen(){
        var guard = 0;
        while (items.length < C.QUIZ_LEN && guard++ < 120){
          var it = genOne(subj, type, diff);
          if (!it || seen[it.prompt]) continue;
          if ((Store.recentExclude || []).indexOf(it.prompt) >= 0) continue;
          seen[it.prompt] = 1; items.push(it); if (fresh.length < 120) fresh.push(it);
        }
        guard = 0;
        while (items.length < C.QUIZ_LEN && guard++ < 120){
          var it2 = genOne(subj, type, diff);
          if (!it2 || seen[it2.prompt]) continue;
          seen[it2.prompt] = 1; items.push(it2); if (fresh.length < 120) fresh.push(it2);
        }
      }
      if (window.eduSync && window.eduSync.qbankPull){
        window.eduSync.qbankPull({ subj:subj, type:type, difficulty:diff, limit:C.QUIZ_LEN, exclude:exclude })
          .then(function(res){
            (res && res.items || []).forEach(function(q){ if (!isLegacyPrompt(q.prompt)) add(qbToItem(q)); });
            fillToLen();
            if (window.eduSync && window.eduSync.qbankEnsure && fresh.length){
              window.eduSync.qbankEnsure({ subj:subj, type:type, difficulty:diff,
                items: fresh.filter(function(x){return x&&x.prompt;}).map(function(x){
                  return { prompt:x.prompt, options:x.options||[], correct:x.correct, note:x.note||'' };
                }) });
            }
            finish(items);
          })
          .catch(function(){ fillToLen(); finish(items); });
      } else {
        fillToLen(); finish(items);
      }
    });
  }

  window.eduEngine = {
    genOne: genOne,
    assemble: assemble,
    diffOf: diffOf,
    rebuildWrong: rebuildWrong,
    isLegacyPrompt: isLegacyPrompt
  };
})();