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
function me(){return {innerHTML:'',style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},setAttribute(){},getAttribute(){return null},querySelector(){return me()},querySelectorAll(){return[]},textContent:'',value:'',appendChild(){},removeChild(){},addEventListener(){},options:[],children:[],offsetWidth:0,offsetHeight:0,getContext(){return new Proxy({}, {get:()=>()=>{}})}};}
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
  const types={zh:['poem','zi','stroke','pinyin','yun','read','fan','liang'],math:['calc','judge','word','order'],en:['word','dialogue']};
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
],wrong:[{subj:'math',type:'calc',q:'b',times:1,prompt:'b',correct:'1'}],settings:{},usage:{date:'2026-08-30',n:1,secs:120},maxCombo:3,badges:{s1:1},submits:1,wishes:[],wishLog:[]});
let iH='';const b=me();
Object.defineProperty(b,'innerHTML',{get(){return iH},set(v){iH=v}});
const orig=global.document.getElementById;
global.document.getElementById=(id)=> id==='eduStatsBody'?b:me();
W.eduNav('stats');
console.log('HAS_KPI='+(iH.indexOf('累计答题')>=0&&iH.indexOf('正确率')>=0?'1':'0'));
console.log('HAS_TREND='+(iH.indexOf('st-trend')>=0?'1':'0'));
console.log('HAS_SUBJ='+(iH.indexOf('分科正确率')>=0?'1':'0'));
console.log('TOTAL_REC='+(iH.match(/class="sk"/g)||[]).length);
''')
    assert 'HAS_KPI=1' in out and 'HAS_TREND=1' in out and 'HAS_SUBJ=1' in out, out
    assert 'TOTAL_REC=6' in out, out


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
