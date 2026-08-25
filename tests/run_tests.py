# -*- coding: utf-8 -*-
"""零依赖测试运行器: python tests/run_tests.py (无需 pytest)."""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import conftest  # noqa: E402  提供 client 夹具(手动注入)


def main():
    import test_pages
    import test_parse
    import test_astro
    import test_calendar_feed

    ok = True
    client = conftest.make_client()

    for mod in (test_parse, test_pages, test_astro, test_calendar_feed):
        for name in sorted(dir(mod)):
            if not name.startswith('test_'):
                continue
            fn = getattr(mod, name)
            try:
                if name == 'test_jionlp_span_future_start':
                    # 该用例内部自带降级守卫, 无需夹具
                    fn()
                elif fn.__code__.co_argcount:
                    fn(client)
                else:
                    fn()
                print(f'PASS {mod.__name__}.{name}')
            except Exception:
                ok = False
                print(f'FAIL {mod.__name__}.{name}')
                traceback.print_exc(limit=3)
    print('== 结果:', 'ALL PASS' if ok else 'FAILED ==')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
