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
    assert 'js/edu/edu-main.js' in html
    # 页面骨架关键区（已移除顶部条 kid-bar，改为 in-quiz 控件）
    for probe in ('eduLearnPage', 'eduWishPage', 'eduBadgesPage',
                  'eduBottomNav', 'id="kidDelBtn"', 'id="eduMaskQuit"'):
        assert probe in html, f'missing {probe}'
    assert 'class="kid-bar"' not in html
    assert 'id="kbTitle"' not in html


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

# Module files in dependency order (matching edu-main.js)
_MODULE_FILES = [
    'edu-constants.js',
    'edu-math-utils.js',
    'edu-core.js',
    'edu-speech.js',
    'edu-state.js',
    'edu-parent.js',
    'edu-quiz-engine.js',
    'edu-engine.js',
    'edu-legacy.js',
    'edu-zh.js',
    'edu-math.js',
    'edu-en.js',
    'edu-paradise.js',
    'edu-daily.js',
    'edu-practice.js',
    'edu-header.js',
    'edu-kids.js',
    'edu-nav.js',
    'edu-home.js',
    'edu-mine.js',
    'edu-edit.js',
    'edu-report.js',
    'edu-mask.js',
    'edu-wish.js',
    'edu-badges.js',
    'edu-course.js',
    'edu-stats.js',
    'edu-dash.js',
    'edu-backup.js',
    'edu-settings.js',
    'edu-fab.js',
    'edu-bootstrap.js',
]

def _concat_modules():
    """Read all module files in order and concatenate into one script string."""
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'js', 'edu')
    parts = []
    for fname in _MODULE_FILES:
        path = os.path.join(base, fname)
        with open(path, 'r', encoding='utf-8') as f:
            parts.append(f.read())
    return '\n'.join(parts)

# Cache concatenated script
_CONCAT_SCRIPT = None

def _get_concat_script():
    global _CONCAT_SCRIPT
    if _CONCAT_SCRIPT is None:
        _CONCAT_SCRIPT = _concat_modules()
    return _CONCAT_SCRIPT

def _node_check():
    # Check syntax of concatenated script (write to temp file to avoid command line length limit)
    script = _get_concat_script()
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8') as tmp:
        tmp.write(script)
        tmp_path = tmp.name
    try:
        r = subprocess.run(['node', '--check', tmp_path], capture_output=True, text=True)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return r.returncode == 0, r.stderr

def _harness(script_body):
    """用 node 运行拼接后的 education 模块 + 注入脚本, 返回 stdout/stderr."""
    script = _get_concat_script()
    harness = r'''
const fs=require('fs'),vm=require('vm');
global.window=global;
global.Edu = {};  // Must exist before modules define window.Edu.*
global.esc=s=>String(s||'').replace(/</g,'<').replace(/&/g,'&');
const store={};
function me(){return {innerHTML:'',style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},setAttribute(){},getAttribute(){return null},querySelector(){return me()},querySelectorAll(){return[]},textContent:'',value:'',appendChild(){},removeChild(){},remove(){},addEventListener(){},options:[],children:[],offsetWidth:0,offsetHeight:0,focus(){},scrollIntoView(){},getContext(){return new Proxy({}, {get:()=>()=>{}})}};}
global.document={getElementById:()=>me(),querySelectorAll:()=>[],querySelector:()=>me(),createElement:()=>me(),createTextNode:()=>({}),addEventListener(){},removeEventListener(){},documentElement:{style:{}},body:me()};
global.localStorage={getItem:k=>k in store?store[k]:null,setItem(k,v){store[k]=String(v)},removeItem(k){delete store[k]}};
global.location={};global.navigator={userAgent:'node'};global.performance={now:()=>0};global.HTMLElement=function(){};global.Node=function(){};
global.eduKids={active:()=>({id:'kk'}),all:()=>[{id:'kk'}],list:()=>[{id:'kk'}],byId:()=>null,tierOf:()=>'workbench',ageOf:()=>6,tierLabel:()=>'',genderIcon:()=>'?',remove(){},setActive(){},hasAny:()=>1,update(){},add(){}};
global.eduSync={setOnState(){},qbankPull:()=>Promise.resolve({items:[]}),qbankEnsure:()=>Promise.resolve(),qbankLearn:()=>Promise.resolve(),pushState(){},hydrate:()=>Promise.resolve()};
vm.createContext(global);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'), global);
const W=global;
''' + script_body
    # Write script to temp file for vm.runInContext
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8') as tmp:
        tmp.write(script)
        tmp_path = tmp.name
    try:
        r = subprocess.run(['node', '-e', harness, tmp_path], capture_output=True, text=True)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    assert r.returncode == 0, r.stderr
    return r.stdout

def _harness_temp(script_body):
    """Like _harness but returns (stdout, temp_path) for tests needing custom harness."""
    script = _get_concat_script()
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8') as tmp:
        tmp.write(script)
        tmp_path = tmp.name
    harness = r'''
const fs=require('fs'),vm=require('vm');
global.window=global;
global.Edu = {};  // Must exist before modules define window.Edu.*
global.esc=s=>String(s||'').replace(/</g,'<').replace(/&/g,'&');
const store={};
function me(){return {innerHTML:'',style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},setAttribute(){},getAttribute(){return null},querySelector(){return me()},querySelectorAll(){return[]},textContent:'',value:'',appendChild(){},removeChild(){},remove(){},addEventListener(){},options:[],children:[],offsetWidth:0,offsetHeight:0,focus(){},scrollIntoView(){},getContext(){return new Proxy({}, {get:()=>()=>{}})}};}
global.document={getElementById:()=>me(),querySelectorAll:()=>[],querySelector:()=>me(),createElement:()=>me(),createTextNode:()=>({}),addEventListener(){},removeEventListener(){},documentElement:{style:{}},body:me()};
global.localStorage={getItem:k=>k in store?store[k]:null,setItem(k,v){store[k]=String(v)},removeItem(k){delete store[k]}};
global.location={};global.navigator={userAgent:'node'};global.performance={now:()=>0};global.HTMLElement=function(){};global.Node=function(){};
global.eduKids={active:()=>({id:'kk'}),all:()=>[{id:'kk'}],list:()=>[{id:'kk'}],byId:()=>null,tierOf:()=>'workbench',ageOf:()=>6,tierLabel:()=>'',genderIcon:()=>'?',remove(){},setActive(){},hasAny:()=>1,update(){},add(){}};
global.eduSync={setOnState(){},qbankPull:()=>Promise.resolve({items:[]}),qbankEnsure:()=>Promise.resolve(),qbankLearn:()=>Promise.resolve(),pushState(){},hydrate:()=>Promise.resolve()};
vm.createContext(global);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),global);
const W=global;
''' + script_body
    r = subprocess.run(['node', '-e', harness, tmp_path], capture_output=True, text=True)
    return r.stdout, tmp_path

def _concat_script_path():
    """写拼接后的模块到临时文件, 返回路径(node -e <harness> <path> 使用)."""
    script = _get_concat_script()
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8') as tmp:
        tmp.write(script)
        tmp_path = tmp.name
    return tmp_path

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
    """闯关 Tab 升级为课程地图页: 期刊地图 + 激励汇总 + 成就徽章."""
    out = _harness(r'''
store['edu_record_v1_kk']=JSON.stringify({stars:12,badges:{s1:1,s10:1,c5:1,d3:1,z1:1,all:1},records:[{subj:'zh'}],wrong:[],wishes:[],points:5,course:{}});
W.Edu.Store.loadAllState();
let iH='';const b=me();
Object.defineProperty(b,'innerHTML',{get(){return iH},set(v){iH=v}});
const orig=global.document.getElementById;
global.document.getElementById=(id)=> id==='eduBadgesBody'?b:me();
W.eduNav('badges');
console.log('CM_WRAP='+(iH.indexOf('cm-wrap')>=0?'1':'0'));
console.log('MAP_COURSE='+(iH.indexOf('cm-course')>=0?'1':'0'));
console.log('NODE_CUR='+(iH.indexOf('cm-node current')>=0?'1':'0'));
console.log('NODE_LOCK='+(iH.indexOf('cm-node locked')>=0?'1':'0'));
console.log('STAT_POINTS='+(iH.indexOf('积分')>=0?'1':'0'));
console.log('STAT_STREAK='+(iH.indexOf('连续打卡')>=0?'1':'0'));
console.log('MILESTONE='+(iH.indexOf('星星里程碑')>=0?'1':'0'));
console.log('CM_BADGE_ON='+(iH.match(/class="cm-badge on"/g)||[]).length);
console.log('CM_BADGE_DIM='+(iH.match(/class="cm-badge dim"/g)||[]).length);
''')
    assert 'CM_WRAP=1' in out, out
    assert 'MAP_COURSE=1' in out and 'NODE_CUR=1' in out and 'NODE_LOCK=1' in out, out
    assert 'STAT_POINTS=1' in out and 'STAT_STREAK=1' in out, out
    assert 'MILESTONE=1' in out, out
    assert 'CM_BADGE_ON=6' in out and 'CM_BADGE_DIM=10' in out, out


def test_course_level_pass_unlock_points():
    """高正确率通关关卡: 3 星 / 通关 / 解锁下一关 / +3 积分 / 星星累计."""
    out = _harness(r'''
store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],course:{},points:0,pointLog:[]});
W.Edu.Store.loadAllState();
const C=W.Edu.Course;
// 模拟进入数学第 0 关(口算峡谷)闯关
W.Edu.Store.state.courseIn={subj:'math',idx:0,t:'calc'};
// 10 题全对、首次答对、用时短 -> 通关
const res=C.recordQuizResult('math','calc',{right:10,total:10,triesUsed:0,fast:true});
console.log('PASS='+(res.passed&&res.passedNow?'1':'0'));
console.log('LSTARS='+res.stars);
console.log('UNLOCK_NEXT='+(!!res.unlockedNext?'1':'0'));
// 第 1 关已解锁(口算后是判断)
console.log('UNLOCKED='+C.unlockedCount('math'));
console.log('POINTS='+C.totalPoints());
console.log('NODE0_PASSED='+(C.nodeProg('math',0).passed?'1':'0'));
''')
    assert 'PASS=1' in out, out
    assert 'LSTARS=3' in out, out
    assert 'UNLOCK_NEXT=1' in out, out
    assert 'UNLOCKED=2' in out, out
    assert 'POINTS=3' in out, out
    assert 'NODE0_PASSED=1' in out, out


def test_course_level_fail_no_unlock():
    """正确率不足不通关: 不解锁下一关, 标记再试, 但不计入积分."""
    out = _harness(r'''
store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],course:{},points:0});
W.Edu.Store.loadAllState();
const C=W.Edu.Course;
W.Edu.Store.state.courseIn={subj:'math',idx:0,t:'calc'};
const res=C.recordQuizResult('math','calc',{right:4,total:10,triesUsed:3,fast:false});
console.log('PASS='+(res.passed?'1':'0'));
console.log('TRY_AGAIN='+(res.tryAgain?'1':'0'));
console.log('LSTARS='+res.stars);
console.log('UNLOCKED='+C.unlockedCount('math'));
console.log('POINTS='+C.totalPoints());
console.log('NODE0_PASSED='+(C.nodeProg('math',0).passed?'1':'0'));
''')
    assert 'PASS=0' in out, out
    assert 'TRY_AGAIN=1' in out, out
    assert 'LSTARS=0' in out, out      # 正确率40% <60%, 未达星级门槛
    assert 'UNLOCKED=1' in out, out
    assert 'POINTS=0' in out, out
    assert 'NODE0_PASSED=0' in out, out


def test_course_star_milestone():
    """累计星星达到阈值触发一次性特殊奖励(积分)."""
    out = _harness(r'''
store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],course:{},points:0});
W.Edu.Store.loadAllState();
const C=W.Edu.Course;
W.Edu.Store.state.stars=21; // 越过 20 星阈值
const res=C.recordQuizResult('math','calc',{right:10,total:10,triesUsed:0,fast:true});
console.log('MIL_COUNT='+(res.milestones?res.milestones.length:0));
console.log('MIL_NAME='+(res.milestones&&res.milestones[0]?res.milestones[0].txt:''));
console.log('POINTS='+C.totalPoints());
// 再次结算不应重复发奖
const r2=C.recordQuizResult('math','calc',{right:10,total:10,triesUsed:0,fast:true});
console.log('MIL2_COUNT='+(r2.milestones?r2.milestones.length:0));
console.log('POINTS2='+C.totalPoints());
''')
    assert 'MIL_COUNT=1' in out, out
    assert 'MIL_NAME=小勇士' in out, out
    assert 'POINTS=8' in out, out     # 3(通关) + 5(里程碑)
    assert 'MIL2_COUNT=0' in out, out
    assert 'POINTS2=8' in out, out    # 不重复发奖


def test_course_integration_quiz_engine(client):
    """答题引擎交卷时联动课程: 高正确率自动通关/解锁 + 完成页显示关卡进度行."""
    out = _harness(r'''
(async()=>{
  store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],settings:{},course:{},points:0});
  const inserted=[];
  function cap(){ const el={className:'',style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},setAttribute(){},getAttribute(){return null},querySelector:()=>cap(),querySelectorAll:()=>[],textContent:'',value:'',addEventListener(){},options:[],children:[],offsetWidth:0,offsetHeight:0,focus(){},scrollIntoView(){},getContext(){return new Proxy({}, {get:()=>()=>{}})}};
    Object.defineProperty(el,'innerHTML',{set(v){el._h=String(v);inserted.push(el.className+'|'+String(v));},get(){return el._h}});
    el.appendChild=(c)=>{el.children.push(c);}; return el; }
  const container=cap();
  const mkIn=(n)=>{const inp={_v:'',className:'qi-in',style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},setAttribute(){},getAttribute(){return '0'},addEventListener(){},focus(){}};Object.defineProperty(inp,'value',{get(){return inp._v},set(v){inp._v=String(v)}});return inp;};
  const inps={0:mkIn(0)};
  global.document={getElementById:id=>{ if(id==='wb-math-body'||id==='quizShell') return container; if(id==='qi-in-0') return inps[0]; if(id==='qi-0') return {querySelector:()=>inps[0]}; if(id==='restOverlay') return null; return cap(); },querySelectorAll:()=>[],querySelector:()=>cap(),createElement:()=>cap(),createTextNode:()=>({}),addEventListener(){},removeEventListener(){},documentElement:{style:{}},body:{appendChild(){}}};
  global.localStorage={getItem:k=>k in store?store[k]:null,setItem(k,v){store[k]=String(v)},removeItem(k){delete store[k]}};
  global.location={};global.navigator={userAgent:'node'};global.performance={now:()=>0};global.HTMLElement=function(){};global.Node=function(){};
  global.eduKids={active:()=>({id:'kk'}),all:()=>[{id:'kk'}],list:()=>[{id:'kk'}],byId:()=>null,tierOf:()=>'workbench',ageOf:()=>6,tierLabel:()=>'',genderIcon:()=>'?',remove(){},setActive(){},hasAny:()=>1,update(){},add(){}};
  global.eduSync={setOnState(){},qbankPull:()=>Promise.resolve({items:[]}),qbankEnsure:()=>Promise.resolve(),qbankLearn:()=>Promise.resolve(),pushState(){},hydrate:()=>Promise.resolve()};
  vm.createContext(global);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),global);
  const W=global;
  // 进入数学口算闯关(第 0 关)
  W.wbMath('calc');
  await new Promise(r=>setTimeout(r,150));
  W.Edu.Store.state.stars=0; W.Edu.Store.state.points=0; W.Edu.Store.state.course={};
  W.Edu.Course.launchLevel('math',0);
  // 直接构造通关卷并交卷
  W.Edu.QuizEngine.quiz={subj:'math',type:'calc',items:[{input:true,prompt:'7+8=?',correct:'15'}],answers:{0:'15'},view:0,submitted:false,_t:Date.now(),startedAt:Date.now()};
  W.Edu.QuizEngine.quizSpace=null;
  W.Edu.QuizEngine.submitQuiz();
  const joined=inserted.join('\n');
  console.log('QD_COURSE_LINE='+(joined.indexOf('qd-course pass')>=0?'1':'0'));
  console.log('PASSED_NODE='+(W.Edu.Course.nodeProg('math',0).passed?'1':'0'));
  console.log('UNLOCKED='+W.Edu.Course.unlockedCount('math'));
  console.log('POINTS='+W.Edu.Course.totalPoints());
})();
''')
    assert 'QD_COURSE_LINE=1' in out, out
    assert 'PASSED_NODE=1' in out, out
    assert 'UNLOCKED=2' in out, out
    assert 'POINTS=3' in out, out


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
W.Edu.Store.loadAllState();
let iH='';const b=me();
Object.defineProperty(b,'innerHTML',{get(){return iH},set(v){iH=v}});
const orig=global.document.getElementById;
global.document.getElementById=(id)=> id==='eduStatsBody'?b:me();
W.eduNav('stats');
console.log('HAS_KPI='+(iH.indexOf('累计答题')>=0&&iH.indexOf('正确率')>=0?'1':'0'));
console.log('HAS_TREND='+(iH.indexOf('st-trend')>=0?'1':'0'));
console.log('HAS_RING='+(iH.indexOf('st-ring')>=0&&iH.indexOf('分科掌握率')>=0?'1':'0'));
console.log('TOTAL_REC='+(iH.match(/class="sk"/g)||[]).length);
console.log('DUE_ROWS='+(iH.match(/class="st-wrong-row"/g)||[]).length);
console.log('HAS_DUE_CARD='+(iH.indexOf('今日待复习')>=0?'1':'0'));
''')
    assert 'HAS_KPI=1' in out and 'HAS_TREND=1' in out and 'HAS_RING=1' in out, out
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
  W.Edu.Store.loadAllState();
  W.eduNav('learn');
  const itemsR=await eng.assemble('math','calc');
  const small=itemsR.filter(it=>{const m=String(it.prompt).match(/\d+/g);return m && m.every(n=>+n<=5)}).length;
  // 无范围设置且高难度(L5): 出现乘法 (genOne 循环40次, 近乎必然遇到 ×)
  store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],settings:{},level:{math:5}});
  W.Edu.Store.loadAllState();
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
global.window=global;global.esc=s=>String(s||'').replace(/</g,'<').replace(/&/g,'&');
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
global.eduKids={active:()=>({id:'kk'}),all:()=>[{id:'kk'}],list:()=>[{id:'kk'}],byId:()=>null,tierOf:()=>'workbench',ageOf:()=>6,tierLabel:()=>'',genderIcon:()=>'?',remove(){},setActive(){},hasAny:()=>1,update(){},add(){}};
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
  W.Edu.QuizEngine.resumeYes();   // 新交互: 存在上次练习时弹确认, 点「继续上次」后才还原
  await new Promise(r=>setTimeout(r,150));
  // 合并行: 同一元素内含 闯关/极速练习 与 难度档
  let merged=__ins.filter(x=>x.indexOf('boss')<0 && x.indexOf('极速练习')>=0 && (x.indexOf('lv-at')>=0));
  console.log('MERGED='+(merged.length?'1':'0'));
  console.log('HASBTN='+((__ins.join('').indexOf('闯关')>=0 && __ins.join('').indexOf('极速练习')>=0)?'1':'0'));
})();
'''
    r = subprocess.run(['node', '-e', out_body, _harness_temp(out_body)[1]], capture_output=True, text=True)
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
  const resumeMask={style:{}};
  const byId=(id)=>{
    if(id==='wb-math-body') return body;
    if(id==='qi-0') return {querySelector:()=>items[0]};
    if(id==='qi-1') return {querySelector:()=>items[1]};
    if(id==='eduMaskResume') return resumeMask;
    return me();
  };
  global.document.getElementById=byId;
  W.wbMath('calc');
  // 新交互: 存在上次练习时不再静默恢复, 弹出「继续上次」确认; 用户点「继续上次」后才还原
  console.log('PROMPT_GATE='+(resumeMask.style.display==='flex'?'1':'0'));
  W.Edu.QuizEngine.resumeYes();
  await new Promise(r=>setTimeout(r,60));
  console.log('V0='+inputs[0].value);
  console.log('V1='+inputs[1].value);
  console.log('KEPT='+(store['edu_quiz_v1_kk']?'1':'0'));
})();
''')
    assert 'PROMPT_GATE=1' in out, out
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
  const itemEl={classList:{add(){},remove(){},toggle(){},contains(){return false}},querySelector:()=>me(),querySelectorAll:()=>[btn]};
  global.document.getElementById=(id)=> id==='wb-zh-body'?body : (id==='qi-0'?itemEl : me());
  W.wbZh('zi');
  W.Edu.QuizEngine.resumeYes();   // 新交互: 存在上次练习时弹确认, 点「继续上次」后才还原
  await new Promise(r=>setTimeout(r,60));
  W.pickOpt(0,'a');
  const snap=JSON.parse(store['edu_quiz_v1_kk']||'null');
  console.log('SAVED='+(snap && snap.submitted===false && snap.answers && snap.answers[0]==='a' ? '1':'0'));
})();
''')
    assert 'SAVED=1' in out, out


def test_quiz_wrong_retry_then_reveal(client):
    """答错给「再试一次」机会(不跳过), 第二次答错才揭示正确答案(教学时刻)."""
    out = _harness(r'''
(async()=>{
  store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],settings:{}});
  store['edu_quiz_v1_kk']=JSON.stringify({
    subj:'zh', type:'zi',
    items:[{options:[{v:'a',label:'好'},{v:'b',label:'不'}],prompt:'选对字',correct:'a'}],
    answers:{}, order:{}, submitted:false, _t:Date.now()
  });
  const mkBtn=(v)=>{const el={disabled:false,cls:new Set(),
    getAttribute:(k)=>k==='data-v'?v:null,
    classList:{add:c=>el.cls.add(c),remove:c=>el.cls.delete(c),
      toggle:(c,f)=>{ if(f===undefined)f=!el.cls.has(c); f?el.cls.add(c):el.cls.delete(c); },
      contains:c=>el.cls.has(c)}}; return el;};
  let btns=[mkBtn('a'),mkBtn('b')];
  const body={style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},appendChild(){},
    querySelectorAll(){return[]},querySelector(){return me()}};
  Object.defineProperty(body,'innerHTML',{get(){return ''},set(){}});
  const itemEl={classList:{add(){},remove(){},toggle(){},contains(){return false}},
    querySelector:()=>me(),querySelectorAll:()=>btns};
  const cbtn={disabled:false,textContent:''};
  global.document.getElementById=(id)=> id==='wb-zh-body'?body : (id==='qi-0'?itemEl : (id==='qzConfirm'?cbtn : me()));
  W.wbZh('zi');
  W.Edu.QuizEngine.resumeYes();   // 新交互: 存在上次练习时弹确认, 点「继续上次」后才还原
  await new Promise(r=>setTimeout(r,60));
  // 1) 第一次答错: 选项保留可选(可再试), 未自动计时跳转
  W.pickOpt(0,'b');
  W.Edu.QuizEngine.confirmAnswer();
  const optsDisabled=btns.some(b=>b.disabled);
  const advanced=!!W.Edu.QuizEngine.advTimer;
  console.log('RETRY_AVAIL='+((!optsDisabled && !advanced)?'1':'0'));
  // 2) 第二次答错: 锁定选项并揭示正确答案
  W.pickOpt(0,'b');
  W.Edu.QuizEngine.confirmAnswer();
  const revealed=btns.some(b=>b.getAttribute('data-v')==='a' && b.classList.contains('reveal-correct') && b.disabled);
  console.log('REVEAL='+(revealed?'1':'0'));
})();
''')
    assert 'RETRY_AVAIL=1' in out, out
    assert 'REVEAL=1' in out, out


def test_quiz_wrong_input_needs_next():
    """输入题答错: 揭示正确答案并显示「下一题 ▶」按钮, 不自动跳转; 点按钮才前进."""
    harness = r'''
const fs=require('fs'),vm=require('vm');
global.window=global;global.esc=s=>String(s||'').replace(/</g,'&lt;').replace(/&/g,'&amp;');
const store={}; const inserted=[];
function cap(){ const el={className:'',style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},setAttribute(){},getAttribute(){return null},querySelector:()=>cap(),querySelectorAll:()=>[],textContent:'',value:'',addEventListener(){},options:[],children:[],offsetWidth:0,offsetHeight:0,focus(){},scrollIntoView(){},getContext(){return new Proxy({}, {get:()=>()=>{}})}};
  Object.defineProperty(el,'innerHTML',{set(v){el._h=String(v);inserted.push(el.className+'|'+String(v));},get(){return el._h}});
  el.appendChild=(c)=>{el.children.push(c);}; return el; }
const container=cap(); container.id='quizShell';
const mkIn=(n)=>{const inp={_v:'',className:'qi-in',style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},setAttribute(){},getAttribute(){return '0'},addEventListener(){},focus(){}};Object.defineProperty(inp,'value',{get(){return inp._v},set(v){inp._v=String(v)}});return inp;};
const inp0=mkIn(0), inp1=mkIn(1);
const q0=cap(), q1=cap();
global.document={getElementById:id=>{ if(id==='wb-math-body'||id==='quizShell') return container; if(id==='qi-in-0') return inp0; if(id==='qi-in-1') return inp1; if(id==='qi-0') return q0; if(id==='qi-1') return q1; if(id==='restOverlay') return null; return cap(); },querySelectorAll:()=>[],querySelector:()=>cap(),createElement:()=>cap(),createTextNode:()=>({}),addEventListener(){},removeEventListener(){},documentElement:{style:{}},body:{appendChild(){}}};
global.localStorage={getItem:k=>k in store?store[k]:null,setItem(k,v){store[k]=String(v)},removeItem(k){delete store[k]}};
global.location={};global.navigator={userAgent:'node'};global.performance={now:()=>0};global.HTMLElement=function(){};global.Node=function(){};
global.eduKids={active:()=>({id:'kk'}),all:()=>[{id:'kk'}],list:()=>[{id:'kk'}],byId:()=>null,tierOf:()=>'workbench',ageOf:()=>6,tierLabel:()=>'',genderIcon:()=>'?',remove(){},setActive(){},hasAny:()=>1,update(){},add(){}};
global.eduSync={setOnState(){},qbankPull:()=>Promise.resolve({items:[]}),qbankEnsure:()=>Promise.resolve(),qbankLearn:()=>Promise.resolve(),pushState(){},hydrate:()=>Promise.resolve()};
vm.createContext(global);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),global);
const W=global; global.__ins=inserted;
'''
    out_body = harness + r'''
(async()=>{
  store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],settings:{}});
  W.wbMath('calc');
  await new Promise(r=>setTimeout(r,150));
  const curOf=()=>{ const m=__ins.filter(x=>x.indexOf('题 / 共')>=0); return m.length?m[m.length-1]:''; };
  const p0=curOf();
  W.quizInputSubmit(0,'999');
  await new Promise(r=>setTimeout(r,400));
  const joined=__ins.join('\n');
  const hasReveal=joined.indexOf('正确答案是')>=0;
  const hasNext=joined.indexOf('下一题 ▶')>=0;
  const p1=curOf();
  console.log('REVEAL='+(hasReveal?'1':'0'));
  console.log('NEXT_BTN='+(hasNext?'1':'0'));
  console.log('NO_AUTO='+(p0===p1?'1':'0'));
})();
'''
    r = subprocess.run(['node', '-e', out_body, _concat_script_path()], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert 'REVEAL=1' in r.stdout, r.stdout
    assert 'NEXT_BTN=1' in r.stdout, r.stdout
    assert 'NO_AUTO=1' in r.stdout, r.stdout


def test_quiz_completion_page(client):
    """完成页升级: 答对/正确率/星星 + 鼓励语 + 「返回首页」「再练一次」大按钮; 高分提示解锁下一关."""
    harness = r'''
const fs=require('fs'),vm=require('vm');
global.window=global;global.esc=s=>String(s||'').replace(/</g,'&lt;').replace(/&/g,'&amp;');
const store={}; const inserted=[];
function cap(){ const el={className:'',style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},setAttribute(){},getAttribute(){return null},querySelector:()=>cap(),querySelectorAll:()=>[],textContent:'',value:'',addEventListener(){},options:[],children:[],offsetWidth:0,offsetHeight:0,focus(){},scrollIntoView(){},getContext(){return new Proxy({}, {get:()=>()=>{}})}};
  Object.defineProperty(el,'innerHTML',{set(v){el._h=String(v);inserted.push(el.className+'|'+String(v));},get(){return el._h}});
  el.appendChild=(c)=>{el.children.push(c);}; return el; }
const container=cap();
const inps={};
const mkIn=(n)=>{const inp={_v:'',className:'qi-in',style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},setAttribute(){},getAttribute(){return '0'},addEventListener(){},focus(){}};Object.defineProperty(inp,'value',{get(){return inp._v},set(v){inp._v=String(v)}});inps[n]=inp;return inp;};
inps[0]=mkIn(0);
global.document={getElementById:id=>{ if(id==='wb-math-body'||id==='quizShell') return container; if(id==='qi-in-0') return inps[0]; if(id==='qi-0') return {querySelector:()=>inps[0]}; if(id==='restOverlay') return null; return cap(); },querySelectorAll:()=>[],querySelector:()=>cap(),createElement:()=>cap(),createTextNode:()=>({}),addEventListener(){},removeEventListener(){},documentElement:{style:{}},body:{appendChild(){}}};
global.localStorage={getItem:k=>k in store?store[k]:null,setItem(k,v){store[k]=String(v)},removeItem(k){delete store[k]}};
global.location={};global.navigator={userAgent:'node'};global.performance={now:()=>0};global.HTMLElement=function(){};global.Node=function(){};
global.eduKids={active:()=>({id:'kk'}),all:()=>[{id:'kk'}],list:()=>[{id:'kk'}],byId:()=>null,tierOf:()=>'workbench',ageOf:()=>6,tierLabel:()=>'',genderIcon:()=>'?',remove(){},setActive(){},hasAny:()=>1,update(){},add(){}};
global.eduSync={setOnState(){},qbankPull:()=>Promise.resolve({items:[]}),qbankEnsure:()=>Promise.resolve(),qbankLearn:()=>Promise.resolve(),pushState(){},hydrate:()=>Promise.resolve()};
vm.createContext(global);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),global);
const W=global; global.__ins=inserted;
'''
    out_body = harness + r'''
(async()=>{
  store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],settings:{},level:{math:2}});
  store['edu_quiz_v1_kk']=JSON.stringify({subj:'math',type:'calc',
    items:[{input:true,prompt:'7+8=?',correct:'15'}], answers:{0:'15'}, order:{}, submitted:false, _t:Date.now()});
  W.wbMath('calc');
  W.Edu.QuizEngine.resumeYes();   // 新交互: 存在上次练习时弹确认, 点「继续上次」后才还原
  await new Promise(r=>setTimeout(r,150));
  W.Edu.QuizEngine.quiz.answers[0]='15';
  W.Edu.QuizEngine.submitQuiz();
  const joined=__ins.join('\n');
  console.log('QD_STATS='+(joined.indexOf('qd-stats')>=0&&joined.indexOf('正确率')>=0&&joined.indexOf('100%')>=0?'1':'0'));
  console.log('QD_ENC='+(joined.indexOf('qd-enc')>=0?'1':'0'));
  console.log('QD_HOME='+(joined.indexOf('返回首页')>=0?'1':'0'));
  console.log('QD_AGAIN='+(joined.indexOf('再练一次')>=0?'1':'0'));
  console.log('QD_UNLOCK='+(joined.indexOf('已解锁')>=0?'1':'0'));
})();
'''
    r = subprocess.run(['node', '-e', out_body, _concat_script_path()], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert 'QD_STATS=1' in r.stdout, r.stdout
    assert 'QD_ENC=1' in r.stdout, r.stdout
    assert 'QD_HOME=1' in r.stdout, r.stdout
    assert 'QD_AGAIN=1' in r.stdout, r.stdout
    assert 'QD_UNLOCK=1' in r.stdout, r.stdout



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
  W.Edu.Store.loadAllState();
  W.eduNav('stats');
  const CELLS=(statsEl._h.match(/class="st-map-cell/g)||[]).length;
  const CELL1=statsEl._h.indexOf('闯关地图')>=0?'1':'0';
  const PASSED=statsEl._h.indexOf('st-map-cell passed')>=0?'1':'0';
  // 每日挑战: 两次生成内容一致(确定性) + 一题一屏渲染(1个题目卡 + 10个进度点)
  W.startDaily();
  await new Promise(r=>setTimeout(r,60));
  const a=String(dEl._h||'');
  const cardsA=(a.match(/qi-head/g)||[]).length;
  const dotsA=(a.match(/qz-dot(?: |")/g)||[]).length;
  W.startDaily();
  await new Promise(r=>setTimeout(r,60));
  const b=String(dEl._h||'');
  console.log('MAP1='+CELL1);
  console.log('MAP_CELLS='+CELLS);
  console.log('PASSED='+PASSED);
  console.log('DAILY_BANNER='+(b.indexOf('每日挑战')>=0?'1':'0'));
  console.log('DAILY_CARD='+(cardsA===1?'1':'0'));
  console.log('DAILY_DOTS='+(dotsA===10?'10':'N'));
  console.log('DAILY_SAME='+(a===b?'1':'0'));
})();
''')

    assert 'MAP1=1' in out, out
    assert 'MAP_CELLS=15' in out, out
    assert 'PASSED=1' in out, out
    assert 'DAILY_BANNER=1' in out, out
    assert 'DAILY_CARD=1' in out, out
    assert 'DAILY_DOTS=10' in out, out
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


def test_quiz_header_live_count(client):
    """闯关/极速练习横幅: 徽章随模式变化, 副行固定「已答对 N 题」并随作答实时刷新(不再显示难度星)."""
    harness = r'''
const fs=require('fs'),vm=require('vm');
global.window=global;global.esc=s=>String(s||'').replace(/</g,'<').replace(/&/g,'&');
const store={}; const inserted=[];
function cap(){ const el={className:'',style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},setAttribute(){},getAttribute(){return null},querySelector:()=>cap(),querySelectorAll:()=>[],textContent:'',value:'',addEventListener(){},options:[],children:[],offsetWidth:0,offsetHeight:0,focus(){},scrollIntoView(){},getContext(){return new Proxy({}, {get:()=>()=>{}})}};
  Object.defineProperty(el,'innerHTML',{set(v){el._h=String(v);inserted.push(el.className+'|'+String(v));},get(){return el._h}});
  el.appendChild=(c)=>{el.children.push(c);};
  return el;
}
const container=cap(); let lvSub=null;
global.document={getElementById:id=>{
  if(id==='wb-math-body'||id==='quizShell') return container;
  if(id==='lvSub'){ if(!lvSub){lvSub=cap();lvSub.className='lv-sub';} return lvSub; }
  return cap();},querySelectorAll:()=>[],querySelector:()=>cap(),createElement:()=>cap(),createTextNode:()=>({}),addEventListener(){},removeEventListener(){},documentElement:{style:{}},body:cap()};
global.localStorage={getItem:k=>k in store?store[k]:null,setItem(k,v){store[k]=String(v)},removeItem(k){delete store[k]}};
global.location={};global.navigator={userAgent:'node'};global.performance={now:()=>0};global.HTMLElement=function(){};global.Node=function(){};
global.eduKids={active:()=>({id:'kk'}),all:()=>[{id:'kk'}],list:()=>[{id:'kk'}],byId:()=>null,tierOf:()=>'workbench',ageOf:()=>6,tierLabel:()=>'',genderIcon:()=>'?',remove(){},setActive(){},hasAny:()=>1,update(){},add(){}};
global.eduSync={setOnState(){},qbankPull:()=>Promise.resolve({items:[]}),qbankEnsure:()=>Promise.resolve(),qbankLearn:()=>Promise.resolve(),pushState(){},hydrate:()=>Promise.resolve()};
vm.createContext(global);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),global);
const W=global; global.__ins=inserted; global.__lv=()=>lvSub;
'''
    out_body = harness + r'''
(async()=>{
  const h=W.quizHeaderHtml('su','zh','pinyin');
  console.log('SU_BADGE='+(h.indexOf('极速练习 · 拼音')>=0?'1':'0'));
  console.log('SU_NO_STARS='+(h.indexOf('难度⭐')<0 && h.indexOf('题过关')<0 ? '1':'0'));
  // 模拟刷新前已答: 第0题答对, 第1题答错 → 恢复后横幅应显示「已答对 1 题」
  store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],settings:{}});
  store['edu_quiz_v1_kk']=JSON.stringify({subj:'math',type:'calc',
    items:[{input:true,prompt:'7+8=?',correct:'15'},{input:true,prompt:'3+9=?',correct:'12'}],
    answers:{0:'15',1:'99'}, order:{}, submitted:false, _t:Date.now()});
  W.wbMath('calc');
  W.Edu.QuizEngine.resumeYes();   // 新交互: 存在上次练习时弹确认, 点「继续上次」后才还原
  await new Promise(r=>setTimeout(r,150));
  const bannerH=__ins.filter(x=>x.indexOf('lv-banner')>=0).join('');
  console.log('COUNT_RESTORED='+(bannerH.indexOf('已答对 <b>1</b> 题')>=0?'1':'0'));
  // 把第1题改成正确答案 → 横幅 live 刷新为「已答对 2 题」
  W.onQuizInput(1,'12');
  const lv=__lv();
  console.log('COUNT_LIVE='+(lv && lv.innerHTML.indexOf('已答对 <b>2</b> 题')>=0?'1':'0'));
})();
'''
    stdin_ = _concat_script_path()
    try:
        rr = subprocess.run(['node', '-e', out_body, stdin_], capture_output=True, text=True)
        stdout = rr.stdout
    finally:
        try: os.unlink(stdin_)
        except OSError: pass
    assert 'SU_BADGE=1' in stdout, stdout
    assert 'SU_NO_STARS=1' in stdout, stdout
    assert 'COUNT_RESTORED=1' in stdout, stdout
    assert 'COUNT_LIVE=1' in stdout, stdout


def test_one_question_per_screen_and_advance(client):
    """一题一屏: 只渲染1个题目卡; 作答后自动跳到下一题; 答完全部点亮「完成闯关」."""
    harness = r'''
const fs=require('fs'),vm=require('vm');
global.window=global;global.esc=s=>String(s||'').replace(/</g,'&lt;').replace(/&/g,'&amp;');
const store={}; const inserted=[];
function cap(){ const el={className:'',style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},setAttribute(){},getAttribute(){return null},querySelector:()=>cap(),querySelectorAll:()=>[],textContent:'',value:'',addEventListener(){},options:[],children:[],offsetWidth:0,offsetHeight:0,focus(){},scrollIntoView(){},getContext(){return new Proxy({}, {get:()=>()=>{}})}};
  Object.defineProperty(el,'innerHTML',{set(v){el._h=String(v);inserted.push(el.className+'|'+String(v));},get(){return el._h}});
  el.appendChild=(c)=>{el.children.push(c);};
  return el;
}
const container=cap(); container.id='quizShell';
let lvSub=null;
global.document={getElementById:id=>{
  if(id==='wb-math-body'||id==='quizShell') return container;
  if(id==='lvSub'){ if(!lvSub){lvSub=cap();lvSub.className='lv-sub';} return lvSub; }
  return cap();},querySelectorAll:()=>[],querySelector:()=>cap(),createElement:()=>cap(),createTextNode:()=>({}),addEventListener(){},removeEventListener(){},documentElement:{style:{}},body:cap()};
global.localStorage={getItem:k=>k in store?store[k]:null,setItem(k,v){store[k]=String(v)},removeItem(k){delete store[k]}};
global.location={};global.navigator={userAgent:'node'};global.performance={now:()=>0};global.HTMLElement=function(){};global.Node=function(){};
global.eduKids={active:()=>({id:'kk'}),all:()=>[{id:'kk'}],list:()=>[{id:'kk'}],byId:()=>null,tierOf:()=>'workbench',ageOf:()=>6,tierLabel:()=>'',genderIcon:()=>'?',remove(){},setActive(){},hasAny:()=>1,update(){},add(){}};
global.eduSync={setOnState(){},qbankPull:()=>Promise.resolve({items:[]}),qbankEnsure:()=>Promise.resolve(),qbankLearn:()=>Promise.resolve(),pushState(){},hydrate:()=>Promise.resolve()};
vm.createContext(global);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),global);
const W=global; global.__ins=inserted;
'''
    out_body = harness + r'''
(async()=>{
  store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],settings:{}});
  W.wbMath('calc');
  await new Promise(r=>setTimeout(r,150));
  // 一题一屏: 每次渲染只出现 1 个题目卡 + 10 个进度圆点
  const itemHits=__ins.filter(x=>/class="quiz-item"/.test(x)).length;
  const dotsAll=__ins.join('\n');
  const dotsHits=(dotsAll.match(/qz-dot(?: |")/g)||[]).length;
  console.log('ONECARD='+(itemHits===1?'1':'N:'+itemHits));
  console.log('DOTS='+(dotsHits===10?'10':'N:'+dotsHits));
  console.log('SUBMIT_BTN='+(__ins.some(x=>x.indexOf('qi-submit')>=0 && x.indexOf('确认')>=0)?'1':'0'));
  const joined=__ins.join('\n');
  console.log('PROG_TOP='+(joined.indexOf('qz-prog-top')>=0&&joined.indexOf('qz-track')>=0?'1':'0'));
  console.log('PROG_TXT='+(joined.indexOf('第 1 题')>=0&&joined.indexOf('/ 共 10 题')>=0?'1':'0'));
  // 「完成闯关」按钮存在于页脚, 初始未就绪(disabled)
  const firstFooter=__ins.filter(x=>x.indexOf('qz-finish')>=0)[0]||'';
  console.log('FINISH_PRESENT='+(firstFooter.indexOf('qz-finish')>=0?'1':'0'));
  console.log('FINISH_INIT='+(firstFooter.indexOf('qz-finish ready')<0?'1':'0'));
  // 作答当前(第0)题 → 答对 1.5s 后自动跳到下一题: 最后一帧题目卡内容发生变化
  const snapshot=()=>{ const c=__ins.filter(x=>/class="quiz-item"/.test(x)); return c.length?c[c.length-1]:''; };
  const s0=snapshot();
  const c0=W.Edu.QuizEngine.quiz.items[0].correct;
  W.quizInputSubmit(0,c0);
  await new Promise(r=>setTimeout(r,1600));
  const s1=snapshot();
  console.log('ADVANCED='+(s0!==s1?'1':'0'));
})();
'''
    stdin_ = _concat_script_path()
    try:
        rr = subprocess.run(['node', '-e', out_body, stdin_], capture_output=True, text=True)
        stdout = rr.stdout
    finally:
        try: os.unlink(stdin_)
        except OSError: pass
    assert 'ONECARD=1' in stdout, stdout
    assert 'DOTS=10' in stdout, stdout
    assert 'SUBMIT_BTN=1' in stdout, stdout
    assert 'PROG_TOP=1' in stdout, stdout
    assert 'PROG_TXT=1' in stdout, stdout
    assert 'FINISH_PRESENT=1' in stdout, stdout
    assert 'FINISH_INIT=1' in stdout, stdout
    assert 'ADVANCED=1' in stdout, stdout


def test_rapid_double_enter_no_skip(client):
    """iPad 连续两次快速回车: 自动跳题定时器需合并, 不应跳过中间的题(每次只前进1题)."""
    harness = r'''
const fs=require('fs'),vm=require('vm');
global.window=global;global.esc=s=>String(s||'').replace(/</g,'&lt;').replace(/&/g,'&amp;');
const store={}; const inserted=[];
function cap(){ const el={className:'',style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},setAttribute(){},getAttribute(){return null},querySelector:()=>cap(),querySelectorAll:()=>[],textContent:'',value:'',addEventListener(){},options:[],children:[],offsetWidth:0,offsetHeight:0,focus(){},scrollIntoView(){},getContext(){return new Proxy({}, {get:()=>()=>{}})}};
  Object.defineProperty(el,'innerHTML',{set(v){el._h=String(v);inserted.push(el.className+'|'+String(v));},get(){return el._h}});
  el.appendChild=(c)=>{el.children.push(c);};
  return el;
}
const container=cap(); container.id='quizShell';
global.document={getElementById:id=>{ if(id==='wb-math-body'||id==='quizShell') return container; return cap();},querySelectorAll:()=>[],querySelector:()=>cap(),createElement:()=>cap(),createTextNode:()=>({}),addEventListener(){},removeEventListener(){},documentElement:{style:{}},body:cap()};
global.localStorage={getItem:k=>k in store?store[k]:null,setItem(k,v){store[k]=String(v)},removeItem(k){delete store[k]}};
global.location={};global.navigator={userAgent:'node'};global.performance={now:()=>0};global.HTMLElement=function(){};global.Node=function(){};
global.eduKids={active:()=>({id:'kk'}),all:()=>[{id:'kk'}],list:()=>[{id:'kk'}],byId:()=>null,tierOf:()=>'workbench',ageOf:()=>6,tierLabel:()=>'',genderIcon:()=>'?',remove(){},setActive(){},hasAny:()=>1,update(){},add(){}};
global.eduSync={setOnState(){},qbankPull:()=>Promise.resolve({items:[]}),qbankEnsure:()=>Promise.resolve(),qbankLearn:()=>Promise.resolve(),pushState(){},hydrate:()=>Promise.resolve()};
vm.createContext(global);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),global);
const W=global; global.__ins=inserted;
'''
    out_body = harness + r'''
(async()=>{
  store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],settings:{}});
  W.wbMath('calc');
  await new Promise(r=>setTimeout(r,150));
  const progress=()=>{ const m=__ins.filter(x=>x.indexOf('题 / 共')>=0); return m.length?m[m.length-1]:''; };
  const p0=progress();
  // 同一题连续两次快速回车(模拟 iPad 双击回车)答对: 定时器应合并为一次跳转 → 进度 +1
  const c0=W.Edu.QuizEngine.quiz.items[0].correct;
  W.quizInputSubmit(0,c0);
  W.quizInputSubmit(0,c0);
  await new Promise(r=>setTimeout(r,1600));
  const p1=progress();
  const curOf=(s)=>{ const mm=/第 (\d+) 题/.exec(s); return mm?Number(mm[1]):-1; };
  console.log('P0='+curOf(p0));
  console.log('P1='+curOf(p1));
  console.log('NO_SKIP='+(curOf(p1)===curOf(p0)+1 && curOf(p1)<=10?'1':'0'));
})();
'''
    stdin_ = _concat_script_path()
    try:
        rr = subprocess.run(['node', '-e', out_body, stdin_], capture_output=True, text=True)
        stdout = rr.stdout
    finally:
        try: os.unlink(stdin_)
        except OSError: pass
    assert 'P0=1' in stdout, stdout
    assert 'P1=2' in stdout, stdout
    assert 'NO_SKIP=1' in stdout, stdout


def test_top_nav_restructure(client):
    """顶部条已整体移除: 无 kid-bar 顶条, 退出确认弹窗保留, 无 PC 顶部导航; 退出/声音入口迁入答题横幅(qz-ctl)."""
    r = client.get('/edu/')
    html = r.get_data(as_text=True)
    for probe in ('id="eduMaskQuit"', 'quitConfirm()'):
        assert probe in html, f'missing {probe}'
    for absent in ('class="kid-bar"', 'id="kbBack"', 'id="kidLv"', 'id="kbStarBar"', 'id="soundToggle"',
                   'id="kbTitle"', 'id="kidPickDrop"', 'id="moreMenuDrop"'):
        assert absent not in html, f'should be removed: {absent}'
    assert 'eduTopNav' not in html
    assert '<nav class="edu-bottom-nav" id="eduBottomNav"></nav>' in html
    # 答题横幅自带 退出+声音 控件行 (node 层验证)
    out = _harness(r'''
(async()=>{
  let bodyH='';const body={style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},appendChild(){},querySelector(){return me()},querySelectorAll(){return[]},scrollIntoView(){},focus(){}};
  Object.defineProperty(body,'innerHTML',{get(){return bodyH},set(v){bodyH=String(v)}});
  const byId=(id)=>(id==='wb-math-body'||id==='quizShell')?body:me();
  global.document.getElementById=byId;
  store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],settings:{},level:{math:2}});
  W.eduNav('learn');
  W.wbMath('calc');
  await new Promise(r=>setTimeout(r,120));
  console.log('QCTL='+((bodyH.indexOf('qc-exit')>=0&&bodyH.indexOf('qc-sound')>=0&&bodyH.indexOf('soundToggle')>=0)?'1':'0'));
})();
''')
    assert 'QCTL=1' in out, out


def test_home_v2_layout():
    """首页 v2(3区块): 顶部 头像+欢迎语+星星+宝贝切换, 中部大「继续学习」含进度, 下部课程横向列表."""
    harness = r'''
const fs=require('fs'),vm=require('vm');
global.window=global;global.esc=s=>String(s||'').replace(/</g,'&lt;').replace(/&/g,'&amp;');
const store={};
function node(){const el={style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},setAttribute(){},getAttribute(){return null},textContent:'',value:'',appendChild(){},removeChild(){},addEventListener(){},options:[],children:[],offsetWidth:0,offsetHeight:0,focus(){},scrollIntoView(){},querySelector:()=>node(),querySelectorAll:()=>[],getContext(){return new Proxy({}, {get:()=>()=>{}})}};
  Object.defineProperty(el,'innerHTML',{get(){return el._h},set(v){el._h=String(v)}}); return el;}
const body=node(), ava=node(), ident=node(), lv=node(), nav=node(), drop=node();
const byId=(id)=>(id==='eduHomeBody'?body:(id==='kidAva'?ava:(id==='kidIdent'?ident:(id==='kidLv'?lv:(id==='kidPickDrop'?drop:(id==='eduBottomNav'?nav:node()))))));
global.document={getElementById:byId,querySelectorAll:()=>[],querySelector:()=>node(),createElement:()=>node(),createTextNode:()=>({}),addEventListener(){},removeEventListener(){},documentElement:{style:{}},body:node()};
global.localStorage={getItem:k=>k in store?store[k]:null,setItem(k,v){store[k]=String(v)},removeItem(k){delete store[k]}};
global.location={};global.navigator={userAgent:'node'};global.performance={now:()=>0};global.HTMLElement=function(){};global.Node=function(){};
const kids=[{id:'a',name:'小米',birthYear:2018,gender:'male'},{id:'b',name:'小花',birthYear:2019,gender:'female'}];
global.eduKids={active:()=>({id:'a',name:'小米',birthYear:2018,gender:'male'}),all:()=>kids,byId:id=>kids.find(k=>k.id===id),tierOf:()=>'workbench',ageOf:()=>6,tierLabel:()=>'',genderIcon:g=>g==='female'?'👧':'👦',remove(){},setActive(){},hasAny:()=>1,update(){},add(){}};
global.eduSync={setOnState(){},qbankPull:()=>Promise.resolve({items:[]}),qbankEnsure:()=>Promise.resolve(),qbankLearn:()=>Promise.resolve(),pushState(){},hydrate:()=>Promise.resolve()};
vm.createContext(global);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),global);
const W=global;
'''
    out_body = harness + r'''
(async()=>{
  const pz=n=>(n<10?'0':'')+n; const today=new Date();
  const kd=off=>{const t=new Date(today.getTime()-off*86400000);return t.getFullYear()+'-'+pz(t.getMonth()+1)+'-'+pz(t.getDate());};
  store['edu_record_v1_a']=JSON.stringify({stars:6,
    records:[{t:Date.now(),date:kd(0),subj:'zh',type:'zi',ok:true},{t:Date.now(),date:kd(1),subj:'zh',type:'zi',ok:true}],
    usage:{date:kd(0),n:1,secs:60},wrong:[{subj:'zh',type:'zi',q:'1',prompt:'火',correct:'huo',nextDue:Date.now()-1000}],
    wishes:[{name:'去公园',cost:10,done:false}],badges:{lit:1},level:{zh:3,math:5,en:0},settings:{}});
  store['edu_pref_v1_a']=JSON.stringify({mode:'workbench',subj:'zh'});
  W.eduNav('home');
  const h=body._h||'';
  console.log('GREET='+((h.indexOf('早上好')>=0||h.indexOf('下午好')>=0||h.indexOf('晚上好')>=0)?'1':'0'));
  console.log('MODE='+(h.indexOf('幼小衔接')>=0&&h.indexOf('mode-select')>=0?'1':'0'));
  console.log('NO_STARS='+(h.indexOf('⭐')<0?'1':'0'));
  console.log('CONTINUE='+(h.indexOf('🚀 继续学习')>=0?'1':'0'));
  console.log('TRACK='+(h.indexOf('hc-track')>=0?'1':'0'));
  console.log('COUNT='+((h.match(/题/g)||[]).length>=1?'1':'0'));
  console.log('COURSE_ZH='+(h.indexOf('语文')>=0?'1':'0'));
  console.log('COURSE_MATH='+(h.indexOf('数学')>=0?'1':'0'));
  console.log('COURSE_DAILY='+(h.indexOf('每日挑战')>=0?'1':'0'));
  console.log('TAG_GO='+(h.indexOf('hc-tag go')>=0?'1':'0'));
  console.log('TAG_DONE='+(h.indexOf('已通关 🎉')>=0?'1':'0'));
  console.log('TAG_TODO='+(h.indexOf('hc-tag todo')>=0?'1':'0'));
  console.log('GRID='+(h.indexOf('home-course-scroll')>=0?'1':'0'));
  console.log('CPROG='+(h.indexOf('hc-track')>=0&&h.indexOf('hc-fill')>=0?'1':'0'));
  console.log('NO_KIDROW='+(h.indexOf('hw-kid')<0?'1':'0'));
  console.log('NO_AVA='+(h.indexOf('hw-ava')<0?'1':'0'));
  console.log('GREET2='+(h.indexOf('今天也要开开心心学习哦')>=0?'1':'0'));
  console.log('LBAR='+(h.indexOf('home-sec-head')>=0?'1':'0'));
})();
'''
    stdin_ = _concat_script_path()
    try:
        rr = subprocess.run(['node', '-e', out_body, stdin_], capture_output=True, text=True)
        stdout = rr.stdout
    finally:
        try: os.unlink(stdin_)
        except OSError: pass
    for probe in ('GREET=1','MODE=1','NO_STARS=1','CONTINUE=1','TRACK=1','COUNT=1',
                  'COURSE_ZH=1','COURSE_MATH=1','COURSE_DAILY=1','NO_KIDROW=1','NO_AVA=1',
                  'GREET2=1','LBAR=1',
                  'TAG_GO=1','TAG_DONE=1','TAG_TODO=1','GRID=1','CPROG=1'):
        assert probe in stdout, stdout

def test_home_course_teaser():
    """首页集成了课程地图旅程预览卡: 展示当前旅程/节点点位, 并含「闯关地图」入口."""
    out = _harness(r'''
(async()=>{
  const today=new Date();const pz=n=>(n<10?'0':'')+n;
  const kd=off=>{const t=new Date(today.getTime()-off*86400000);return t.getFullYear()+'-'+pz(t.getMonth()+1)+'-'+pz(t.getDate());};
  store['edu_record_v1_kk']=JSON.stringify({stars:4,
    records:[{t:Date.now(),date:kd(0),subj:'zh',type:'zi',ok:true},{t:Date.now(),date:kd(1),subj:'zh',type:'read',ok:true}],
    usage:{date:kd(0),n:1,secs:60},wrong:[],wishes:[],badges:{lit:1},level:{},settings:{},
    course:{zh:{nodes:[{stars:3,best:3,passed:true,done:true},{stars:0,best:0,passed:false,done:false},{},{},{},{},{},{}],unlocked:2},
            math:{nodes:[{},{},{},{},{},{}],unlocked:1},
            en:{nodes:[{},{},{},{},{}],unlocked:1}},
    points:8,pointLog:[{date:kd(0),pts:3,label:'语文通关'}]});
  store['edu_pref_v1_kk']=JSON.stringify({mode:'workbench',subj:'zh'});
  let iH='';const b=me();
  Object.defineProperty(b,'innerHTML',{get(){return iH},set(v){iH=String(v)}});
  const orig=global.document.getElementById;
  global.document.getElementById=(id)=> id==='eduHomeBody'?b:me();
  W.eduNav('home');
  console.log('TEASER='+(iH.indexOf('home-cousrteaser')>=0?'1':'0'));
  console.log('TEASER_TXT='+(iH.indexOf('闯关地图')>=0?'1':'0'));
  console.log('TEASER_TITLE='+(iH.indexOf('语文识字之旅')>=0?'1':'0'));
  console.log('TEASER_STEPS='+((iH.match(/cmt-dot/g)||[]).length>=3?'1':'0'));
  console.log('TEASER_CUR='+(iH.indexOf('cmt-dot done-cur')>=0?'1':'0'));
})();
''')
    for probe in ('TEASER=1','TEASER_TXT=1','TEASER_TITLE=1','TEASER_STEPS=1','TEASER_CUR=1'):
        assert probe in out, out

def test_dock_busy_guard():
    """答题(Dock守卫): 起卷/极速练习进行中底部导航置灰禁用, 结束/交卷后恢复可点."""
    out = _harness(r'''
(async()=>{
  let bodyH='';const body={style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},appendChild(){},querySelector(){return me()},querySelectorAll(){return[]},scrollIntoView(){},focus(){}};
  Object.defineProperty(body,'innerHTML',{get(){return bodyH},set(v){bodyH=String(v)}});
  let navH='';const nav={style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},appendChild(){},querySelector(){return me()},querySelectorAll(){return[]}};
  Object.defineProperty(nav,'innerHTML',{get(){return navH},set(v){navH=String(v)}});
  const byId=(id)=>(id==='wb-math-body'||id==='quizShell')?body:(id==='eduBottomNav'?nav:me());
  global.document.getElementById=byId;
  store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],settings:{},level:{zh:4}});
  W.eduNav('learn');
  W.wbMath('calc');
  await new Promise(r=>setTimeout(r,90));
  console.log('DOCK_DISABLED='+(navH.indexOf('disabled')>=0?'1':'0'));
  W.startPractice('math','calc');
  await new Promise(r=>setTimeout(r,40));
  console.log('DOCK_DISABLED2='+(navH.indexOf('disabled')>=0?'1':'0'));
  await new Promise(r=>setTimeout(r,1200));
  const c1=W.PRACTICE.cur.correct;
  W.practiceAnswer(c1);
  await new Promise(r=>setTimeout(r,1200));
  W.stopPractice();
  console.log('DOCK_ENABLED='+(navH.indexOf('disabled')<0?'1':'0'));
  process.exit(0);
})();
''')
    assert 'DOCK_DISABLED=1' in out, out
    assert 'DOCK_DISABLED2=1' in out, out
    assert 'DOCK_ENABLED=1' in out, out


def test_bottom_nav_fixed_4tab_and_mine():
    """底部导航重构: 固定4Tab(学习/报告/排行/我的), 不再按模式渲染学科Tab; 我的页渲染资料头+功能入口."""
    harness = r'''
const fs=require('fs'),vm=require('vm');
global.window=global;
const store={};
function node(){const el={style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},setAttribute(){},getAttribute(){return null},textContent:'',value:'',appendChild(){},removeChild(){},addEventListener(){},options:[],children:[],offsetWidth:0,offsetHeight:0,focus(){},scrollIntoView(){},querySelector:()=>node(),querySelectorAll:()=>[],getContext(){return new Proxy({}, {get:()=>()=>{}})}};
  Object.defineProperty(el,'innerHTML',{get(){return el._h},set(v){el._h=String(v)}}); return el;}
const homeBody=node(), nav=node(), mineBody=node(), back=node(), mode=node(), kidBar=node(), titleEl=node();
const byId=(id)=>(id==='eduHomeBody'?homeBody:(id==='eduBottomNav'?nav:(id==='eduMineBody'?mineBody:(id==='kbBack'?back:(id==='modeToggleWrap'?mode:(id==='kidBar'?kidBar:(id==='kbTitle'?titleEl:node())))))));
global.document={getElementById:byId,querySelectorAll:()=>[],querySelector:()=>node(),createElement:()=>node(),createTextNode:()=>({}),addEventListener(){},removeEventListener(){},documentElement:{style:{}},body:node()};
global.localStorage={getItem:k=>k in store?store[k]:null,setItem(k,v){store[k]=String(v)},removeItem(k){delete store[k]}};
global.location={};global.navigator={userAgent:'node'};global.performance={now:()=>0};global.HTMLElement=function(){};global.Node=function(){};
const kids=[{id:'a',name:'小米',birthYear:2018,gender:'male'},{id:'b',name:'小花',birthYear:2019,gender:'female'}];
global.eduKids={active:()=>({id:'a',name:'小米',birthYear:2018,gender:'male'}),all:()=>kids,byId:id=>kids.find(k=>k.id===id),tierOf:()=>'workbench',ageOf:()=>6,tierLabel:()=>'',genderIcon:g=>g==='female'?'👧':'👦',remove(){},setActive(){},hasAny:()=>1,update(){},add(){}};
global.eduSync={setOnState(){},qbankPull:()=>Promise.resolve({items:[]}),qbankEnsure:()=>Promise.resolve(),qbankLearn:()=>Promise.resolve(),pushState(){},hydrate:()=>Promise.resolve()};
vm.createContext(global);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),global);
const W=global;
'''
    out_body = harness + r'''
(async()=>{
  store['edu_record_v1_a']=JSON.stringify({stars:8,records:[],wrong:[],wishes:[],badges:{lit:1},settings:{goal:5,lv:3}});
  store['edu_pref_v1_a']=JSON.stringify({mode:'workbench',subj:'zh'});
  W.eduNav('home');
  const n=nav._h||'';
  console.log('TAB_LEARN='+(n.indexOf('学习')>=0?'1':'0'));
  console.log('TAB_REPORT='+(n.indexOf('报告')>=0?'1':'0'));
  console.log('TAB_RANK='+(n.indexOf('闯关')>=0?'1':'0'));
  console.log('TAB_MINE='+(n.indexOf('我的')>=0?'1':'0'));
  console.log('NO_SUBJ='+(n.indexOf('语文')<0&&n.indexOf('每日挑战')<0?'1':'0'));
  console.log('NO_HOME_TAB='+(/首页/.test(n)?'0':'1'));
  W.eduNav('mine');
  const m=mineBody._h||'';
  console.log('MINE_NAME='+(m.indexOf('我的')>=0||m.indexOf('小米')>=0?'1':'0'));
  console.log('MINE_SETTINGS='+(m.indexOf('家长设置')>=0?'1':'0'));
  console.log('MINE_REPORT='+(m.indexOf('学习报告')>=0?'1':'0'));
  console.log('MINE_MGR='+(m.indexOf('宝贝管理')>=0?'1':'0'));
  console.log('MINE_STARS='+(m.indexOf('⭐')>=0?'1':'0'));
})();
'''
    stdin_ = _concat_script_path()
    try:
        rr = subprocess.run(['node', '-e', out_body, stdin_], capture_output=True, text=True)
        stdout = rr.stdout
    finally:
        try: os.unlink(stdin_)
        except OSError: pass
    for probe in ('TAB_LEARN=1','TAB_REPORT=1','TAB_RANK=1','TAB_MINE=1','NO_SUBJ=1','NO_HOME_TAB=1',
                  'MINE_NAME=1','MINE_SETTINGS=1','MINE_REPORT=1','MINE_MGR=1','MINE_STARS=1'):
        assert probe in stdout, stdout


def test_dash_charts_pdf_replay():
    """家长看板: 图表(雷达/环/饼/折线)与新 KPI 渲染; PDF 报告含标题/KPI/本地数据说明; 错题回放显示题干/孩子作答/正确答案."""
    out = _harness(r'''
(async()=>{
  const t=new Date();
  function kd(d){const p=x=>('0'+x).slice(-2);return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate());}
  function d0(n){return new Date(t.getTime()-n*86400000);}
  store['edu_record_v1_kk']=JSON.stringify({stars:12,badges:{s1:1,s10:1},maxCombo:0,submits:1,points:3,level:{},
    records:[
      {t:t.getTime(),date:kd(t),subj:'zh',type:'poem',prompt:'床前明月光',correct:'A',got:'A',ok:true},
      {t:t.getTime(),date:kd(t),subj:'math',type:'calc',prompt:'3+5',correct:'8',got:'7',ok:false},
      {t:t.getTime()-86400000,date:kd(d0(1)),subj:'en',type:'word',prompt:'apple',correct:'apple',got:'applo',ok:false},
      {t:t.getTime()-2*86400000,date:kd(d0(2)),subj:'math',type:'word',prompt:'树上有3只鸟',correct:'3',got:'3',ok:true},
      {t:t.getTime()-3*86400000,date:kd(d0(3)),subj:'zh',type:'zi',prompt:'天',correct:'天',got:'大',ok:false}
    ],
    wrong:[
      {subj:'math',type:'calc',q:'3+5',times:1,prompt:'3+5',correct:'8',nextDue:t.getTime()-3600000},
      {subj:'en',type:'word',q:'apple',times:1,prompt:'apple',correct:'apple',nextDue:t.getTime()-7200000},
      {subj:'zh',type:'zi',q:'天',times:1,prompt:'天',correct:'天',nextDue:t.getTime()+999999999}
    ],
    starLog:[{date:kd(t),s:5},{date:kd(d0(1)),s:3}],
    dailySecs:{[kd(t)]:1200,[kd(d0(1))]:600},
    usage:{date:kd(t),n:2,secs:1200},
    adv:{zh:{poem:{passed:1,stars:2}},math:{calc:{stars:1}}},
    settings:{},wishes:[],wishLog:[]});
  W.Edu.Store.loadAllState();
  let iH='';const b=me();
  Object.defineProperty(b,'innerHTML',{get(){return iH},set(v){iH=v}});
  const db=me(); const mask={style:{}};
  const orig=global.document.getElementById;
  global.document.getElementById=(id)=> id==='eduStatsBody'?b : (id==='detailBody'?db : (id==='eduMaskDetail'?mask : (id==='detailTitle'?{textContent:''} : (id==='detailSub'?{textContent:''} : orig(id)))));
  W.eduNav('stats');
  console.log('HAS_PDF='+(iH.indexOf('导出PDF')>=0?'1':'0'));
  console.log('HAS_KID='+(iH.indexOf('dash-kid')>=0?'1':'0'));
  console.log('HAS_RADAR='+(iH.indexOf('dash-radar')>=0?'1':'0'));
  console.log('HAS_DONUT='+(iH.indexOf('dash-donut')>=0&&iH.indexOf('薄弱知识点分布')>=0?'1':'0'));
  console.log('HAS_LINE='+(iH.indexOf('dash-line')>=0?'1':'0'));
  console.log('HAS_MINS='+(iH.indexOf('今日已用')>=0?'1':'0'));
  console.log('TRENDS='+(iH.match(/class="st-trend"/g)||[]).length);
  console.log('RECS='+(iH.match(/class="dash-rec /g)||[]).length);
  console.log('MAP_CELLS='+(iH.match(/class="st-map-cell/g)||[]).length);
  console.log('DUE_ROWS='+(iH.match(/class="st-wrong-row/g)||[]).length);
  console.log('RATE='+(iH.indexOf('40%')>=0?'1':'0'));
  const pd=W.Edu.Dash.buildPdfHtml();
  console.log('PDF_TITLE='+(pd.indexOf('学习报告')>=0?'1':'0'));
  console.log('PDF_KPI='+(pd.indexOf('连续打卡')>=0?'1':'0'));
  console.log('PDF_SUB='+(pd.indexOf('本机')>=0?'1':'0'));
  W.Edu.Dash.openReplay(0);
  const rp=String(db.innerHTML||'');
  console.log('RP_PROMPT='+(rp.indexOf('床前明月光')>=0?'1':'0'));
  console.log('RP_GOT='+(rp.indexOf('孩子作答')>=0?'1':'0'));
  console.log('RP_RIGHT='+(rp.indexOf('正确答案')>=0?'1':'0'));
  console.log('RP_BADGE='+(rp.indexOf('<b class="rp-badge">✓</b>')>=0?'1':'0'));
  console.log('RP_MASK='+(mask.style.display==='flex'?'1':'0'));
})();
''')
    for probe in ('HAS_PDF=1','HAS_KID=1','HAS_RADAR=1','HAS_DONUT=1','HAS_LINE=1','HAS_MINS=1',
                  'TRENDS=2','RECS=5','MAP_CELLS=15','DUE_ROWS=2','RATE=1',
                  'PDF_TITLE=1','PDF_KPI=1','PDF_SUB=1',
                  'RP_PROMPT=1','RP_GOT=1','RP_RIGHT=1','RP_BADGE=1','RP_MASK=1'):
        assert probe in out, out


def test_dash_switch_kid_autosave():
    """看板切换宝贝: 先保存当前宝贝状态, 再加载目标宝贝数据并重渲看板."""
    out = _harness(r'''
(async()=>{
  const t=new Date();
  function kd(d){const p=x=>('0'+x).slice(-2);return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate());}
  store['edu_record_v1_kk']=JSON.stringify({stars:10,records:[{t:t.getTime(),date:kd(t),subj:'zh',type:'poem',prompt:'a',correct:'x',got:'x',ok:true}],wrong:[],wishes:[],settings:{},maxCombo:0,submits:1,badges:{},points:0,level:{}});
  store['edu_record_v1_kk2']=JSON.stringify({stars:3,records:[
    {t:t.getTime(),date:kd(t),subj:'math',type:'calc',prompt:'1',correct:'1',got:'1',ok:true},
    {t:t.getTime(),date:kd(t),subj:'en',type:'word',prompt:'w',correct:'w',got:'x',ok:false}
  ],wrong:[],wishes:[],settings:{},maxCombo:0,submits:1,badges:{},points:0,level:{}});
  let cur='kk'; let switched=[];
  global.eduKids={active:()=>({id:cur,name:'小米',gender:'male'}),all:()=>[{id:'kk',name:'小米',gender:'male'},{id:'kk2',name:'豆豆',gender:'female'}],byId:()=>null,tierOf:()=>'workbench',ageOf:()=>6,tierLabel:()=>'',genderIcon:()=>'?',remove(){},setActive:(id)=>{cur=id;switched.push(id);},hasAny:()=>1,update(){},add(){}};
  W.Edu.Store.loadAllState();
  let iH='';const b=me();
  Object.defineProperty(b,'innerHTML',{get(){return iH},set(v){iH=v}});
  const orig=global.document.getElementById;
  global.document.getElementById=(id)=> id==='eduStatsBody'?b:orig(id);
  W.eduNav('stats');
  console.log('BEFORE_N='+(iH.indexOf('⭐ 10')>=0?'1':'0'));
  W.Edu.Store.state.stars=999;
  W.Edu.Dash.switchKid('kk2');
  console.log('SWITCHED='+(switched.join(',')==='kk2'?'1':'0'));
  console.log('SAVED='+(JSON.parse(store['edu_record_v1_kk']||'{}').stars===999?'1':'0'));
  console.log('LOADED='+(W.Edu.Store.state.stars===3?'1':'0'));
  console.log('AFTER_TOT='+(iH.match(/class="dash-rec /g)||[]).length);
})();
''')
    for probe in ('BEFORE_N=1','SWITCHED=1','SAVED=1','LOADED=1','AFTER_TOT=2'):
        assert probe in out, out


def test_backup_anonymized_and_restore():
    """数据安全: 备份 JSON 不含姓名/头像等识别字段; 导入后按宝贝 id 写回并恢复状态."""
    out = _harness(r'''
(async()=>{
  const t=new Date();
  function kd(d){const p=x=>('0'+x).slice(-2);return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate());}
  store['edu_record_v1_kk']=JSON.stringify({stars:12,records:[{t:t.getTime(),date:kd(t),subj:'zh',type:'poem',prompt:'a',correct:'x',got:'x',ok:true}],wrong:[],wishes:[],settings:{sound:true,eyeMin:20},maxCombo:0,submits:1,badges:{},points:0,level:{}});
  store['edu_workbench_v1_kk']=JSON.stringify({mode:'workbench',subj:'zh'});
  store['edu_record_v1_kk2']=JSON.stringify({stars:5,records:[],wrong:[],wishes:[],settings:{},maxCombo:0,submits:0,badges:{},points:0,level:{}});
  global.eduKids={active:()=>({id:'kk',name:'小米',gender:'male'}),all:()=>[{id:'kk',name:'小米',gender:'male'},{id:'kk2',name:'豆豆',gender:'female'}],tierOf:()=>'workbench',ageOf:()=>6,tierLabel:()=>'',genderIcon:()=>'?',remove(){},setActive(){},hasAny:()=>1,update(){},add(){}};
  const bk=W.Edu.Backup.buildBackup();
  const txt=JSON.stringify(bk);
  console.log('BK_KIDS='+(bk.kids.length===2?'1':'0'));
  console.log('BK_NO_NAME='+((txt.indexOf('小米')<0&&txt.indexOf('豆豆')<0)&&!(txt.indexOf('"name"')>=0)?'1':'0'));
  console.log('BK_NO_AVATAR='+(txt.indexOf('avatar')<0?'1':'0'));
  console.log('BK_STARS='+(bk.kids[0].state.stars===12?'1':'0'));
  delete store['edu_record_v1_kk']; delete store['edu_workbench_v1_kk']; delete store['edu_record_v1_kk2'];
  const ok=W.Edu.Backup.restoreJson(bk);
  const s=JSON.parse(store['edu_record_v1_kk']||'{}');
  const s2=JSON.parse(store['edu_record_v1_kk2']||'{}');
  console.log('RESTORED='+(ok&&s.stars===12&&s2.stars===5?'1':'0'));
  console.log('RESTORED_WB='+(store['edu_workbench_v1_kk']&&JSON.parse(store['edu_workbench_v1_kk']).subj==='zh'?'1':'0'));
  console.log('STATE_ACTIVE='+(W.Edu.Store.state.stars===12?'1':'0'));
})();
''')
    for probe in ('BK_KIDS=1','BK_NO_NAME=1','BK_NO_AVATAR=1','BK_STARS=1',
                  'RESTORED=1','RESTORED_WB=1','STATE_ACTIVE=1'):
        assert probe in out, out


def test_settings_confirm_and_reset_gate():
    """安全二次确认: 删除需输入匹配文字才执行, 重置需勾选「我已知晓」."""
    out = _harness(r'''
(async()=>{
  const ids={}; const maskConfirm={style:{}},maskReset={style:{}};
  const el=id=>{ if(!ids[id]) ids[id]={value:'',checked:false,textContent:'',style:{},focus(){},disabled:false,files:[],classList:{add(){},remove(){},toggle(){},contains(){return false}}}; return ids[id];};
  const orig=global.document.getElementById;
  global.document.getElementById=(id)=> id==='eduMaskConfirm'?maskConfirm : (id==='eduMaskReset'?maskReset : el(id));
  let cbCalls=0;
  W.openConfirm({title:'删除宝贝',expect:'小米',cb:()=>{cbCalls++;}});
  ids['cInput'].value='不匹配的文字';
  W.confirmOk();
  console.log('MISMATCH_BLOCK='+(cbCalls===0?'1':'0'));
  ids['cInput'].value='小米';
  W.confirmOk();
  console.log('MATCH_OK='+(cbCalls===1?'1':'0'));
  console.log('MASK_HIDDEN='+(maskConfirm.style.display==='none'?'1':'0'));
  W.openReset();
  const ack=ids['resetAck'];
  W.resetGo();
  console.log('ACK_GATE='+(ack.checked===false&&cbCalls===1?'1':'0'));
  ack.checked=true;
  console.log('ACK_READY='+(ack.checked===true?'1':'0'));
})();
''')
    for probe in ('MISMATCH_BLOCK=1','MATCH_OK=1','MASK_HIDDEN=1','ACK_GATE=1','ACK_READY=1'):
        assert probe in out, out


def test_settings_persist_eye_sound_font():
    """设置保存: 护眼时长/音效/字体大小 写入 settings 与 localStorage, 字体类名生效; 原有字段保留."""
    out = _harness(r'''
(async()=>{
  const ids={};
  const el=id=>{ if(!ids[id]) ids[id]={value:'',checked:false,textContent:'',style:{},focus(){},disabled:false,files:[]}; return ids[id];};
  let root={className:'edu-font-m'};
  root.classList={add(c){root.className=(root.className+' '+c).trim();},remove(){},toggle(){},contains(){return false}};
  global.document.documentElement=root;
  const orig=global.document.getElementById;
  global.document.getElementById=(id)=> id==='eduMaskSet'?{style:{}} : el(id);
  store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],settings:{},points:0,level:{}});
  W.Edu.Store.loadAllState();
  el('setRange').value='10'; el('setDailyQ').value='15';
  el('setEyeMin').value='30'; el('setSound').checked=false; el('setFont').value='l';
  W.setSave();
  const s=W.Edu.Store.state.settings;
  console.log('EYE='+(s.eyeMin===30?'1':'0'));
  console.log('SOUND='+(s.sound===false?'1':'0'));
  console.log('SPEAK_KEY='+(store['edu_speak_v1']==='false'?'1':'0'));
  console.log('FONT='+(s.font==='l'?'1':'0'));
  console.log('FONT_CLS='+(root.className.indexOf('edu-font-l')>=0?'1':'0'));
  console.log('KEEP='+(s.dailyQ===15&&s.nocarry===false?'1':'0'));
})();
''')
    for probe in ('EYE=1','SOUND=1','SPEAK_KEY=1','FONT=1','FONT_CLS=1','KEEP=1'):
        assert probe in out, out


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
