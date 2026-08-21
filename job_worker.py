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
   本进程领取并执行"合并去重笔记、整理/合并/提炼知识库",以及
   scope=cleanup 的黑名单字样清理 + 操作日志/邮件记录/任务执行记录清理。
2. 每个周六 22:00 自动入队一周整理待办(仅当近 7 天有新增笔记或知识);
   每周日 03:00 自动入队清理(黑名单字样 或 有过期的日志/邮件/任务记录)。

数据:结构化元数据在 tasks.db;大模型调用复用 knowledge 的 opencode
serve 客户端。
"""
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from timeutil import cn_now

if os.environ.get('TZ'):
    try:
        time.tzset()
    except Exception:
        pass

from app import app, db, get_job_setting, apply_sensitive_log_filter
from notes import Note, NoteJob, merge_duplicate_notes
from knowledge import (KbDocument, KbPage, KB_LLM_DISABLED, _session_create,
                       _send,
                       KB_OPENCODE_BASE_URL,
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
    '1. 提炼关键要点,整理成结构化 Markdown(可用 ## 分节、- 列表);\n'
    '2. 若存在明显重复的条目,单独列出并说明保留了哪一条;\n'
    '3. 输出整理报告即可,无需客套。\n\n'
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


def _merge_notes_msg():
    merged, left = merge_duplicate_notes()
    return '笔记去重合并:合并 %d 条重复笔记,剩余 %d 条' % (merged, left)


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


def _cleanup_keep_days():
    return int(get_job_setting('job_cleanup_keep_days', '7') or 7)


def _has_cleanup_work():
    """是否还有待清理内容: 黑名单字样 或 过期的日志/邮件/任务执行记录。"""
    if _has_blacklist_hits():
        return True
    days = _cleanup_keep_days()
    from app import OperationLog, EmailRecord
    cutoff_log = cn_now() - timedelta(days=days)
    cutoff_email = cn_now() - timedelta(days=days)
    cutoff_job = cn_now() - timedelta(days=days)
    try:
        if OperationLog.query.filter(
                OperationLog.created_at < cutoff_log).first():
            return True
        if EmailRecord.query.filter(
                EmailRecord.created_at < cutoff_email).first():
            return True
        if NoteJob.query.filter(NoteJob.created_at < cutoff_job).first():
            return True
    except Exception:
        pass
    return False


def _cleanup_logs_msg():
    """清理超过保留期的操作日志,返回报告文本。"""
    from app import OperationLog
    days = _cleanup_keep_days()
    cutoff = cn_now() - timedelta(days=days)
    try:
        deleted = OperationLog.query.filter(
            OperationLog.created_at < cutoff).delete(
                synchronize_session=False)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return '操作日志清理:失败(%s)' % e
    if not deleted:
        return '操作日志清理:%d 天内无过期日志,跳过' % days
    return '操作日志清理:删除 %d 条(保留 %d 天)' % (deleted, days)


def _cleanup_emails_msg():
    """清理超过保留期的邮件记录,返回报告文本。"""
    from app import EmailRecord
    days = _cleanup_keep_days()
    cutoff = cn_now() - timedelta(days=days)
    try:
        deleted = EmailRecord.query.filter(
            EmailRecord.created_at < cutoff).delete(
                synchronize_session=False)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return '邮件记录清理:失败(%s)' % e
    if not deleted:
        return '邮件记录清理:%d 天内无过期记录,跳过' % days
    return '邮件记录清理:删除 %d 条(保留 %d 天)' % (deleted, days)


def _cleanup_jobs_msg():
    """清理超过保留期的定时任务执行记录,返回报告文本。"""
    days = _cleanup_keep_days()
    cutoff = cn_now() - timedelta(days=days)
    try:
        deleted = NoteJob.query.filter(
            NoteJob.created_at < cutoff).delete(
                synchronize_session=False)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return '任务执行记录清理:失败(%s)' % e
    if not deleted:
        return '任务执行记录清理:%d 天内无过期记录,跳过' % days
    return '任务执行记录清理:删除 %d 条(保留 %d 天)' % (deleted, days)


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


def _sync_result(job, reports):
    """把当前累计的执行日志同步到 job.result,供前端实时展示。"""
    text = '\n'.join(r for r in reports if r)
    job.result = text
    job.updated_at = cn_now()
    db.session.add(job)


def run_organization(job):
    """按 scope 执行整理任务(笔记去重不调大模型,其余基于 opencode 接口),返回 (结果文本, 是否被停止)。

    - notes:  笔记去重合并(不调用大模型)
    - kb:     知识点合并 + 知识点标签 + 知识点提炼(仅未提炼) + 文档标题提炼(仅未提炼)
    - all:    笔记去重合并 + kb 全部 + 整理报告
    - refine: 全量提炼(所有文档/知识点重新提炼 + 合并 + 标签) + 笔记去重合并
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
        _sync_result(job, reports)
        db.session.commit()

    if job.scope == 'cleanup':
        _step('黑名单字清理', lambda: _cleanup_blacklist_msg(job))
        _step('操作日志清理', _cleanup_logs_msg)
        _step('邮件记录清理', _cleanup_emails_msg)
        _step('任务执行记录清理', _cleanup_jobs_msg)

    if job.scope in ('notes', 'all'):
        _step('笔记去重合并', _merge_notes_msg)
    if job.scope in ('kb', 'all'):
        _step('知识点合并', _merge_msg)
        _step('知识点标签', lambda: '知识点标签:为 %d 个知识点提取标签'
              % tag_points_untagged())
        _step('知识点提炼', lambda: '知识点提炼:更新 %d 条知识点标题/概要'
              % refine_points_unrefined())
        _step('整理文档(提取标题)', lambda: '整理文档:更新 %d 篇文档名称(15字内)'
              % refine_docs_unrefined())
    if job.scope == 'refine':
        _step('笔记去重合并', _merge_notes_msg)
        _step('知识点合并', _merge_msg)
        _step('知识点标签', lambda: '知识点标签:为 %d 个知识点提取标签'
              % tag_points_untagged())
        _step('知识点提炼(全量)', lambda: '知识点提炼:更新 %d 条知识点标题/概要'
              % refine_points_all())
        _step('整理文档(全量)', lambda: '整理文档:更新 %d 篇文档名称(15字内)'
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


def _notify_job_result(job, message):
    """任务完成/失败后给相关人员发送站内通知。"""
    try:
        from app import create_notification, User
        targets = []
        if job.created_by:
            u = db.session.get(User, job.created_by)
            if u and not u.is_disabled:
                targets.append(u.id)
        else:
            targets = [u.id for u in User.query.filter(
                User.role == 'admin', User.is_disabled == False).all()]
        if not targets:
            return
        for uid in targets:
            create_notification(uid, 'job_result', message)
        db.session.commit()
    except Exception as e:
        logger.warning('job notify failed: %s', e)


def _execute(job):
    job.status = 'running'
    job.progress = 5
    job.phase = '准备'
    job.cancel = 0
    job.started_at = cn_now()
    db.session.commit()
    try:
        if job.scope == 'backup':
            result, cancelled = run_backup(job)
        else:
            result, cancelled = run_organization(job)
        job.finished_at = cn_now()
        if cancelled:
            job.status = 'cancelled'
            job.result = result or ''
            db.session.commit()
            logger.info('job %s cancelled', job.id)
            _notify_job_result(job, f'定时任务 #{job.id}({job.scope}) 已停止')
            return
        job.status = 'done'
        job.result = result or ''
        job.progress = 100
        db.session.commit()
        logger.info('job %s done', job.id)
        _notify_job_result(job, f'定时任务 #{job.id}({job.scope}) 执行完成')
    except Exception as e:
        job.finished_at = cn_now()
        job.status = 'failed'
        job.error = str(e)
        db.session.commit()
        logger.exception('job %s error', job.id)
        _notify_job_result(job, f'定时任务 #{job.id}({job.scope}) 执行失败: {e}')


def _claim():
    # 单实例:取最早的 queued 作业
    job = NoteJob.query.filter_by(status='queued').order_by(
        NoteJob.created_at, NoteJob.id).first()
    if job:
        job.status = 'running'
        job.started_at = cn_now()
        db.session.commit()
    return job


RECOVER_AFTER_MINUTES = int(os.environ.get('JOB_RECOVER_MINUTES', '20'))


def _recover_stale():
    """把因进程突然退出而长期无心跳的 running 作业恢复为 queued,实现续跑。"""
    cutoff = cn_now() - timedelta(minutes=RECOVER_AFTER_MINUTES)
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
                           created_by=None, created_at=cn_now()))
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
    if not _has_cleanup_work():
        return
    db.session.add(NoteJob(scope='cleanup', status='queued', trigger='auto',
                           created_by=None, created_at=cn_now()))
    db.session.commit()
    logger.info('入队本周自动清理(黑名单字/操作日志/邮件/任务记录)')


def _enqueue_auto_backup(now):
    """每周自动备份(默认周一 03:00 本地时间),时间窗 5 分钟,7 天内不重复。"""
    if get_job_setting('job_backup_enabled', '1') != '1':
        return
    wd = int(get_job_setting('job_backup_weekday', '1'))
    hr = int(get_job_setting('job_backup_hour', '3'))
    mm = int(get_job_setting('job_backup_minute', '0'))
    if (wd >= 0 and now.weekday() != wd) or now.hour != hr:
        return
    if not (mm <= now.minute < mm + 5):
        return
    since = now - timedelta(days=7)
    if db.session.query(NoteJob.id).filter(
            NoteJob.trigger == 'auto', NoteJob.scope == 'backup',
            NoteJob.created_at >= since).first():
        return
    db.session.add(NoteJob(scope='backup', status='queued', trigger='auto',
                           created_by=None, created_at=now))
    db.session.commit()
    logger.info('入队每周自动备份待办')


def main():
    with app.app_context():
        logger.info('job_worker started, interval=%ss 触发器=todo', INTERVAL)
    current_sleep = 1  # 空转退避: 1, 2, 4, 8, 16, 30 秒封顶
    while True:
        try:
            with app.app_context():
                now = cn_now()
                _enqueue_auto(now)
                _enqueue_auto_cleanup(now)
                _enqueue_auto_backup(cn_now())
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