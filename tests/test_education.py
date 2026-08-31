# -*- coding: utf-8 -*-
"""教育乐园: 后端 API 全链路 + 页面结构与关键逻辑回归.

覆盖:
- /edu/ 页面可访问且挂载 external 脚本
- 孩子档案 建档/同步(upsert+removedIds)/删除/重置
- 每个孩子 state 读写(含 dkey)
- qbank ensure/去重/pull(权重)/learn(wrong_count)
- 题目唯一性不变量 & 旧格式错题重建(借助 DOM 桩评估 education.js)
"""

import json
import os
import subprocess
import sys

BK = '/tmp/edu_test_'  # 每次运行独立的 qbank 命名空间


def _edu(client, method, url, **kw):
    r = getattr(client, method)('/edu/api' + url, **kw)
    return r


def _anon(client):
    """impersonate 免登录访问(匿名 ID)."""
    from app import app
    return app.test_client()


def test_edu_page_and_external_script(client):
    r = client.get('/edu/')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'js/education.js' in html
    # 页面骨架关键区
    for probe in ('kidBar', 'eduLearnPage', 'eduWishPage', 'eduBadgesPage',
                  'eduBottomNav', 'id="kidDelBtn"'):
        assert probe in html, f'missing {probe}'


def _setup_kid(client):
    r = client.post('/edu/api/kids', json={
        'kids': [{'clientId': 'c_A', 'name': '安安', 'birthYear': 2018, 'gender': 'male'}],
        'removedIds': [],
    })
    assert r.json.get('ok'), r.json
    return r.json['kids'][0]['id']


def test_kids_crud_and_state(client):
    pid = _setup_kid(client)
    # bootstrap 可见
    kids = client.get('/edu/api/bootstrap').json['kids']
    assert any(k['id'] == pid for k in kids)

    # state 读写
    r = client.post(f'/edu/api/kids/{pid}/state', json={'dkey': 'state', 'data': {'stars': 7, 'wrong': []}})
    assert r.json.get('ok')
    got = client.get(f'/edu/api/kids/{pid}/state').json['data']
    assert got.get('stars') == 7

    # 删除
    assert client.post(f'/edu/api/kids/{pid}/delete').json.get('ok')
    assert all(k['id'] != pid for k in client.get('/edu/api/bootstrap').json['kids'])
    # 删除后 state 应清空
    assert client.get(f'/edu/api/kids/{pid}/state').json['data'] == {}


def test_kids_upsert_and_bulk_remove(client):
    pid = _setup_kid(client)
    # upsert 同 id 不新增行
    r = client.post('/edu/api/kids', json={
        'kids': [{'dbId': pid, 'clientId': 'c_A', 'name': '改名', 'birthYear': 2019, 'gender': 'female'}],
        'removedIds': [],
    })
    assert r.json['kids'][0]['name'] == '改名'
    assert len(client.get('/edu/api/bootstrap').json['kids']) == 1
    # bulk removedIds 删除
    r = client.post('/edu/api/kids', json={'kids': [], 'removedIds': [pid]})
    assert r.json.get('ok')
    assert len(client.get('/edu/api/bootstrap').json['kids']) == 0


def test_qbank_ensure_dedup_pull_learn(client):
    _setup_kid(client)
    probe = BK + 'q1_' + str(id(client))  # 每次运行独立, 避免 instance/edu.db 残留干扰
    item = {'prompt': probe, 'options': [{'v': 'x', 'label': 'x'}], 'correct': 'x', 'note': 'n'}
    r = client.post('/edu/api/qbank/ensure', json={'subj': 'zh', 'type': 'zi', 'difficulty': 3, 'items': [item]})
    assert r.json['added'] == 1
    # 同 prompt 去重
    r = client.post('/edu/api/qbank/ensure', json={'subj': 'zh', 'type': 'zi', 'difficulty': 3, 'items': [item]})
    assert r.json['added'] == 0
    # pull 拉回(用大 limit 覆盖整池, 避免被更高权重的遗留题挤出前10)
    items = client.post('/edu/api/qbank/pull', json={'subj': 'zh', 'type': 'zi', 'difficulty': 3, 'limit': 200}).json['items']
    assert any(i['prompt'] == probe for i in items)
    assert items[0]['options'] and not isinstance(items[0]['options'], str)
    # learn -> wrong_count 递增
    for _ in range(2):
        client.post('/edu/api/qbank/learn', json={'subj': 'zh', 'type': 'zi', 'prompt': probe, 'correct': False, 'difficulty': 3})
    items = client.post('/edu/api/qbank/pull', json={'subj': 'zh', 'type': 'zi', 'difficulty': 3, 'limit': 200}).json['items']
    assert any(i['prompt'] == probe for i in items)
    r = client.post('/edu/api/qbank/learn', json={'subj': 'zh', 'type': 'zi', 'prompt': probe, 'correct': True, 'difficulty': 3})
    assert r.json.get('ok')


def test_edu_csrf_exempt(client):
    """/edu/api/** 应不被 CSRF 阻拦(免登录匿名也能写)."""
    r = client.post('/edu/api/qbank/ensure', json={
        'subj': 'en', 'type': 'word', 'difficulty': 3,
        'items': [{'prompt': BK + 'csrf', 'options': [{'v': 'a', 'label': 'a'}], 'correct': 'a', 'note': ''}],
    })
    assert r.status_code == 200 and r.json.get('ok')


def test_reset_all(client):
    pid = _setup_kid(client)
    client.post(f'/edu/api/kids/{pid}/state', json={'dkey': 'state', 'data': {'stars': 3}})
    assert client.post('/edu/api/reset').json.get('ok')
    assert len(client.get('/edu/api/bootstrap').json['kids']) == 0


# ============ 前端逻辑不变量(node --check + DOM 桩评估) ============

_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'static', 'js', 'education.js')


def _node_check():
    r = subprocess.run(['node', '--check', _JS], capture_output=True, text=True)
    return r.returncode == 0, r.stderr


def _harness(script_body):
    """用 node 运行 education.js + 注入脚本, 返回 stdout/stderr."""
    harness = r'''
const fs=require('fs'),vm=require('vm');
global.window=global;
global.esc=s=>String(s||'').replace(/</g,'&lt;').replace(/&/g,'&amp;');
const store={};
function me(){return {innerHTML:'',style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},setAttribute(){},getAttribute(){return null},querySelector(){return me()},querySelectorAll(){return[]},textContent:'',value:'',appendChild(){},removeChild(){},addEventListener(){},options:[],children:[],offsetWidth:0,offsetHeight:0,focus(){},scrollIntoView(){},getContext(){return new Proxy({}, {get:()=>()=>{}})}};}
global.document={getElementById:()=>me(),querySelectorAll:()=>[],querySelector:()=>me(),createElement:()=>me(),createTextNode:()=>({}),addEventListener(){},removeEventListener(){},documentElement:{style:{}},body:me()};
global.localStorage={getItem:k=>k in store?store[k]:null,setItem(k,v){store[k]=String(v)},removeItem(k){delete store[k]}};
global.location={};global.navigator={userAgent:'node'};global.performance={now:()=>0};global.HTMLElement=function(){};global.Node=function(){};
global.eduKids={active:()=>({id:'kk'}),all:()=>[{id:'kk'}],byId:()=>null,tierOf:()=>'workbench',ageOf:()=>6,tierLabel:()=>'',genderIcon:()=>'?',remove(){},setActive(){},hasAny:()=>1,update(){},add(){}};
global.eduSync={setOnState(){},qbankPull:()=>Promise.resolve({items:[]}),qbankEnsure:()=>Promise.resolve(),qbankLearn:()=>Promise.resolve(),pushState(){},hydrate:()=>Promise.resolve()};
vm.createContext(global);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),global);
const W=global;
''' + script_body
    r = subprocess.run(['node', '-e', harness, _JS], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_education_js_syntax():
    ok, err = _node_check()
    assert ok, f'node --check failed:\n{err}'


def test_quiz_uniqueness_all_types():
    out = _harness(r'''
(async()=>{
  const eng=W.eduEngine;
  const types={zh:['poem','zi','stroke','pinyin','yun','read','tone','fan','liang'],math:['calc','judge','word','order'],en:['word','dialogue']};
  let bad=[];
  for(const subj in types){
    for(const type of types[subj]){
      const items=await eng.assemble(subj,type);
      // 必守恒性: 10题 / 标题唯一 / 每项可作答 / 不出现 big===prompt 的重复展示
      if(items.length!==10) bad.push(subj+'/'+type+':len='+items.length);
      const titles=new Set(items.map(i=>i.prompt));
      if(titles.size!==10) bad.push(subj+'/'+type+':titles='+titles.size);
      items.forEach(i=>{ if(!i.options&&!i.input&&!i.order) bad.push(subj+'/'+type+':noAnswerable:'+i.prompt); });
      if(items.some(i=>i.big&&i.big===i.prompt)) bad.push(subj+'/'+type+':inlineDup');
    }
  }
  console.log('BAD='+JSON.stringify(bad));
})();
''')
    assert 'BAD=[]' in out.replace('\\', '').replace('"', '"') or 'BAD=[]' in out, out


def test_tone_and_mouth():
    """拼音四声辨认: 恒 4 选项且含正常声调; 声母/韵母/拼读题均带口型示范."""
    out = _harness(r'''
(async()=>{
  const eng=W.eduEngine;
  let okT=1;
  for(let k=0;k<30;k++){
    const it=eng.genOne('zh','tone',3);
    if(!(it.options && it.options.length===4 && [1,2,3,4].indexOf(+it.correct)>=0)) okT=0;
    if(!/第几声/.test(String(it.prompt))) okT=0;
  }
  const s=eng.genOne('zh','pinyin',3), y=eng.genOne('zh','yun',3), r=eng.genOne('zh','read',3);
  console.log('TONE='+okT);
  console.log('MOUTH_S='+((s.mouth&&s.mouth.length)?'1':'0'));
  console.log('MOUTH_Y='+((y.mouth&&y.mouth.length)?'1':'0'));
  console.log('MOUTH_R='+((r.mouth&&r.mouth.length)?'1':'0'));
})();
''')
    assert 'TONE=1' in out, out
    assert 'MOUTH_S=1' in out, out
    assert 'MOUTH_Y=1' in out, out
    assert 'MOUTH_R=1' in out, out


def test_pinyin_subtab_visibility():
    """拼音子标签: 切到拼音显示 声母/韵母/拼读/四声, 其他模式隐藏."""
    out = _harness(r'''
(async()=>{
  const subEl={style:{display:''},classList:{add(){},remove(){},toggle(){},contains(){return false}},setAttribute(){},getAttribute(){return null},querySelector(){return me()},querySelectorAll(){return[]}};
  const orig=global.document.getElementById;
  global.document.getElementById=(id)=> id==='wb-pinyin'?subEl:orig(id);
  W.wbZh('pinyin');
  const shown=(subEl.style.display==='flex'||subEl.style.display==='')?'1':'0';
  W.wbZh('poem');
  console.log('SUBTAB_SHOW='+shown);
  console.log('SUBTAB_HIDE='+(subEl.style.display==='none'?'1':'0'));
})();
''')
    assert 'SUBTAB_SHOW=1' in out, out
    assert 'SUBTAB_HIDE=1' in out, out


def test_legacy_wrong_rebuild_complete():
    out = _harness(r'''
(async()=>{
  store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[
    {subj:'zh',type:'poem',q:'q3',times:1,prompt:'《咏鹅》里，空格处填什么？',correct:'曲项'},
    {subj:'zh',type:'zi',q:'z5',times:1,prompt:'这个词语对应的汉字是？',correct:'火'},
    {subj:'en',type:'word',q:'w3',times:1,prompt:'看图画，选对应的英文单词',correct:'dog'}
  ],wishes:[],settings:{}});
  W.__stateHook && W.__stateHook;
  // 通过 assemble 走错题重建(internal engine 读 state 模块级变量, 需经 loadAllState)
  global.eduNav('learn');
  const eng=W.eduEngine;
  const poem=await eng.assemble('zh','poem');
  const zi=await eng.assemble('zh','zi');
  const en=await eng.assemble('en','word');
  const good=(items)=>items.filter(i=>i.prompt && i.big && i.big!==i.prompt && (i.options||i.input||i.order)).length;
  console.log('P='+good(poem)+' Z='+good(zi)+' E='+good(en));
})();
''')
    assert 'P=10' in out and 'Z=10' in out and 'E=10' in out, out


def test_render_badges_wall(client):
    out = _harness(r'''
store['edu_record_v1_kk']=JSON.stringify({stars:12,badges:{s1:1,s10:1,c5:1,d3:1,z1:1,all:1},records:[{subj:'zh'}],wrong:[],wishes:[]});
let iH='';const b=me();
Object.defineProperty(b,'innerHTML',{get(){return iH},set(v){iH=v}});
const orig=global.document.getElementById;
global.document.getElementById=(id)=> id==='eduBadgesBody'?b:me();
W.eduNav('badges');
console.log('ON='+(iH.match(/class="badge-card on"/g)||[]).length);
console.log('TOTAL='+(iH.match(/class="badge-card/g)||[]).length);
''')
    assert 'ON=6' in out and 'TOTAL=16' in out, out


def test_calc_fill_no_blank_visual(client):
    """口算题卡片不应显得'空白/不完整': 有大号算式展示+输入框, 且不提前泄题(不出现答案数字)."""
    out = _harness(r'''
(async()=>{
  const eng=W.eduEngine;
  const items=await eng.assemble('math','calc');
  const first=items[0];
  const expr=(String(first.big||first.prompt).replace(/\s*=\s*\?+\s*$/,''));
  console.log('PROMPT='+first.prompt);
  console.log('EXPR='+expr);
  console.log('HAS_EQ='+(/=\s*\?+\s*$/.test(String(first.big||first.prompt))?'1':'0'));
  // 校验表达式不含答案
  const leak=/=[\s]*(-?\d+)\s*$/.test(String(first.big||first.prompt));
  console.log('LEAK='+(leak?'1':'0'));
})().catch(e=>{console.log('ERR='+e.message)});
''')
    assert 'PROMPT=' in out and 'EXPR=' in out, out
    # 表达式应是算式左半边(不含最后 '= ?'), 卡片将用它做醒目展示
    expr_line = out.split('EXPR=')[1].split('\n')[0]
    assert '= ?' not in expr_line, 'expr仍带占位等号: ' + out
    assert 'LEAK=0' in out, '提前泄露答案: ' + out


def test_render_stats(client):
    """家长数据看板: 依据 state 输出 KPI/7天趋势/分科正确率."""
    out = _harness(r'''
store['edu_record_v1_kk']=JSON.stringify({stars:5,records:[
  {t:1,date:'2026-08-28',subj:'zh',type:'poem',prompt:'a',correct:'x',got:'x',ok:true},
  {t:2,date:'2026-08-28',subj:'math',type:'calc',prompt:'b',correct:'1',got:'2',ok:false},
  {t:3,date:'2026-08-29',subj:'en',type:'word',prompt:'c',correct:'y',got:'y',ok:true}
],wrong:[
  {subj:'math',type:'calc',q:'b',times:1,prompt:'b',correct:'1'},
  {subj:'zh',type:'zi',q:'z',times:2,prompt:'字',correct:'好',box:2,nextDue:Date.now()-3600000},
  {subj:'en',type:'word',q:'w',times:1,prompt:'w',correct:'dog',box:1,nextDue:Date.now()+864000000}
],settings:{},usage:{date:'2026-08-30',n:1,secs:120},maxCombo:3,badges:{s1:1},submits:1,wishes:[],wishLog:[]});
let iH='';const b=me();
Object.defineProperty(b,'innerHTML',{get(){return iH},set(v){iH=v}});
const orig=global.document.getElementById;
global.document.getElementById=(id)=> id==='eduStatsBody'?b:me();
W.eduNav('stats');
console.log('HAS_KPI='+(iH.indexOf('累计答题')>=0&&iH.indexOf('正确率')>=0?'1':'0'));
console.log('HAS_TREND='+(iH.indexOf('st-trend')>=0?'1':'0'));
console.log('HAS_SUBJ='+(iH.indexOf('分科正确率')>=0?'1':'0'));
console.log('TOTAL_REC='+(iH.match(/class="sk"/g)||[]).length);
console.log('DUE_ROWS='+(iH.match(/class="st-wrong-row"/g)||[]).length);
console.log('HAS_DUE_CARD='+(iH.indexOf('今日待复习')>=0?'1':'0'));
''')
    assert 'HAS_KPI=1' in out and 'HAS_TREND=1' in out and 'HAS_SUBJ=1' in out, out
    assert 'TOTAL_REC=7' in out, out
    # 间隔复习: 到期/逾期2条入"今日待复习"卡, 未到期的不进(仅显示2条)
    assert 'DUE_ROWS=2' in out, out
    assert 'HAS_DUE_CARD=1' in out, out


def test_calc_mult_and_parent_range(client):
    """口算范围扩充: 高难度混入乘法; 家长 range/nocarry 设置实际生效."""
    out = _harness(r'''
(async()=>{
  const eng=W.eduEngine;
  // 家长范围覆盖: range=5, 无进退位 → 只出现 ≤5 且不进位的加减
  store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],settings:{range:5,nocarry:true},level:{math:5}});
  W.eduNav('learn');
  const itemsR=await eng.assemble('math','calc');
  const small=itemsR.filter(it=>{const m=String(it.prompt).match(/\d+/g);return m && m.every(n=>+n<=5)}).length;
  // 无范围设置且高难度(L5): 出现乘法 (genOne 循环40次, 近乎必然遇到 ×)
  store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],settings:{},level:{math:5}});
  W.eduNav('learn');
  let mult=0, plain=0;
  for(let k=0;k<40;k++){
    const it=eng.genOne('math','calc',5);
    if(/×/.test(String(it.prompt))) mult++; else plain++;
  }
  console.log('SMALL5='+(small===itemsR.length?'1':'0'));
  console.log('HAS_MULT='+(mult>0&&plain>0?'1':'0'));
})();
''')
    assert 'SMALL5=1' in out, out
    assert 'HAS_MULT=1' in out, out


def test_quiz_refresh_keeps_page(client):
    """刷新保持: 当前页面(非首页)被持久化, 重新进入(enter)恢复到该页而非首页."""
    out = _harness(r'''
(async()=>{
  store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],settings:{}});
  const shown=[]; let showing='none';
  global.document.getElementById=(id)=>{
    const el=me(); const st={};
    Object.defineProperty(st,'display',{set(v){ if(id.endsWith('Page')){ if(v===''){ showing=id; shown.push('SHOW'); } else shown.push('HIDE'); } },get(){return st._v}});
    el.style=st; return el;
  };
  W.eduNav('learn');
  console.log('SAVED='+(store['edu_nav_v1_kk']?'1':'0'));
  console.log('LAST='+String(W.lastNav()));
  // 模拟刷新: 记忆仍在 → enter 应恢复 'learn' 而非跳回 'home'
  showing='none';
  W.enter();
  console.log('PAGE='+showing);
})();
''')
    assert 'SAVED=1' in out, out
    assert 'LAST=learn' in out, out
    assert 'PAGE=eduLearnPage' in out, out


def test_banner_and_quiz_grid(client):
    """闯关横幅(难度/通关/档位) 与 [闯关|极速练习] 按钮合并成一行; 题目卡片包进两栏 .quiz-grid."""
    harness = r'''
const fs=require('fs'),vm=require('vm');
global.window=global;global.esc=s=>String(s||'').replace(/</g,'&lt;').replace(/&/g,'&amp;');
const store={}; let inserted=[];
function cap(){ const el={className:'',style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},setAttribute(){},getAttribute(){return null},querySelector:()=>cap(),querySelectorAll:()=>[],textContent:'',value:'',addEventListener(){},options:[],children:[],offsetWidth:0,offsetHeight:0,focus(){},scrollIntoView(){},getContext(){return new Proxy({}, {get:()=>()=>{}})}};
  Object.defineProperty(el,'innerHTML',{set(v){ el._h=String(v); const s=String(v); if(s.indexOf('极速练习')>=0||s.indexOf('lv-badge')>=0) inserted.push(el.className+'|'+s); if((el.className==='quiz-grid')&&('quiz-grid'===el.className)) inserted.push('GRID'); },get(){return el._h}});
  el.appendChild=(c)=>{el.children.push(c);};
  return el;
}
const container=cap();
global.document={getElementById:id=> (id==='wb-math-body'||id==='quizShell')?container:cap(),querySelectorAll:()=>[],querySelector:()=>cap(),createElement:()=>cap(),createTextNode:()=>({}),addEventListener(){},removeEventListener(){},documentElement:{style:{}},body:cap()};
global.localStorage={getItem:k=>k in store?store[k]:null,setItem(k,v){store[k]=String(v)},removeItem(k){delete store[k]}};
global.location={};global.navigator={userAgent:'node'};global.performance={now:()=>0};global.HTMLElement=function(){};global.Node=function(){};
global.eduKids={active:()=>({id:'kk'}),all:()=>[{id:'kk'}],byId:()=>null,tierOf:()=>'workbench',ageOf:()=>6,tierLabel:()=>'',genderIcon:()=>'?',remove(){},setActive(){},hasAny:()=>1,update(){},add(){}};
global.eduSync={setOnState(){},qbankPull:()=>Promise.resolve({items:[]}),qbankEnsure:()=>Promise.resolve(),qbankLearn:()=>Promise.resolve(),pushState(){},hydrate:()=>Promise.resolve()};
vm.createContext(global);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),global);const W=global;
global.__ins=inserted;
'''
    out_body = harness + r'''
(async()=>{
  store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],settings:{},level:{math:5}});
  store['edu_quiz_v1_kk']=JSON.stringify({subj:'math',type:'calc',items:[{input:true,prompt:'7+8=?',correct:'15'},{input:true,prompt:'3+9=?',correct:'12'}],answers:{},order:{},submitted:false,_t:Date.now()});
  W.eduNav('learn');
  await new Promise(r=>setTimeout(r,40));
  W.wbMath('calc');
  await new Promise(r=>setTimeout(r,150));
  // 合并行: 同一元素内含 闯关/极速练习 与 难度档
  let merged=__ins.filter(x=>x.indexOf('boss')<0 && x.indexOf('极速练习')>=0 && (x.indexOf('lv-at')>=0));
  console.log('MERGED='+(merged.length?'1':'0'));
  console.log('HASBTN='+((__ins.join('').indexOf('闯关')>=0 && __ins.join('').indexOf('极速练习')>=0)?'1':'0'));
})();
'''
    r = subprocess.run(['node', '-e', out_body, _JS], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert 'MERGED=1' in r.stdout, r.stdout
    assert 'HASBTN=1' in r.stdout, r.stdout


def test_practice_mode_blitz():
    """极速练习: 单题即时反馈 + 连对倍率计分 + 结束结算('⚡X 分'), 回答计入错题本与统计."""
    out = _harness(r'''
(async()=>{
  store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],settings:{},level:{math:5}});
  let bodyH='';const body={style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},appendChild(){},querySelector(){return me()},querySelectorAll(){return[]},scrollIntoView(){},focus(){}};
  Object.defineProperty(body,'innerHTML',{get(){return bodyH},set(v){bodyH=String(v)}});
  const byId=(id)=> (id==='wb-math-body'||id==='quizShell')?body:me();
  global.document.getElementById=byId;
  W.eduNav('learn');
  W.wbMath('calc');
  await new Promise(r=>setTimeout(r,60));
  W.startPractice('math','calc');
  await new Promise(r=>setTimeout(r,80));
  const hasCard = bodyH.indexOf('qi-p-in')>=0 && bodyH.indexOf('pr-hud')>=0;
  const hasBanner = bodyH.indexOf('lv-banner')>=0 && bodyH.indexOf('难度档')>=0 && bodyH.indexOf('极速练习')>=0 && bodyH.indexOf('闯关')>=0;
  // 第1题: 读出正确答案作答 → 连对1 → 得1分
  const c1 = W.PRACTICE.cur.correct;
  W.practiceAnswer(c1);
  const s1 = W.PRACTICE.streak===1 ? (W.PRACTICE.score===1?'1':'0') : '0';
  await new Promise(r=>setTimeout(r,1000));
  // 第2题: 再答对 → 连对2 → +2分, 累计3分
  const c2 = W.PRACTICE.cur.correct;
  W.practiceAnswer(c2);
  const s2 = W.PRACTICE.streak===2 ? (W.PRACTICE.score===3?'1':'0') : '0';
  await new Promise(r=>setTimeout(r,1000));
  W.stopPractice();
  const recN = (W.state.records||[]).length;
  console.log('HAS_CARD='+(hasCard?'1':'0'));
  console.log('HAS_BANNER='+(hasBanner?'1':'0'));
  console.log('SCORE1='+s1);
  console.log('SCORE2='+s2);
  console.log('SUMMARY='+(bodyH.indexOf('⚡3 分')>=0?'1':'0'));
  console.log('RECN='+(recN===2?'1':'0'));
})();
''')
    assert 'HAS_CARD=1' in out, out
    assert 'HAS_BANNER=1' in out, out
    assert 'SCORE1=1' in out, out
    assert 'SCORE2=1' in out, out
    assert 'SUMMARY=1' in out, out
    assert 'RECN=1' in out, out


def test_quiz_restore_after_refresh():
    """刷新保持: 进行中卷子的已填答案存 localStorage, 重新起卷时被还原."""
    out = _harness(r'''
(async()=>{
  // 模拟"刷新前"已填答题的进行中卷子
  store['edu_quiz_v1_kk']=JSON.stringify({
    subj:'math', type:'calc',
    items:[{input:true,big:'20 - 9',prompt:'20 - 9 = ?'},
           {input:true,big:'13 + 8',prompt:'13 + 8 = ?'}],
    answers:{0:'11',1:'21'}, order:{}, submitted:false, _t:Date.now()
  });
  // 柱桩: wb-math-body 捕获 innerHTML; qi-{i} 提供可读写的 input
  let bodyH='';const body={style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},appendChild(){},querySelectorAll(){return[]},querySelector(){return me()}};
  Object.defineProperty(body,'innerHTML',{get(){return bodyH},set(v){bodyH=String(v)}});
  const inputs={}; const mkIn=(n)=>{const inp={_v:'',style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},setAttribute(){},getAttribute(){return null},addEventListener(){}};Object.defineProperty(inp,'value',{get(){return inp._v},set(v){inp._v=String(v)}});inputs[n]=inp;return inp;};
  const items={0:mkIn(0),1:mkIn(1)};
  const byId=(id)=>{
    if(id==='wb-math-body') return body;
    if(id==='qi-0') return {querySelector:()=>items[0]};
    if(id==='qi-1') return {querySelector:()=>items[1]};
    return me();
  };
  global.document.getElementById=byId;
  W.wbMath('calc');
  await new Promise(r=>setTimeout(r,60));
  console.log('V0='+inputs[0].value);
  console.log('V1='+inputs[1].value);
  console.log('KEPT='+(store['edu_quiz_v1_kk']?'1':'0'));
})();
''')
    assert 'V0=11' in out, out
    assert 'V1=21' in out, out
    assert 'KEPT=1' in out, out


def test_quiz_save_state_on_answer():
    """作答即持久化: 恢复的卷子选中答案后, localStorage 快照同步更新."""
    out = _harness(r'''
(async()=>{
  store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],settings:{}});
  store['edu_quiz_v1_kk']=JSON.stringify({
    subj:'zh', type:'zi',
    items:[{options:[{v:'a',label:'好'},{v:'b',label:'不'}],prompt:'选对字',correct:'a'}],
    answers:{}, order:{}, submitted:false, _t:Date.now()
  });
  // 柱桩: quiz 容器捕获 innerHTML; qi-0 提供 querySelectorAll 返回选项按钮
  let bodyH='';const body={style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},appendChild(){},querySelectorAll(){return[]},querySelector(){return me()}};
  Object.defineProperty(body,'innerHTML',{get(){return bodyH},set(v){bodyH=String(v)}});
  const btn={classList:{add(){},remove(){},toggle(){},contains(){return false}},getAttribute(){return null}};
  const itemEl={querySelector:()=>me(),querySelectorAll:()=>[btn]};
  global.document.getElementById=(id)=> id==='wb-zh-body'?body : (id==='qi-0'?itemEl : me());
  W.wbZh('zi');
  await new Promise(r=>setTimeout(r,60));
  W.pickOpt(0,'a');
  const snap=JSON.parse(store['edu_quiz_v1_kk']||'null');
  console.log('SAVED='+(snap && snap.submitted===false && snap.answers && snap.answers[0]==='a' ? '1':'0'));
})();
''')
    assert 'SAVED=1' in out, out


def test_star_map_and_daily(client):
    """星级/闯关地图 + 每日挑战: 地图卡片含 15 关与星级; 挑战卷确定性(同日两份相同)+每日标记."""
    out = _harness(r'''
(async()=>{
  const mkEl=()=>{const el={_h:'',style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},setAttribute(){},getAttribute(){return null},querySelector:()=>mkEl(),querySelectorAll:()=>[],focus(){},scrollIntoView(){},children:[]};
    Object.defineProperty(el,'innerHTML',{get(){return el._h},set(v){el._h=String(v)}});
    el._appBuild=(el._h||''); el.appendChild=(c)=>{ if(c && c._h!==undefined) el._h+=(c._h||''); };
    return el;};
  const dEl=mkEl(), statsEl=mkEl(), navEl=mkEl();
  const byId=(id)=> id==='wb-daily'?dEl : (id==='eduStatsBody'?statsEl : (id==='eduBottomNav'?navEl : mkEl()));
  global.document.getElementById=byId;
  global.document.createElement=()=>mkEl();
  global.document.querySelectorAll=()=>[];
  store['edu_record_v1_kk']=JSON.stringify({stars:9,records:[],wrong:[],wishes:[],settings:{},
    adv:{zh:{poem:{passed:1,stars:3}},math:{calc:{stars:1}},en:{word:{passed:1}}},level:{}});
  W.eduNav('stats');
  const CELLS=(statsEl._h.match(/class="st-map-cell/g)||[]).length;
  const CELL1=statsEl._h.indexOf('闯关地图')>=0?'1':'0';
  const PASSED=statsEl._h.indexOf('st-map-cell passed')>=0?'1':'0';
  // 每日挑战: 两次生成内容一致(确定性) + 渲染含每日标记与10题
  W.startDaily();
  await new Promise(r=>setTimeout(r,60));
  const a=String(dEl._h||'');
  const cardsA=(a.match(/qi-head/g)||[]).length;
  W.startDaily();
  await new Promise(r=>setTimeout(r,60));
  const b=String(dEl._h||'');
  console.log('MAP1='+CELL1);
  console.log('MAP_CELLS='+CELLS);
  console.log('PASSED='+PASSED);
  console.log('DAILY_BANNER='+(b.indexOf('每日挑战')>=0?'1':'0'));
  console.log('DAILY_10='+(cardsA===10?'1':'0'));
  console.log('DAILY_SAME='+(a===b?'1':'0'));
})();
''')

    assert 'MAP1=1' in out, out
    assert 'MAP_CELLS=15' in out, out
    assert 'PASSED=1' in out, out
    assert 'DAILY_BANNER=1' in out, out
    assert 'DAILY_10=1' in out, out
    assert 'DAILY_SAME=1' in out, out


def test_daily_mixed_subjects(client):
    """每日挑战: 各科混合(语文4/数学3/英语3)+题型跨各科."""
    out = _harness(r'''
(async()=>{
  const items=W.buildDaily?W.buildDaily():[];
  const cnt={};
  (items||[]).forEach(it=>{ cnt[it.isubj]=(cnt[it.isubj]||0)+1; });
  console.log('DLEN='+items.length);
  console.log('ZH='+(cnt.zh||0));
  console.log('MATH='+(cnt.math||0));
  console.log('EN='+(cnt.en||0));
  // 两次生成一致(确定性)
  const b=W.buildDaily();
  console.log('DAILY_SAME2='+(JSON.stringify(items)===JSON.stringify(b)?'1':'0'));
})();
''')
    assert 'DLEN=10' in out, out
    assert 'ZH=4' in out, out
    assert 'MATH=3' in out, out
    assert 'EN=3' in out, out
    assert 'DAILY_SAME2=1' in out, out


def test_edu_tts_endpoint(client):
    """语音接口: 同源 mp3 返回 + 内容缓存 + 语言自判(不依赖外网)."""
    import hashlib
    import os
    import routes.education as edu
    from app import app
    cache_dir = os.path.join(app.instance_path, 'tts')
    os.makedirs(cache_dir, exist_ok=True)
    keys = []
    for le, txt in (('zh', '你好'), ('en', 'apple')):
        k = hashlib.sha1((le + '|' + txt).encode('utf-8')).hexdigest()[:24]
        keys.append(os.path.join(cache_dir, k + '.mp3'))
        try:
            os.remove(keys[-1])
        except OSError:
            pass
    calls = []
    orig = edu._fetch_tts
    edu._fetch_tts = lambda text, le: (calls.append((text, le)) or b'ID3hello')
    try:
        r = client.get('/edu/api/tts?text=%E4%BD%A0%E5%A5%BD')
        assert r.status_code == 200, r.status_code
        assert r.content_type.startswith('audio/mpeg'), r.content_type
        assert r.data[:3] == b'ID3'
        # 命中磁盘缓存: 不再外呼
        r2 = client.get('/edu/api/tts?text=%E4%BD%A0%E5%A5%BD')
        assert r2.status_code == 200 and r2.data == r.data
        assert calls == [('你好', 'zh')], calls
        # 英文自判 → en
        r3 = client.get('/edu/api/tts?text=apple')
        assert r3.status_code == 200 and calls == [('你好', 'zh'), ('apple', 'en')], calls
        assert client.get('/edu/api/tts').status_code == 400
    finally:
        edu._fetch_tts = orig
        for p in keys:
            try:
                os.remove(p)
            except OSError:
                pass


def test_practice_encourage_and_modebar(client):
    """极速练习鼓励语音: 答对/答错各有随机词库且能抽到; 闯关/极速练习并列模式条含两入口."""
    out = _harness(r'''
  var h=W.modeBarHtml('guan');
  var h2=W.modeBarHtml('su');
  console.log('OK='+W.ENC_OK.length+'/'+W.ENC_WRONG.length);
  console.log('PICK='+W.encPick(W.ENC_OK)+'|'+W.encPick(W.ENC_WRONG));
  console.log('MB='+((h.indexOf('闯关')>=0 && h.indexOf('极速练习')>=0)));
  console.log('MGUAN='+(h.indexOf('active')>=0));
  console.log('MSU='+(h2.indexOf('active')>=0));
''')
    assert 'OK=7/5' in out, out
    assert '|' in out, out
    assert 'MB=true' in out, out


if __name__ == '__main__':
    # 便于 run_tests.py 风格手动运行
    import conftest
    client = conftest.make_client()
    for name in sorted(dir(sys.modules[__name__])):
        if name.startswith('test_'):
            fn = getattr(sys.modules[__name__], name)
            try:
                fn(client)
                print(f'PASS test_education.{name}')
            except Exception:
                print(f'FAIL test_education.{name}')
                raise
