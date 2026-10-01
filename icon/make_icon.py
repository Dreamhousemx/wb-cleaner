# -*- coding: utf-8 -*-
"""从 AI 生成的原始图重建应用图标，并打包成多尺寸 .ico。

做四件事：
  1. 用最小二乘拟合背景渐变（避开字形与水印区域），重建一张没有任何水印/杂点的干净底图
  2. 从原图提取白色字形蒙版（按亮度软阈值，保留抗锯齿），去掉角落的水印
  3. 字形重新居中并缩放到统一比例，保证各尺寸下视觉一致
  4. 加圆角透明蒙版，导出 1024 PNG 与多尺寸 ICO（256/128/64/48/40/32/24/20/16）

用法： python icon/make_icon.py [原始图路径]
输出： icon/app-icon.png、icon/app-icon.ico
"""

import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON_DIR = os.path.join(ROOT, "icon")
DEFAULT_SRC = os.path.join(
    ICON_DIR, "raw", "Flat_vector_app_icon__full_ble_2026-10-01T07-06-37.png")

GLYPH_BOX = 0.60      # 字形（含留白）占画布的比例
CORNER_RADIUS = 0.225  # 圆角半径 / 边长
WATERMARK_BOX = (0.66, 0.82)   # 水印保护区（按比例）：x>0.66W 且 y>0.82H 一律视为无效


def fit_background(rgb):
    """线性拟合 color(x, y) = a + b*x + c*y，只用干净背景像素。"""
    h, w, _ = rgb.shape
    lum = rgb.mean(axis=2)

    yy, xx = np.mgrid[0:h, 0:w]
    mask = lum < 150                                     # 背景（亮的是字形）
    mask &= ~((xx > w * WATERMARK_BOX[0]) & (yy > h * WATERMARK_BOX[1]))
    mask[::2, :] = False                                 # 行采样，加速

    X = np.stack([np.ones(mask.sum()), xx[mask].astype(np.float64),
                  yy[mask].astype(np.float64)], axis=1)
    model = np.zeros((h, w, 3), dtype=np.float64)
    coefs = []
    for ch in range(3):
        y = rgb[:, :, ch][mask].astype(np.float64)
        c, *_ = np.linalg.lstsq(X, y, rcond=None)
        coefs.append(c)
        model[:, :, ch] = c[0] + c[1] * xx + c[2] * yy
        resid = np.abs(model[:, :, ch] - rgb[:, :, ch])[mask]
        print("    通道 %d 拟合残差：平均 %.2f / 最大 %.2f（0~255）"
              % (ch, resid.mean(), resid.max()))
    return np.clip(model, 0, 255).astype(np.uint8)


def glyph_mask(rgb):
    """按亮度提取白色字形，返回 0~255 的软蒙版。"""
    lum = rgb.mean(axis=2).astype(np.float64)
    low, high = 140.0, 200.0
    a = np.clip((lum - low) / (high - low), 0.0, 1.0) * 255.0

    h, w = a.shape
    yy, xx = np.mgrid[0:h, 0:w]
    a[(xx > w * WATERMARK_BOX[0]) & (yy > h * WATERMARK_BOX[1])] = 0.0   # 抹掉水印
    return a


def recenter_glyph(alpha, canvas=1024, box_ratio=GLYPH_BOX):
    """把字形裁到实际 bbox，缩放到目标比例，并居中放进新画布。"""
    ys, xs = np.nonzero(alpha > 8)
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    print("    字形原始 bbox：%dx%d（占画布 %.0f%%）"
          % (x1 - x0, y1 - y0, 100 * (x1 - x0) / alpha.shape[1]))

    crop = Image.fromarray(alpha[y0:y1, x0:x1].astype(np.uint8), mode="L")
    target = int(canvas * box_ratio)
    scale = target / max(crop.size)
    crop = crop.resize((max(1, round(crop.width * scale)),
                        max(1, round(crop.height * scale))), Image.LANCZOS)

    out = Image.new("L", (canvas, canvas), 0)
    out.paste(crop, ((canvas - crop.width) // 2, (canvas - crop.height) // 2))
    out = out.filter(ImageFilter.GaussianBlur(1.1))       # 轻微羽化，缩小后更顺滑
    return out


def rounded_mask(size, radius_ratio=CORNER_RADIUS):
    m = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(m).rounded_rectangle(
        [0, 0, size * 4 - 1, size * 4 - 1], radius=int(size * 4 * radius_ratio), fill=255)
    return m.resize((size, size), Image.LANCZOS)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    if not os.path.isfile(src):
        print("找不到原始图：%s" % src)
        return 1

    print("源图：%s" % src)
    im = Image.open(src).convert("RGB")
    side = min(im.size)
    if im.size != (side, side):
        im = im.crop((0, 0, side, side))
    rgb = np.asarray(im)

    print("[1] 拟合背景渐变")
    bg = fit_background(rgb)

    print("[2] 提取字形蒙版")
    alpha = glyph_mask(rgb)
    print("    字形像素占比 %.1f%%" % (100 * (alpha > 128).mean()))

    print("[3] 重新居中与缩放")
    mask = recenter_glyph(alpha)

    print("[4] 合成并导出")
    base = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    base.paste(Image.fromarray(bg, "RGB"), (0, 0))
    white = Image.new("RGBA", (side, side), (255, 255, 255, 255))
    base = Image.composite(white, base, mask)

    png_path = os.path.join(ICON_DIR, "app-icon.png")
    base.save(png_path)
    print("    PNG -> %s" % png_path)

    sizes = [256, 128, 64, 48, 40, 32, 24, 20, 16]
    frames = []
    for s in sizes:
        frame = base.resize((s, s), Image.LANCZOS)
        frame.putalpha(Image.composite(frame.getchannel("A"),
                                       Image.new("L", (s, s), 0), rounded_mask(s)))
        frames.append(frame)

    ico_path = os.path.join(ICON_DIR, "app-icon.ico")
    frames[0].save(ico_path, format="ICO",
                   sizes=[(f.width, f.height) for f in frames],
                   append_images=frames[1:])
    print("    ICO -> %s（%s）" % (ico_path, ", ".join("%dpx" % s for s in sizes)))

    # 界面本体直接用同一张图：浏览器标签页/应用窗口图标 + 顶栏 logo
    web_png = os.path.join(ROOT, "web", "app-icon.png")
    base.resize((256, 256), Image.LANCZOS).save(web_png)
    print("    供界面使用 -> %s" % web_png)

    print("[5] 生成预览页")
    preview = os.path.join(ICON_DIR, "preview.html")
    write_preview(preview, base, sizes)
    print("    预览 -> %s" % preview)
    print("    源尺寸：%d x %d" % (side, side))
    return 0


NAMES = [
    ("扫尘", "Sweep", "推荐：与图标（扫帚 + 星光）完全呼应。把缓存与垃圾比作灰尘，"
                      "「扫尘」本身也是中式年前大扫除的说法，干净利落。"),
    ("净匣", "CleanVault", "呼应「清理前先收进隔离区」的安全设计——匣子既能收纳也能清空，"
                           "产品感最强，适合做成正经软件名。"),
    ("腾地方", "MakeRoom", "最直白：「给 C 盘腾个地方」。一看就懂用途，口语亲切，"
                           "适合个人自用工具。"),
    ("拾掇", "Tidy", "北方话「收拾、整理」。「拾掇一下电脑」很有生活气息，温和不吓人。"),
]


def _b64(img, fmt="PNG"):
    import base64
    import io
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def write_preview(path, base, sizes):
    """把各尺寸内联成 data URI，生成一个自包含的预览页（离线可看）。"""
    tiles = []
    for s in sizes:
        small = base.resize((s, s), Image.LANCZOS)
        small.putalpha(Image.composite(small.getchannel("A"),
                                       Image.new("L", (s, s), 0), rounded_mask(s)))
        b64 = _b64(small)
        tiles.append((s, b64))

    def tag(s, b64, px):
        return ('<span class="cell"><img src="data:image/png;base64,%s" '
                'style="width:%dpx;height:%dpx" alt="%d">'
                '<em>%dpx%s</em></span>') % (b64, px, px, s, s,
                                             " · 放大 %dx" % (px // s) if px > s else "")

    real = "".join(tag(s, b, s) for s, b in tiles)
    blown = "".join(tag(s, b, s * (6 if s <= 32 else 2 if s <= 64 else 1))
                    for s, b in tiles if s in (16, 32, 48, 64, 128))
    taskbar = "".join(
        '<span class="tb"><img src="data:image/png;base64,%s" style="width:32px;height:32px">'
        '<em>%dpx</em></span>' % (b, s) for s, b in tiles if s in (16, 32, 48))

    names = "".join(
        '<div class="name"><b>%s</b><span class="en">%s</span><p>%s</p></div>'
        % (n, en, esc(d)) for n, en, d in NAMES)
    hero = _b64(base.resize((256, 256), Image.LANCZOS))

    html = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>扫尘 —— 应用图标预览</title>
<style>
:root{color-scheme:light}
*{box-sizing:border-box}
body{margin:0;background:#eef1f6;color:#16202e;
 font:14px/1.6 "Microsoft YaHei UI","Microsoft YaHei",-apple-system,Segoe UI,sans-serif}
.wrap{max-width:920px;margin:0 auto;padding:34px 22px 60px}
h1{font-size:23px;margin:0 0 4px}
.sub{color:#7d8ba1;font-size:13px;margin-bottom:26px}
h2{font-size:15px;margin:30px 0 12px;padding-left:9px;border-left:3px solid #2563eb}
.panel{background:#fff;border:1px solid #e1e7f0;border-radius:12px;padding:20px;
 box-shadow:0 1px 2px rgba(22,32,46,.06)}
.hero{display:flex;gap:26px;align-items:center;flex-wrap:wrap}
.hero img{width:128px;height:128px;filter:drop-shadow(0 6px 18px rgba(37,99,235,.28))}
.hero .meta{font-size:13px;color:#47566b}
.hero .meta b{color:#16202e}
.cells{display:flex;align-items:flex-end;gap:26px;flex-wrap:wrap}
.cell{display:flex;flex-direction:column;align-items:center;gap:6px}
.cell em,.tb em{font-style:normal;font-size:11px;color:#7d8ba1}
.tb{display:flex;flex-direction:column;align-items:center;gap:5px;
 padding:9px 12px;border-radius:9px;background:linear-gradient(180deg,#2b3748,#1b2432)}
.dark{background:linear-gradient(180deg,#2b3748,#1b2432);border-radius:12px;
 padding:22px;border:1px solid #33405a}
.names{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.name{background:#fff;border:1px solid #e1e7f0;border-radius:10px;padding:13px 15px}
.name b{font-size:16px}
.name .en{font-size:11px;color:#7d8ba1;margin-left:7px;letter-spacing:.4px}
.name p{margin:6px 0 0;font-size:12px;color:#47566b}
.tip{margin-top:24px;background:#fff8e6;border:1px solid #ffe0a3;border-radius:10px;
 padding:12px 15px;color:#7c5a00;font-size:12.5px}
code{font-family:Consolas,Menlo,monospace;background:#eef1f6;padding:1px 5px;border-radius:4px}
</style></head><body><div class="wrap">
<h1>扫尘 · 应用图标</h1>
<div class="sub">WBCleaner 桌面快捷方式图标 · 白扫帚 + 星光，蓝紫渐变</div>

<div class="panel hero">
  <img src="data:image/png;base64,__HERO__" alt="icon">
  <div class="meta">
    <p><b>app-icon.ico</b> · 9 个尺寸（16/20/24/32/40/48/64/128/256），圆角透明</p>
    <p>设快捷方式图标：右键快捷方式 → 属性 → 更改图标 → 选 <code>app-icon.ico</code></p>
    <p>窗口/任务栏图标直接取自同一张图的 favicon，无需额外配置</p>
  </div>
</div>

<h2>实际像素尺寸（不放大，就是桌面上的真实观感）</h2>
<div class="panel"><div class="cells">__REAL__</div></div>

<h2>放大看清细节</h2>
<div class="panel"><div class="cells">__BLOWN__</div></div>

<h2>放到深色任务栏上的效果</h2>
<div class="dark"><div class="cells">__TASKBAR__</div></div>

<h2>名字候选</h2>
<div class="names">__NAMES__</div>

<div class="tip"><b>小尺寸提醒：</b>16px 下扫帚柄会比笔画略细，这是正常现象；
如果希望 16px 更实在，可以把 <code>GLYPH_BOX</code> 从 0.60 调大到 0.66 再跑一次
<code>python icon/make_icon.py</code>。</div>
</div></body></html>"""

    html = (html.replace("__HERO__", hero).replace("__REAL__", real)
                .replace("__BLOWN__", blown).replace("__TASKBAR__", taskbar)
                .replace("__NAMES__", names))
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(html)


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


if __name__ == "__main__":
    sys.exit(main())
