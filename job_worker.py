#!/usr/bin/env python

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
"""笔记/知识库整理后台进程(单实例)。

职责:
1. 消费 note_job 队列:手动触发(后台管理页)与自动定时任务均为入队,
   本进程领取并执行"使用大模型整理/合并/提炼笔记与知识库",以及
   scope=cleanup 的黑名单字样清理(不调用大模型)。
2. 每个周六 22:00 自动入队一周整理待办(仅当近 7 天有新增笔记或知识);
   每周日 03:00 自动入队黑名单字清理(仅当检测到黑名单字样)。

数据:结构化元数据在 tasks.db;大模型调用复用 knowledge 的 opencode
serve 客户端。
"""
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta

if os.environ.get('TZ'):
    try:
        time.tzset()
    except Exception:
        pass

from app import app, db, get_job_setting, apply_sensitive_log_filter
from notes import Note, NoteJob, parse_tags_json
from knowledge import (KbDocument, KbPage, KB_LLM_DISABLED, _session_create,
                       _send, _parse_tag_json, _parse_str_map,
                       KB_OPENCODE_BASE_URL, extract_point_tags,
                       tag_points_untagged, merge_duplicate_points,
                       refine_points_unrefined, refine_points_all,
                       refine_docs_unrefined, refine_docs_all,
                       clean_blacklist_keywords)

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(name)s %(levelname)s %(message)s')
logger = logging.getLogger('job_worker')
apply_sensitive_log_filter()

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

_TAG_PROMPT = (
    '你是笔记整理助手。下面是一组编号的笔记(标题+内容摘要)。'
    '请为每条笔记推荐 2~4 个简短中文标签(如 "工作"、"会议"、"学习"、"Python")。\n'
    '只输出一个 JSON 对象,键为笔记编号字符串,值为标签数组,'
    '例如 {"1":["工作","周报"],"2":["学习"]}。不要输出其他内容。\n\n'
)

_NOTE_REFINE_PROMPT = (
    '你是笔记整理助手。下面是一组编号的笔记(原标题+内容摘要)。请为每条'
    '提炼润色一个简洁、准确的标题(30 字内,中文,保留关键信息,'
    '不要以"笔记""记录""清单"结尾)。\n'
    '只输出一个 JSON 对象,键为笔记编号字符串,值为标题字符串,'
    '例如 {"1":"分中心项目委测试处统计数据","2":"会议待办清单"}。'
    '不要输出其他内容。\n\n'
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


def _auto_tag_notes(limit=ORG_MAX_NOTES):
    """用 opencode 为近期无标签的笔记推荐标签并写入。返回 (处理条数, 新增标签数)。"""
    notes = Note.query.order_by(Note.created_at.desc()).limit(limit).all()
    targets = [n for n in notes if not parse_tags_json(n.tags)]
    if not targets:
        return 0, 0
    changed = total_added = 0
    CHUNK = 30
    for i in range(0, len(targets), CHUNK):
        chunk = targets[i:i + CHUNK]
        lines = [f'{n}. {note.title}\n{(note.content or "")[:200]}'
                 for n, note in enumerate(chunk, 1)]
        prompt = _TAG_PROMPT + '\n\n'.join(lines) + '\n'
        try:
            raw = _llm(prompt)
        except Exception as e:
            logger.warning('auto tag chunk failed: %s', e)
            continue
        mapping = _parse_tag_json(raw)
        for n, note in enumerate(chunk, 1):
            tags = mapping.get(str(n))
            if not tags:
                continue
            cur = parse_tags_json(note.tags)
            added = [t for t in tags if t and t not in cur]
            if added:
                note.tags = json.dumps(cur + added, ensure_ascii=False)
                changed += 1
                total_added += len(added)
    db.session.commit()
    return changed, total_added


def _refine_note_titles(full=False, limit=ORG_MAX_NOTES):
    """用 opencode 提炼润色笔记标题(可选只处理未提炼的)。返回报告文本。"""
    notes = Note.query.order_by(Note.created_at.desc()).limit(limit).all()
    targets = [n for n in notes if full or n.refined_at is None]
    if not targets:
        return '笔记标题提炼:无待提炼笔记'
    changed = 0
    CHUNK = 30
    for i in range(0, len(targets), CHUNK):
        chunk = targets[i:i + CHUNK]
        lines = [f'{n}. 原标题:{note.title}\n{(note.content or "")[:200]}'
                 for n, note in enumerate(chunk, 1)]
        prompt = _NOTE_REFINE_PROMPT + '\n\n'.join(lines) + '\n'
        try:
            raw = _llm(prompt)
        except Exception as e:
            logger.warning('note refine chunk failed: %s', e)
            continue
        mapping = _parse_str_map(raw)
        for n, note in enumerate(chunk, 1):
            t = mapping.get(str(n))
            if t and t != note.title:
                note.title = t[:80]
                note.refined_at = datetime.utcnow()
                changed += 1
    db.session.commit()
    return '笔记标题提炼:更新 %d 条笔记标题' % changed


def _auto_tag_msg():
    changed, added = _auto_tag_notes()
    return '笔记-标签匹配:为 %d 条笔记补充 %d 个标签' % (changed, added)


def _merge_msg():
    merged, left = merge_duplicate_points()
    return '知识点合并:合并 %d 条重复知识点,剩余 %d 条' % (merged, left)


def _resolve_cleanup_terms(job=None):
    """清理黑名单词源优先级: 任务自定义 > 后台配置自定义 > 系统默认 KB_TAG_BLACKLIST。"""
    raw = ''
    if job and job.target:
        raw = job.target
    if not raw:
        raw = get_job_setting('job_cleanup_terms', '')
    terms = [t.strip() for t in re.split(r'[，,;；]+', raw) if t.strip()]
    return terms or None


def _cleanup_blacklist_msg(job=None):
    """清理黑名单字样(支持自定义名单)。返回报告文本。"""
    report = clean_blacklist_keywords(terms=_resolve_cleanup_terms(job),
                                      dry_run=False)
    if not report:
        return '黑名单字清理:未发现黑名单字样'
    lines = ['黑名单字清理:共 %d 处' % sum(n for _, n in report)]
    for name, n in report:
        lines.append('  %s: %d 行' % (name, n))
    lines.append('提示:如向量检索(SochDB)文本含这些字样,'
                 '需对相关文档重新识别以重建向量。')
    return '\n'.join(lines)


def _has_blacklist_hits():
    return bool(clean_blacklist_keywords(terms=_resolve_cleanup_terms(),
                                         dry_run=True))


def _report_msg(text):
    result = _llm(text)
    if result and result.strip():
        return '整理报告:\n' + result.strip()
    return None


def run_backup(job):
    """执行数据备份(scope=backup),返回 (结果文本, 是否被停止)。"""
    from backup import create_backup, prune_backups
    try:
        name, size, err = create_backup()
    except Exception as e:
        return '备份失败: %s' % e, False
    if err:
        return '备份失败: %s' % err, False
    keep = int(get_job_setting('job_backup_keep', '14'))
    removed = []
    try:
        removed = prune_backups(keep)
    except Exception as e:
        logger.warning('backup prune failed: %s', e)
    msg = '自动备份成功:%s(%.2f MB)' % (name, size / 1024.0 / 1024.0)
    if removed:
        msg += '; 已按保留策略(保留 %d 份)清理: %s' % (
            keep, ', '.join(removed))
    return msg, False


def run_organization(job):
    """按 scope 执行整理任务(全部基于 opencode 接口),返回 (结果文本, 是否被停止)。

    - notes:  笔记标签匹配 + 笔记标题提炼(仅未提炼)
    - kb:     知识点合并 + 知识点标签 + 知识点提炼(仅未提炼) + 文档标题提炼(仅未提炼)
    - all:    以上全部
    - refine: 全量提炼(所有笔记/文档/知识点重新提炼 + 合并 + 标签)
    - cleanup: 清理黑名单字样(不调用大模型)
    每个阶段之间检查 job.cancel 以支持手动停止;阶段切换时写 phase/
    updated_at 作为心跳,便于进程中断后按超时恢复。
    """
    reports = []
    cancelled = False

    def _refresh():
        try:
            db.session.refresh(job)
        except Exception:
            pass

    def _step(name, fn):
        nonlocal cancelled
        _refresh()
        if job.cancel:
            cancelled = True
            return
        job.phase = name
        db.session.commit()
        try:
            msg = fn()
            if msg:
                reports.append(msg)
        except Exception as e:
            reports.append('%s:失败(%s)' % (name, e))
        job.progress = min(90, job.progress + 10)
        db.session.commit()

    if job.scope == 'cleanup':
        _step('黑名单字清理', lambda: _cleanup_blacklist_msg(job))

    if job.scope in ('notes', 'all'):
        _step('笔记-标签匹配', _auto_tag_msg)
        _step('笔记标题提炼', lambda: _refine_note_titles(False))
    if job.scope in ('kb', 'all'):
        _step('知识点合并', _merge_msg)
        _step('知识点标签', lambda: '知识点标签:为 %d 个知识点提取标签'
              % tag_points_untagged())
        _step('知识点提炼', lambda: '知识点提炼:更新 %d 条知识点标题/概要'
              % refine_points_unrefined())
        _step('文档标题提炼', lambda: '文档标题提炼:更新 %d 篇文档标题'
              % refine_docs_unrefined())
    if job.scope == 'refine':
        _step('笔记标题提炼(全量)', lambda: _refine_note_titles(True))
        _step('知识点合并', _merge_msg)
        _step('知识点标签', lambda: '知识点标签:为 %d 个知识点提取标签'
              % tag_points_untagged())
        _step('知识点提炼(全量)', lambda: '知识点提炼:更新 %d 条知识点标题/概要'
              % refine_points_all())
        _step('文档标题提炼(全量)', lambda: '文档标题提炼:更新 %d 篇文档标题'
              % refine_docs_all())

    _refresh()
    if not cancelled and not job.cancel and job.scope in ('notes', 'kb', 'all'):
        text = _gather(job)
        if text.strip():
            _step('整理报告', lambda: _report_msg(text))

    if cancelled or job.cancel:
        return ('\n'.join(reports) + '\n(任务被手动停止)' if reports else ''), True
    if not reports:
        return '本次无待整理素材(没有符合条件的笔记或知识)。', False
    return '\n'.join(reports), False


def _create_report_note(job, result):
    try:
        kind = '清理' if job.scope == 'cleanup' else '整理'
        n = Note(user_id=job.created_by, thread_id=None,
                 title=f'{kind}报告 {datetime.now().strftime("%Y-%m-%d %H:%M")}',
                 content=result, tags='[]',
                 version=1, simhash='0')
        db.session.add(n)
        db.session.commit()
    except Exception as e:
        logger.warning('report note write failed: %s', e)


def _execute(job):
    job.status = 'running'
    job.progress = 5
    job.phase = '准备'
    job.cancel = 0
    job.started_at = datetime.utcnow()
    db.session.commit()
    try:
        if job.scope == 'backup':
            result, cancelled = run_backup(job)
        else:
            result, cancelled = run_organization(job)
        job.finished_at = datetime.utcnow()
        if cancelled:
            job.status = 'cancelled'
            job.result = result or ''
            db.session.commit()
            logger.info('job %s cancelled', job.id)
            return
        job.status = 'done'
        job.result = result or ''
        job.progress = 100
        db.session.commit()
        if job.scope != 'backup':
            _create_report_note(job, result)
        logger.info('job %s done', job.id)
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
        job.started_at = datetime.utcnow()
        db.session.commit()
    return job


RECOVER_AFTER_MINUTES = int(os.environ.get('JOB_RECOVER_MINUTES', '20'))


def _recover_stale():
    """把因进程突然退出而长期无心跳的 running 作业恢复为 queued,实现续跑。"""
    cutoff = datetime.utcnow() - timedelta(minutes=RECOVER_AFTER_MINUTES)
    stale = []
    for j in NoteJob.query.filter_by(status='running').all():
        if j.updated_at is None or j.updated_at < cutoff:
            stale.append(j)
    for j in stale:
        j.status = 'queued'
        j.phase = ''
        j.progress = 0
        j.cancel = 0
        j.started_at = None
    if stale:
        db.session.commit()
        logger.info('已恢复 %d 个中断的任务为 queued', len(stale))
    else:
        db.session.rollback()


def _enqueue_auto(now):
    if get_job_setting('job_organize_enabled', '1') != '1':
        return
    wd = int(get_job_setting('job_organize_weekday', '5'))
    hr = int(get_job_setting('job_organize_hour', '22'))
    if (wd >= 0 and now.weekday() != wd) or now.hour != hr:
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


def _enqueue_auto_cleanup(now):
    if get_job_setting('job_cleanup_enabled', '1') != '1':
        return
    wd = int(get_job_setting('job_cleanup_weekday', '6'))
    hr = int(get_job_setting('job_cleanup_hour', '3'))
    if (wd >= 0 and now.weekday() != wd) or now.hour != hr:
        return
    since = now - timedelta(days=7)
    if db.session.query(NoteJob.id).filter(
            NoteJob.trigger == 'auto', NoteJob.scope == 'cleanup',
            NoteJob.created_at >= since).first():
        return
    if not _has_blacklist_hits():
        return
    db.session.add(NoteJob(scope='cleanup', status='queued', trigger='auto',
                           created_by=None, created_at=datetime.now()))
    db.session.commit()
    logger.info('入队本周自动黑名单字清理')


def _enqueue_auto_backup(now):
    """每日自动备份(默认 03:00 本地时间),时间窗 5 分钟,12 小时内不重复。"""
    if get_job_setting('job_backup_enabled', '1') != '1':
        return
    hr = int(get_job_setting('job_backup_hour', '3'))
    mm = int(get_job_setting('job_backup_minute', '0'))
    utc_hr = (hr - 8) % 24  # TZ=Asia/Shanghai → UTC 差 -8
    target = utc_hr * 60 + mm
    cur = now.hour * 60 + now.minute
    if not (target <= cur < target + 5):
        return
    since = now - timedelta(hours=12)
    if db.session.query(NoteJob.id).filter(
            NoteJob.trigger == 'auto', NoteJob.scope == 'backup',
            NoteJob.created_at >= since).first():
        return
    db.session.add(NoteJob(scope='backup', status='queued', trigger='auto',
                           created_by=None, created_at=now))
    db.session.commit()
    logger.info('入队每日自动备份待办')


def main():
    with app.app_context():
        logger.info('job_worker started, interval=%ss 触发器=todo', INTERVAL)
    current_sleep = 1  # 空转退避: 1, 2, 4, 8, 16, 30 秒封顶
    while True:
        try:
            with app.app_context():
                now = datetime.now()
                _enqueue_auto(now)
                _enqueue_auto_cleanup(now)
                _enqueue_auto_backup(datetime.utcnow())
                _recover_stale()
                job = _claim()
                if job:
                    logger.info('processing job %s scope=%s trigger=%s',
                                job.id, job.scope, job.trigger)
                    _execute(job)
                    current_sleep = 1
                else:
                    time.sleep(current_sleep)
                    current_sleep = min(current_sleep * 2, 30)
        except Exception as e:
            logger.error('job_worker loop error: %s', e)
            time.sleep(current_sleep)
            current_sleep = min(current_sleep * 2, 30)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        import sys
        sys.exit(0)