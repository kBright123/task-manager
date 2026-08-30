# This file is part of 知行合一 · 任务与知识管理系统 (TaskManager).
# Copyright (C) 2026 TaskManager contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

# -*- coding: utf-8 -*-
"""教育娱乐模式：前端学习乐园 + 独立后端数据库。

定位: 教育模式使用自己独立的数据库(edu.db), 不依赖也不写工作模式数据库,
支持免登录访问(未登录时按浏览器生成的匿名 ID 归属数据)。

数据:
- 孩子档案(名字/出生年份/性别)
- 每个孩子的学习状态: 星星、答题记录、错题本、星愿、兑换记录、徽章、
  每日用量、连击、闯关进度 等(以 JSON 弹存储于 edu_data 表)。

页面由前端 JS 驱动, 本模块负责:
- 渲染页面骨架(/edu/)
- 提供 /edu/api/** REST 接口, 供前端读写数据。
"""
import json
import logging
import os
import threading
from datetime import datetime

from flask import Blueprint, jsonify, request, render_template, current_app
from flask_login import current_user
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, text
from sqlalchemy.orm import sessionmaker, scoped_session, declarative_base

logger = logging.getLogger(__name__)

education_bp = Blueprint('education', __name__, url_prefix='/edu')

# ---- 独立数据库(edu.db), 与工作模式 tasks.db 完全解耦 ----
_engine_lock = threading.Lock()
_engine = None
_Session = None
Base = declarative_base()

# 前端量较大的 JSON 用 Text 存; 记录/错题等整体随 state 一起存,减少表数量与同步复杂度
class EduProfile(Base):
    __tablename__ = 'edu_profile'
    id = Column(Integer, primary_key=True)
    owner = Column(String(80), nullable=False, index=True)
    name = Column(String(40), default='宝贝')
    birth_year = Column(Integer, default=2018)
    gender = Column(String(12), default='')
    sort = Column(Integer, default=0)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

class EduData(Base):
    __tablename__ = 'edu_data'
    id = Column(Integer, primary_key=True)
    owner = Column(String(80), nullable=False, index=True)
    profile_id = Column(Integer, nullable=False, index=True)
    dkey = Column(String(40), default='state')   # 'state' | 'levels' | 'workbench'
    payload = Column(Text, default='{}')
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

class EduQBank(Base):
    """题目库: 按归属/学科/类型/难度存储, 支持去重、权重拉取、作答统计."""
    __tablename__ = 'edu_qbank'
    id = Column(Integer, primary_key=True)
    owner = Column(String(80), nullable=False, index=True)
    subj = Column(String(16), nullable=False, index=True)      # 'zh' | 'math' | 'en'
    type = Column(String(16), nullable=False, index=True)      # 'poem','zi','stroke','pinyin','yun','read','fan','liang','calc','judge','word','order','word','dialogue'
    difficulty = Column(Integer, default=3, index=True)        # 1~5
    prompt = Column(Text, nullable=False)                      # 题干(去重键的一部分)
    options = Column(Text, default='')                         # JSON 数组 [{v,label}]
    correct = Column(String(200), nullable=False)              # 正确答案
    note = Column(Text, default='')                            # 解析/备注
    used_count = Column(Integer, default=0)                    # 被出题次数
    wrong_count = Column(Integer, default=0)                   # 答错次数
    last_seen = Column(DateTime)                               # 最近出题/复现时间
    created_at = Column(DateTime)


def _db_path():
    return os.path.join(current_app.instance_path, 'edu.db')


def _get_session():
    global _engine, _Session
    with _engine_lock:
        if _engine is None:
            path = _db_path()
            _engine = create_engine('sqlite:///' + path, echo=False)
            Base.metadata.create_all(_engine)
            _migrate(_engine)
            _Session = scoped_session(sessionmaker(bind=_engine))
    return _Session()


def _migrate(engine):
    """轻量迁移: 旧库补新增列(create_all 不会改已存在表)."""
    with engine.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(edu_data)")).fetchall()]
        if cols and 'created_at' not in cols:
            conn.execute(text("ALTER TABLE edu_data ADD COLUMN created_at DATETIME"))
        cols2 = [r[1] for r in conn.execute(text("PRAGMA table_info(edu_profile)")).fetchall()]
        if cols2 and 'created_at' not in cols2:
            conn.execute(text("ALTER TABLE edu_profile ADD COLUMN created_at DATETIME"))
        conn.commit()


def _owner_id():
    """数据归属: 已登录按账号 id, 免登录用前端匿名 ID."""
    if current_user and getattr(current_user, 'is_authenticated', False):
        return 'u' + str(current_user.id)
    anon = (request.headers.get('X-Edu-Anon') or request.args.get('anon') or '').strip()
    return 'anon_' + (anon or 'unknown')


def _drop_profile_data(sess, owner, pid):
    """删除孩子档案及其所有数据弹(仅限归属内)."""
    sess.query(EduProfile).filter_by(id=pid, owner=owner).delete()
    sess.query(EduData).filter_by(owner=owner, profile_id=pid).delete()


@education_bp.route('/')
def index():
    """教育学习乐园(前端驱动, 数据走 /edu/api/**)."""
    return render_template('education.html')


# ==================== API ====================

@education_bp.route('/api/bootstrap', methods=['GET', 'POST'])
def bootstrap():
    """返回当前归属下的孩子档案列表.

    免登录: 前端需带 X-Edu-Anon(匿名ID); POST 时 body 可带前端本地孩子用于合并。
    """
    sess = _get_session()
    owner = _owner_id()
    rows = sess.query(EduProfile).filter_by(owner=owner).order_by(EduProfile.sort).all()
    kids = [dict(id=p.id, name=p.name, birthYear=p.birth_year, gender=p.gender,
                 created=getattr(p, 'created_at', None).isoformat() if p.created_at else '')
            for p in rows]
    sess.close()
    return jsonify(ok=True, owner=owner, kids=kids)


@education_bp.route('/api/kids', methods=['POST'])
def save_kids():
    """整体同步孩子档案(前端把本地所有孩子发来做 upsert + 删除).

    body: { kids: [{clientId, name, birthYear, gender}], removedIds: [...] }
    返回 { kids: [{id, clientId, name, birthYear, gender}] }
    """
    data = request.get_json(silent=True) or {}
    sess = _get_session()
    owner = _owner_id()
    out = []
    for i, k in enumerate(data.get('kids') or []):
        name = (k.get('name') or '宝贝')[:40]
        birth_year = int(k.get('birthYear') or 2018)
        gender = (k.get('gender') or '')[:12]
        pid = k.get('dbId')
        p = None
        if pid:
            try:
                pid = int(pid)
            except (TypeError, ValueError):
                pid = None
            if pid:
                p = sess.query(EduProfile).filter_by(id=pid, owner=owner).first()
        if p:
            p.name = name; p.birth_year = birth_year; p.gender = gender; p.sort = i
        else:
            p = EduProfile(owner=owner, name=name, birth_year=birth_year, gender=gender, sort=i)
            sess.add(p)
        sess.flush()
        pid2 = p.id
        out.append(dict(id=pid2, clientId=k.get('clientId'), name=p.name,
                        birthYear=p.birth_year, gender=p.gender))
    # 删除已移除的本地孩子(仅限归属内)
    for rid in data.get('removedIds') or []:
        try:
            _drop_profile_data(sess, owner, int(rid))
        except (TypeError, ValueError):
            continue
    sess.commit()
    sess.close()
    return jsonify(ok=True, owner=owner, kids=out)


@education_bp.route('/api/kids/<int:pid>/delete', methods=['POST'])
def delete_kid(pid):
    sess = _get_session()
    owner = _owner_id()
    _drop_profile_data(sess, owner, pid)
    sess.commit()
    sess.close()
    return jsonify(ok=True)


@education_bp.route('/api/kids/<int:pid>/state', methods=['GET', 'POST'])
def kid_state(pid):
    """读写某个孩子的数据弹(state/levels 等).

    GET ?dkey=state  -> 返回 {data: {...}}
    POST body {dkey:'state', data:{...}} -> 保存
    """
    sess = _get_session()
    owner = _owner_id()
    dkey = (request.args.get('dkey') or request.values.get('dkey') or 'state')
    if request.method == 'GET':
        row = sess.query(EduData).filter_by(owner=owner, profile_id=pid, dkey=dkey).first()
        payload = json.loads(row.payload) if row and row.payload else {}
        sess.close()
        return jsonify(ok=True, data=payload)
    # POST
    body = request.get_json(silent=True) or {}
    payload = body.get('data') or {}
    row = sess.query(EduData).filter_by(owner=owner, profile_id=pid, dkey=dkey).first()
    now = datetime.utcnow()
    if row:
        row.payload = json.dumps(payload, ensure_ascii=False)
        row.updated_at = now
    else:
        sess.add(EduData(owner=owner, profile_id=pid, dkey=dkey,
                         payload=json.dumps(payload, ensure_ascii=False),
                         created_at=now, updated_at=now))
    sess.commit()
    sess.close()
    return jsonify(ok=True)


@education_bp.route('/api/reset', methods=['POST'])
def reset_all():
    """家长重置: 删除当前归属下所有孩子与数据."""
    sess = _get_session()
    owner = _owner_id()
    ids = [p.id for p in sess.query(EduProfile).filter_by(owner=owner).all()]
    sess.query(EduProfile).filter_by(owner=owner).delete()
    if ids:
        sess.query(EduData).filter(
            EduData.owner == owner, EduData.profile_id.in_(ids)).delete(synchronize_session=False)
    sess.commit()
    sess.close()
    return jsonify(ok=True)


# ==================== 题库 ====================

@education_bp.route('/api/qbank/ensure', methods=['POST'])
def qbank_ensure():
    """批量入库题目: 按 owner+subj+type+prompt 去重(仅首次入库).
    body: { subj, type, difficulty, items: [{prompt, options[], correct, note}] }
    """
    data = request.get_json(silent=True) or {}
    subj = data.get('subj')
    typ = data.get('type')
    diff = int(data.get('difficulty') or 3)
    items = data.get('items') or []
    if not (subj and typ and items):
        return jsonify(ok=False, error='missing fields'), 400
    sess = _get_session()
    owner = _owner_id()
    added = 0
    for it in items:
        prompt = (it.get('prompt') or '').strip()
        if not prompt:
            continue
        exists = sess.query(EduQBank).filter_by(
            owner=owner, subj=subj, type=typ, prompt=prompt
        ).first()
        if exists:
            continue
        opts = it.get('options') or []
        row = EduQBank(
            owner=owner, subj=subj, type=typ, difficulty=diff,
            prompt=prompt, options=json.dumps(opts, ensure_ascii=False),
            correct=str(it.get('correct') or ''), note=it.get('note') or '',
            created_at=datetime.utcnow()
        )
        sess.add(row)
        added += 1
    sess.commit()
    sess.close()
    return jsonify(ok=True, added=added)


@education_bp.route('/api/qbank/pull', methods=['POST'])
def qbank_pull():
    """按权重拉题: 答错优先 -> 做过少 -> 难度匹配.
    body: { subj, type, difficulty, limit, exclude: [prompts] }
    """
    data = request.get_json(silent=True) or {}
    subj = data.get('subj')
    typ = data.get('type')
    diff = int(data.get('difficulty') or 3)
    limit = int(data.get('limit') or 10)
    exclude = set(data.get('exclude') or [])
    if not (subj and typ):
        return jsonify(ok=False, error='missing fields'), 400
    sess = _get_session()
    owner = _owner_id()
    from sqlalchemy import func
    q = sess.query(EduQBank).filter_by(owner=owner, subj=subj, type=typ)
    # 难度优先: 同档 -> 相邻档
    rows = q.filter(EduQBank.difficulty.in_([diff, max(1,diff-1), min(5,diff+1)])).all()
    if not rows:
        sess.close()
        return jsonify(ok=True, items=[])
    # 权重: wrong_count降序 -> used_count升序 -> 随机
    scored = []
    for r in rows:
        if r.prompt in exclude:
            continue
        w = (r.wrong_count or 0) * 1000 - (r.used_count or 0) * 10 + (100 - abs((r.difficulty or 3) - diff))
        scored.append((w, r))
    scored.sort(key=lambda x: -x[0])
    out = []
    for _, r in scored[:limit]:
        out.append(dict(
            id=r.id, subj=r.subj, type=r.type, difficulty=r.difficulty,
            prompt=r.prompt, options=json.loads(r.options or '[]'),
            correct=r.correct, note=r.note
        ))
    sess.close()
    return jsonify(ok=True, items=out)


@education_bp.route('/api/qbank/learn', methods=['POST'])
def qbank_learn():
    """记录作答反馈: 用于更新 wrong_count/used_count/last_seen."""
    data = request.get_json(silent=True) or {}
    subj = data.get('subj')
    typ = data.get('type')
    prompt = (data.get('prompt') or '').strip()
    correct = data.get('correct')
    diff = int(data.get('difficulty') or 3)
    if not (subj and typ and prompt):
        return jsonify(ok=False, error='missing fields'), 400
    sess = _get_session()
    owner = _owner_id()
    row = sess.query(EduQBank).filter_by(
        owner=owner, subj=subj, type=typ, prompt=prompt
    ).first()
    if row:
        row.used_count = (row.used_count or 0) + 1
        if correct is False:
            row.wrong_count = (row.wrong_count or 0) + 1
        row.last_seen = datetime.utcnow()
        sess.commit()
    sess.close()
    return jsonify(ok=True)
