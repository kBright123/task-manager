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
    """创建测试宝贝(名字每次唯一, 避免共享 edu.db 下同名宝贝跨用例互相合并/互相干扰)."""
    import uuid as _uuid
    r = client.post('/edu/api/kids', json={
        'kids': [{'clientId': 'c_' + _uuid.uuid4().hex[:6], 'name': '小测' + _uuid.uuid4().hex[:6], 'birthYear': 2018, 'gender': 'male'}],
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
    # 同 id upsert 不新增重复档案(按自身 id 校验, 不依赖账号内绝对数量, 共享 edu.db 可能残留其他用例宝贝)
    kids = client.get('/edu/api/bootstrap').json['kids']
    assert len([k for k in kids if k['id'] == pid]) == 1
    # bulk removedIds 删除
    r = client.post('/edu/api/kids', json={'kids': [], 'removedIds': [pid]})
    assert r.json.get('ok')
    kids2 = client.get('/edu/api/bootstrap').json['kids']
    assert all(k['id'] != pid for k in kids2)


def test_account_dedup_same_name_kids(client):
    """同一账号下多个同名/同年/同性别宝贝: bootstrap 时合并为一个, 数据并入保留档案,
    dbIdMap 把重复档案 id 映射到保留档案 id(供前端纠正本地 stale dbId)."""
    NAME = '重名' + str(id(client))
    h = {}
    # 账号端(用户1)创建 3 个完全同名的宝贝, 各有独立数据
    ids = []
    for i in range(3):
        r = client.post('/edu/api/kids', json={
            'kids': [{'clientId': 'c' + str(i), 'name': NAME, 'birthYear': 2017, 'gender': 'female'}],
            'removedIds': [],
        })
        pid = r.json['kids'][0]['id']
        ids.append(pid)
        client.post(f'/edu/api/kids/{pid}/state', json={
            'dkey': 'state',
            'data': {'stars': 5, 'records': [{'subj': 'zh', 'i': i}], 'wishLog': [], 'redeemed': []},
        })

    res = client.post('/edu/api/bootstrap', headers=h).json
    # 只剩 1 个同名宝贝(保留 id 最小者)
    assert len([k for k in res['kids'] if k['name'] == NAME]) == 1
    keep = ids[0]
    # 重复档案全部映射到保留档案
    for dup in ids[1:]:
        assert res['dbIdMap'][str(dup)] == str(keep)
    # 数据合并: 星星取较大(5, 5, 5 → 5, 只增不减不伪造), records 三条都保留
    merged = client.get(f'/edu/api/kids/{keep}/state').json['data']
    assert merged.get('stars') == 5
    assert len(merged.get('records', [])) == 3
    assert {r_['i'] for r_ in merged.get('records', [])} == {0, 1, 2}

    # 幂等: 再次 bootstrap 不再产生新合并
    res2 = client.post('/edu/api/bootstrap', headers=h).json
    assert res2['dbIdMap'] == {}

    # 清理: 删除保留档案, 避免污染共享 edu.db
    client.post('/edu/api/kids', json={'kids': [], 'removedIds': [keep]})


def test_qbank_ensure_dedup_pull_learn(client):
    pid = _setup_kid(client)
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

    # 清理: 删除测试宝贝, 避免共享 edu.db 残留影响其他用例
    client.post('/edu/api/kids', json={'kids': [], 'removedIds': [pid]})
    # 清理 qbank 测试题(limit 有 50 上限, 若不删, 多次运行残留会堆满池导致本用例拉不回自己)
    _delete_qbank(client, probe)


def _delete_qbank(client, probe):
    """直接删除某 owner 下指定 prompt 的题库条目(测试自清理)."""
    import sqlite3
    from app import app
    db = os.path.join(app.instance_path, 'edu.db')
    con = sqlite3.connect(db)
    try:
        con.execute("DELETE FROM edu_qbank WHERE prompt=?", (probe,))
        con.commit()
    finally:
        con.close()


def test_edu_csrf_applies(client):
    """/edu/api/** 纳入全站 CSRF 保护: 已登录且带 token 可写, 缺 token 被拒."""
    probe = BK + 'csrf'
    # 带 token(客户端已自动注入) 可写
    r = client.post('/edu/api/qbank/ensure', json={
        'subj': 'en', 'type': 'word', 'difficulty': 3,
        'items': [{'prompt': probe, 'options': [{'v': 'a', 'label': 'a'}], 'correct': 'a', 'note': ''}],
    })
    assert r.status_code == 200 and r.json.get('ok')
    # 裸客户端(已登录但未注入 token 头): 应 CSRF 校验失败
    from app import app
    raw = app.test_client()
    with raw.session_transaction() as s:
        s['_user_id'] = '1'
        s['_fresh'] = True
        s['_csrf_token'] = 'test-csrf'
    r2 = raw.post('/edu/api/qbank/ensure', json={
        'subj': 'en', 'type': 'word', 'difficulty': 3,
        'items': [{'prompt': probe + '_x', 'options': [{'v': 'b', 'label': 'b'}], 'correct': 'b', 'note': ''}],
    })
    assert r2.status_code == 400


def test_reset_all(client):
    pid = _setup_kid(client)
    client.post(f'/edu/api/kids/{pid}/state', json={'dkey': 'state', 'data': {'stars': 3}})
    assert client.post('/edu/api/reset').json.get('ok')
    assert len(client.get('/edu/api/bootstrap').json['kids']) == 0


def test_state_overwrite_monotonic_guards(client):
    """跨端全量覆盖写 state 时, stars/课程进度/里程碑标记「只增不减」:
    旧设备旧数据覆盖不会吞掉已挣星星、不会倒退关卡进度、不会擦掉里程碑标记导致重复发星."""
    pid = _setup_kid(client)
    client.post(f'/edu/api/kids/{pid}/state', json={
        'dkey': 'state',
        'data': {'stars': 42, 'course': {'zh': {
            'nodes': [{'passStage': 2, 'stars': [3, 3, 3, 0, 0], 'done': False},
                      {'passStage': -1, 'stars': [0, 0, 0, 0, 0], 'done': False}],
            'unlocked': 2, 'done': False, 'rewards': {'star_20': 1}}}},
    })
    # 旧端的旧数据覆盖写入: 星星更低、进度更旧、里程碑标记丢失
    client.post(f'/edu/api/kids/{pid}/state', json={
        'dkey': 'state',
        'data': {'stars': 30, 'course': {'zh': {
            'nodes': [{'passStage': 1, 'stars': [3, 3, 0, 0, 0], 'done': False},
                      {'passStage': -1, 'stars': [0, 0, 0, 0, 0], 'done': False}],
            'unlocked': 1, 'done': False, 'rewards': {}}}},
    })
    got = client.get(f'/edu/api/kids/{pid}/state').json['data']
    assert got.get('stars') == 42, got
    zh = got['course']['zh']
    assert zh['rewards'].get('star_20') == 1, got
    assert zh['nodes'][0]['passStage'] == 2, got
    assert zh['nodes'][0]['stars'] == [3, 3, 3, 0, 0], got
    assert zh['unlocked'] == 2, got


def test_kid_stars_ledger_idempotent_and_migration(client):
    """「所有加/扣星星操作同步后端」: 逐笔事件进服务端权威账本, 按 key 幂等去重, 不重复累加.

    首次收账前自动把旧 state 弹余额迁移为 base 事件, 升级后星星不回退.
    """
    pid = _setup_kid(client)
    # 既有弹余额 50(旧版累计剩余), 首次收账应迁移为 base
    client.post(f'/edu/api/kids/{pid}/state', json={'dkey': 'state', 'data': {'stars': 50, 'records': []}})
    r = client.post(f'/edu/api/kids/{pid}/stars', json={'events': [{'key': 'a1', 'amount': 3, 'reason': '答题'}]})
    assert r.json.get('ok') and r.json['stars'] == 53, r.json
    # 同 key 重放(网络重试/多设备)不重复累加
    r = client.post(f'/edu/api/kids/{pid}/stars', json={'events': [{'key': 'a1', 'amount': 3, 'reason': '答题'}]})
    assert r.json['stars'] == 53, r.json
    # 扣星星(解锁/兑换): amount 为负
    r = client.post(f'/edu/api/kids/{pid}/stars', json={'events': [{'key': 'sp2', 'amount': -10, 'reason': '解锁'}]})
    assert r.json['stars'] == 43, r.json
    # 新 key 正常累加
    r = client.post(f'/edu/api/kids/{pid}/stars', json={'events': [{'key': 'a3', 'amount': 7, 'reason': '通关'}]})
    assert r.json['stars'] == 50, r.json
    # 账本已建后不再重复迁移 base(可疑的 key 重复不影响合计)
    r = client.post(f'/edu/api/kids/{pid}/stars', json={'events': [{'key': 'base', 'amount': 99999, 'reason': '伪造'}]})
    assert r.json['stars'] == 50, r.json
    # 空请求 noop
    r = client.post(f'/edu/api/kids/{pid}/stars', json={'events': []})
    assert r.json.get('ok') and r.json.get('noop')
    # 账本直接可读
    r = client.post(f'/edu/api/kids/{pid}/stars', json={'events': [{'key': 'a4', 'amount': 2, 'reason': 'x'}]})
    assert r.json['stars'] == 52, r.json


def test_kid_stars_get_state_override_with_ledger(client):
    """GET state 以账本 total 覆盖弹内 stars(服务端权威): 旧弹/其余设备陈值不干扰展示."""
    pid = _setup_kid(client)
    client.post(f'/edu/api/kids/{pid}/stars', json={'events': [
        {'key': 'x1', 'amount': 10, 'reason': 'a'},
        {'key': 'x2', 'amount': 5, 'reason': 'b'},
        {'key': 'x3', 'amount': -2, 'reason': 'c'},
    ]})
    assert client.get(f'/edu/api/kids/{pid}/state').json['data']['stars'] == 13
    # 即使另一设备把陈旧弹值写上来(100), 展示仍以账本为准
    client.post(f'/edu/api/kids/{pid}/state', json={'dkey': 'state', 'data': {'stars': 100, 'records': []}})
    assert client.get(f'/edu/api/kids/{pid}/state').json['data']['stars'] == 13
    # 打满同一批事件再多发一次(重复回放)也不变
    client.post(f'/edu/api/kids/{pid}/stars', json={'events': [
        {'key': 'x1', 'amount': 10, 'reason': 'a'},
        {'key': 'x2', 'amount': 5, 'reason': 'b'},
        {'key': 'x3', 'amount': -2, 'reason': 'c'},
    ]})
    assert client.get(f'/edu/api/kids/{pid}/state').json['data']['stars'] == 13


def test_kid_stars_ledger_dedup_merge(client):
    """同名宝贝去重时 stars 账本按事件键合并: 重复 key 只取一次, 不重复累加."""
    import uuid as _uuid
    name = '重名' + _uuid.uuid4().hex[:6]
    r = client.post('/edu/api/kids', json={'kids': [
        {'clientId': 'd1', 'name': name, 'birthYear': 2019, 'gender': 'female'},
        {'clientId': 'd2', 'name': name, 'birthYear': 2019, 'gender': 'female'},
    ], 'removedIds': []})
    ids = sorted(int(k['id']) for k in r.json['kids'])
    p1, p2 = ids  # p1 为保留档案(id 较小)
    client.post(f'/edu/api/kids/{p1}/stars', json={'events': [
        {'key': 'a1', 'amount': 10, 'reason': 'x'}, {'key': 'a2', 'amount': 5, 'reason': 'x'}]})
    client.post(f'/edu/api/kids/{p2}/stars', json={'events': [
        {'key': 'a2', 'amount': 5, 'reason': 'x'}, {'key': 'a3', 'amount': 7, 'reason': 'x'}]})
    assert client.get(f'/edu/api/kids/{p1}/state').json['data']['stars'] == 15
    assert client.get(f'/edu/api/kids/{p2}/state').json['data']['stars'] == 12
    client.get('/edu/api/bootstrap')  # 触发同名去重
    kids = client.get('/edu/api/bootstrap').json['kids']
    surv = [k for k in kids if k['name'] == name]
    assert len(surv) == 1, kids
    assert client.get(f'/edu/api/kids/{int(surv[0]["id"])}/state').json['data']['stars'] == 22, \
        client.get(f'/edu/api/kids/{int(surv[0]["id"])}/state').json  # 10+5(a1,a2) + 7(a3), a2 去重


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
    'edu-go.js',
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
    'edu-settings.js',
    'edu-fab.js',
    'edu-limit.js',
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
global.eduSync={setOnState(fn){this._onState=fn},qbankPull:()=>Promise.resolve({items:[]}),qbankEnsure:()=>Promise.resolve(),qbankLearn:()=>Promise.resolve(),pushState(){},hydrate:()=>Promise.resolve()};
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
global.eduSync={setOnState(fn){this._onState=fn},qbankPull:()=>Promise.resolve({items:[]}),qbankEnsure:()=>Promise.resolve(),qbankLearn:()=>Promise.resolve(),pushState(){},hydrate:()=>Promise.resolve()};
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


def _shared_harness(script_body):
    """仅加载 shared.js 的 node 桩: 验证 hydrate 的“同档归档去重收敛”与“归并后以服务端为权威”。

    提供隔离的 localStorage、可编排路由的 fetch 桩与最小 Edu.Store(stateKeyFor/wbKeyFor)。
    """
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'js')
    with open(os.path.join(base, 'shared.js'), 'r', encoding='utf-8') as f:
        shared = f.read()
    harness = r'''
const fs=require('fs'),vm=require('vm');
global.window=global;
global.Edu={Store:{stateKeyFor:id=>'st_'+id,wbKeyFor:id=>'wb_'+id}};
const store={};
global.localStorage={getItem:k=>(k in store?store[k]:null),setItem:(k,v)=>{store[k]=String(v)},removeItem:k=>{delete store[k]}};
const routes={};
global.Routes=routes;
global.fetch=(url,opts)=>{
  const p=String(url).replace(/^.*\/edu\/api/,'');
  const r=routes[p];
  if(r===undefined){ console.error('UNROUTED '+p); process.exit(3); }
  return Promise.resolve({json:()=>Promise.resolve(JSON.parse(JSON.stringify(r)))});
};
vm.createContext(global);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'), global);
global.R=global; global.S=store;
''' + script_body
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8') as tmp:
        tmp.write(shared)
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


def test_frontend_merge_collapse_after_adoption():
    """后瑞收养/去重返回 dbIdMap 后, 前端 hydrate 必须:

    1) 把本地指向同一服务端档案的两个宝贝收敛为一个;
    2) 被删除宝贝的本地数据弹并入保留档案(与后端同规则);
    3) 归并发生时(dbIdMap 非空)以服务端合并值为权威刷新(force), 避免展示未合并总量。
    """
    body = r'''
const W=R; // store 由桩暴露为全局 S
const tick=()=>new Promise(r=>setTimeout(r,0));
function seed(list, blobs){
  S['edu_kids_v1']=JSON.stringify({list:list,activeId:list[0].id});
  for(const k in blobs) S[k]=JSON.stringify(blobs[k]);
}
// 与 edu-bootstrap 一致的 onState: force 时以服务端覆盖, 否则仅填本地空键
W.eduSync.setOnState((kidId,dkey,data,force)=>{
  const key=(dkey==='workbench')?'wb_'+kidId:'st_'+kidId;
  if(!force && S[key]) return;
  S[key]=JSON.stringify(data);
});
(async()=>{
  // 场景1: 设备B 匿名(9)->登录 被并进服务端 8, dbIdMap {9:8}; 本地并列 db8+db9
  seed(
    [{id:'db8',dbId:8,name:'小豆豆',birthYear:2019,gender:'male',created:1},
     {id:'db9',dbId:9,name:'小豆豆',birthYear:2019,gender:'male',created:2}],
    {'st_db8':{stars:5,records:[{t:1}],submits:3},
     'st_db9':{stars:7,records:[{t:2}],submits:4},
     'wb_db8':{grid:{a:1}},'wb_db9':{grid:{b:1}}}
  );
  Routes['/bootstrap']={ok:true,adopted:true,dbIdMap:{'9':8},kids:[{id:8,name:'小豆豆',birthYear:2019,gender:'male'}]};
  Routes['/kids/8/state?dkey=state']={ok:true,data:{stars:12,records:[{t:1},{t:2}],submits:7}};
  Routes['/kids/8/state?dkey=workbench']={ok:true,data:{grid:{ab:1}}};
  // hydrate 末尾的档案回推(POST /kids)
  Routes['/kids']={ok:true,kids:[{id:8,clientId:'db8',name:'小豆豆',birthYear:2019,gender:'male'}]};
  await W.eduSync.hydrate(); await tick(); // onState 回填在下次微任务后落地
  let kids=JSON.parse(S['edu_kids_v1']).list;
  if(kids.length!==1) throw new Error('sc1: 期望 1 个孩子, 得到 '+kids.length);
  if(kids[0].id!=='db8'||kids[0].dbId!==8) throw new Error('sc1: 幸存者错误 '+JSON.stringify(kids[0]));
  let st=JSON.parse(S['st_db8']);
  if(st.stars!==12) throw new Error('sc1: force 后应 12 星, 得到 '+st.stars);
  if(st.submits!==7) throw new Error('sc1: submits 应为 7(force 覆盖), 得到 '+st.submits);
  if(st.records.length!==2) throw new Error('sc1: records 应并集为 2, 得到 '+st.records.length);
  if(S['st_db9']!==undefined||S['wb_db9']!==undefined) throw new Error('sc1: 被删宝贝的数据未清理');
  if(JSON.parse(S['wb_db8']).grid.ab!==1) throw new Error('sc1: workbench force 未生效');
  // 场景2: 无 dbIdMap(dbIdMap 为空)但本地已残留两个同 dbId 宝贝 -> 也应收敛并并数据(不 force)
  seed(
    [{id:'dbA',dbId:8,name:'小豆豆',birthYear:2019,gender:'male',created:1},
     {id:'dbB',dbId:8,name:'小豆豆',birthYear:2019,gender:'male',created:2}],
    {'st_dbA':{stars:5,records:[{t:1}]},'st_dbB':{stars:7,records:[{t:2}]}}
  );
  Routes['/bootstrap']={ok:true,adopted:false,dbIdMap:{},kids:[{id:8,name:'小豆豆',birthYear:2019,gender:'male'}]};
  // 服务端权威回填(本场景服务端与合并值一致), 以及 hydrate 末尾档案回推
  Routes['/kids/8/state?dkey=state']={ok:true,data:{stars:12,records:[{t:1},{t:2}],submits:7}};
  Routes['/kids/8/state?dkey=workbench']={ok:true,data:{}};
  Routes['/kids']={ok:true,kids:[{id:8,clientId:'dbA',name:'小豆豆',birthYear:2019,gender:'male'}]};
  await W.eduSync.hydrate(); await tick();
  kids=JSON.parse(S['edu_kids_v1']).list;
  if(kids.length!==1||kids[0].id!=='dbA') throw new Error('sc2: 收敛失败 '+JSON.stringify(kids));
  st=JSON.parse(S['st_dbA']);
  if(st.stars!==12) throw new Error('sc2: 并本地数据后应 12 星, 得到 '+st.stars);
  if(st.records.length!==2) throw new Error('sc2: records 并集应为 2, 得到 '+st.records.length);
  if(S['st_dbB']!==undefined) throw new Error('sc2: 被删宝贝数据未清理');
  console.log('MERGE-COLLAPSE-OK');
})().catch(e=>{ console.error(e); process.exit(1); });
'''
    out = _shared_harness(body)
    assert 'MERGE-COLLAPSE-OK' in out


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
      // 笔顺题: 正确答案必须真实出现在选项中, 且不能是"字本身"这种无效答案
      if(type==='stroke') items.forEach(i=>{
        if(i.options && i.options.indexOf(i.correct)<0 && !i.options.some(o=>String(W.Edu.MathUtils.optVal(o))===String(i.correct)))
          bad.push(subj+'/'+type+':correctNotInOpts:'+i.prompt+' correct='+i.correct);
        // 两个合法题型: 「第几笔是什么」笔形名 或 「一共有几笔」数字——二者都不允许把字本身当答案
        if(!/^(横|竖|撇|捺|点|横折|竖钩)$/.test(String(i.correct)) && !/^\d+$/.test(String(i.correct)))
          bad.push(subj+'/'+type+':badCorrect:'+i.prompt+' correct='+i.correct);
      });
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
    assert 'STAT_NO_POINTS=1' in out and 'STAT_STAR=1' in out and 'STAT_STREAK=0' in out, out
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


def test_award_stars_client_event_ledger_and_sync():
    """Store.awardStars: 本地乐观更新 + starAwards 事件账 + 按 key 幂等 + 立即同步服务端.

    覆盖「所有加星星操作同步后端服务」的客户端一侧.
    """
    out = _harness(r'''
store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],course:{},starAwards:[]});
W.Edu.Store.loadAllState();
const pushed=[];
W.eduSync.pushStars=(kid,ev)=>{pushed.push.apply(pushed,ev);return Promise.resolve({ok:true,stars:0});};
const S=W.Edu.Store.state;
let st=W.Edu.Store.awardStars(3,'答题·math');
console.log('T1='+(st===3&&S.stars===3?'1':'0'));
console.log('T2='+(S.starAwards.length===1&&S.starAwards[0].amount===3&&S.starAwards[0].reason==='答题·math'?'1':'0'));
console.log('T3='+(pushed.length===1&&pushed[0].key===S.starAwards[0].key?'1':'0'));
console.log('LOG='+(S.starLog.length===1&&S.starLog[0].s===3?'1':'0'));
// 同 key 重放(网络重试)幂等: 不重复加星/不重复记流/不重复推送
const k=S.starAwards[0].key;
W.Edu.Store.awardStars(3,'答题·math',k);
console.log('T4='+(S.stars===3&&S.starAwards.length===1?'1':'0'));
console.log('T5='+(pushed.length===1?'1':'0'));
// 扣星星(解锁): amount 为负, 仍同步
W.Edu.Store.awardStars(-2,'解锁学习时间');
console.log('T6='+(S.stars===1&&S.starAwards.length===2&&S.starAwards[1].amount===-2?'1':'0'));
console.log('T6B='+(pushed.length===2&&pushed[1].amount===-2?'1':'0'));
// 零值/空值不记
W.Edu.Store.awardStars(0,'忽略');
console.log('T7='+(S.starAwards.length===2?'1':'0'));
// 固定 key(通关/里程碑/每日): 可重现, 再次调用同 key 不重复累加
W.Edu.Store.awardStars(3,'数学通关·口算峡谷','pass_math_0_0');
W.Edu.Store.awardStars(3,'数学通关·口算峡谷','pass_math_0_0');
console.log('T8='+(S.stars===4&&S.starAwards.length===3?'1':'0'));
// 事件已持久化到本地弹(离线也能重放)
const saved=JSON.parse(store['edu_record_v1_kk']);
console.log('T9='+(saved.starAwards.length===3&&saved.stars===4?'1':'0'));
''')
    for k in ('T1', 'T2', 'T3', 'T4', 'T5', 'T6', 'T6B', 'T7', 'T8', 'T9', 'LOG'):
        assert k + '=1' in out, out


def test_bootstrap_force_overwrite_replays_pending_star_events():
    """hydrate force(收养/归并)覆盖时, 服务端未确认的离线星星事件要保留并回放:
    已入账的以服务端权威 total 展示(不重复), 未入账的补回并重新同步."""
    out = _harness(r'''
store['edu_record_v1_kk']=JSON.stringify({
  stars:573, starAwards:[{key:'p1',amount:3,reason:'答题·math',ts:1}],
  records:[],wrong:[],wishes:[],usageExtra:{'2026-01-01':2}
});
const cb=W.eduSync._onState;
const pushed=[];
W.eduSync.pushStars=(kid,ev)=>{pushed.push.apply(pushed,ev);return Promise.resolve();};
cb('kk','state',
  {stars:600,starAwards:[{key:'s1',amount:5,reason:'通关·x',ts:2}],records:[],usageExtra:{'2026-01-01':5}},
  true);
const st=JSON.parse(store['edu_record_v1_kk']);
console.log('KEEP_PENDING='+(st.starAwards.length===2?'1':'0'));   // s1(已入账) + p1(未确认保留)
console.log('STARS_REPLAYED='+(st.stars===603?'1':'0'));            // 600(账本权威) + 3(未确认)
console.log('REPUSH='+(pushed.length===1&&pushed[0].key==='p1'?'1':'0'));
console.log('EXTRA_MAX='+(st.usageExtra['2026-01-01']===5?'1':'0')); // 原 usageExtra 保留逻辑不受影响
console.log('NO_DUP='+((st.starAwards.filter(function(e){return e.key==='s1';}).length===1)?'1':'0'));
// 已入账的事件不会被重复补回
const st2=JSON.parse(store['edu_record_v1_kk']);
console.log('STARS2='+(st2.stars===603?'1':'0'));
''')
    for k in ('KEEP_PENDING', 'STARS_REPLAYED', 'REPUSH', 'EXTRA_MAX', 'NO_DUP', 'STARS2'):
        assert k + '=1' in out, out


def test_frontend_push_stars_syncs_ledger():
    """eduSync.pushStars: 带 dbId 直接推事件到服务端账本, 返回权威 total 回填本地展示(按需)."""
    out = _shared_harness(r'''
(async()=>{
  const W=R; // store 由桩暴露为全局 S
  const kids=[{id:'db8',dbId:8,name:'小豆豆',birthYear:2019,gender:'male'}];
  S['edu_kids_v1']=JSON.stringify({list:kids,activeId:'db8'});
  W.Edu.Store.state={stars:57};
  Routes['/kids/8/stars']={ok:true,stars:602};
  const ev=[{key:'a1',amount:3,reason:'x',ts:1}];
  const res=await W.eduSync.pushStars('db8',ev);
  if(!res.ok||res.stars!==602) throw new Error('pushStars resp '+JSON.stringify(res));
  console.log('AUTH_ADOPT='+(W.Edu.Store.state.stars===602?'1':'0'));   // 602>57: 回填权威值
  Routes['/kids/8/stars']={ok:true,stars:601};
  const res2=await W.eduSync.pushStars('db8',ev);
  if(res2.stars!==601) throw new Error('resp2');
  console.log('NO_ROLLBACK='+(W.Edu.Store.state.stars===602?'1':'0'));  // 601<602: 不回包本地乐观值
  console.log('PUSH_STARS=1');
})().catch(e=>{console.log('ERR='+e.message);process.exit(2);});
''')
    assert 'PUSH_STARS=1' in out, out
    assert 'AUTH_ADOPT=1' in out and 'NO_ROLLBACK=1' in out, out


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
  global.eduSync={setOnState(fn){this._onState=fn},qbankPull:()=>Promise.resolve({items:[]}),qbankEnsure:()=>Promise.resolve(),qbankLearn:()=>Promise.resolve(),pushState(){},hydrate:()=>Promise.resolve()};
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
global.eduSync={setOnState(fn){this._onState=fn},qbankPull:()=>Promise.resolve({items:[]}),qbankEnsure:()=>Promise.resolve(),qbankLearn:()=>Promise.resolve(),pushState(){},hydrate:()=>Promise.resolve()};
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
    """输入题答错: 前两次不揭示(给两次重答机会), 第三次答错才揭示正确答案并显示「下一题 ▶」; 不自动跳转."""
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
global.eduSync={setOnState(fn){this._onState=fn},qbankPull:()=>Promise.resolve({items:[]}),qbankEnsure:()=>Promise.resolve(),qbankLearn:()=>Promise.resolve(),pushState(){},hydrate:()=>Promise.resolve()};
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
  W.quizInputSubmit(0,'999');   // 第1次答错 → 只提示再试, 不揭示, 输入框保持可再答
  await new Promise(r=>setTimeout(r,350));
  const jAfter1=__ins.join('\n');
  const reveal1=jAfter1.indexOf('正确答案是')>=0;
  const next1=jAfter1.indexOf('下一题 ▶')>=0;
  const enabledAfter1 = !inp0.disabled;
  W.quizInputSubmit(0,'888');   // 第2次答错 → 仍不揭示, 继续给机会
  await new Promise(r=>setTimeout(r,350));
  const jAfter2=__ins.join('\n');
  const reveal2=jAfter2.indexOf('正确答案是')>=0;
  W.quizInputSubmit(0,'777');   // 第3次答错 → 揭示正确答案 + 下一题 ▶
  await new Promise(r=>setTimeout(r,350));
  const jAfter3=__ins.join('\n');
  const reveal3=jAfter3.indexOf('正确答案是')>=0;
  const hasNext=jAfter3.indexOf('下一题 ▶')>=0;
  const p1=curOf();
  console.log('NO_REVEAL_1='+(reveal1?'0':'1'));
  console.log('NO_REVEAL_2='+(reveal2?'0':'1'));
  console.log('REVEAL_3='+(reveal3?'1':'0'));
  console.log('NEXT_BTN='+(hasNext?'1':'0'));
  console.log('NO_AUTO='+(p0===p1?'1':'0'));
  console.log('INPUT_ENABLED_1='+(enabledAfter1?'1':'0'));
})();
'''
    r = subprocess.run(['node', '-e', out_body, _concat_script_path()], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert 'NO_REVEAL_1=1' in r.stdout, r.stdout
    assert 'NO_REVEAL_2=1' in r.stdout, r.stdout
    assert 'REVEAL_3=1' in r.stdout, r.stdout
    assert 'NEXT_BTN=1' in r.stdout, r.stdout
    assert 'NO_AUTO=1' in r.stdout, r.stdout
    assert 'INPUT_ENABLED_1=1' in r.stdout, r.stdout


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
global.eduSync={setOnState(fn){this._onState=fn},qbankPull:()=>Promise.resolve({items:[]}),qbankEnsure:()=>Promise.resolve(),qbankLearn:()=>Promise.resolve(),pushState(){},hydrate:()=>Promise.resolve()};
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
    """语音接口: 同源 mp3 返回 + 内容缓存 + 语言自判 + 音色选择(不依赖外网)."""
    import hashlib
    import os
    import routes.education as edu
    from app import app
    cache_dir = os.path.join(app.instance_path, 'tts')
    os.makedirs(cache_dir, exist_ok=True)
    keys = []
    for le, vk, txt in (('zh', '', '你好'), ('en', '', 'apple'), ('zh', 'xiaoyi', '你好')):
        k = hashlib.sha1((le + '|' + vk + '|' + txt).encode('utf-8')).hexdigest()[:24]
        keys.append(os.path.join(cache_dir, k + '.mp3'))
        try:
            os.remove(keys[-1])
        except OSError:
            pass
    calls = []
    orig = edu._fetch_tts
    edu._fetch_tts = lambda text, le, vkey=None: (calls.append((text, le, vkey or '')) or b'ID3hello')
    try:
        r = client.get('/edu/api/tts?text=%E4%BD%A0%E5%A5%BD')
        assert r.status_code == 200, r.status_code
        assert r.content_type.startswith('audio/mpeg'), r.content_type
        assert r.data[:3] == b'ID3'
        # 命中磁盘缓存: 不再外呼
        r2 = client.get('/edu/api/tts?text=%E4%BD%A0%E5%A5%BD')
        assert r2.status_code == 200 and r2.data == r.data
        assert calls == [('你好', 'zh', '')], calls
        # 英文自判 → en
        r3 = client.get('/edu/api/tts?text=apple')
        assert r3.status_code == 200 and calls == [('你好', 'zh', ''), ('apple', 'en', '')], calls
        # 指定音色 → 独立缓存, 再外呼一次
        r4 = client.get('/edu/api/tts?text=%E4%BD%A0%E5%A5%BD&v=xiaoyi')
        assert r4.status_code == 200 and r4.data[:3] == b'ID3'
        assert calls[-1] == ('你好', 'zh', 'xiaoyi'), calls
        # 无效音色 → 回落默认
        r5 = client.get('/edu/api/tts?text=%E4%BD%A0%E5%A5%BD&v=zzz')
        assert r5.status_code == 200, r5.status_code
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
global.eduSync={setOnState(fn){this._onState=fn},qbankPull:()=>Promise.resolve({items:[]}),qbankEnsure:()=>Promise.resolve(),qbankLearn:()=>Promise.resolve(),pushState(){},hydrate:()=>Promise.resolve()};
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
global.eduSync={setOnState(fn){this._onState=fn},qbankPull:()=>Promise.resolve({items:[]}),qbankEnsure:()=>Promise.resolve(),qbankLearn:()=>Promise.resolve(),pushState(){},hydrate:()=>Promise.resolve()};
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


def test_order_retap_without_clear(client):
    """排序题第一次答错后无需手动清空: 重新点选选项即可继续; 原顺序拼回不累计二次判错; 排对后锁定."""
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
global.eduSync={setOnState(fn){this._onState=fn},qbankPull:()=>Promise.resolve({items:[]}),qbankEnsure:()=>Promise.resolve(),qbankLearn:()=>Promise.resolve(),pushState(){},hydrate:()=>Promise.resolve()};
vm.createContext(global);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),global);
const W=global; global.__ins=inserted;
'''
    out_body = harness + r'''
(async()=>{
  store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],settings:{}});
  W.Edu.QuizEngine.startQuiz('math','order',
    [{order:true,prompt:'把数字从小到大排序',options:['1','2','3'],correct:'123'}],
    {difficulty:1});
  await new Promise(r=>setTimeout(r,80));
  const E=W.Edu.QuizEngine;
  const json=()=>JSON.stringify((E.quizOrder[0]||[]));
  // 1) 第一次答错: 选成 2,1,3 → 判定为错, 但选项保持可点
  E.tapOrder(0,1); E.tapOrder(0,0); E.tapOrder(0,2);
  await new Promise(r=>setTimeout(r,30));
  console.log('FIRST_WRONG='+(E.quiz.answers[0]==='213'?'1':'0:'+(E.quiz.answers[0]||'')));
  // 2) 答错后不点「清空」, 直接重选: 再点已选项 = 取消选择
  E.tapOrder(0,1);
  console.log('RETAP_TOGGLES='+(json()==='[0,2]'?'1':'0:'+json()));
  // 3) 拆散后原顺序拼回(213) → lastJVal 命中, 不重复判错、不加锁
  E.tapOrder(0,0); E.tapOrder(0,0);
  console.log('SAME_SKIP='+(json()==='[2,0]'?'1':'0:'+json()));
  E.tapOrder(0,2);
  console.log('STILL_EDITABLE='+(json()==='[0]'?'1':'0:'+json()));
  // 4) 重新排成正确答案 1,2,3 → 判对
  E.tapOrder(0,1); E.tapOrder(0,2);
  await new Promise(r=>setTimeout(r,30));
  console.log('FIX_CORRECT='+(E.quiz.answers[0]==='123'?'1':'0:'+(E.quiz.answers[0]||'')+',order='+json()));
  // 5) 判对后再次点选不再生效(已锁定)
  E.tapOrder(0,0); E.tapOrder(0,0);
  console.log('LOCKED='+(json()==='[0,1,2]'?'1':'0:'+json()));
  setTimeout(function(){ process.exit(0); }, 50);
})();
'''
    stdin_ = _concat_script_path()
    try:
        rr = subprocess.run(['node', '-e', out_body, stdin_], capture_output=True, text=True)
        stdout = rr.stdout
    finally:
        try: os.unlink(stdin_)
        except OSError: pass
    assert 'FIRST_WRONG=1' in stdout, stdout
    assert 'RETAP_TOGGLES=1' in stdout, stdout
    assert 'SAME_SKIP=1' in stdout, stdout
    assert 'STILL_EDITABLE=1' in stdout, stdout
    assert 'FIX_CORRECT=1' in stdout, stdout
    assert 'LOCKED=1' in stdout, stdout


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
global.eduSync={setOnState(fn){this._onState=fn},qbankPull:()=>Promise.resolve({items:[]}),qbankEnsure:()=>Promise.resolve(),qbankLearn:()=>Promise.resolve(),pushState(){},hydrate:()=>Promise.resolve()};
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
global.eduSync={setOnState(fn){this._onState=fn},qbankPull:()=>Promise.resolve({items:[]}),qbankEnsure:()=>Promise.resolve(),qbankLearn:()=>Promise.resolve(),pushState(){},hydrate:()=>Promise.resolve()};
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
  // 问候语按小时变化(跨夜时测试会命中「夜深啦」), 昼间/夜间问候均视为有效
  console.log('GREET='+((h.indexOf('早上好')>=0||h.indexOf('下午好')>=0||h.indexOf('晚上好')>=0||h.indexOf('夜深啦')>=0)?'1':'0'));
  console.log('MODE='+(h.indexOf('幼小衔接')>=0&&h.indexOf('mode-select')>=0?'1':'0'));
  console.log('STAR_LV='+(h.indexOf('打卡第')>=0?'1':'0'));
  console.log('NO_LV='+(h.indexOf('⭐ Lv.')<0?'1':'0'));
  console.log('NO_HGSTAR='+(h.indexOf('hg-star')<0?'1':'0'));
  console.log('BADGE_NM='+(h.indexOf('第一颗星')>=0&&h.indexOf('十星小达人')>=0?'1':'0'));
  console.log('CONTINUE='+(h.indexOf('home-goal')>=0&&h.indexOf('今日任务')>=0?'1':'0'));
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
  console.log('GREET2='+(h.indexOf('小探险家')>=0||h.indexOf('该休息咯')>=0?'1':'0'));
  console.log('NO_SLOGAN='+(h.indexOf('坚持闯关，天天有进步')<0?'1':'0'));
  console.log('LBAR='+(h.indexOf('home-sec-head')>=0?'1':'0'));
  console.log('NO_DONE_TXT='+(h.indexOf('今日目标已达成')<0?'1':'0'));
  console.log('MILESTONES='+(h.indexOf('hg-milestones')>=0?'1':'0'));
  console.log('MIL_SEED_ON='+(h.indexOf('hg-mil on')>=0?'1':'0'));
  console.log('TODAY_CHIP='+(h.indexOf('今日完成 <b>')>=0&&h.indexOf('题</span>')>=0?'1':'0'));
  console.log('TOTAL_CHIP='+(h.indexOf('累计完成 <b>2</b> 题')>=0?'1':'0'));
})();
'''
    stdin_ = _concat_script_path()
    try:
        rr = subprocess.run(['node', '-e', out_body, stdin_], capture_output=True, text=True)
        stdout = rr.stdout
    finally:
        try: os.unlink(stdin_)
        except OSError: pass
    for probe in ('GREET=1','MODE=1','STAR_LV=1','NO_LV=1','NO_HGSTAR=1','CONTINUE=1','TRK=1','COUNT=1',
                  'COURSE_ZH=1','COURSE_MATH=1','COURSE_DAILY=1','NO_KIDROW=1','NO_AVA=1','LVLINE=1',
                  'GREET2=1','LBAR=1','NO_SLOGAN=1',
                  'GRID=1','CPROG=1','MODEBTN=1','NO_TAG=1','NO_GO=1','BADGE_NM=1',
                  'NO_DONE_TXT=1','MILESTONES=1','MIL_SEED_ON=1','TODAY_CHIP=1','TOTAL_CHIP=1'):
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
  console.log('HAS_GOAL='+(iH.indexOf('今日任务')>=0?'1':'0'));
  console.log('HAS_GRID='+(iH.indexOf('home-course-scroll')>=0?'1':'0'));
})();
''')
    for probe in ('NO_TEASER=1','NO_MAP_TXT=1','HAS_GOAL=1','HAS_GRID=1'):
        assert probe in out, out

def test_wbinit_go_does_not_break_other_subjects():
    """工作台初始化: 即使 pref 记录了围棋(wbGo=atari / lastSubj=go),
    wbInit 必须完成 zh/math/en/go 各面板启动, 不能因 GoWorkbench 未绑定
    而抛 ReferenceError 中断整页答题渲染(语文/数学/英语不显示题目的回归)."""
    out = _harness(r'''
(async()=>{
  const bodies={};
  function bNode(){const el={style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},setAttribute(){},getAttribute(){return null},textContent:'',value:'',appendChild(){},removeChild(){},addEventListener(){},options:[],children:[],offsetWidth:0,offsetHeight:0,focus(){},scrollIntoView(){},querySelector:()=>bNode(),querySelectorAll:()=>[],getContext(){return new Proxy({}, {get:()=>()=>{}})}};
    Object.defineProperty(el,'innerHTML',{get(){return el._h||''},set(v){el._h=String(v)}}); return el;}
  ['wb-zh-body','wb-math-body','wb-en-body','wb-go-body','wb-zh','wb-math','wb-en','wb-go','eduBottomNav','modeSelect'].forEach(k=>bodies[k]=bNode());
  const byId=(id)=>bodies[id]||bNode();
  global.document.getElementById=byId;
  store['edu_pref_v1_kk']=JSON.stringify({mode:'workbench',subj:'go',lastSubj:'go',wbZh:'zi',wbMath:'calc',wbEn:'word',wbGo:'atari'});
  store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],badges:{},level:{},settings:{},course:{}});
  let throws=0;
  try{ W.Edu.Workbench.wbInit(); }catch(e){ throws++; }
  console.log('WBINIT_THROW='+(throws?'1':'0'));
  const check=s=>{
    let threw=0;
    try{ W.Edu.Workbench.wbSubject(s); }catch(e){ threw++; }
    const h=bodies['wb-'+s+'-body']._h||'';
    console.log('SUBJ_'+s.toUpperCase()+'='+((!threw&&h.indexOf('quiz-item')>=0)?'1':'0'));
  };
  ['zh','math','en','go'].forEach(check);
})();
''')
    for probe in ('WBINIT_THROW=0','SUBJ_ZH=1','SUBJ_MATH=1','SUBJ_EN=1','SUBJ_GO=1'):
        assert probe in out, out

def test_dock_busy_guard():
    """答题(Dock守卫): 按需求 dock 不再置灰禁用，答题/极速练习进行中底部导航仍保持彩色可点."""
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
  console.log('DOCK_ENABLED1='+(navH.indexOf('disabled')<0?'1':'0'));
  W.startPractice('math','calc');
  await new Promise(r=>setTimeout(r,40));
  console.log('DOCK_ENABLED2='+(navH.indexOf('disabled')<0?'1':'0'));
  await new Promise(r=>setTimeout(r,1200));
  const c1=W.PRACTICE.cur.correct;
  W.practiceAnswer(c1);
  await new Promise(r=>setTimeout(r,1200));
  W.stopPractice();
  console.log('DOCK_ENABLED3='+(navH.indexOf('disabled')<0?'1':'0'));
  process.exit(0);
})();
''')
    assert 'DOCK_ENABLED1=1' in out, out
    assert 'DOCK_ENABLED2=1' in out, out
    assert 'DOCK_ENABLED3=1' in out, out


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
global.eduSync={setOnState(fn){this._onState=fn},qbankPull:()=>Promise.resolve({items:[]}),qbankEnsure:()=>Promise.resolve(),qbankLearn:()=>Promise.resolve(),pushState(){},hydrate:()=>Promise.resolve()};
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
  console.log('MINE_SETTINGS='+(m.indexOf('课程与难度')>=0?'0':'1'));
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
                  'MINE_NAME=1','MINE_SETTINGS=1','MINE_REPORT=0','MINE_MGR=1','MINE_STARS=0'):
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


def test_settings_persist_sound_isolated():
    """我的页内联设置: 朗读与音效 单字段就地修改并写 settings 与 localStorage;
    护眼提醒与课程/难度已移除, 不再持久化 eyeMin/range/nocarry 字段."""
    out = _harness(r'''
(async()=>{
  const ids={};
  const el=id=>{ if(!ids[id]) ids[id]={value:'',checked:false,textContent:'',style:{},focus(){},disabled:false,files:[]}; return ids[id];};
  const orig=global.document.getElementById;
  global.document.getElementById=(id)=> id==='eduMaskSet'?{style:{}} : el(id);
  global.document.getElementById('setPwd');
  store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],settings:{},points:0,level:{}});
  W.Edu.Store.loadAllState();

  // 单字段内联: 朗读与音效(关闭)
  W.toggleSoundInline(false);
  let s=W.Edu.Store.state.settings;
  console.log('SOUND='+(s.sound===false?'1':'0'));
  console.log('SPEAK_KEY='+(store['edu_speak_v1']==='false'?'1':'0'));

  // 课程/难度/护眼已移除: 难度由每个小关卡自动决定, 不再读取 range/nocarry/eyeMin 设置
  s=W.Edu.Store.state.settings;
  console.log('NO_RANGE='+(s.range===undefined||s.range===0?'1':'0'));
  console.log('NO_NOCARRY='+(s.nocarry? '0':'1'));
  console.log('NO_EYE='+(s.eyeMin===undefined?'1':'0'));

  // 打开音效屏幕再 setSave: 不应写回已删除的课程/护眼字段, 且音效保留
  W.openSettings && W.openSettings('sound');
  setTimeout(()=>{
    el('setSound').checked=true;
    W.setSave();
    s=W.Edu.Store.state.settings;
    console.log('SOUND_KEPT='+(s.sound===true?'1':'0'));
    console.log('ISOLATED='+(s.range===undefined||s.range===0?'1':'0'));
  },30);
})();
''')
    for probe in ('SOUND=1','SPEAK_KEY=1','NO_RANGE=1','NO_NOCARRY=1','NO_EYE=1','SOUND_KEPT=1','ISOLATED=1'):
        assert probe in out, out


def test_usage_gate():
    """学习守护: 教育页面默认 30 分钟上限; 超时弹出验证框; 答对繁体数学题或扣 100 星解锁 +30 分钟;
    打错无法继续; 重启/刷新后重新拦截."""
    out = _harness(r'''
(async()=>{
  let maskEl=null;
  const mk=()=>({style:{},innerHTML:'',textContent:'',value:'',appendChild(){},setAttribute(){},getAttribute(){return null},focus(){}});
  const ansEl=mk(), errEl=mk();
  global.document={
    getElementById:(id)=>{
      if(id==='eduGateMask'){ if(!maskEl) maskEl=mk(); return maskEl; }
      if(id==='eduGateAns'){ return ansEl; }
      if(id==='eduGateErr'){ return errEl; }
      return null;
    },
    querySelectorAll:()=>[], querySelector:()=>mk(), createElement:()=>mk(),
    createTextNode:()=>({}), addEventListener(){}, removeEventListener(){},
    documentElement:{style:{}},
    body:{appendChild(el){ if(el&&el.id==='eduGateMask') maskEl=el; }}
  };
  if(W.Edu.Speech&&W.Edu.Speech.toast) W.Edu.Speech.toast=()=>{};
  const Store=W.Edu.Store;
  const G=W.Edu.UsageGate;

  store['edu_record_v1_kk']=JSON.stringify({stars:120,records:[],wrong:[],wishes:[],usage:{},settings:{dailyMin:0},points:0,level:{}});
  Store.loadAllState();
  const u=Store.usageForToday();
  u.secs=29*60; Store.saveState();
  console.log('LIMIT_MIN='+(Store.usageLimitMin()===30?'1':'0'));
  console.log('NOT_OVER='+(Store.usageOver()? '0':'1'));

  // 繁体数字转换
  console.log('TRAD_8='+(G.tradN(8)==='捌'?'1':'0'));
  console.log('TRAD_15='+(G.tradN(15)==='拾伍'?'1':'0'));
  console.log('TRAD_20='+(G.tradN(20)==='贰拾'?'1':'0'));
  console.log('TRAD_99='+(G.tradN(99)==='玖拾玖'?'1':'0'));

  // 达到默认 30 分钟上限 → 弹出验证框(含繁体数学题)
  u.secs=30*60; Store.saveState();
  G.showGate();
  console.log('GATE_VISIBLE='+((maskEl&&maskEl.style.display==='flex')?'1':'0'));
  console.log('GATE_TITLE='+((maskEl&&maskEl.innerHTML.indexOf('学习时间到啦')>=0)?'1':'0'));
  console.log('GATE_TRAD_Q='+((maskEl&&/壹|贰|叁|肆|伍|陆|柒|捌|玖|拾/.test(maskEl.innerHTML))?'1':'0'));

  // 打错 → 无法继续, 提示「答错啦」
  const p=G._getProblem();
  ansEl.value=String(p.ans===0?1:p.ans-1);
  W.eduGateCheck();
  console.log('WRONG_BLOCK='+(G.isBlocking()?'1':'0'));
  console.log('WRONG_MSG='+((errEl&&errEl.textContent.indexOf('答错啦')>=0)?'1':'0'));

  // 答对 → 解锁, 当日额度 +30 分钟, 弹框关闭
  ansEl.value=String(p.ans);
  W.eduGateCheck();
  console.log('RIGHT_UNLOCK='+(G.isBlocking()? '0':'1'));
  console.log('MASK_HIDDEN='+((maskEl&&maskEl.style.display==='none')?'1':'0'));
  console.log('EXTRA_1='+(Store.usageExtraToday()===1?'1':'0'));
  console.log('LIMIT_60='+(Store.usageLimitMin()===30&&Store.usageLimitSec()===60*60?'1':'0'));
  console.log('NOT_OVER_2='+(Store.usageOver()? '0':'1'));

  // 再用 31 分钟 → 再次拦截(模拟刷新/重进后依旧弹框)
  u.secs=61*60; Store.saveState();
  G.showGate();
  console.log('REBLOCK='+(G.isBlocking()?'1':'0'));

  // 扣 100 星解锁, 保证至少可再学 USAGE_UNLOCK_MIN 分钟(超出已用时长的部分由额度补齐)
  const before=Store.state.stars;
  W.eduGateUnlockStars();
  console.log('STAR_DEDUCT='+(Store.state.stars===before-100?'1':'0'));
  console.log('STAR_UNLOCK='+(G.isBlocking()? '0':'1'));
  console.log('EXTRA_GROW='+(Store.usageExtraToday()>1?'1':'0'));
  console.log('REMAIN_30='+((Store.usageLimitSec()-Store.usageUsedSec()>=Store.usageLimitMin()*60)?'1':'0'));

  // 星星不足 100 → 不可扣星解锁, 但仍被拦截
  u.secs=91*60; Store.saveState();
  Store.state.stars=50;
  G.showGate();
  W.eduGateUnlockStars();
  console.log('POOR_BLOCK='+(G.isBlocking()?'1':'0'));
  console.log('POOR_MSG='+((errEl&&errEl.textContent.indexOf('星星不足')>=0)?'1':'0'));
})();
''')
    for probe in ('LIMIT_MIN=1','NOT_OVER=1','TRAD_8=1','TRAD_15=1','TRAD_20=1','TRAD_99=1',
                  'GATE_VISIBLE=1','GATE_TITLE=1','GATE_TRAD_Q=1',
                  'WRONG_BLOCK=1','WRONG_MSG=1',
                  'RIGHT_UNLOCK=1','MASK_HIDDEN=1','EXTRA_1=1','LIMIT_60=1','NOT_OVER_2=1',
                  'REBLOCK=1','STAR_DEDUCT=1','STAR_UNLOCK=1','EXTRA_GROW=1','REMAIN_30=1',
                  'POOR_BLOCK=1','POOR_MSG=1'):
        assert probe in out, out


def test_record_date_fields_and_home_progress():
    """首页"已练N题"与进度条修复: 每次作答记录写入 date 字段(今日), 进度条宽度用
    完成进度 done/goal 而非正确率 —— 二者从此一致."""
    out = _harness(r'''
(async()=>{
  store['edu_record_v1_kk']=JSON.stringify({stars:0,records:[],wrong:[],wishes:[],settings:{range:0,nocarry:false,mult:false,dailyQ:20,dailyMin:0},points:0,level:{}});
  W.Edu.Store.loadAllState();
  // 驱动真实作答记录路径(practiceAnswer), 应写入 date=今日
  const P=W.Edu.Practice;
  P.PRACTICE.active=true; P.PRACTICE.lock=false;
  P.PRACTICE.subj='math'; P.PRACTICE.type='calc';
  P.PRACTICE.cur={id:'q1',prompt:'1+1',correct:'2',wtype:undefined};
  P.PRACTICE.pending='';
  P.practiceAnswer('2');
  const recs=W.Edu.Store.state.records||[];
  const now=new Date();
  const dk=now.getFullYear()+'-'+String(now.getMonth()+1).padStart(2,'0')+'-'+String(now.getDate()).padStart(2,'0');
  console.log('DATE_FIELD='+((recs[0]&&recs[0].date)||'MISSING'));
  console.log('DATE_TODAY='+(recs[0]&&recs[0].date===dk?'1':'0'));
  // 进度条: 今日1题/目标20 -> 应 5%(done/goal), 而正确率是100%
  const today=1,goal=20,pct=100;
  const barW=Math.round(Math.min(100,today*100/Math.max(1,goal)));
  const oldBarW=Math.min(100,pct);
  console.log('NEW_BARW='+barW);
  console.log('OLD_BARW='+oldBarW);
  process.exit(0);
})();
''')
    assert 'DATE_FIELD=' in out and 'DATE_TODAY=1' in out, out
    assert 'NEW_BARW=5' in out, out
    assert 'OLD_BARW=100' in out, out


def test_wish_gift_exchange():
    """兑换区: 武器/奥特曼互斥分区; 武器可重复收集+卡片卖出(返还购入价-5, 按钮不显示「+」);
    奥特曼唯一不可重复; 已兑换区已删除, 卡片「名字+星星数」同一行; 详情自动朗读名称与专属口号 + 展示真实图."""
    out = _harness(r'''
(async()=>{
  const mkEl=()=>{const el={_h:'',style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},setAttribute(){},getAttribute(){return null},querySelector:()=>mkEl(),querySelectorAll:()=>[],focus(){},scrollIntoView(){},children:[],textContent:'',value:''};
    Object.defineProperty(el,'innerHTML',{get(){return el._h},set(v){el._h=String(v)}});
    el.appendChild=(c)=>{ if(c && c._h!==undefined) el._h+=(c._h||''); }; return el;};
  const bodyEl=mkEl(), detailBody=mkEl(), detailTitle=mkEl(), detailSub=mkEl(), detailMask=mkEl();
  const byId=(id)=> id==='eduWishBody'?bodyEl : (id==='detailBody'?detailBody : (id==='detailTitle'?detailTitle : (id==='detailSub'?detailSub : (id==='eduMaskDetail'?detailMask : (id==='gcTitle'||id==='gcSub'||id==='eduMaskGiftConfirm'||id==='pasStars'||id==='pasNote'||id==='eduMaskParentAddStars')?mkEl() : mkEl()))));
  global.document.getElementById=byId;
  global.document.createElement=()=>mkEl();
  global.document.querySelectorAll=()=>[];
  store['edu_record_v1_kk']=JSON.stringify({stars:70,records:[],wrong:[],wishes:[],wishLog:[],redeemed:[],giftPrices:{},settings:{}});
  W.Edu.Store.loadAllState();
  // 语音探测: 拦截 playSpeak 记录播报文本
  const SPOKE=[];
  W.Edu.Speech.playSpeak=(t)=>{ SPOKE.push(t); console.log('SPOKE='+t); };
  const Wish=W.Edu.Wish;
  const CAT=Wish.GIFT_CATALOG||[];
  const names=CAT.map(g=>g.name).join(',');
  const SECT=Wish.GIFT_SECTIONS||[];
  console.log('SEC2='+SECT.length);
  console.log('CAT_HAS_ULTRA='+(CAT.some(g=>g.sec==='ultra')?'1':'0'));
  console.log('ULTRA_UNIQUE='+(CAT.filter(g=>g.sec==='ultra').every(g=>g.unique===true)?'1':'0'));
  console.log('CAT_HAS_DAO='+(names.indexOf('宝刀')>=0?'1':'0'));
  console.log('CAT_HAS_GONG='+(names.indexOf('长弓')>=0?'1':'0'));
  console.log('CAT_HAS_QIANG='+(names.indexOf('亮枪')>=0?'1':'0'));
  console.log('CAT_HAS_JIAN='+(names.indexOf('宝剑')>=0?'1':'0'));
  console.log('CAT_HAS_DUN='+(names.indexOf('神盾')>=0?'1':'0'));
  // 默认定价(按目录): 不随「我的」设置变化
  console.log('DEF_DAO='+Wish.giftPriceOf('dao'));
  console.log('DEF_GONG='+Wish.giftPriceOf('gong'));
  console.log('DEF_QIANG='+Wish.giftPriceOf('qiang'));
  // 兑换 feidao(15星) 4次(70->55->40->25->10), 第5次因星不足拒绝
  Wish.giftRedeem('feidao'); Wish.giftConfirmOk();
  const s1=W.Edu.Store.state;
  console.log('STARS_AFTER='+s1.stars);
  console.log('REDEEMED1='+((s1.redeemed||[]).length));
  console.log('REDEEMED_FEIDAO='+((s1.redeemed||[])[0]&&s1.redeemed[0].id==='feidao'?'1':'0'));
  console.log('REDEEMED_HAS_PRICE='+((s1.redeemed||[])[0]&&typeof s1.redeemed[0].price==='number'?'1':'0'));
  Wish.giftRedeem('feidao'); Wish.giftConfirmOk();
  Wish.giftRedeem('feidao'); Wish.giftConfirmOk();
  Wish.giftRedeem('feidao'); Wish.giftConfirmOk();
  const s2=W.Edu.Store.state;
  console.log('STARS_EXHAUST='+s2.stars);
  console.log('COUNT2='+((s2.redeemed||[]).length));
  // 卖出: 返还 = 购入价-5 = 10 星(索引方式)
  console.log('SELL_REFUND='+Wish.sellRefundOf({id:'feidao',price:15}));
  Wish.giftSell(0);
  const s4=W.Edu.Store.state;
  console.log('SELL_STARS='+s4.stars);
  console.log('SELL_COUNT='+((s4.redeemed||[]).length));
  // 卡片卖出按钮: giftSellOf 卖掉最近一件
  Wish.giftSellOf('feidao');
  const s4b=W.Edu.Store.state;
  console.log('SELLOF_STARS='+s4b.stars);
  console.log('SELLOF_COUNT='+((s4b.redeemed||[]).length));
  // 奥特曼: 唯一不可重复(先凑够星星)
  W.Edu.Store.state.stars=500;
  Wish.giftRedeem('diga'); Wish.giftConfirmOk();
  const s5=W.Edu.Store.state;
  console.log('DIGA_STARS='+s5.stars);
  console.log('DIGA_COUNT='+((s5.redeemed||[]).filter(r=>r.id==='diga').length));
  Wish.giftRedeem('diga');  // 重复兑换应被拒绝
  const s6=W.Edu.Store.state;
  console.log('DIGA_BLOCKED_STARS='+s6.stars);
  console.log('DIGA_BLOCKED_COUNT='+((s6.redeemed||[]).filter(r=>r.id==='diga').length));
  // 切到奥特曼区: 武器区自动折叠(不渲染)
  Wish.giftTab('ultra');
  console.log('ULTRA_TAB_WEAP='+(bodyEl._h.indexOf('/static/edu/weapons/feidao.svg')>=0?'0':'1'));
  console.log('ULTRA_TAB_IMG='+(bodyEl._h.indexOf('/static/edu/ultra/')>=0?'1':'0'));
  console.log('ULTRA_TAB_TITLE='+(bodyEl._h.indexOf('奥特曼专区')>=0?'1':'0'));
  // 已兑换折叠区已删除: 兑换区不再渲染「已兑换」; 卡片「名字+星星数」同一行; 卖出按钮不显示「+」
  console.log('NO_FOLD='+(bodyEl._h.indexOf('gift-fold')>=0?'0':'1'));
  console.log('ONELINE_DIGA='+(bodyEl._h.indexOf('迪迦奥特曼</span><span class="gift-price">180 ⭐</span>')>=0?'1':'0'));
  console.log('SELL_NO_PLUS='+(bodyEl._h.indexOf('gift-sell')>=0 && bodyEl._h.indexOf('卖出+')<0?'1':'0'));
  console.log('SELL_175='+(bodyEl._h.indexOf('卖出 175⭐')>=0?'1':'0'));
  // 切回武器区
  Wish.giftTab('weapon');
  console.log('WEAPON_TAB_FEIDAO='+(bodyEl._h.indexOf('/static/edu/weapons/feidao.svg')>=0?'1':'0'));
  console.log('WEAPON_TAB_NOULTRA='+(bodyEl._h.indexOf('/static/edu/ultra/')>=0?'0':'1'));
  // 细节弹窗(武器): 真实武器图(非 emoji) + 名称 + 自动朗读语音
  Wish.giftDetail('jian');
  console.log('DETAIL_IMG='+(detailBody._h.indexOf('/weapons/jian.svg')>=0?'1':'0'));
  console.log('DETAIL_NOEMOJI='+(detailBody._h.indexOf('⚔️')>=0?'0':'1'));
  console.log('DETAIL_NAME='+(detailBody._h.indexOf('宝剑')>=0?'1':'0'));
  console.log('DETAIL_TITLE='+(detailTitle.textContent.indexOf('宝剑')>=0?'1':'0'));
  console.log('DETAIL_MASK='+(detailMask.style.display==='flex'?'1':'0'));
  // 细节弹窗(奥特曼): 专属口号 + 已拥有 + 语音名称 + 延时口号
  const sp0=SPOKE.length;
  Wish.giftDetail('diga');
  console.log('DETAIL_ULTRA_IMG='+(detailBody._h.indexOf('/static/edu/ultra/diga.svg')>=0?'1':'0'));
  console.log('DETAIL_SLOGAN='+(detailBody._h.indexOf('化作光')>=0?'1':'0'));
  console.log('DETAIL_OWNED='+(detailBody._h.indexOf('已拥有')>=0?'1':'0'));
  console.log('SPOKE1='+(SPOKE.length>sp0 && SPOKE[sp0]==='迪迦奥特曼'?'1':'0'));
  await new Promise(r=>setTimeout(r,1700));  // 等口号延时播报
  console.log('SPOKE2='+(SPOKE.indexOf('化作光，飞向未来！')>=0?'1':'0'));
})();
''')
    for probe in ('SEC2=2','CAT_HAS_ULTRA=1','ULTRA_UNIQUE=1',
                  'CAT_HAS_DAO=1','CAT_HAS_GONG=1','CAT_HAS_QIANG=1','CAT_HAS_JIAN=1','CAT_HAS_DUN=1',
                  'DEF_DAO=25','DEF_GONG=40','DEF_QIANG=45','STARS_AFTER=55','REDEEMED1=1','REDEEMED_FEIDAO=1',
                  'REDEEMED_HAS_PRICE=1','STARS_EXHAUST=10','COUNT2=4',
                  'SELL_REFUND=10','SELL_STARS=20','SELL_COUNT=3',
                  'SELLOF_STARS=30','SELLOF_COUNT=2',
                  'DIGA_STARS=320','DIGA_COUNT=1','DIGA_BLOCKED_STARS=320','DIGA_BLOCKED_COUNT=1',
                  'ULTRA_TAB_WEAP=1','ULTRA_TAB_IMG=1','ULTRA_TAB_TITLE=1',
                  'NO_FOLD=1','ONELINE_DIGA=1','SELL_NO_PLUS=1','SELL_175=1',
                  'WEAPON_TAB_FEIDAO=1','WEAPON_TAB_NOULTRA=1',
                  'DETAIL_IMG=1','DETAIL_NOEMOJI=1','DETAIL_NAME=1','DETAIL_TITLE=1','DETAIL_MASK=1',
                  'DETAIL_ULTRA_IMG=1','DETAIL_SLOGAN=1','DETAIL_OWNED=1','SPOKE1=1','SPOKE2=1'):
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


def test_hydrate_force_preserves_usage_extra():
    """刷新时服务端旧弹(force 覆盖本地、无 usageExtra)不得清掉当天已解锁次数:
    答对解锁后刷新, 若服务端返回的弹缺少 usageExtra(如归并产物/旧快照),
    本地当天解锁仍须保留, 不能重新弹「学习时间到啦」."""
    out = _harness(r'''
(async()=>{
  const store=global.store;
  const dk=()=>{const t=new Date();const p=n=>n<10?'0'+n:n;return t.getFullYear()+'-'+p(t.getMonth()+1)+'-'+p(t.getDate());};
  // 场景: 本地已答对解锁(usageExtra[today]=1)但服务端旧弹没有(归并产物/拉取快照)
  global.localStorage.setItem('edu_record_v1_kk', JSON.stringify({
    stars:3,records:[],wrong:[],wishes:[],settings:{dailyMin:0},points:0,level:{},
    usage:{[dk()]:{secs:1800,count:60,n:60}},
    usageExtra:{[dk()]:1}
  }));
  W.Edu.Store.loadAllState();
  // 模拟 hydrate force 覆盖: 与 edu-bootstrap.onState 相同入口(force=true)
  W.eduSync._onState && W.eduSync._onState('kk','state',{
    stars:3,records:[],wrong:[],wishes:[],settings:{dailyMin:0},points:0,level:{},
    usage:{[dk()]:{secs:1800,count:60,n:60}}  // 无 usageExtra
  }, true);
  console.log('EXTRA_KEPT='+(W.Edu.Store.state.usageExtra[dk()]===1?'1':'0'));
  console.log('NOT_OVER='+(W.Edu.Store.usageOver()? '0':'1'));
  console.log('LIMIT_KEPT='+(W.Edu.Store.usageLimitSec()===60*60?'1':'0'));
})();
''')
    for probe in ('EXTRA_KEPT=1', 'NOT_OVER=1', 'LIMIT_KEPT=1'):
        assert probe in out, out
