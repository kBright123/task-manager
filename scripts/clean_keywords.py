#!/usr/bin/env python3

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

"""清理知识库/随手记中识别出的黑名单字样(如机构名:邮储银行/邮储/邮政)。

默认关键字来自 knowledge.KB_TAG_BLACKLIST(环境变量 KB_TAG_BLACKLIST,
逗号/分号分隔,默认 邮储银行,邮储,邮政)。处理范围:
  - 主库(tasks.db): 所有文本列中的关键字字面删除;标签列(kb_point.tags /
    note.tags)中命中关键字的标签整条移除;搜索/问答缓存(kb_history / kb_cache)
    中命中关键字的记录删除。
  - 长词优先替换,避免子串残留(如先删"邮储银行"再删"邮储")。

用法:
  python scripts/clean_keywords.py                # 直接清理
  python scripts/clean_keywords.py --dry-run      # 仅预览将受影响的行
  python scripts/clean_keywords.py --terms "A,公司B" --db /path/tasks.db

注意:
  - SochDB 向量库中的文本不会随本脚本同步重建;若清理后需要向量检索一致,
    可对相关文档重新执行识别(重新嵌入)。
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kb.knowledge import (DB_PATH, KB_CACHE_PATH, KB_TAG_BLACKLIST,
                       clean_blacklist_keywords)

DEFAULT_DB = DB_PATH
DEFAULT_CACHE_DB = KB_CACHE_PATH


def main():
    ap = argparse.ArgumentParser(description='清理知识库/随手记中的黑名单字样')
    ap.add_argument('--db', default=DEFAULT_DB, help='主库路径')
    ap.add_argument('--cache-db', default=DEFAULT_CACHE_DB, help='缓存库路径')
    ap.add_argument('--terms', default='',
                    help='要清理的关键字,逗号/分号分隔(默认 KB_TAG_BLACKLIST)')
    ap.add_argument('--dry-run', action='store_true', help='仅预览,不写库')
    args = ap.parse_args()

    if args.terms:
        terms = [t.strip() for t in re.split(r'[，,;；]+', args.terms)
                 if t.strip()]
    else:
        terms = KB_TAG_BLACKLIST
    if not terms:
        print('未指定有效关键字', file=sys.stderr)
        return 1
    # 长词优先,避免子串残留
    terms = sorted(set(terms), key=len, reverse=True)
    mode = '预览(dry-run)' if args.dry_run else '清理'
    print(f'== 关键字清理({mode}) ==')
    print(f'关键字: {", ".join(terms)}')
    print(f'主库: {args.db}')

    report = clean_blacklist_keywords(terms, args.dry_run,
                                      db_path=args.db, cache_path=args.cache_db)
    total = sum(n for _, n in report)
    print(f'受影响: {total} 处')
    for name, n in report:
        print(f'  {name}: {n} 行')
    print('(dry-run,未写入)' if args.dry_run else '完成。')
    if not args.dry_run:
        print('提示:如知识库向量检索(SochDB)中的文档文本含这些字样,'
              '需对相关文档重新识别以重建向量。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
