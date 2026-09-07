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
"""数据备份/恢复(每日定时任务 + 后台手动)。

- 备份源:/app/instance(tasks.db + kb_data + notes + uploads)
- 备份目标:项目目录 /app/backups(bind-mount 到宿主机 ./backups,容器重建不丢失)
- tasks.db / cache.db 使用 SQLite 在线备份(online backup)保证一致性快照;
  notes / uploads / kb.soch 为普通文件拷贝。
- 恢复:从备份 tar.gz 恢复,恢复前自动对当前数据做一次安全备份;
  tasks.db 采用在线备份写入同一文件(不换 inode,各进程立即生效),并失效缓存。
"""
import logging
import os
import shutil
import sqlite3
import stat
import tarfile
import tempfile
from datetime import datetime

logger = logging.getLogger('backup')

_ROOT = os.path.dirname(os.path.abspath(__file__))
INSTANCE = os.environ.get('INSTANCE_DIR') or os.path.join(_ROOT, 'instance')
BACKUP_DIR = os.environ.get('BACKUP_DIR') or os.path.join(_ROOT, 'backups')

_WAL_SUFFIXES = ('-wal', '-shm', '-journal')


def backup_dir():
    return BACKUP_DIR


def _snapshot_sqlite(src, dst):
    """用 SQLite 在线备份接口复制一份一致快照(src 为活动库,dst 为输出文件)。"""
    src_conn = sqlite3.connect(src)
    dst_conn = sqlite3.connect(dst)
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()


def _is_special(path):
    """判断是否为 socket/FIFO 等无法备份的特殊文件。"""
    try:
        mode = os.lstat(path).st_mode
        return not (stat.S_ISREG(mode) or stat.S_ISDIR(mode) or stat.S_ISLNK(mode))
    except OSError:
        return True


def _ignore_special(directory, names):
    """copytree 的 ignore 回调:跳过 socket(如 sochdb.sock)等特殊文件。"""
    return [n for n in names if _is_special(os.path.join(directory, n))]


def _copy_dir(src, dst):
    if os.path.isdir(src):
        shutil.copytree(src, dst, dirs_exist_ok=True,
                        ignore=_ignore_special)
    else:
        os.makedirs(dst, exist_ok=True)


def create_backup():
    """创建一致快照 backups/backup-<时间戳>.tar.gz。

    返回 (文件名, 字节数, 错误信息或 None)。
    """
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        name = 'backup-%s.tar.gz' % datetime.now().strftime('%Y%m%d-%H%M%S')
        path = os.path.join(BACKUP_DIR, name)
        with tempfile.TemporaryDirectory() as tmp:
            dst = os.path.join(tmp, 'instance')
            os.makedirs(dst)
            _snapshot_sqlite(os.path.join(INSTANCE, 'tasks.db'),
                             os.path.join(dst, 'tasks.db'))
            kdir = os.path.join(dst, 'kb_data')
            os.makedirs(kdir, exist_ok=True)
            cache_src = os.path.join(INSTANCE, 'kb_data', 'cache.db')
            if os.path.isfile(cache_src):
                _snapshot_sqlite(cache_src, os.path.join(kdir, 'cache.db'))
            soch = os.path.join(INSTANCE, 'kb_data', 'kb.soch')
            if os.path.isdir(soch):
                _copy_dir(soch, os.path.join(kdir, 'kb.soch'))
            _copy_dir(os.path.join(INSTANCE, 'notes'),
                      os.path.join(dst, 'notes'))
            _copy_dir(os.path.join(INSTANCE, 'uploads'),
                      os.path.join(dst, 'uploads'))
            with tarfile.open(path, 'w:gz') as t:
                t.add(dst, arcname='instance')
        return name, os.path.getsize(path), None
    except Exception as e:
        logger.exception('create_backup failed')
        return '', 0, str(e)


def list_backups():
    """列出 backups/ 下的备份文件(按创建时间倒序)。"""
    out = []
    if not os.path.isdir(BACKUP_DIR):
        return out
    for f in sorted(os.listdir(BACKUP_DIR)):
        if f.startswith('backup-') and f.endswith('.tar.gz'):
            p = os.path.join(BACKUP_DIR, f)
            try:
                out.append({
                    'name': f,
                    'path': p,
                    'size': os.path.getsize(p),
                    'created_at': datetime.fromtimestamp(os.path.getmtime(p)),
                })
            except OSError:
                continue
    return sorted(out, key=lambda b: b['created_at'], reverse=True)


def delete_backup(name):
    if not (name.startswith('backup-') and name.endswith('.tar.gz')):
        return False
    p = os.path.join(BACKUP_DIR, name)
    if os.path.isfile(p):
        os.remove(p)
        return True
    return False


def prune_backups(keep=14):
    """按保留数量清理过期备份,返回被删除的文件名列表。"""
    removed = []
    files = sorted(list_backups(), key=lambda b: b['name'])
    for b in files[:-max(1, int(keep))]:
        try:
            os.remove(b['path'])
            removed.append(b['name'])
        except OSError:
            pass
    return removed


def _restore_sqlite(src, dst):
    """把备份库 src 在线写回活动库 dst(覆盖内容,保持同一 inode)。"""
    s = sqlite3.connect(src)
    d = sqlite3.connect(dst, timeout=30)
    try:
        d.execute('PRAGMA busy_timeout=30000')
        s.backup(d)
    finally:
        d.close()
        s.close()


def _replace_dir(src, dst):
    parent = os.path.dirname(dst)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if os.path.isdir(dst):
        shutil.rmtree(dst, ignore_errors=True)
    if os.path.isdir(src):
        shutil.copytree(src, dst)


def restore_backup(name):
    """从 backups/<name>.tar.gz 恢复 instance。

    恢复前自动对当前数据做一次安全备份(backup-pre-restore-*.tar.gz)。
    返回 (是否成功, 报告文本)。
    """
    if not (name.startswith('backup-') and name.endswith('.tar.gz')):
        return False, '非法备份文件名'
    path = os.path.join(BACKUP_DIR, name)
    if not os.path.isfile(path):
        return False, '备份文件不存在: %s' % name
    try:
        safe_name, _size, _err = create_backup()
        if not safe_name:
            return False, '恢复前安全备份失败,已中止恢复'
        with tempfile.TemporaryDirectory() as tmp:
            with tarfile.open(path, 'r:gz') as t:
                for m in t.getmembers():
                    _p = os.path.realpath(os.path.join(tmp, m.name))
                    if not _p.startswith(os.path.realpath(tmp) + os.sep):
                        return False, '备份包存在非法路径(path traversal),已中止恢复(当前数据安全备份: %s)' % safe_name
                t.extractall(tmp, filter='data')
            src = os.path.join(tmp, 'instance')
            if not os.path.isdir(src):
                return False, '备份内容不完整,已中止恢复(当前数据安全备份: %s)' % safe_name
            if os.path.isfile(os.path.join(src, 'tasks.db')):
                _restore_sqlite(os.path.join(src, 'tasks.db'),
                                os.path.join(INSTANCE, 'tasks.db'))
            cache = os.path.join(src, 'kb_data', 'cache.db')
            if os.path.isfile(cache):
                try:
                    _restore_sqlite(cache,
                                    os.path.join(INSTANCE, 'kb_data',
                                                 'cache.db'))
                except Exception as e:
                    logger.warning('cache.db restore skipped: %s', e)
            _replace_dir(os.path.join(src, 'notes'),
                         os.path.join(INSTANCE, 'notes'))
            _replace_dir(os.path.join(src, 'uploads'),
                         os.path.join(INSTANCE, 'uploads'))
            soch = os.path.join(src, 'kb_data', 'kb.soch')
            if os.path.isdir(soch):
                _replace_dir(soch, os.path.join(INSTANCE, 'kb_data',
                                                'kb.soch'))
        try:
            from kb.knowledge import _bump_data_version
            _bump_data_version()
        except Exception:
            pass
        try:
            from app import db
            db.engine.dispose()
        except Exception:
            pass
        return True, ('已从 %s 恢复(恢复前自动安全备份: %s)。'
                      '建议重启容器使所有进程完全生效。' % (name, safe_name))
    except Exception as e:
        logger.exception('restore_backup failed')
        return False, '恢复失败: %s' % e
