#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地程序化生成绘本配图 (Pillow) 到 static/img/books/。

用法:
    source venv/bin/activate
    python scripts/generate_book_images.py           # 生成全部绘本页面
    python scripts/generate_book_images.py <book_id> # 只生成某一本
    python scripts/generate_book_images.py --force   # 覆盖已有图片

设计:
    - 每页图片直接由剧情构造: 背景主题(bg) + 场景主元素(ems 第一个可绘制词元,
      否则用该页 k 关键词兜底), 保证图片与剧情一一对应;
    - 离线、确定性 (同一页重跑结果一致)、无任何网络/版权依赖;
    - 输出 800x600 JPEG 到 static/img/books/<id>/pNN.jpg。

依赖: pillow>=10 (本项目 requirements 已包含)。
"""
import argparse
import math
import os
import random
import re
import sys

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "static", "img", "books")
JS_PATH = os.path.join(ROOT, "static", "js", "edu", "edu-books.js")
W, H = 800, 600

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

# theme -> 顶部/底部渐变色
THEMES = {
    "meadow": ("#aee6ff", "#d9f6c2"),
    "sunny":  ("#8fd6ff", "#fff1b8"),
    "forest": ("#bfe6cf", "#8fcf9f"),
    "night":  ("#1d2c4f", "#41528f"),
    "river":  ("#96d2ff", "#d9f1ff"),
    "farm":   ("#aee1ff", "#f7e6ab"),
    "rose":   ("#ffe4ec", "#ffd0dd"),
    "dawn":   ("#ffd9a0", "#ffefd0"),
    "dusk":   ("#ff9e6d", "#ffd3a3"),
    "home":   ("#ffe9c9", "#fff6e2"),
    "sky":    ("#a3ddff", "#d9f1ff"),
    "snow":   ("#dfeaf5", "#f6faff"),
}

PAL_SHADOW = (60, 50, 40, 70)


def hexc(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def gradient(img, top, bottom):
    d = ImageDraw.Draw(img)
    t, b = hexc(top), hexc(bottom)
    for y in range(H):
        k = y / H
        col = tuple(int(t[i] + (b[i] - t[i]) * k) for i in range(3))
        d.line([(0, y), (W, y)], fill=col)


def soft_ellipse(base, x, y, rx, ry, fill, blur=6):
    ov = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    d.ellipse([x - rx, y - ry, x + rx, y + ry], fill=fill)
    ov = ov.filter(ImageFilter.GaussianBlur(blur))
    base.alpha_composite(ov)


def pxl(d, x, y, rx, ry, fill, outline=None, width=2):
    d.ellipse([x - rx, y - ry, x + rx, y + ry], fill=fill, outline=outline, width=width)


def rrt(d, box, r, fill, outline=None, width=2):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def eye(d, x, y, s=1.0, color="#20242e"):
    """可爱眼睛 (黑珠+高光)"""
    r = 3.6 * s
    d.ellipse([x - r, y - r, x + r, y + r], fill=color)
    d.ellipse([x - r * 0.45, y - r * 0.5, x - r * 0.1, y - r * 0.1], fill=(255, 255, 255, 235))


def mouth(d, x, y, s=1.0, w=3, color="#5b3428"):
    d.arc([x - 7 * s, y - 4 * s, x + 7 * s, y + 6 * s], start=20, end=160, fill=color, width=w)


def blush(base, x, y, s=1.0, color=(255, 140, 120, 90)):
    soft_ellipse(base, x, y, 8 * s, 5 * s, color)


# --------------------------------------------------------------------------
# 环境背景
# --------------------------------------------------------------------------
def draw_env(base, theme, seed):
    rng = random.Random(seed)
    d = ImageDraw.Draw(base)

    if theme in ("night", "dusk"):
        # 月亮
        mxx, myy = 640, 110
        soft_ellipse(base, mxx, myy, 46, 46, (255, 235, 160, 210), 12)
        pxl(d, mxx, myy, 34, 34, "#ffe9a6")
        pxl(d, mxx + 10, myy - 6, 7, 7, "#f2d98f")
        pxl(d, mxx - 8, myy + 10, 5, 5, "#f2d98f")
        # 星星
        for _ in range(120):
            x = rng.randint(10, W - 10); y = rng.randint(8, int(H * 0.45))
            r = rng.choice([2, 2, 3])
            d.point((x, y), fill=(255, 255, 230, 255))
    elif theme in ("snow",):
        for _ in range(90):
            x = rng.randint(5, W - 5); y = rng.randint(5, H - 5)
            r = rng.randint(2, 4)
            d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, 220))
    elif theme in ("rain", ):
        pass

    if theme not in ("night", "dusk", "snow", "dawn"):
        # 太阳
        sx, sy = 690, 100
        soft_ellipse(base, sx, sy, 55, 55, (255, 214, 90, 90), 16)
        pxl(d, sx, sy, 34, 34, "#ffd94a")
        pxl(d, sx, sy, 24, 24, "#ffed8f")

    if theme in ("dawn", "dusk"):
        # 地平线日出大太阳 + 暖光晕
        cx0, cy0 = W // 2, 430
        soft_ellipse(base, cx0 + 60, 300, 230, 130, (255, 190, 120, 90), 20)
        soft_ellipse(base, cx0, 440, 130, 130, (255, 190, 120, 110), 22)
        pxl(d, cx0, 420, 96, 96, (255, 180, 90) if theme == "dusk" else "#ffc95e")
        pxl(d, cx0, 420, 80, 80, (255, 205, 120) if theme == "dusk" else "#ffde80")
        for y, w, a in [(470, 2, 170), (483, 2, 120), (496, 2, 80)]:
            d.line([(0, y), (W, y)], fill=(255, 220, 150, a), width=w)
        if theme == "dusk":
            for _ in range(60):
                x = rng.randint(10, W - 10); y = rng.randint(8, int(H * 0.4))
                d.point((x, y), fill=(255, 255, 230, 255))

    # 云
    for _ in range(rng.randint(1, 3)):
        cx = rng.randint(60, W - 120); cy = rng.randint(60, 180)
        for (ox, oy, rr) in [(0, 0, 26), (28, -8, 20), (-28, -6, 18), (14, 12, 18), (-14, 12, 18)]:
            soft_ellipse(base, cx + ox, cy + oy, rr, rr, (255, 255, 255, 120), 8)
        for (ox, oy, rr) in [(0, 0, 24), (26, -6, 18), (-26, -4, 16), (14, 10, 16), (-14, 10, 16)]:
            pxl(d, cx + ox, cy + oy, rr, rr, "#ffffff")

    # 地面/山/水
    if theme in ("meadow", "sunny", "farm"):
        for i, (hy, basey, col) in enumerate([(0.62, 600, "#86c46a"), (0.78, 600, "#a5d97f"),
                                              (0.90, 600, "#cde9a0")]):
            top = int(H * (hy - (0.10 if i else 0.16)))
            d.polygon([(0, 600), (0, basey), (0, top), (W, top),
                       (W, basey), (W, 600)],
                      fill=col)
        # 草
        for _ in range(40):
            x = rng.randint(0, W); y = rng.randint(int(H * 0.68), H - 20)
            d.line([(x, y), (x + rng.choice([-3, 3]), y - 8)], fill=(80, 150, 70, 200), width=2)
    elif theme in ("forest",):
        for i, (hy, col) in enumerate([(0.74, "#6fae5e"), (0.88, "#88c571")]):
            top = int(H * hy)
            d.polygon([(0, 600), (0, top), (W, top), (W, 600)], fill=col)
        for x in range(30, W, 78):
            tr = rng.randint(34, 52)
            soft_ellipse(base, x, 560, tr, 70, (40, 90, 50, 80), 10)
    elif theme in ("river", "sky"):
        # 前景水面
        d.polygon([(0, 520), (0, 600), (W, 600), (W, 520)], fill="#6fc3ef")
        for i in range(3):
            y = 545 + i * 22
            for x in range(0, W, 60):
                d.arc([x, y, x + 30, y + 14], 200, 320, fill=(255, 255, 255, 160), width=2)
    elif theme in ("snow",):
        for i, (hy, col) in enumerate([(0.72, "#dbe9f7"), (0.86, "#e9f3fc")]):
            top = int(H * hy)
            d.polygon([(0, 600), (0, top), (W, top), (W, 600)], fill=col)
        for _ in range(80):
            x = rng.randint(0, W); y = rng.randint(int(H * 0.7), H - 20)
            r = rng.randint(2, 5)
            d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, 200))
    elif theme in ("farm",):
        # 栅栏
        for x in range(40, W, 46):
            rrt(d, [x, 480 - 60, x + 10, 560 - 60], 4, "#a5763f")
        rrt(d, [30, 500 - 60, W - 30, 508 - 60], 3, "#c89b60")
        rrt(d, [30, 530 - 60, W - 30, 538 - 60], 3, "#c89b60")
    elif theme in ("home",):
        # 室内: 墙裙 + 地板
        d.rectangle([0, 0, W, H], fill="#ffe9c9")
        rrt(d, [0, int(H * 0.78), W, H], 0, "#e0b57f")
        rrt(d, [560, 120, 760, 420], 18, "#bfd6ff", outline="#8fb4e8", width=6)
        d.line([(660, 120), (660, 420)], fill="#8fb4e8", width=6)
        d.line([(560, 270), (760, 270)], fill="#8fb4e8", width=6)
    elif theme in ("night", "dusk"):
        for i, (hy, col) in enumerate([(0.78, "#2f3e63"), (0.9, "#1d2c4f")]):
            top = int(H * hy)
            d.polygon([(0, 600), (0, top), (W, top), (W, 600)], fill=col)


def draw_tree(base, x, basey, s, leaf, trunk="#8a5a35"):
    d = ImageDraw.Draw(base)
    rrt(d, [x - 9 * s, basey - 60 * s, x + 9 * s, basey], 6, trunk)
    soft_ellipse(base, x, basey - 78 * s, 55 * s, 52 * s, (240, 255, 235, 60), 12)
    pxl(d, x, basey - 80 * s, 46 * s, 44 * s, leaf)
    pxl(d, x - 28 * s, basey - 86 * s, 20 * s, 18 * s, leaf)
    pxl(d, x + 28 * s, basey - 86 * s, 20 * s, 18 * s, leaf)


def draw_flower(base, x, y, s, petal="#ff8fb1", core="#ffd94a"):
    d = ImageDraw.Draw(base)
    for a in range(0, 360, 60):
        px = x + math.cos(math.radians(a)) * 9 * s
        py = y + math.sin(math.radians(a)) * 9 * s
        d.ellipse([px - 8 * s, py - 8 * s, px + 8 * s, py + 8 * s], fill=petal)
    d.ellipse([x - 7 * s, y - 7 * s, x + 7 * s, y + 7 * s], fill=core)


# --------------------------------------------------------------------------
# 角色/物体 (扁平可爱风)
# --------------------------------------------------------------------------
def draw_character(base, token, cx, basey, s=1.0):
    d = ImageDraw.Draw(base)
    if token in ("🐢", "turtle", "tortoise"):
        # 乌龟
        body = (0, int(basey - 48 * s))
        soft_ellipse(base, body[0] - 6 * s, body[1] + 20 * s, 44 * s, 10 * s, PAL_SHADOW, 8)
        # 腿
        for dx in (-40, -20, 20, 40):
            pxl(d, body[0] + dx * s, body[1] + 30 * s, 8 * s, 12 * s, "#79b14d")
        # 壳
        soft_ellipse(base, body[0], body[1], 46 * s, 40 * s, (245, 255, 235, 80), 10)
        pxl(d, body[0], body[1], 44 * s, 38 * s, "#8fd15a")
        for a in range(0, 360, 45):
            px = body[0] + math.cos(math.radians(a)) * 30 * s
            py = body[1] + math.sin(math.radians(a)) * 26 * s
            d.polygon([(px - 10 * s, py - 7 * s), (px + 10 * s, py - 7 * s), (px, py + 8 * s)],
                      fill=(110, 175, 78, 255))
        # 头
        pxl(d, body[0], body[1] - 50 * s, 20 * s, 16 * s, "#79b14d")
        hx = body[0] + 8 * s
        eye(d, hx, body[1] - 52 * s, 0.8)
        mouth(d, hx + 6 * s, body[1] - 46 * s, 0.7)
    elif token in ("🐰", "rabbit", "hare"):
        cy = int(basey - 60 * s)
        soft_ellipse(base, cx, basey, 42 * s, 10 * s, PAL_SHADOW, 8)
        # 耳朵
        for ex in (-16, 16):
            d.rounded_rectangle([cx + ex * s - 9 * s, cy - 96 * s, cx + ex * s + 9 * s, cy - 20 * s],
                                10, fill="#f2efe9", outline="#c9bfb0", width=2)
            d.rounded_rectangle([cx + ex * s - 4 * s, cy - 92 * s, cx + ex * s + 4 * s, cy - 24 * s],
                                4, fill="#ffb7c5")
        # 身体
        pxl(d, cx, cy, 34 * s, 42 * s, "#f2efe9", outline="#c9bfb0", width=2)
        pxl(d, cx, cy - 44 * s, 24 * s, 22 * s, "#f2efe9", outline="#c9bfb0", width=2)
        eye(d, cx - 9 * s, cy - 46 * s)
        eye(d, cx + 9 * s, cy - 46 * s)
        mouth(d, cx, cy - 38 * s, 0.7)
        draw_tail(base, cx, cy, 26 * s, -1, "#ffffff")
    elif token in ("🐺", "wolf"):
        cy = int(basey - 58 * s)
        soft_ellipse(base, cx, basey, 44 * s, 10 * s, PAL_SHADOW, 8)
        for ex in (-18, 18):
            d.polygon([(cx + ex * s - 12 * s, cy - 84 * s), (cx + ex * s, cy - 48 * s),
                       (cx + ex * s + 12 * s, cy - 84 * s)], fill="#6b7280")
            d.polygon([(cx + ex * s - 6 * s, cy - 76 * s), (cx + ex * s, cy - 54 * s),
                       (cx + ex * s + 6 * s, cy - 76 * s)], fill="#9aa3b0")
        pxl(d, cx, cy, 40 * s, 44 * s, "#767f8e", outline="#565e6c", width=2)
        pxl(d, cx, cy - 42 * s, 26 * s, 26 * s, "#8b95a3", outline="#646c79", width=2)
        # 鼻子/嘴
        d.polygon([(cx - 8 * s, cy - 30 * s), (cx + 8 * s, cy - 30 * s), (cx, cy - 20 * s)], fill="#3a3f4a")
        eye(d, cx - 10 * s, cy - 40 * s)
        eye(d, cx + 10 * s, cy - 40 * s)
        draw_tail(base, cx, cy + 20 * s, 30, 1, "#767f8e")
    elif token in ("🐷", "pig"):
        cy = int(basey - 52 * s)
        soft_ellipse(base, cx, basey, 46 * s, 10 * s, PAL_SHADOW, 8)
        pxl(d, cx, cy, 40 * s, 38 * s, "#ffb3c1", outline="#f292a6", width=2)
        pxl(d, cx, cy - 36 * s, 26 * s, 24 * s, "#ffc0cc", outline="#f292a6", width=2)
        d.polygon([(cx - 10 * s, cy - 12 * s), (cx + 10 * s, cy - 12 * s), (cx, cy - 16 * s)], fill="#ff8ba0")
        eye(d, cx - 11 * s, cy - 34 * s)
        eye(d, cx + 11 * s, cy - 34 * s)
        mouth(d, cx, cy - 26 * s, 0.7)
        # 耳朵
        d.polygon([(cx - 26 * s, cy - 50 * s), (cx - 16 * s, cy - 66 * s), (cx - 8 * s, cy - 48 * s)], fill="#ffb3c1")
        d.polygon([(cx + 26 * s, cy - 50 * s), (cx + 16 * s, cy - 66 * s), (cx + 8 * s, cy - 48 * s)], fill="#ffb3c1")
        # 卷尾巴
        tx, ty = cx + 40 * s, cy + 32 * s
        d.arc([tx - 8, ty - 8, tx + 8, ty + 8], 90, 400, fill="#f292a6", width=3)
    elif token in ("🦆", "duck", "duckling", "🐤", "🐣", "chick"):
        yellow = "#ffd23f" if token in ("🐤", "🐣", "duckling", "chick") else "#ffd95c"
        cy = int(basey - 44 * s)
        soft_ellipse(base, cx, basey, 34 * s, 9 * s, PAL_SHADOW, 8)
        pxl(d, cx, cy + 6 * s, 30 * s, 26 * s, yellow)
        pxl(d, cx, cy - 24 * s, 20 * s, 22 * s, yellow)
        eye(d, cx + 8 * s, cy - 26 * s, 0.85)
        # 嘴
        d.polygon([(cx + 6 * s, cy - 16 * s), (cx + 26 * s, cy - 13 * s), (cx + 6 * s, cy - 8 * s)], fill="#ff9f1c")
        # 翅
        d.arc([cx - 30 * s, cy - 4 * s, cx - 6 * s, cy + 30 * s], 90, 270, fill="#f2b93a", width=8)
        draw_tail(base, cx, cy + 10 * s, 20, -1, yellow)
    elif token in ("🦢", "swan"):
        cy = int(basey - 60 * s)
        soft_ellipse(base, cx, basey, 48 * s, 10 * s, PAL_SHADOW, 8)
        pxl(d, cx, cy + 20 * s, 36 * s, 26 * s, "#ffffff", outline="#d9d4c9", width=2)
        # 长颈
        d.rounded_rectangle([cx - 8 * s, cy - 84 * s, cx + 8 * s, cy - 10 * s], 8, fill="#ffffff",
                            outline="#d9d4c9", width=2)
        pxl(d, cx, cy - 92 * s, 14 * s, 14 * s, "#ffffff", outline="#d9d4c9", width=2)
        d.polygon([(cx + 2 * s, cy - 90 * s), (cx + 24 * s, cy - 90 * s), (cx + 6 * s, cy - 82 * s)], fill="#ff9f1c")
        eye(d, cx - 2 * s, cy - 94 * s, 0.8)
        # 翅
        d.arc([cx - 36 * s, cy - 4 * s, cx - 4 * s, cy + 28 * s], 90, 280, fill="#f0ede4", width=9)
    elif token in ("🐔", "hen", "chicken"):
        cy = int(basey - 46 * s)
        pxl(d, cx, cy, 32 * s, 30 * s, "#fff3e0", outline="#e3c9a0", width=2)
        pxl(d, cx, cy - 26 * s, 18 * s, 18 * s, "#fff3e0", outline="#e3c9a0", width=2)
        # 鸡冠
        d.ellipse([cx - 12 * s, cy - 54 * s, cx - 6 * s, cy - 42 * s], fill="#ef5b6e")
        d.ellipse([cx - 2 * s, cy - 58 * s, cx + 6 * s, cy - 44 * s], fill="#ef5b6e")
        d.polygon([(cx + 14 * s, cy - 20 * s), (cx + 26 * s, cy - 16 * s), (cx + 12 * s, cy - 12 * s)], fill="#ff9f1c")
        eye(d, cx + 6 * s, cy - 26 * s, 0.8)
    elif token in ("🐦", "bird", "crow", "raven"):
        black = token in ("crow", "乌鸦", "raven")
        col = "#4b4f58" if black else "#7ec9f0"
        cy = int(basey - 46 * s)
        pxl(d, cx, cy, 22 * s, 18 * s, col)
        pxl(d, cx - 4 * s, cy - 18 * s, 14 * s, 14 * s, col)
        eye(d, cx - 8 * s, cy - 18 * s, 0.7, "#f2f4f7")
        d.polygon([(cx - 16 * s, cy - 12 * s), (cx - 30 * s, cy - 9 * s), (cx - 14 * s, cy - 6 * s)], fill="#f2a83a")
        # 翅
        d.arc([cx - 24 * s, cy - 2 * s, cx + 2 * s, cy + 16 * s], 100, 280, fill=col, width=7)
        for dx in (-2, 1, 4):
            d.polygon([(cx + dx * 2 * s, cy + 12 * s), (cx + dx * 2 * s - 3 * s, cy + 24 * s),
                       (cx + dx * 2 * s + 3 * s, cy + 24 * s)], fill="#f2a83a")
    elif token in ("🐒", "monkey"):
        cy = int(basey - 50 * s)
        soft_ellipse(base, cx, basey, 36 * s, 9 * s, PAL_SHADOW, 8)
        pxl(d, cx, cy, 34 * s, 40 * s, "#a2713e", outline="#7d5426", width=2)
        pxl(d, cx, cy - 38 * s, 24 * s, 22 * s, "#c8956a")
        eye(d, cx - 9 * s, cy - 38 * s)
        eye(d, cx + 9 * s, cy - 38 * s)
        mouth(d, cx, cy - 30 * s, 0.8)
        # 耳朵
        pxl(d, cx - 30 * s, cy - 30 * s, 9 * s, 11 * s, "#c8956a")
        pxl(d, cx + 30 * s, cy - 30 * s, 9 * s, 11 * s, "#c8956a")
        # 尾巴
        d.arc([cx + 28 * s, cy - 6 * s, cx + 52 * s, cy + 26 * s], 70, 260, fill="#7d5426", width=4)
    elif token in ("🐴", "horse"):
        cy = int(basey - 62 * s)
        soft_ellipse(base, cx, basey, 52 * s, 10 * s, PAL_SHADOW, 8)
        pxl(d, cx, cy, 40 * s, 42 * s, "#c98b4e", outline="#a06a33", width=2)
        pxl(d, cx, cy - 44 * s, 26 * s, 26 * s, "#c98b4e", outline="#a06a33", width=2)
        # 鬃毛
        d.polygon([(cx - 22 * s, cy - 58 * s), (cx - 34 * s, cy - 42 * s), (cx - 20 * s, cy - 34 * s),
                   (cx - 34 * s, cy - 18 * s), (cx - 22 * s, cy - 8 * s)], fill="#7a4a26")
        eye(d, cx + 10 * s, cy - 46 * s, 0.95)
        d.arc([cx + 18 * s, cy - 28 * s, cx + 40 * s, cy - 4 * s], 260, 90, fill="#a06a33", width=3)
        # 腿
        for dx in (-30, -12, 12, 30):
            rrt(d, [int(cx + dx * s - 6 * s), int(cy + 18 * s), int(cx + dx * s + 6 * s), int(basey)], 5,
                "#c98b4e", outline="#a06a33", width=2)
        draw_tail(base, cx, cy + 10 * s, 32, 1, "#7a4a26")
    elif token in ("🐂", "cow"):
        cy = int(basey - 56 * s)
        pxl(d, cx, cy, 42 * s, 38 * s, "#ffffff", outline="#cfc9bd", width=2)
        pxl(d, cx, cy - 34 * s, 24 * s, 26 * s, "#ffffff", outline="#cfc9bd", width=2)
        # 斑块
        d.ellipse([cx - 26 * s, cy - 30 * s, cx - 14 * s, cy - 16 * s], fill="#4b4f58")
        d.ellipse([cx + 16 * s, cy - 2 * s, cx + 26 * s, cy + 10 * s], fill="#4b4f58")
        d.ellipse([cx - 4 * s, cy + 18 * s, cx + 8 * s, cy + 28 * s], fill="#4b4f58")
        eye(d, cx - 9 * s, cy - 32 * s)
        eye(d, cx + 9 * s, cy - 32 * s)
        for ex in (-14, 14):
            d.polygon([(cx + ex * s - 5 * s, cy - 58 * s), (cx + ex * s + 5 * s, cy - 58 * s),
                       (cx + ex * s, cy - 46 * s)], fill="#cfc9bd")
        d.polygon([(cx - 6 * s, cy - 20 * s), (cx + 14 * s, cy - 16 * s), (cx - 6 * s, cy - 12 * s)], fill="#ff8ba0")
        for dx in (-32, -14, 14, 32):
            rrt(d, [int(cx + dx * s - 5 * s), int(cy + 18 * s), int(cx + dx * s + 5 * s), int(basey)], 4,
                "#ffffff", outline="#cfc9bd", width=2)
    elif token in ("🐑", "sheep"):
        cy = int(basey - 46 * s)
        soft_ellipse(base, cx, basey, 40 * s, 9 * s, PAL_SHADOW, 8)
        # 毛
        for (dx, dy, rr) in [(-18, -10, 16), (18, -10, 16), (0, 4, 20), (-24, 12, 14), (24, 12, 14), (0, -26, 14)]:
            pxl(d, cx + dx * s, cy + dy * s, rr * s, rr * s, "#fffaf0")
        pxl(d, cx, cy - 24 * s, 14 * s, 16 * s, "#3a3f4a")
        eye(d, cx - 5 * s, cy - 26 * s, 0.7, "#ffffff")
        eye(d, cx + 5 * s, cy - 26 * s, 0.7, "#ffffff")
        d.polygon([(cx - 14 * s, cy + 20 * s), (cx + 8 * s, cy + 20 * s), (cx - 6 * s, cy + 30 * s)], fill="#3a3f4a")
        for dx in (-18, 18):
            pxl(d, cx + dx * s, cy + 24 * s, 4 * s, 10 * s, "#3a3f4a")
    elif token in ("🐘", "elephant"):
        cy = int(basey - 60 * s)
        soft_ellipse(base, cx, basey, 60 * s, 10 * s, PAL_SHADOW, 8)
        pxl(d, cx, cy, 56 * s, 50 * s, "#9aa3b0", outline="#7b8490", width=2)
        pxl(d, cx, cy - 44 * s, 34 * s, 30 * s, "#9aa3b0", outline="#7b8490", width=2)
        eye(d, cx - 10 * s, cy - 44 * s, 1.0, "#f2f4f7")
        # 象鼻
        d.rounded_rectangle([cx + 24 * s, cy - 40 * s, cx + 34 * s, cy + 12 * s], 6, fill="#9aa3b0")
        d.arc([cx + 4 * s, cy - 2 * s, cx + 36 * s, cy + 26 * s], 180, 340, fill="#7b8490", width=3)
        # 耳朵
        pxl(d, cx - 48 * s, cy - 34 * s, 22 * s, 26 * s, "#b3bcc9", outline="#7b8490", width=2)
        for dx in (-40, 40):
            rrt(d, [int(cx + dx * s - 8 * s), int(cy + 16 * s), int(cx + dx * s + 8 * s), int(basey)], 6,
                "#9aa3b0", outline="#7b8490", width=2)
        draw_tail(base, cx, cy + 30 * s, 24, 1, "#7b8490")
    elif token in ("🐿️", "squirrel"):
        cy = int(basey - 40 * s)
        pxl(d, cx, cy, 16 * s, 22 * s, "#c98b4e")
        pxl(d, cx, cy - 18 * s, 12 * s, 12 * s, "#c98b4e")
        eye(d, cx - 3 * s, cy - 18 * s, 0.7)
        for a in range(30, 330, 12):
            px = cx + 20 * s + math.cos(math.radians(a)) * 10 * s
            py = cy - 4 * s + math.sin(math.radians(a)) * 10 * s
            d.polygon([(px - 3, py - 6), (px + 3, py - 6), (px, py)], fill="#a2713e")
    elif token in ("🐇",):
        draw_character(base, "🐰", cx, basey, s)
    elif token in ("👦", "boy"):
        cy = int(basey - 62 * s)
        pxl(d, cx, cy + 16 * s, 24 * s, 28 * s, "#4f9ad1")
        # 头
        pxl(d, cx, cy - 20 * s, 18 * s, 20 * s, "#ffe0c0")
        # 头发
        d.arc([cx - 18 * s, cy - 34 * s, cx + 18 * s, cy - 8 * s], 200, 340, fill="#4a3520", width=6)
        eye(d, cx - 7 * s, cy - 20 * s)
        eye(d, cx + 7 * s, cy - 20 * s)
        mouth(d, cx, cy - 12 * s, 0.7)
        # 腿
        rrt(d, [int(cx - 18 * s), int(cy + 36 * s), int(cx - 6 * s), int(basey)], 4, "#8a5a35")
        rrt(d, [int(cx + 6 * s), int(cy + 36 * s), int(cx + 18 * s), int(basey)], 4, "#8a5a35")
    elif token in ("👧", "girl"):
        cy = int(basey - 60 * s)
        pxl(d, cx, cy + 14 * s, 24 * s, 28 * s, "#ef7fa0")
        pxl(d, cx, cy - 22 * s, 17 * s, 20 * s, "#ffe0c0")
        # 双发髻
        pxl(d, cx - 16 * s, cy - 30 * s, 9 * s, 9 * s, "#4a3520")
        pxl(d, cx + 16 * s, cy - 30 * s, 9 * s, 9 * s, "#4a3520")
        d.arc([cx - 17 * s, cy - 34 * s, cx + 17 * s, cy - 10 * s], 200, 340, fill="#4a3520", width=5)
        eye(d, cx - 7 * s, cy - 22 * s)
        eye(d, cx + 7 * s, cy - 22 * s)
        mouth(d, cx, cy - 14 * s, 0.7)
        rrt(d, [int(cx - 18 * s), int(cy + 34 * s), int(cx - 6 * s), int(basey)], 4, "#ef7fa0")
        rrt(d, [int(cx + 6 * s), int(cy + 34 * s), int(cx + 18 * s), int(basey)], 4, "#ef7fa0")
    elif token in ("👩", "woman", "grandmother", "mother", "ma"):
        cy = int(basey - 62 * s)
        # 裙摆
        d.polygon([(cx - 26 * s, cy + 26 * s), (cx + 26 * s, cy + 26 * s), (cx + 16 * s, cy + 44 * s),
                   (cx - 16 * s, cy + 44 * s)], fill="#8fb4e8")
        pxl(d, cx, cy + 12 * s, 22 * s, 26 * s, "#c96a7a")
        pxl(d, cx, cy - 22 * s, 17 * s, 20 * s, "#ffe0c0")
        d.arc([cx - 17 * s, cy - 36 * s, cx + 17 * s, cy - 12 * s], 200, 340, fill="#cfd4dd", width=5)
        pxl(d, cx, cy - 30 * s, 8 * s, 8 * s, "#cfd4dd")
        eye(d, cx - 7 * s, cy - 22 * s)
        eye(d, cx + 7 * s, cy - 22 * s)
        mouth(d, cx, cy - 14 * s, 0.7)
    elif token in ("👨", "man", "hunter", "farmer", "father", "dad"):
        cy = int(basey - 62 * s)
        pxl(d, cx, cy + 14 * s, 26 * s, 30 * s, "#c47a3c")
        pxl(d, cx, cy - 20 * s, 18 * s, 20 * s, "#ffd9a8")
        # 帽子
        d.arc([cx - 19 * s, cy - 36 * s, cx + 19 * s, cy - 14 * s], 200, 340, fill="#9a5a2e", width=6)
        rrt(d, [int(cx - 22 * s), int(cy - 20 * s), int(cx + 22 * s), int(cy - 16 * s)], 3, "#9a5a2e")
        eye(d, cx - 8 * s, cy - 22 * s)
        eye(d, cx + 8 * s, cy - 22 * s)
        mouth(d, cx, cy - 12 * s, 0.8)
        rrt(d, [int(cx - 20 * s), int(cy + 36 * s), int(cx - 7 * s), int(basey)], 4, "#5a4a3a")
        rrt(d, [int(cx + 7 * s), int(cy + 36 * s), int(cx + 20 * s), int(basey)], 4, "#5a4a3a")
    elif token in ("👥", "crowd", "people", "👪", "family"):
        for i, (dx, sc) in enumerate([(-30, 0.7), (0, 0.9), (30, 0.7)]):
            draw_character(base, "👦" if i != 1 else "👧", cx + dx * s, basey + 20 * s, s * sc)
    elif token in ("🔍", "search"):
        d.ellipse([cx - 12 * s, cy - 12 * s, cx + 12 * s, cy + 12 * s], outline="#e8edf2", width=4)
        d.line([(cx + 9, cy + 9), (cx + 18, cy + 18)], fill="#e8edf2", width=4)


def draw_tail(base, x, y, r, flip, color):
    d = ImageDraw.Draw(base)
    ang = -150 if flip > 0 else -30
    for a in range(0, 200, 20):
        rr = r * (1 - a / 280)
        px = x + math.cos(math.radians(ang + a * flip)) * rr * 0.6
        py = y + math.sin(math.radians(ang + a * flip)) * rr * 0.6
        d.ellipse([px - rr * 0.35, py - rr * 0.35, px + rr * 0.35, py + rr * 0.35], fill=color)


def draw_object(base, token, cx, cy, s=1.0):
    d = ImageDraw.Draw(base)
    if token in ("🍐", "pear"):
        # 梨子
        d.ellipse([cx - 14 * s, cy - 8 * s, cx + 14 * s, cy + 20 * s], fill="#b8cf5a")
        d.ellipse([cx - 10 * s, cy - 16 * s, cx + 10 * s, cy - 2 * s], fill="#cfdf7d")
        d.line([(cx, cy - 18 * s), (cx + 3 * s, cy - 28 * s)], fill="#7a9a3a", width=3)
        pxl(d, cx - 2 * s, cy - 29 * s, 3 * s, 4 * s, "#7a4a26")
    elif token in ("🧺", "basket"):
        rrt(d, [int(cx - 26 * s), int(cy - 14 * s), int(cx + 26 * s), int(cy + 16 * s)], 8, "#c89b60",
            outline="#a5763f", width=3)
        rrt(d, [int(cx - 30 * s), int(cy + 10 * s), int(cx + 30 * s), int(cy + 20 * s)], 6, "#a5763f")
        d.line([(cx - 22 * s, cy - 14 * s), (cx, cy - 28 * s), (cx + 22 * s, cy - 14 * s)], fill="#a5763f", width=4)
        d.ellipse([cx - 12 * s, cy - 24 * s, cx + 12 * s, cy - 2 * s], fill="#ffd94a")
    elif token in ("🍶", "bottle", "glass", "pitcher", "🏺", "jar", "vat"):
        # 玻璃瓶/缸
        body = "#7ec4f2"
        if token in ("🏺", "jar", "vat"):
            body = "#c98a5a"
        rrt(d, [int(cx - 14 * s), int(cy - 6 * s), int(cx + 14 * s), int(cy + 26 * s)], 7, body,
            outline="#4a6a8a", width=3)
        rrt(d, [int(cx - 6 * s), int(cy - 26 * s), int(cx + 6 * s), int(cy - 4 * s)], 3, body,
            outline="#4a6a8a", width=2)
        # 水
        d.ellipse([cx - 14 * s, cy - 18 * s, cx + 12 * s, cy + 10 * s], fill="#bfe6ff")
    elif token in ("🪨", "stone", "rock", "pebble"):
        g = (176, 184, 194, 255)
        soft_ellipse(base, cx, cy + 14 * s, 26 * s, 12 * s, PAL_SHADOW, 8)
        d.polygon([(cx - 26 * s, cy + 18 * s), (cx - 18 * s, cy - 8 * s), (cx + 8 * s, cy - 18 * s),
                   (cx + 26 * s, cy - 4 * s), (cx + 22 * s, cy + 20 * s)], fill=g,
                  outline=(150, 158, 168, 255), width=2)
        d.line([(cx - 12 * s, cy - 10 * s), (cx - 2 * s, cy + 4 * s)], fill=(140, 148, 158, 255), width=2)
    elif token in ("🧱", "brick"):
        for dy in range(-1, 2):
            for dx in range(0, 3):
                rrt(d, [int(cx + dx * 34 * s - 30 * s), int(cy + dy * 22 * s - 20 * s),
                        int(cx + dx * 34 * s - 2 * s), int(cy + dy * 22 * s + 20 * s)], 4,
                    "#d26454", outline="#a03c30", width=2)
        rrt(d, [int(cx + 12 * s), int(cy - 18 * s), int(cx + 20 * s), int(cy + 18 * s)], 3,
            "#a03c30")
    elif token in ("🌾", "straw", "wheat"):
        for i in range(-2, 3):
            x = cx + i * 14 * s
            d.line([(x, cy), (x, cy - 34 * s)], fill="#d9a83a", width=3)
            d.polygon([(x, cy - 40 * s), (x - 8 * s, cy - 28 * s), (x + 8 * s, cy - 28 * s)], fill="#e8c96a")
    elif token in ("🪵", "wood", "log"):
        for i in range(-2, 3):
            rrt(d, [int(cx + i * 26 * s - 12 * s), int(cy - 10 * s), int(cx + i * 26 * s + 12 * s), int(cy + 10 * s)],
                6, "#b98a52", outline="#8a5a35", width=2)
            d.ellipse([cx + i * 26 * s - 6 * s, cy - 6 * s, cx + i * 26 * s + 6 * s, cy + 6 * s],
                      fill="#e8cf9f")
    elif token in ("🌳", "tree", "🌲", "pine"):
        if token == "🌲":
            d.polygon([(cx - 30 * s, cy + 30 * s), (cx + 30 * s, cy + 30 * s), (cx, cy - 40 * s)], fill="#3f8f4e")
            rrt(d, [int(cx - 8 * s), int(cy + 30 * s), int(cx + 8 * s), int(cy + 46 * s)], 4, "#8a5a35")
        else:
            rrt(d, [int(cx - 8 * s), int(cy + 6 * s), int(cx + 8 * s), int(cy + 40 * s)], 5, "#8a5a35")
            pxl(d, cx, cy, 34 * s, 30 * s, "#58a35a")
            pxl(d, cx - 20 * s, cy - 6 * s, 14 * s, 13 * s, "#58a35a")
            pxl(d, cx + 20 * s, cy - 6 * s, 14 * s, 13 * s, "#58a35a")
    elif token in ("🌸", "flower", "🌺", "🌼", "🌻"):
        draw_flower(base, cx, cy, s)
    elif token in ("💧", "water", "drop", "🌊", "wave"):
        for i in range(3):
            y = cy - i * 20 * s
            d.polygon([(cx - 10 * s, y + 6 * s), (cx, y - 12 * s), (cx + 10 * s, y + 6 * s)], fill="#7ec4f2")
            d.polygon([(cx - 6 * s, y + 14 * s), (cx - 20 * s, y + 8 * s), (cx - 4 * s, y + 2 * s)], fill="#7ec4f2")
    elif token in ("🌙", "moon"):
        pxl(d, cx, cy, 32 * s, 32 * s, "#d9c27a")
        pxl(d, cx, cy, 29 * s, 29 * s, "#ffe9a6")
        pxl(d, cx + 9 * s, cy + 3 * s, 22 * s, 22 * s, "#c9b46a")
        d.arc([cx - 34 * s, cy - 34 * s, cx + 34 * s, cy + 34 * s], 200, 340, fill="#d9c27a", width=3)
    elif token in ("⭐", "star", "✨", "🌟", "sparkle"):
        for _ in range(4):
            x = cx + random.randint(-30, 30) * s
            y = cy + random.randint(-30, 30) * s
            r = 6 * s
            pts = []
            for kk in range(8):
                ang = math.pi / 4 * kk
                rr = (3 * r if kk % 2 else r) * (1 - 0.15 * (kk % 2))
                pts.append((x + math.cos(ang) * rr, y + math.sin(ang) * rr))
            d.polygon(pts, fill="#d9b84a", outline="#c9a51c", width=2)
            pts2 = []
            for kk in range(8):
                ang = math.pi / 4 * kk
                rr = (r * (0.62 if kk % 2 else 0.85))
                pts2.append((x + math.cos(ang) * rr, y + math.sin(ang) * rr))
            d.polygon(pts2, fill="#fff6c0")
    elif token in ("🍖", "food", "🍷", "feast"):
        d.ellipse([cx - 26 * s, cy - 4 * s, cx + 26 * s, cy + 22 * s], fill="#e8d9b8")
        d.ellipse([cx - 18 * s, cy - 16 * s, cx + 18 * s, cy + 6 * s], fill="#c98a5a", outline="#a06a33", width=3)
        d.line([(cx - 12 * s, cy - 14 * s), (cx + 12 * s, cy + 2 * s)], fill="#a06a33", width=2)
    elif token in ("🏁", "flag", "finish"):
        d.line([(cx - 40 * s, cy + 24 * s), (cx - 40 * s, cy - 22 * s)], fill="#3a3f4a", width=4)
        d.polygon([(cx - 40 * s, cy - 22 * s), (cx - 6 * s, cy - 14 * s), (cx - 40 * s, cy - 6 * s)], fill="#ef5b6e")
        rrt(d, [int(cx - 46 * s), int(cy + 24 * s), int(cx + 46 * s), int(cy + 36 * s)], 6, "#ef5b6e")
    elif token in ("🎉", "party", "confetti"):
        for _ in range(12):
            x = cx + random.randint(-40, 40) * s
            y = cy + random.randint(-30, 30) * s
            d.polygon([(x - 4, y - 4), (x + 4, y - 4), (x, y + 4)], fill=random.choice(
                ["#ef5b6e", "#ffd94a", "#7ec4f2", "#58a35a", "#c96a7a"]))
    elif token in ("🏠", "house"):
        draw_house(base, cx, cy + 40 * s, 1.2 * s)
    elif token in ("❄️", "snowflake"):
        for a in range(0, 360, 60):
            px = cx + math.cos(math.radians(a)) * 10 * s
            py = cy + math.sin(math.radians(a)) * 10 * s
            d.line([(cx, cy), (px, py)], fill="#aec9e8", width=2)
    elif token in ("📖", "book"):
        rrt(d, [int(cx - 22 * s), int(cy - 16 * s), int(cx + 6 * s), int(cy + 16 * s)], 4, "#8fb4e8")
        rrt(d, [int(cx - 4 * s), int(cy - 16 * s), int(cx + 24 * s), int(cy + 16 * s)], 4, "#c96a7a")
        d.line([(cx - 2 * s, cy - 16 * s), (cx - 2 * s, cy + 16 * s)], fill="#6a8ab8", width=2)
    elif token in ("⚖️", "scale"):
        d.line([(cx, cy + 16 * s), (cx, cy - 8 * s)], fill="#9aa3b0", width=5)
        d.arc([cx - 12 * s, cy - 26 * s, cx + 12 * s, cy - 2 * s], 200, 340, fill="#9aa3b0", width=4)
        d.line([(cx - 26 * s, cy - 10 * s), (cx + 26 * s, cy - 10 * s)], fill="#9aa3b0", width=5)
        for dx in (-24, 24):
            d.polygon([(cx + dx * s - 12 * s, cy - 10 * s), (cx + dx * s + 12 * s, cy - 10 * s),
                       (cx + dx * s, cy + 6 * s)], fill="#b3bcc9")
        d.line([(cx - 24 * s, cy - 10 * s), (cx - 24 * s, cy + 4 * s)], fill="#9aa3b0", width=3)
        d.line([(cx + 24 * s, cy - 10 * s), (cx + 24 * s, cy + 4 * s)], fill="#9aa3b0", width=3)
    elif token in ("🚣", "boat", "船"):
        d.polygon([(cx - 40 * s, cy), (cx + 40 * s, cy), (cx + 30 * s, cy + 22 * s),
                   (cx - 30 * s, cy + 22 * s)], fill="#a5763f")
        d.line([(cx, cy), (cx, cy - 26 * s)], fill="#4a3520", width=4)
        d.polygon([(cx, cy - 30 * s), (cx + 26 * s, cy - 8 * s), (cx, cy - 4 * s)], fill="#c96a7a")
    elif token in ("☀️", "sun"):
        pxl(d, cx, cy, 26 * s, 26 * s, "#ffd94a")
        for a in range(0, 360, 45):
            px = cx + math.cos(math.radians(a)) * 38 * s
            py = cy + math.sin(math.radians(a)) * 38 * s
            d.line([(cx + math.cos(math.radians(a)) * 26 * s,
                     cy + math.sin(math.radians(a)) * 26 * s), (px, py)], fill="#ffd94a", width=4)
    elif token in ("☁️", "cloud"):
        for (ox, oy, rr) in [(0, 0, 20), (20, -6, 16), (-20, -4, 14), (10, 10, 14), (-10, 10, 14)]:
            pxl(d, cx + ox, cy + oy, rr, rr, "#ffffff")
    elif token in ("🥚", "egg"):
        d.ellipse([cx - 14 * s, cy - 18 * s, cx + 14 * s, cy + 12 * s], fill="#fff7e6", outline="#e3d4b8", width=2)
    elif token in ("📦", "crate", "📢", "horn"):
        if token in ("📢", "horn"):
            rrt(d, [int(cx - 20 * s), int(cy - 10 * s), int(cx + 6 * s), int(cy + 10 * s)], 4, "#ff8b3d")
            d.polygon([(cx + 6 * s, cy - 10 * s), (cx + 30 * s, cy - 18 * s), (cx + 30 * s, cy + 18 * s),
                       (cx + 6 * s, cy + 10 * s)], fill="#ffb23d")
        else:
            rrt(d, [int(cx - 22 * s), int(cy - 18 * s), int(cx + 22 * s), int(cy + 18 * s)], 5, "#c98a5a",
                outline="#8a5a35", width=2)
    elif token in ("🏞️", "pond", "🏔️", "mountain"):
        # 山 + 倒影
        d.polygon([(cx - 60 * s, cy), (cx - 20 * s, cy - 60 * s), (cx + 30 * s, cy)],
                  fill="#7ba86b", outline="#5c8a4e", width=2)
        d.polygon([(cx + 30 * s, cy), (cx + 60 * s, cy - 40 * s), (cx + 90 * s, cy)],
                  fill="#8bbd79", outline="#5c8a4e", width=2)
        d.polygon([(cx - 20 * s, cy - 60 * s), (cx - 12 * s, cy - 46 * s), (cx - 28 * s, cy - 46 * s)], fill="#e8f4ec")
    elif token in ("🛏️", "bed"):
        rrt(d, [int(cx - 34 * s), int(cy - 8 * s), int(cx + 34 * s), int(cy + 22 * s)], 6, "#c98a5a")
        d.polygon([(cx - 34 * s, cy - 14 * s), (cx - 14 * s, cy - 14 * s), (cx - 14 * s, cy - 4 * s),
                   (cx - 34 * s, cy - 4 * s)], fill="#8fb4e8")
        rrt(d, [int(cx - 14 * s), int(cy - 10 * s), int(cx + 34 * s), int(cy + 4 * s)], 4, "#7ec4f2")
        pxl(d, cx + 26 * s, cy - 14 * s, 8 * s, 14 * s, "#ef7fa0")
    elif token in ("🚪", "door"):
        rrt(d, [int(cx - 24 * s), int(cy - 30 * s), int(cx + 24 * s), int(cy + 30 * s)], 10, "#c98a5a")
        pxl(d, cx + 14 * s, cy, 4 * s, 4 * s, "#ffd94a")
    elif token in ("🪓", "axe"):
        d.line([(cx - 10 * s, cy + 30 * s), (cx + 24 * s, cy - 20 * s)], fill="#8a5a35", width=5)
        d.polygon([(cx + 26 * s, cy - 26 * s), (cx + 42 * s, cy - 14 * s), (cx + 20 * s, cy - 6 * s)], fill="#8b95a3")
    elif token in ("👗", "dress"):
        d.polygon([(cx - 16 * s, cy - 16 * s), (cx + 16 * s, cy - 16 * s), (cx + 8 * s, cy + 26 * s),
                   (cx - 8 * s, cy + 26 * s)], fill="#ef7fa0")
        pxl(d, cx, cy - 20 * s, 8 * s, 8 * s, "#ef7fa0")
    elif token in ("⛰️",):
        draw_object(base, "🏞️", cx, cy, s)
    elif token in ("🌈",):
        for a, col in enumerate(["#ff5e6b", "#ffd94a", "#7ec4f2"]):
            d.arc([cx - 50 * s + a * 8 * s, cy - 24 * s, cx + 50 * s - a * 8 * s, cy + 40 * s],
                  200, 340, fill=col, width=7)


def draw_house(base, cx, by, s):
    d = ImageDraw.Draw(base)
    rrt(d, [int(cx - 46 * s), int(by - 56 * s), int(cx + 46 * s), int(by)], 8, "#f2e2be",
        outline="#d8b98a", width=3)
    d.polygon([(cx - 54 * s, by - 52 * s), (cx, by - 96 * s), (cx + 54 * s, by - 52 * s)], fill="#c96a7a",
              outline="#a8455a", width=3)
    rrt(d, [int(cx - 14 * s), int(by - 40 * s), int(cx + 14 * s), int(by)], 2, "#7a4a26", outline="#8a5a35", width=2)
    for dx in (-24, 8):
        rrt(d, [int(cx + dx * s), int(by - 48 * s), int(cx + dx * s + 14 * s), int(by - 34 * s)], 2,
            "#aee6ff", outline="#8fb4e8", width=2)


# 可绘制词元 -> 人类可读的绘制入口
DRAWABLE_CHAR = set("🐢🐰🐺🐷🐶🐸🐨🦆🐤🐣🐔🦢🐦🐒🐴🐂🐑🐘🐿️🐇🐂")
DRAWABLE_OBJ = set("🍐🧺🍶🏺🪨🧱🌾🪵🌳🌲🌸🌺🌼🌻💧🌊🌙⭐✨🌟🍖🍷🏁🎉🏠❄️📖⚖️🚣☀️☁️🥚📦📢🏞️🏔️🛏️🚪🪓👗🌈⛰️船")

CHAR_TOKENS = ["🐢", "🐰", "🐺", "🐷", "🦆", "🐤", "🐣", "🐔", "🦢", "🐦", "🐒", "🐴",
               "🐂", "🐑", "🐘", "🐿️", "🐇", "👦", "👧", "👩", "👨", "👥", "👪"]
OBJ_TOKENS = ["🍐", "🧺", "🍶", "🏺", "🪨", "🧱", "🌾", "🪵", "🌳", "🌲", "🌸", "🌺", "🌼",
              "🌻", "💧", "🌊", "🌙", "⭐", "✨", "🌟", "🍖", "🍷", "🏁", "🎉", "🏠", "❄️",
              "📖", "⚖️", "🚣", "☀️", "☁️", "🥚", "📦", "📢", "🏞️", "🏔️", "🛏️", "🚪", "🪓",
              "👗", "🌈", "⛰️", "船"]

# 人类角色/动物同义词 (k 兜底映射)
K_CHAR = {"hare": "🐰", "turtle": "🐢", "tortoise": "🐢", "wolf": "🐺", "sheep": "🐑",
          "shepherd": "👨", "farmer": "👨", "pig": "🐷", "duck": "🦆", "duckling": "🐤",
          "chick": "🐤", "swan": "🦢", "bird": "🐦", "crow": "🐦", "raven": "🐦", "monkey": "🐒",
          "horse": "🐴", "cow": "🐂", "elephant": "🐘", "squirrel": "🐿️", "boy": "👦",
          "girl": "👧", "mother": "👩", "grandmother": "👩", "grandma": "👩", "man": "👨",
          "hunter": "👨", "father": "👨", "man": "👨"}
K_OBJ = {"pear": "🍐", "basket": "🧺", "bottle": "🍶", "glass": "🍶", "water": "💧",
         "stone": "🪨", "brick": "🧱", "straw": "🌾", "wood": "🪵", "tree": "🌳",
         "forest": "🌳", "flower": "🌸", "moon": "🌙", "sun": "☀️", "sunrise": "☀️",
         "finish": "🏁", "mountain": "🏞️", "jug": "🏺", "jar": "🏺", "boat": "🚣",
         "scale": "⚖️", "well": "🏞️", "river": "💧", "nap": "🌙", "sleep": "🌙",
         "surprise": "✨", "spring": "🌸", "winter": "❄️", "snow": "❄️", "food": "🍖",
         "winner": "🏁", "field": "🌾", "farm": "🏠", "house": "🏠", "home": "🏠",
         "family": "👪", "children": "👥", "road": "🌳", "race": "🏁", "run": "🐴",
         "laugh": "🎉", "happy": "🎉", "dance": "🎉", "song": "🌟", "dream": "🌙",
         "night": "🌙", "flag": "🏁", "pond": "🏞️", "egg": "🥚", "sky": "☀️", "victory": "🏁"}


def parse_pages():
    src = open(JS_PATH, encoding="utf-8").read()
    res = {}
    for b in BOOKS:
        block = re.search(r"id: '" + b["id"] + r"'.*?pages: \[(.*?)\n      \]", src, re.S)
        if not block:
            sys.exit("JS 中找不到绘本: %s" % b["id"])
        pages = re.findall(r"\{ k: '([^']*)', bg: '([^']*)', ems: \[([^\]]*)\],", block.group(1))
        res[b["id"]] = pages
    return res


def pick_subject(page):
    k, bg, ems_str = page
    toks = re.findall(r"'([^']*)'", ems_str)
    for t in toks:
        if t in CHAR_TOKENS:
            return t
    for t in toks:
        if t in OBJ_TOKENS:
            return t
    if k in K_CHAR:
        return K_CHAR[k]
    if k in K_OBJ:
        return K_OBJ[k]
    return None


def gen_page(book_id, page, fname):
    k, bg, ems_str = page
    toks = re.findall(r"'([^']*)'", ems_str)
    seed = sum(ord(c) for c in book_id) * 7919 + int(fname[1:3]) * 131
    rng = random.Random(seed)
    img = Image.new("RGBA", (W, H))
    top, bottom = THEMES.get(bg, THEMES["meadow"])
    gradient(img, top, bottom)
    draw_env(img, bg, seed)
    d = ImageDraw.Draw(img)

    # 背景装饰: 树/花
    for _ in range(2 if bg in ("meadow", "sunny", "farm", "rose") else 1):
        tx = rng.randint(40, W - 40)
        draw_tree(img, tx, H - rng.randint(20, 70), rng.choice([0.5, 0.65, 0.8]),
                  rng.choice(["#58a35a", "#3f8f4e", "#6fae5e"]))
    if bg in ("rose", "meadow", "sunny"):
        for _ in range(5):
            draw_flower(img, rng.randint(30, W - 30), H - rng.randint(30, 120),
                        rng.choice([0.6, 0.8, 1.0]))

    # 主元素
    subj = pick_subject(page)
    cx = W // 2
    basey = int(H * 0.82)
    if subj:
        if subj in CHAR_TOKENS:
            # 人物/动物带伙伴或本体
            draw_character(img, subj, cx, basey, 1.9)
        elif subj in OBJ_TOKENS:
            ocy = int(H * 0.52)
            soft_ellipse(img, cx + 12, ocy + 8, 165, 95, (255, 255, 255, 150), 26)
            draw_object(img, subj, cx, ocy, 2.3)
    # 次要可绘制词元 (除主元素与纯表情/装饰外)
    n = 0
    for t in toks:
        if t == subj:
            continue
        if t in CHAR_TOKENS and n < 2:
            draw_character(img, t, cx + (n - 1) * 170, basey - 30 * (n % 2), 1.1)
            n += 1
        elif t in OBJ_TOKENS and n < 3:
            draw_object(img, t, rng.randint(90, W - 90), rng.randint(int(H * 0.35), int(H * 0.8)), 0.9)
            n += 1

    # 柔和卡片边框 (绘本感)
    frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fd = ImageDraw.Draw(frame)
    fd.rounded_rectangle([8, 8, W - 8, H - 8], 26, outline=(255, 255, 255, 200), width=6)
    img = Image.alpha_composite(img.convert("RGBA"), frame)

    img = img.convert("RGB")
    os.makedirs(os.path.join(OUT_DIR, book_id), exist_ok=True)
    img.save(os.path.join(OUT_DIR, book_id, fname), "JPEG", quality=88)


def main():
    ap = argparse.ArgumentParser(description="本地程序化生成绘本配图")
    ap.add_argument("book_id", nargs="?", default=None, help="只生成指定绘本 id")
    ap.add_argument("--force", action="store_true", help="覆盖已有图片")
    args = ap.parse_args()
    pages = parse_pages()
    targets = [b for b in BOOKS if not args.book_id or b["id"] == args.book_id]
    if not targets:
        sys.exit("未知 book_id: %s" % args.book_id)
    n = 0
    for b in targets:
        for i, page in enumerate(pages[b["id"]]):
            fname = "p%02d.jpg" % (i + 1)
            path = os.path.join(OUT_DIR, b["id"], fname)
            if os.path.exists(path) and os.path.getsize(path) > 3000 and not args.force:
                continue
            gen_page(b["id"], page, fname)
            n += 1
        print("[*] %s: %d页图片就绪" % (b["title"], b["pages"]))
    print("生成完成, 共处理 %d 张图片" % n)


if __name__ == "__main__":
    main()