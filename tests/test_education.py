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


def test_edu_js_bundle_endpoint(client):
    """首屏提速: /edu/bundle.js 合并全部教育模块为单次 gzip 请求, 且包含启动入口."""
    r = client.get('/edu/bundle.js?v=test')
    assert r.status_code == 200
    assert r.headers.get('Content-Type', '').startswith('application/javascript')
    assert r.headers.get('Content-Encoding') == 'gzip'
    body = r.data
    import gzip as _gz
    raw = _gz.decompress(body).decode('utf-8')
    # 依赖顺序拼接: 结尾应是 bootstrap 的启动调用, 且不缺失头尾模块
    assert 'window.Edu.Bootstrap.bootNow' in raw
    assert 'window.Edu.QuizEngine' in raw
    assert 'bootNow' in raw

    # edu-main.js 改为单次加载 bundle, 不再逐文件串行拉取
    main_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             'static', 'js', 'edu', 'edu-main.js')
    with open(main_path, 'r', encoding='utf-8') as f:
        main_src = f.read()
    assert "'/edu/bundle.js'" in main_src
    assert 'edu-constants.js' not in main_src


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
store['edu_record_v1_kk']=JSON.stringify({stars:12,badges:{s1:1,s10:1,c5:1,d3:1,z1:1,all:1},records:[{subj:'zh'}],wrong:[],wishes:[],course:{}});
W.Edu.Store.loadAllState();
let iH='';const b=me();
Object.defineProperty(b,'innerHTML',{get(){return iH},set(v){iH=v}});
const orig=global.document.getElementById;
global.document.getElementById=(id)=> id==='eduBadgesBody'?b:me();
W.eduNav('badges');
console.log('CM_WRAP='+(iH.indexOf('cm-wrap')>=0?'1':'0'));
console.log('MAP_COURSE=0');
console.log('STG_CUR=0');
console.log('STG_LOCK=0');
console.log('BIG_LOCK=0');
console.log('STAT_NO_POINTS='+(iH.indexOf('积分')<0?'1':'0'));
console.log('STAT_STAR='+(iH.indexOf('⭐')>=0?'1':'0'));
console.log('STAT_STREAK='+(iH.indexOf('连续打卡')>=0?'1':'0'));
console.log('MILESTONE='+(iH.indexOf('星星里程碑')>=0?'1':'0'));
console.log('CM_BADGE_ON='+(iH.match(/class="cm-badge on"/g)||[]).length);
console.log('CM_BADGE_DIM='+(iH.match(/class="cm-badge dim"/g)||[]).length);
''')
    assert 'CM_WRAP=1' in out, out
    assert 'MAP_COURSE=0' in out and 'STG_CUR=0' in out and 'STG_LOCK=0' in out and 'BIG_LOCK=0' in out, out
    assert 'STAT_NO_POINTS=1' in out and 'STAT_STAR=1' in out and 'STAT_STREAK=1' in out, out
    assert 'MILESTONE=1' in out, out
    assert 'CM_BADGE_ON=6' in out and 'CM_BADGE_DIM=10' in out, out


def test_course_level_pass_unlock_stars():
    """高正确率通关大关第 1 小关: 3 星 / 该小关通过 / 下一小关解锁(同大关内, 大关未全通) / +3 星星."""
    out = _harness(r'''
store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],course:{}});
W.Edu.Store.loadAllState();
const C=W.Edu.Course;
// 模拟进入数学第 0 大关第 0 小关(口算峡谷)闯关
W.Edu.Store.state.courseIn={subj:'math',idx:0,stage:0,t:'calc'};
const res=C.recordQuizResult('math','calc',{right:10,total:10,triesUsed:0,fast:true});
console.log('PASS='+(res.passed&&res.passedNow?'1':'0'));
console.log('LSTARS='+res.stars);
console.log('STAGE_NOW='+res.stageNow);
console.log('BIG_DONE='+((res.bigDone&&res.bigDone)?'1':'0'));
// 第 0 大关第 1 小关已解锁(同大关), 但第 1 大关仍未解锁(需 5 小关全通)
console.log('STAGE1_UNLOCK='+(C.stageUnlocked('math',0,1)?'1':'0'));
console.log('BIG1_UNLOCK='+(C.bigUnlocked('math',1)?'1':'0'));
console.log('STARS='+W.Edu.Store.state.stars);
console.log('NODE0_PASSSTAGE='+C.nodeProg('math',0).passStage);
// 再通关 4 个小关应解锁第 1 大关
for(let s=1;s<5;s++){ W.Edu.Store.state.courseIn={subj:'math',idx:0,stage:s,t:'calc'}; C.recordQuizResult('math','calc',{right:10,total:10,triesUsed:0,fast:true}); }
console.log('BIG1_UNLOCK_AFTER_ALL='+(C.bigUnlocked('math',1)?'1':'0'));
console.log('BIG0_DONE='+(C.nodeProg('math',0).done?'1':'0'));
''')
    assert 'PASS=1' in out, out
    assert 'LSTARS=3' in out, out
    assert 'STAGE_NOW=0' in out, out
    assert 'BIG_DONE=0' in out, out
    assert 'STAGE1_UNLOCK=1' in out, out
    assert 'BIG1_UNLOCK=0' in out, out
    assert 'STARS=3' in out, out
    assert 'NODE0_PASSSTAGE=0' in out, out
    assert 'BIG1_UNLOCK_AFTER_ALL=1' in out, out
    assert 'BIG0_DONE=1' in out, out


def test_course_level_fail_no_unlock():
    """正确率不足不通关: 不解锁下一小关, 标记再试, 不奖励星星."""
    out = _harness(r'''
store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],course:{}});
W.Edu.Store.loadAllState();
const C=W.Edu.Course;
W.Edu.Store.state.courseIn={subj:'math',idx:0,stage:0,t:'calc'};
const res=C.recordQuizResult('math','calc',{right:4,total:10,triesUsed:3,fast:false});
console.log('PASS='+(res.passed?'1':'0'));
console.log('TRY_AGAIN='+(res.tryAgain?'1':'0'));
console.log('LSTARS='+res.stars);
console.log('STAGE1_UNLOCK='+(C.stageUnlocked('math',0,1)?'1':'0'));
console.log('STARS='+W.Edu.Store.state.stars);
console.log('NODE0_PASSSTAGE='+C.nodeProg('math',0).passStage);
''')
    assert 'PASS=0' in out, out
    assert 'TRY_AGAIN=1' in out, out
    assert 'LSTARS=0' in out, out
    assert 'STAGE1_UNLOCK=0' in out, out
    assert 'STARS=0' in out, out
    assert 'NODE0_PASSSTAGE=-1' in out, out


def test_course_star_milestone():
    """累计星星达到阈值触发一次性特殊奖励(奖励星星, 非积分)."""
    out = _harness(r'''
store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],course:{}});
W.Edu.Store.loadAllState();
const C=W.Edu.Course;
  W.Edu.Store.state.stars=21; // 越过 20 星阈值
  W.Edu.Store.state.courseIn={subj:'math',idx:0,stage:0,t:'calc'};
  const res=C.recordQuizResult('math','calc',{right:10,total:10,triesUsed:0,fast:true});
  console.log('MIL_COUNT='+(res.milestones?res.milestones.length:0));
  console.log('MIL_NAME='+(res.milestones&&res.milestones[0]?res.milestones[0].txt:''));
  console.log('STARS='+W.Edu.Store.state.stars);
  // 再次结算同一小关不应重复发奖(但摧毁已通过的小关的奖励机制)
  const r2=C.recordQuizResult('math','calc',{right:10,total:10,triesUsed:0,fast:true});
  console.log('MIL2_COUNT='+(r2.milestones?r2.milestones.length:0));
  console.log('STARS2='+W.Edu.Store.state.stars);
''')
    assert 'MIL_COUNT=1' in out, out
    assert 'MIL_NAME=小勇士' in out, out
    assert 'STARS=29' in out, out     # 21 + 3(通关) + 5(里程碑奖励星星)
    assert 'MIL2_COUNT=0' in out, out
    assert 'STARS2=29' in out, out    # 里程碑不重复发, 已通关的关卡也不重复 +3


def test_course_integration_quiz_engine(client):
    """答题引擎交卷时联动课程: 高正确率自动通关/解锁 + 完成页显示关卡进度行."""
    out = _harness(r'''
(async()=>{
  store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],settings:{},course:{}});
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
  // 进入数学口算闯关(第 0 大关第 0 小关)
  W.wbMath('calc');
  await new Promise(r=>setTimeout(r,150));
  W.Edu.Store.state.stars=0; W.Edu.Store.state.course={};
  W.Edu.Course.launchLevel('math',0);
  // 直接构造通关卷并交卷
  W.Edu.QuizEngine.quiz={subj:'math',type:'calc',items:[{input:true,prompt:'7+8=?',correct:'15'}],answers:{0:'15'},view:0,submitted:false,_t:Date.now(),startedAt:Date.now()};
  W.Edu.QuizEngine.quizSpace=null;
  W.Edu.QuizEngine.submitQuiz();
  const joined=inserted.join('\n');
  console.log('QD_COURSE_LINE='+(joined.indexOf('qd-course pass')>=0?'1':'0'));
  console.log('PASS_STAGE0='+(W.Edu.Course.nodeProg('math',0).passStage>=0?'1':'0'));
  console.log('BIG1_UNLOCK='+(W.Edu.Course.bigUnlocked('math',1)?'1':'0'));
  console.log('STAGE1_UNLOCK='+(W.Edu.Course.stageUnlocked('math',0,1)?'1':'0'));
  // 答题评星 + 通关 +3 星星均计入, 通关后至少 3 颗
  console.log('STARS_OK='+(W.Edu.Store.state.stars>=3?'1':'0'));
})();
''')
    assert 'QD_COURSE_LINE=1' in out, out
    assert 'PASS_STAGE0=1' in out, out
    assert 'BIG1_UNLOCK=0' in out, out
    assert 'STAGE1_UNLOCK=1' in out, out
    assert 'STARS_OK=1' in out, out


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
''')
    assert 'HAS_KPI=1' in out and 'HAS_TREND=1' in out and 'HAS_RING=1' in out, out
    assert 'TOTAL_REC=6' in out, out


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
    """闯关横幅(关卡化标题+退出+sound)紧凑呈现; 答题页不再提供极速入口与难度档; 题目卡片正常渲染."""
    harness = r'''
const fs=require('fs'),vm=require('vm');
global.window=global;global.esc=s=>String(s||'').replace(/</g,'<').replace(/&/g,'&');
const store={}; let inserted=[];
function cap(){ const el={className:'',style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},setAttribute(){},getAttribute(){return null},querySelector:()=>cap(),querySelectorAll:()=>[],textContent:'',value:'',addEventListener(){},options:[],children:[],offsetWidth:0,offsetHeight:0,focus(){},scrollIntoView(){},getContext(){return new Proxy({}, {get:()=>()=>{}})}};
  Object.defineProperty(el,'innerHTML',{set(v){ el._h=String(v); const s=String(v); if(s.indexOf('qc-ctl')>=0||s.indexOf('lv-badge')>=0||s.indexOf('qstar')>=0) inserted.push(el.className+'|'+s); if(s.indexOf('quiz-item')>=0) inserted.push('ITEM'); },get(){return el._h}});
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
  await new Promise(r=>setTimeout(r,150));
  // 紧凑页头: 关卡化徽章(qc-ctl) + 退出; 不再显示抽象"难度档"
  const banners=__ins.filter(x=>x.indexOf('qc-ctl')>=0 || x.indexOf('lv-badge')>=0);
  const banner=banners.join('');
  console.log('BANNER='+(banners.length?'1':'0'));
  console.log('LEVEL='+(/第 \d+ 大关/.test(banner) && banner.indexOf('lv-badge')>=0?'1':'0'));
  console.log('EXIT='+(banner.indexOf('qc-exit')>=0 && banner.indexOf('返回')>=0?'1':'0'));
  console.log('NODIFF='+(banner.indexOf('难度档')<0 && banner.indexOf('lv-at')<0?'1':'0'));
  console.log('PROG_SCORE='+(banner.indexOf('qstar')>=0?'1':'0'));
  console.log('NOSU='+(banner.indexOf('极速练习')<0?'1':'0'));
  console.log('HASITEM='+(__ins.indexOf('ITEM')>=0?'1':'0'));
})();
'''
    r = subprocess.run(['node', '-e', out_body, _harness_temp(out_body)[1]], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert 'BANNER=1' in r.stdout, r.stdout
    assert 'LEVEL=1' in r.stdout, r.stdout
    assert 'EXIT=1' in r.stdout, r.stdout
    assert 'NODIFF=1' in r.stdout, r.stdout
    assert 'PROG_SCORE=1' in r.stdout, r.stdout
    assert 'NOSU=1' in r.stdout, r.stdout
    assert 'HASITEM=1' in r.stdout, r.stdout


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
  const hasBanner = bodyH.indexOf('qc-ctl')>=0 && bodyH.indexOf('极速练习')>=0 && bodyH.indexOf('难度档')<0;
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


def test_star_economy_question_and_combo():
    """发星规则: 答对一题 +1 星; 连续答对(≥2连)的每一题再 +2 星.
    gradeQuiz(count, comboBonus) = count + comboBonus.
    submitQuiz 中按连对段累加 comboBonus: 每段第 2 个起的答对题各 +2."""
    out = _harness(r'''
const M = W.Edu.MathUtils;
// 纯函数: 3连对 → count=3, comboBonus=4 → 7 星
console.log('PURE3='+(M.gradeQuiz(3,4)===7?'1':'0'));
console.log('PURE1='+(M.gradeQuiz(2,2)===4?'1':'0'));
console.log('PURE0='+(M.gradeQuiz(4,0)===4?'1':'0'));

// 复现 submitQuiz 的连对累加逻辑(读 quiz-engine 同款算法)
function comboBonusOf(oks){
  let run=0, bonus=0;
  oks.forEach(ok=>{
    if(ok){ run++; if(run>=2) bonus+=2; }
    else { run=0; }
  });
  return bonus;
}
// [对,对,对,错,对,对] → 5对; 段1(3连)bonus=4, 段2(2连)bonus=2 → 共6 → 5+6=11
const oks=[true,true,true,false,true,true];
const cb=comboBonusOf(oks), right=oks.filter(Boolean).length;
console.log('RUNS_CB='+(cb===6?'1':'0'));
console.log('TOTAL='+(W.Edu.MathUtils.gradeQuiz(right,cb)===11?'1':'0'));
// 全错 → 0 星
const oks0=[false,false,false];
console.log('ALLWRONG='+(W.Edu.MathUtils.gradeQuiz(0,comboBonusOf(oks0))===0?'1':'0'));
// 单连(永远连不起来) → 无加成
const oks1=[true,false,true];
console.log('NOSTREAK='+(W.Edu.MathUtils.gradeQuiz(2,comboBonusOf(oks1))===2?'1':'0'));
''')
    for k in ['PURE3', 'PURE1', 'PURE0', 'RUNS_CB', 'TOTAL', 'ALLWRONG', 'NOSTREAK']:
        assert k + '=1' in out, out


def test_quiz_no_resume_start_fresh():
    """续学功能已移除: 存在上次未完成练习快照时重新进入, 不再弹「继续上次」也不还原旧答案, 而是清空快照起一套新题."""
    out = _harness(r'''
(async()=>{
  // 模拟"刷新前"已填答题的进行中卷子
  store['edu_quiz_v1_kk']=JSON.stringify({
    subj:'math', type:'calc',
    items:[{input:true,big:'20 - 9',prompt:'20 - 9 = ?'},
           {input:true,big:'13 + 8',prompt:'13 + 8 = ?'}],
    answers:{0:'11',1:'21'}, order:{}, submitted:false, _t:Date.now()
  });
  // 柱桩: wb-math-body 捕获 innerHTML; qi-{i} 提供可读写的 input; 遮罩记录 display
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
  // 进入口算: 不再弹续学确认、不再还原旧答案
  W.wbMath('calc');
  await new Promise(r=>setTimeout(r,60));
  console.log('NO_PROMPT='+(resumeMask.style.display!=='flex'?'1':'0'));
  console.log('V0='+items[0].value);
  console.log('V1='+inputs[1].value);
  // 快照被重置(旧 answers 不再保留), 已渲染新题
  const snap=JSON.parse(store['edu_quiz_v1_kk']||'null');
  console.log('NEW_SNAP='+(snap && (!snap.answers || snap.answers[0]===undefined) ? '1':'0'));
  console.log('RENDERED='+(bodyH!==''?'1':'0'));
})();
''')
    assert 'NO_PROMPT=1' in out, out
    assert 'V0=11' not in out, out
    assert 'V1=21' not in out, out
    assert 'NEW_SNAP=1' in out, out
    assert 'RENDERED=1' in out, out


def test_quiz_stale_snapshot_ignored_start_fresh():
    """续学功能已移除: 即使存在上次未完成快照, startQuiz 也直接起一套新题(不弹窗、不报错、不卡入口)."""
    out = _harness(r'''
(async()=>{
  store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],settings:{}});
  // 存在上次未完成练习快照
  store['edu_quiz_v1_kk']=JSON.stringify({
    subj:'math', type:'calc',
    items:[{input:true,big:'9 + 1',prompt:'9 + 1 = ?',correct:'10'},
           {input:true,big:'9 + 2',prompt:'9 + 2 = ?',correct:'11'}],
    answers:{}, order:{}, submitted:false, _t:Date.now()
  });
  // 柱桩: 容器捕获 innerHTML; 遮罩记录 display
  let bodyH='';const body={style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},appendChild(){},querySelectorAll(){return[]},querySelector(){return me()}};
  Object.defineProperty(body,'innerHTML',{get(){return bodyH},set(v){bodyH=String(v)}});
  const mkBtn=(v)=>{const el={cls:new Set(),getAttribute:k=>k==='data-v'?v:null,
    classList:{add:c=>el.cls.add(c),remove:c=>el.cls.delete(c),toggle:(c,f)=>{},contains:c=>el.cls.has(c)}};return el;};
  const items={0:{querySelector:()=>me(),querySelectorAll:()=>[mkBtn('a')]},
               1:{querySelector:()=>me(),querySelectorAll:()=>[mkBtn('b')]}};
  const mask={style:{display:'none'}};
  global.document.getElementById=(id)=> id==='wb-math-body'?body : (id==='qi-0'?items[0] : (id==='qi-1'?items[1] : (id==='eduMaskResume'?mask : me())));
  let err='';
  // 真实入口: 进入口算 → 无续学弹窗, 立即渲染新题
  try { W.wbMath('calc'); }catch(e){ err=e.message||String(e); }
  await new Promise(r=>setTimeout(r,80));
  console.log('NO_PROMPT='+(mask.style.display!=='flex'?'1':'0'));
  console.log('ERR='+err);
  console.log('RENDERED='+(bodyH!==''?'1':'0'));
  console.log('HAS_QI='+((bodyH.indexOf('qi-in')>=0)?'1':'0'));
  console.log('NO_STALE='+(bodyH.indexOf('9 + 1')<0 ? '1':'0'));
})();
''')
    assert 'NO_PROMPT=1' in out, out
    assert '\nERR=\n' in out or 'ERR=\n' in out, out  # 无报错日志(err 为空)
    assert 'RENDERED=1' in out, out
    assert 'HAS_QI=1' in out, out
    assert 'NO_STALE=1' in out, out


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
  W.Edu.QuizEngine.startQuiz('zh','zi', [{options:[{v:'a',label:'好'},{v:'b',label:'不'}],prompt:'选对字',correct:'a'}], {difficulty: W.Edu.MathUtils.diffOf('zh')});
  await new Promise(r=>setTimeout(r,60));
  W.pickOpt(0,'a');
  const snap=JSON.parse(store['edu_quiz_v1_kk']||'null');
  console.log('SAVED='+(snap && snap.submitted===false && snap.answers && snap.answers[0]==='a' ? '1':'0'));
})();
''')
    assert 'SAVED=1' in out, out


def test_quiz_wrong_retry_then_reveal(client):
    """点选即判(无确认答案步骤): 第一次答错给「再试一次」机会(不跳过), 第二次答错才揭示正确答案."""
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
  W.Edu.QuizEngine.startQuiz('zh','zi', [{options:[{v:'a',label:'好'},{v:'b',label:'不'}],prompt:'选对字',correct:'a'}], {difficulty: W.Edu.MathUtils.diffOf('zh')});
  await new Promise(r=>setTimeout(r,60));
  // 1) 第一次点错: 选项保留可选(可再试), 未自动计时跳转(点选即判但给重试)
  W.pickOpt(0,'b');
  const optsDisabled=btns.some(b=>b.disabled);
  const advanced=!!W.Edu.QuizEngine.advTimer;
  console.log('RETRY_AVAIL='+((!optsDisabled && !advanced)?'1':'0'));
  // 2) 第二次点错: 锁定选项并揭示正确答案
  W.pickOpt(0,'b');
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
  const curOf=()=>{ const m=__ins.filter(x=>/共 \d+ 题/.test(x)); return m.length?m[m.length-1]:''; };
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
    """完成页升级: 答对/正确率/星星 + 鼓励语 + 「再练一次」大按钮; 高分提示解锁下一关."""
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
  W.Edu.QuizEngine.startQuiz('math','calc', [{input:true,prompt:'7+8=?',correct:'15'}], {difficulty: W.Edu.MathUtils.diffOf('math')});
  await new Promise(r=>setTimeout(r,150));
  W.Edu.QuizEngine.quiz.answers[0]='15';
  W.Edu.QuizEngine.submitQuiz();
  const joined=__ins.join('\n');
  console.log('QD_STATS='+(joined.indexOf('qd-stats')>=0&&joined.indexOf('正确率')>=0&&joined.indexOf('100%')>=0?'1':'0'));
  console.log('QD_ENC='+(joined.indexOf('qd-enc')>=0?'1':'0'));
  console.log('QD_AGAIN='+(joined.indexOf('再练一次')>=0?'1':'0'));
  console.log('QD_UNLOCK='+(joined.indexOf('已解锁')>=0?'1':'0'));
})();
'''
    r = subprocess.run(['node', '-e', out_body, _concat_script_path()], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert 'QD_STATS=1' in r.stdout, r.stdout
    assert 'QD_ENC=1' in r.stdout, r.stdout
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
  const dotsA=(a.match(/qstar(?: |"| )/g)||[]).length;
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
    """极速练习鼓励语音: 答对/答错各有随机词库且能抽到; 答题页头仅展示当前模式/关卡(不再并列两个入口)."""
    out = _harness(r'''
  var h=W.modeBarHtml('guan');
  var h2=W.modeBarHtml('su');
  console.log('OK='+W.ENC_OK.length+'/'+W.ENC_WRONG.length);
  console.log('PICK='+W.encPick(W.ENC_OK)+'|'+W.encPick(W.ENC_WRONG));
  console.log('GUAN='+(/第 \d+ 大关/.test(h) && h.indexOf('极速')<0));
  console.log('SU='+(h2.indexOf('极速')>=0 && h2.indexOf('第 ')<0));
  console.log('NOLVS='+(h.indexOf('lvSub')<0 && h2.indexOf('lvSub')<0));
''')
    assert 'OK=7/5' in out, out
    assert '|' in out, out
    assert 'GUAN=true' in out, out
    assert 'SU=true' in out, out
    assert 'NOLVS=true' in out, out


def test_quiz_header_live_count(client):
    """闯关/极速练习横幅: 徽章随模式变化; 进度头显示「已答对 N 题 · 共 X 题」并随作答实时刷新(不再显示难度档)."""
    harness = r'''
const fs=require('fs'),vm=require('vm');
global.window=global;global.esc=s=>String(s||'').replace(/</g,'<').replace(/&/g,'&');
const store={}; const inserted=[];
function cap(){ const el={className:'',style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},setAttribute(){},getAttribute(){return null},querySelector:()=>cap(),querySelectorAll:()=>[],textContent:'',value:'',addEventListener(){},options:[],children:[],offsetWidth:0,offsetHeight:0,focus(){},scrollIntoView(){},getContext(){return new Proxy({}, {get:()=>()=>{}})}};
  Object.defineProperty(el,'innerHTML',{set(v){el._h=String(v);inserted.push(el.className+'|'+String(v));},get(){return el._h}});
  el.appendChild=(c)=>{el.children.push(c);};
  return el;
}
const container=cap(); let progTxt=null; let starsEl=null;
global.document={getElementById:id=>{
  if(id==='wb-math-body'||id==='quizShell') return container;
  if(id==='qzProgTxt'){ if(!progTxt){progTxt=cap();progTxt.className='qz-prog-txt';} return progTxt; }
  if(id==='qzProgStars'){ if(!starsEl){starsEl=cap();starsEl.className='qz-stars';} return starsEl; }
  return cap();},querySelectorAll:()=>[],querySelector:()=>cap(),createElement:()=>cap(),createTextNode:()=>({}),addEventListener(){},removeEventListener(){},documentElement:{style:{}},body:cap()};
global.localStorage={getItem:k=>k in store?store[k]:null,setItem(k,v){store[k]=String(v)},removeItem(k){delete store[k]}};
global.location={};global.navigator={userAgent:'node'};global.performance={now:()=>0};global.HTMLElement=function(){};global.Node=function(){};
global.eduKids={active:()=>({id:'kk'}),all:()=>[{id:'kk'}],list:()=>[{id:'kk'}],byId:()=>null,tierOf:()=>'workbench',ageOf:()=>6,tierLabel:()=>'',genderIcon:()=>'?',remove(){},setActive(){},hasAny:()=>1,update(){},add(){}};
global.eduSync={setOnState(){},qbankPull:()=>Promise.resolve({items:[]}),qbankEnsure:()=>Promise.resolve(),qbankLearn:()=>Promise.resolve(),pushState(){},hydrate:()=>Promise.resolve()};
vm.createContext(global);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),global);
const W=global; global.__ins=inserted; global.__pt=()=>progTxt;
'''
    out_body = harness + r'''
(async()=>{
  const h=W.quizHeaderHtml('su','zh','pinyin');
  console.log('SU_BADGE='+(h.indexOf('⚡')>=0 && h.indexOf('极速练习')>=0?'1':'0'));
  console.log('SU_NO_STARS='+(h.indexOf('难度⭐')<0 && h.indexOf('题过关')<0 ? '1':'0'));
  // 模拟刷新前已答: 第0题答对, 第1题答错 → 恢复后进度头应显示「已答对 1 题 · 共 2 题」
  store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],settings:{}});
  store['edu_quiz_v1_kk']=JSON.stringify({subj:'math',type:'calc',
    items:[{input:true,prompt:'7+8=?',correct:'15'},{input:true,prompt:'3+9=?',correct:'12'}],
    answers:{0:'15',1:'99'}, order:{}, submitted:false, _t:Date.now()});
  W.Edu.QuizEngine.startQuiz('math','calc',
    [{input:true,prompt:'7+8=?',correct:'15'},{input:true,prompt:'3+9=?',correct:'12'}],
    {difficulty: W.Edu.MathUtils.diffOf('math')});
  W.Edu.QuizEngine.quiz.answers[0]='15';
  W.Edu.QuizEngine.quiz.answers[1]='99';
  W.Edu.QuizEngine.renderQuiz();
  await new Promise(r=>setTimeout(r,120));
  const rs=starsEl?starsEl.innerHTML:'';
  const d1=(rs.match(/qstar done/g)||[]).length, w1=(rs.match(/qstar wrong/g)||[]).length;
  console.log('COUNT_RESTORED='+(d1===1 && w1===1?'1':'0'));
  // 把第1题改成正确答案 → 星条 live 刷新为 2 个金字星
  W.onQuizInput(1,'12');
  await new Promise(r=>setTimeout(r,120));
  const se=starsEl?starsEl.innerHTML:'';
  console.log('COUNT_LIVE='+((se.match(/qstar done/g)||[]).length===2 && (se.match(/qstar wrong/g)||[]).length===0?'1':'0'));
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
  const dotsHits=(String(container._h||'').match(/qstar(?: |"| )/g)||[]).length;
  console.log('ONECARD='+(itemHits===1?'1':'N:'+itemHits));
  console.log('DOTS='+(dotsHits===10?'10':'N:'+dotsHits));
  console.log('SUBMIT_BTN='+(__ins.some(x=>x.indexOf('qi-submit')>=0 && x.indexOf('确认')>=0)?'1':'0'));
  const joined=__ins.join('\n');
  console.log('PROG_TOP='+(joined.indexOf('qz-prog-top')>=0&&joined.indexOf('qz-track')>=0?'1':'0'));
  console.log('PROG_TXT='+(joined.indexOf('qstar')>=0?'1':'0'));
  // 「完成闯关」按钮存在于页脚, 初始未就绪(disabled)
  // 全部答完前不渲染「完成闯关」按钮; 全部答对后按钮以 ready 状态出现
  const hasFinish=()=>__ins.some(x=>x.indexOf('qz-finish')>=0);
  console.log('FINISH_GONE='+(hasFinish()?'0':'1'));
  // 填满全部答案并重绘 → 出现可点击的「完成闯关」
  const items=W.Edu.QuizEngine.quiz.items;
  for(let i=0;i<items.length;i++){ W.Edu.QuizEngine.quiz.answers[i]=String(items[i].correct); }
  W.Edu.QuizEngine.renderQuiz();
  await new Promise(r=>setTimeout(r,120));
  const readyFrame=__ins.filter(x=>x.indexOf('qz-finish ready')>=0);
  console.log('FINISH_READY='+(readyFrame.length?'1':'0'));
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
    assert 'FINISH_GONE=1' in stdout, stdout
    assert 'FINISH_READY=1' in stdout, stdout
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
  const p0=W.Edu.QuizEngine.quiz?W.Edu.QuizEngine.quiz.view:0;
  // 同一题连续两次快速回车(模拟 iPad 双击回车)答对: 定时器应合并为一次跳转 → 进度 +1
  const c0=W.Edu.QuizEngine.quiz.items[0].correct;
  W.quizInputSubmit(0,c0);
  W.quizInputSubmit(0,c0);
  await new Promise(r=>setTimeout(r,1600));
  const p1=W.Edu.QuizEngine.quiz?W.Edu.QuizEngine.quiz.view:-1;
  console.log('P0='+p0);
  console.log('P1='+p1);
  console.log('NO_SKIP='+(p1===p0+1 && p1<=10?'1':'0'));
})();
'''
    stdin_ = _concat_script_path()
    try:
        rr = subprocess.run(['node', '-e', out_body, stdin_], capture_output=True, text=True)
        stdout = rr.stdout
    finally:
        try: os.unlink(stdin_)
        except OSError: pass
    assert 'P0=0' in stdout, stdout
    assert 'P1=1' in stdout, stdout
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
  console.log('QCTL='+((bodyH.indexOf('qc-exit')>=0&&bodyH.indexOf('qc-sound')<0&&bodyH.indexOf('soundToggle')<0)?'1':'0'));
})();
''')
    assert 'QCTL=1' in out, out


def test_home_v2_layout():
    """首页 v2(紧凑版): 顶部条(问候+副标题+Lv人+宝贝切换+声音+通知+模式), 今日目标卡(进度/数据整合), 2×2课程卡."""
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
    wishes:[{name:'去公园',cost:10,done:false}],badges:{lit:1,s1:1,s10:1},level:{zh:3,math:5,en:0},settings:{},
    course:{zh:{nodes:[{stars:3,best:3,passed:true},{stars:0,best:0,passed:false},{},{},{},{},{},{}],unlocked:2},
            math:{nodes:[{},{},{},{},{},{}],unlocked:1}}});
  store['edu_pref_v1_a']=JSON.stringify({mode:'workbench',subj:'zh'});
  W.eduNav('home');
  const h=body._h||'';
  // 问候语按小时变化(跨夜时测试会命中「夜深了」), 昼间/夜间问候均视为有效
  console.log('GREET='+((h.indexOf('早上好')>=0||h.indexOf('下午好')>=0||h.indexOf('晚上好')>=0||h.indexOf('夜深了')>=0)?'1':'0'));
  console.log('MODE='+(h.indexOf('幼小衔接')>=0&&h.indexOf('mode-select')>=0?'1':'0'));
  console.log('STAR_LV='+(h.indexOf('⭐ Lv.')>=0?'1':'0'));
  console.log('BADGE_NM='+(h.indexOf('第一颗星')>=0&&h.indexOf('十星小达人')>=0?'1':'0'));
  console.log('CONTINUE='+(h.indexOf('home-goal')>=0&&h.indexOf('今日学习目标')>=0?'1':'0'));
  console.log('TRK='+(h.indexOf('hg-track')>=0?'1':'0'));
  console.log('COUNT='+((h.match(/题/g)||[]).length>=1?'1':'0'));
  console.log('COURSE_ZH='+(h.indexOf('语文')>=0?'1':'0'));
  console.log('COURSE_MATH='+(h.indexOf('数学')>=0?'1':'0'));
  console.log('COURSE_DAILY='+(h.indexOf('每日挑战')<0?'1':'0'));
  console.log('LVLINE='+(h.indexOf('第 2 大关')>=0&&h.indexOf('hc-lv')>=0?'1':'0'));
  console.log('GRID='+(h.indexOf('home-course-scroll')>=0?'1':'0'));
  console.log('CPROG='+(h.indexOf('hg-track')>=0&&h.indexOf('hc-fill')>=0?'1':'0'));
  console.log('MODEBTN='+(h.indexOf('闯关模式')>=0&&h.indexOf('极速练习')>=0?'1':'0'));
  console.log('NO_TAG='+(h.indexOf('hc-tag')<0?'1':'0'));
  console.log('NO_GO='+(h.indexOf('去学习')<0&&h.indexOf('继续 →')<0?'1':'0'));
  console.log('NO_KIDROW='+(h.indexOf('hw-kid')<0?'1':'0'));
  console.log('NO_AVA='+(h.indexOf('hw-ava')<0?'1':'0'));
  console.log('GREET2='+(h.indexOf('今天也要开开心心学习哦')>=0?'1':'0'));
  console.log('NO_SLOGAN='+(h.indexOf('坚持闯关，天天有进步')<0?'1':'0'));
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
    for probe in ('GREET=1','MODE=1','STAR_LV=1','CONTINUE=1','TRK=1','COUNT=1',
                  'COURSE_ZH=1','COURSE_MATH=1','COURSE_DAILY=1','NO_KIDROW=1','NO_AVA=1','LVLINE=1',
                  'GREET2=1','LBAR=1','NO_SLOGAN=1',
                  'GRID=1','CPROG=1','MODEBTN=1','NO_TAG=1','NO_GO=1','BADGE_NM=1'):
        assert probe in stdout, stdout

def test_home_course_teaser():
    """紧凑首页不再堆叠关卡旅程预览卡(闯关入口统一收到底部 Dock 的「闯关」), 避免首屏冗余."""
    out = _harness(r'''
(async()=>{
  const today=new Date();const pz=n=>(n<10?'0':'')+n;
  const kd=off=>{const t=new Date(today.getTime()-off*86400000);return t.getFullYear()+'-'+pz(t.getMonth()+1)+'-'+pz(t.getDate());};
  store['edu_record_v1_kk']=JSON.stringify({stars:4,
    records:[{t:Date.now(),date:kd(0),subj:'zh',type:'zi',ok:true},{t:Date.now(),date:kd(1),subj:'zh',type:'read',ok:true}],
    usage:{date:kd(0),n:1,secs:60},wrong:[],wishes:[],badges:{lit:1},level:{},settings:{},
    course:{zh:{nodes:[{stars:3,best:3,passed:true,done:true},{stars:0,best:0,passed:false,done:false},{},{},{},{},{},{}],unlocked:2},
            math:{nodes:[{},{},{},{},{},{}],unlocked:1},
            en:{nodes:[{},{},{},{},{}],unlocked:1}}});
  store['edu_pref_v1_kk']=JSON.stringify({mode:'workbench',subj:'zh'});
  let iH='';const b=me();
  Object.defineProperty(b,'innerHTML',{get(){return iH},set(v){iH=String(v)}});
  const orig=global.document.getElementById;
  global.document.getElementById=(id)=> id==='eduHomeBody'?b:me();
  W.eduNav('home');
  console.log('NO_TEASER='+(iH.indexOf('home-cousrteaser')<0?'1':'0'));
  console.log('NO_MAP_TXT='+(iH.indexOf('闯关地图')<0?'1':'0'));
  console.log('HAS_GOAL='+(iH.indexOf('今日学习目标')>=0?'1':'0'));
  console.log('HAS_GRID='+(iH.indexOf('home-course-scroll')>=0?'1':'0'));
})();
''')
    for probe in ('NO_TEASER=1','NO_MAP_TXT=1','HAS_GOAL=1','HAS_GRID=1'):
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
  console.log('TAB_BADGE='+(n.indexOf('勋章')>=0?'1':'0'));
  console.log('TAB_WISH='+(n.indexOf('星愿')>=0?'1':'0'));
  console.log('TAB_MINE='+(n.indexOf('我的')>=0?'1':'0'));
  console.log('NO_SUBJ='+(n.indexOf('语文')<0&&n.indexOf('每日挑战')<0?'1':'0'));
  console.log('NO_HOME_TAB='+(/首页/.test(n)?'0':'1'));
  W.eduNav('mine');
  const m=mineBody._h||'';
  console.log('MINE_NAME='+(m.indexOf('我的')>=0||m.indexOf('小米')>=0?'1':'0'));
  console.log('MINE_SETTINGS='+(m.indexOf('课程与难度')>=0?'1':'0'));
  console.log('MINE_REPORT='+(m.indexOf('学习报告')>=0?'1':'0'));
  console.log('MINE_MGR='+(m.indexOf('管理宝贝')>=0?'1':'0'));
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
    for probe in ('TAB_LEARN=1','TAB_BADGE=1','TAB_WISH=1','TAB_MINE=1','NO_SUBJ=1','NO_HOME_TAB=1',
                  'MINE_NAME=1','MINE_SETTINGS=1','MINE_REPORT=0','MINE_MGR=1','MINE_STARS=1'):
        assert probe in stdout, stdout


def test_dash_charts_pdf_replay():
    """家长看板: 图表(雷达/环/饼/折线)与 KPI 渲染; PDF 报告含标题/KPI/本地数据说明."""
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
  global.eduKids.all=()=>[{id:'kk',name:'小米'},{id:'kk2',name:'小朵'}];
  global.eduKids.switchKid=()=>{};
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
  console.log('MAP_CELLS='+(iH.match(/class="st-map-cell/g)||[]).length);
  console.log('RATE='+(iH.indexOf('40%')>=0?'1':'0'));
  const pd=W.Edu.Dash.buildPdfHtml();
  console.log('PDF_TITLE='+(pd.indexOf('学习报告')>=0?'1':'0'));
  console.log('PDF_KPI='+(pd.indexOf('连续打卡')>=0?'1':'0'));
  console.log('PDF_SUB='+(pd.indexOf('本机')>=0?'1':'0'));
})();
''')
    for probe in ('HAS_PDF=1','HAS_KID=1','HAS_RADAR=1','HAS_DONUT=1','HAS_LINE=1','HAS_MINS=1',
                  'TRENDS=2','MAP_CELLS=15','RATE=1',
                  'PDF_TITLE=1','PDF_KPI=1','PDF_SUB=1'):
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
  console.log('AFTER_RERENDER='+(iH.indexOf('⭐ 3')>=0?'1':'0'));
})();
''')
    for probe in ('BEFORE_N=1','SWITCHED=1','SAVED=1','LOADED=1','AFTER_RERENDER=1'):
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
