#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取绘本配图 (LoremFlickr 标签图库) 到本地 static/img/books/。

用法:
    source venv/bin/activate
    python scripts/fetch_book_images.py            # 下载所有缺图页面
    python scripts/fetch_book_images.py <book_id>  # 只抓某一本

设计:
    - 每页的关键词 `k` 直接取自 static/js/edu/edu-books.js 中该页的场景主题
      (从页面剧情/台词抽象出的英文单词), 保证图片与剧情相关;
    - 用 ?lock=<随机盐值> 命中 LoremFlickr 缓存, 同页重抓得到同一张图;
    - 统一转码为 JPEG (800x600, quality=86) 存入 static/img/books/<id>/pNN.jpg;
    - 占位图(auto defaultImage)视为失败并换锁重试; 全部失败则留空,
      前端自动回退本页 emoji 插画 —— 绝不回退到与剧情无关的图;
    - 幂等: 已有图片(size>3KB)跳过, 可加 --force 覆盖。

依赖: requests>=2.31, pillow>=10 (本项目 requirements 已包含)。
"""
import argparse
import hashlib
import io
import os
import random
import re
import sys
import time

try:
    import requests
    from PIL import Image
except ImportError as e:  # pragma: no cover
    sys.exit("缺少依赖: %s (请先安装 requirements.txt)" % e)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "static", "img", "books")
JS_PATH = os.path.join(ROOT, "static", "js", "edu", "edu-books.js")
UA = "TaskManagerEduBooks/1.0 (self-hosted education app)"
HEADERS = {"User-Agent": UA}
SLEEP = 0.5  # 请求间隔

# 绘本元数据 (页数须与 JS 一致)
BOOKS = [
    {"id": "gui-tu-sai-pao", "title": "龟兔赛跑", "pages": 18},
    {"id": "lang-lai-le", "title": "狼来了", "pages": 18},
    {"id": "wu-ya-he-shui", "title": "乌鸦喝水", "pages": 13},
    {"id": "san-zhi-xiao-zhu", "title": "三只小猪", "pages": 19},
    {"id": "xiao-hong-mao", "title": "小红帽", "pages": 16},
    {"id": "chou-xiao-ya", "title": "丑小鸭", "pages": 17},
    {"id": "hou-zi-lao-yue", "title": "猴子捞月", "pages": 16},
    {"id": "shou-zhu-dai-tu", "title": "守株待兔", "pages": 15},
    {"id": "si-ma-guang-za-gang", "title": "司马光砸缸", "pages": 16},
    {"id": "kong-rong-rang-li", "title": "孔融让梨", "pages": 15},
    {"id": "xiao-ma-guo-he", "title": "小马过河", "pages": 16},
    {"id": "cao-chong-cheng-xiang", "title": "曹冲称象", "pages": 15},
]

# 每本兜底关键词 (仅当该页自身主题词失败时, 退而面向整本故事的常见意象)
MOTIFS = {
    "gui-tu-sai-pao": ["hare", "turtle", "race"],
    "lang-lai-le": ["wolf", "sheep", "shepherd"],
    "wu-ya-he-shui": ["crow", "water", "stone"],
    "san-zhi-xiao-zhu": ["pig", "wolf", "brick"],
    "xiao-hong-mao": ["girl", "wolf", "forest"],
    "chou-xiao-ya": ["duckling", "swan", "duck"],
    "hou-zi-lao-yue": ["monkey", "moon", "well"],
    "shou-zhu-dai-tu": ["farmer", "rabbit", "field"],
    "si-ma-guang-za-gang": ["boy", "water", "stone"],
    "kong-rong-rang-li": ["pear", "boy", "family"],
    "xiao-ma-guo-he": ["horse", "river", "cow"],
    "cao-chong-cheng-xiang": ["elephant", "boat", "elephant"],
}


def load_page_keywords():
    """从 edu-books.js 中解析每页共性关键词 { book_id: [k, ...] }"""
    src = open(JS_PATH, encoding="utf-8").read()
    res = {}
    for b in BOOKS:
        block = re.search(r"id: '" + b["id"] + r"'.*?pages: \[(.*?)\n      \]", src, re.S)
        if not block:
            sys.exit("JS 中找不到绘本: %s" % b["id"])
        ks = re.findall(r"\bk: '([^']*)'", block.group(1))
        if len(ks) != b["pages"]:
            sys.exit("%s 关键词数量 %d != 页数 %d (请检查 edu-books.js)" % (b["id"], len(ks), b["pages"]))
        res[b["id"]] = ks
    return res


def md5hex(data):
    return hashlib.md5(data).hexdigest()


def hashlib_md5(path):
    return md5hex(open(path, "rb").read())


def lorem_url(tag, lock):
    return "https://loremflickr.com/800/600/%s?lock=%d" % (tag, lock)


def fetch_image(url):
    """返回图片字节; 占位图/失败抛异常."""
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    if 'defaultImage' in (r.url or ''):
        raise RuntimeError("LoremFlickr 返回 defaultImage 占位图")
    return r.content


def save_as_jpeg(data, path):
    img = Image.open(io.BytesIO(data))
    if img.mode in ("RGBA", "LA", "P"):
        if img.mode == "P":
            img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    if img.width > 800:
        img = img.resize((800, int(img.height * 800 / img.width)), Image.LANCZOS)
    img.save(path, "JPEG", quality=86, optimize=True)


def fetch_book(book, ks, force=False):
    book_dir = os.path.join(OUT_DIR, book["id"])
    os.makedirs(book_dir, exist_ok=True)
    salt = sum(ord(c) for c in book["id"])

    def book_hashes():
        h = set()
        for f in os.listdir(book_dir):
            if f.startswith("p") and f.endswith(".jpg"):
                p = os.path.join(book_dir, f)
                if os.path.getsize(p) > 3_000:
                    h.add(hashlib_md5(p))
        return h

    missing = []
    for i in range(book["pages"]):
        fname = "p%02d.jpg" % (i + 1)
        path = os.path.join(book_dir, fname)
        if not (os.path.exists(path) and os.path.getsize(path) > 3_000) or force:
            missing.append(i)
    if not missing:
        print("[ ] %s 已全部有图 (%d页)" % (book["title"], book["pages"]))
        return
    print("[*] %s 缺 %d 页, 正在抓取..." % (book["title"], len(missing)))
    used = book_hashes()
    for i in missing:
        primary = ks[i]
        motifs = [m for m in MOTIFS[book["id"]] if m != primary]
        path = os.path.join(book_dir, "p%02d.jpg" % (i + 1))
        attempts = [primary] * 6 + motifs * 4 + [primary] * 2
        got = False
        for k, tag in enumerate(attempts):
            lock = (i + 1) * 97 + salt + k * 131 + random.randint(0, 99)
            try:
                data = fetch_image(lorem_url(tag, lock))
                digest = md5hex(data)
                if digest in used:
                    time.sleep(SLEEP)
                    continue  # 与本书已有图片重复, 换一张
                save_as_jpeg(data, path)
                used.add(digest)
                got = True
                print("    + p%02d.jpg  <-  %s" % (i + 1, tag))
                break
            except Exception:
                time.sleep(SLEEP)
        if not got:
            print("    - p%02d (k=%s) 失败, 留空以回退 emoji" % (i + 1, primary))
        time.sleep(SLEEP)


def write_manifest():
    import json
    man = {}
    for b in BOOKS:
        d = os.path.join(OUT_DIR, b["id"])
        pages = [f for i in range(b["pages"])
                 for f in [("p%02d.jpg" % (i + 1))]
                 if os.path.exists(os.path.join(d, f)) and os.path.getsize(os.path.join(d, f)) > 3_000]
        man[b["id"]] = {"title": b["title"], "pages": pages}
    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
    print("manifest.json 已更新 -> static/img/books/manifest.json")


def main():
    ap = argparse.ArgumentParser(description="按剧情关键词从 LoremFlickr 抓取绘本配图")
    ap.add_argument("book_id", nargs="?", default=None, help="只抓指定绘本 id")
    ap.add_argument("--force", action="store_true", help="忽略已有文件重新抓取")
    args = ap.parse_args()

    ks = load_page_keywords()
    targets = [b for b in BOOKS if not args.book_id or b["id"] == args.book_id]
    if not targets:
        sys.exit("未知 book_id: %s" % args.book_id)
    for b in targets:
        fetch_book(b, ks[b["id"]], force=args.force)
    write_manifest()


if __name__ == "__main__":
    main()