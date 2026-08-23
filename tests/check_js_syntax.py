# -*- coding: utf-8 -*-
"""模板内联 JS 语法校验(quickjs new Function, 不执行代码)."""
import re
import sys

import quickjs


def strip(t):
    t = re.sub(r'\{\{.*?\}\}', '0', t, flags=re.S)
    t = re.sub(r'\{%.*?%\}', '', t, flags=re.S)
    return t


def check(files):
    ok = True
    for f in files:
        html = strip(open(f).read())
        blocks = re.findall(
            r'<script(?![^>]*src=)[^>]*>(.*?)</script>', html,
            flags=re.S | re.I)
        for i, b in enumerate(blocks):
            try:
                # 仅编译不执行: 包一层立即函数表达式(不调用)
                quickjs.Context().eval('(function(){\n' + b + '\n})')
            except Exception as e:
                ok = False
                print(f'FAIL {f} block#{i}: {str(e)[:160]}')
        print(f'{f}: {len(blocks)} blocks')
    print('== JS syntax:', 'ALL OK' if ok else 'ERRORS ==')
    return ok


if __name__ == '__main__':
    files = sys.argv[1:] or [
        'templates/base.html', 'templates/dashboard.html',
        'templates/tasks.html', 'templates/notes.html',
        'templates/profile.html', 'templates/task_detail.html',
        'templates/notifications.html']
    sys.exit(0 if check(files) else 1)
