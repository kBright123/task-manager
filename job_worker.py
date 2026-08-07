#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""笔记/知识库整理后台进程(单实例)。

职责:
1. 消费 note_job 队列:手动触发(后台管理页)与自动定时任务均为入队,
   本进程领取并执行"使用大模型整理/合并/提炼笔记与知识库"。
2. 每个周六 22:00 自动入队一周整理待办(仅当近 7 天有新增笔记或知识)。

数据:结构化元数据在 tasks.db;大模型调用复用 knowledge 的 opencode
serve 客户端。
"""
import json
import logging
import os
import time
from datetime import datetime, timedelta

if os.environ.get('TZ'):
    try:
        time.tzset()
    except Exception:
        pass

from app import app, db
from notes import Note, NoteJob
from knowledge import (KbDocument, KbPage, KB_LLM_DISABLED, _session_create,
                       _send, KB_OPENCODE_BASE_URL)

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(name)s %(levelname)s %(message)s')
logger = logging.getLogger('job_worker')

INTERVAL = int(os.environ.get('JOB_INTERVAL', '60'))
ORG_MAX_NOTES = int(os.environ.get('JOB_MAX_NOTES', '80'))
ORG_MAX_KBS = int(os.environ.get('JOB_MAX_KBS', '40'))

_ORG_PROMPT = (
    '你是知识整理助手。下面是近期收集的笔记与知识片段。请完成以下工作:\n'
    '1. 合并相互重复、内容相关的条目,删除明显冗余;\n'
    '2. 提炼关键要点,整理成结构化 Markdown(可用 ## 分节、- 列表);\n'
    '3. 若存在疑似重复的条目,单独列出并说明保留了哪一条;\n'
    '4. 输出结果即为最终整理笔记,无需客套。\n\n'
    '素材如下:\n'
)


def _llm(text):
    import requests
    sid = _session_create()
    try:
        return _send(sid, _ORG_PROMPT + text)
    finally:
        try:
            requests.delete(f'{KB_OPENCODE_BASE_URL}/session/{sid}',
                            timeout=30)
        except Exception:
            pass


def _target_ids(target, prefix):
    """解析 target 中的 'note:1,2' / 'kb:3,4' 形式的 ID 列表。"""
    out = []
    for part in (target or '').split(','):
        part = part.strip()
        if part.startswith(prefix + ':'):
            for x in part[len(prefix) + 1:].split(','):
                if x.strip().isdigit():
                    out.append(int(x))
    return out


def _gather_notes(scope, target):
    q = Note.query.order_by(Note.created_at.desc())
    ids = _target_ids(target, 'note')
    if ids:
        q = q.filter(Note.id.in_(ids))
    return q.limit(ORG_MAX_NOTES).all() if scope != 'kb' else []


def _gather_kb(scope, target):
    if scope == 'notes':
        return ''
    q = KbDocument.query.filter(
        KbDocument.status == 'done').order_by(KbDocument.created_at.desc())
    ids = _target_ids(target, 'kb')
    if ids:
        q = q.filter(KbDocument.id.in_(ids))
    docs = q.limit(ORG_MAX_KBS).all()
    blocks = []
    for doc in docs:
        page = KbPage.query.filter_by(doc_id=doc.id).order_by(
            KbPage.page_no).first()
        txt = ((page.text or '')[:1000]) if page else ''
        blocks.append(f'【知识 · {doc.title}】\n{txt}')
    return '\n\n'.join(blocks)


def _gather(job):
    notes = _gather_notes(job.scope, job.target)
    kb_text = _gather_kb(job.scope, job.target)
    blocks = []
    for n in notes:
        blocks.append(f'【笔记 · {n.title}】\n{(n.content or "")[:1500]}')
    text = '\n\n'.join(blocks)
    if kb_text:
        text += '\n\n' + kb_text
    return text


def run_organization(job):
    text = _gather(job)
    if not text.strip():
        return True, '本次无待整理素材(没有符合条件的笔记或知识)。', ''
    try:
        result = _llm(text)
        return True, result, ''
    except Exception as e:
        return False, '', str(e)


def _create_report_note(job, result):
    try:
        n = Note(user_id=job.created_by, thread_id=None,
                 title=f'整理报告 {datetime.now().strftime("%Y-%m-%d %H:%M")}',
                 content=result, tags=json.dumps(['整理']), version=1,
                 simhash='0')
        db.session.add(n)
        db.session.commit()
    except Exception as e:
        logger.warning('report note write failed: %s', e)


def _execute(job):
    job.status = 'running'
    job.progress = 10
    job.started_at = datetime.utcnow()
    db.session.commit()
    try:
        ok, result, err = run_organization(job)
        job.finished_at = datetime.utcnow()
        if ok:
            job.status = 'done'
            job.result = result
            job.progress = 100
            db.session.commit()
            _create_report_note(job, result)
            logger.info('job %s done', job.id)
        else:
            job.status = 'failed'
            job.error = err
            db.session.commit()
            logger.warning('job %s failed: %s', job.id, err)
    except Exception as e:
        job.finished_at = datetime.utcnow()
        job.status = 'failed'
        job.error = str(e)
        db.session.commit()
        logger.exception('job %s error', job.id)


def _claim():
    # 单实例:取最早的 queued 作业
    job = NoteJob.query.filter_by(status='queued').order_by(
        NoteJob.created_at, NoteJob.id).first()
    if job:
        job.status = 'running'
        db.session.commit()
    return job


def _enqueue_auto(now):
    if not (now.weekday() == 5 and 22 <= now.hour < 24):
        return
    since = now - timedelta(days=7)
    if db.session.query(NoteJob.id).filter(
            NoteJob.trigger == 'auto',
            NoteJob.created_at >= since).first():
        return
    has_new_note = db.session.query(Note.id).filter(
        Note.created_at >= since).first()
    has_kb = db.session.query(KbDocument.id).filter(
        KbDocument.created_at >= since).first()
    if not has_new_note and not has_kb:
        return
    db.session.add(NoteJob(scope='all', status='queued', trigger='auto',
                           created_by=None, created_at=datetime.now()))
    db.session.commit()
    logger.info('入队本周自动整理待办')


def main():
    with app.app_context():
        logger.info('job_worker started, interval=%ss 触发器=todo', INTERVAL)
    while True:
        try:
            with app.app_context():
                now = datetime.now()
                _enqueue_auto(now)
                job = _claim()
                if job:
                    logger.info('processing job %s scope=%s trigger=%s',
                                job.id, job.scope, job.trigger)
                    _execute(job)
                else:
                    time.sleep(INTERVAL)
        except Exception as e:
            logger.error('job_worker loop error: %s', e)
            time.sleep(INTERVAL)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        import sys
        sys.exit(0)