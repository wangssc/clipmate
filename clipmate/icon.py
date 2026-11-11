"""生成托盘/程序图标（app.ico）。

纯 Python 画 + 写 ICO，不依赖 Pillow。只需要跑一次，成品 app.ico 随程序发布。
"""

import os
import struct

BG = (37, 99, 235)       # 蓝
FG = (255, 255, 255)     # 白


def _rrect(u, v, x0, y0, x1, y1, r):
    """点是否落在圆角矩形内（u,v 为 0~1 归一化坐标）。"""
    dx = max(x0 + r - u, 0.0, u - (x1 - r))
    dy = max(y0 + r - v, 0.0, v - (y1 - r))
    if u < x0 or u > x1 or v < y0 or v > y1:
        return False
    return dx * dx + dy * dy <= r * r


def _sample(u, v):
    """返回该点的颜色 (r,g,b,a)，a=0 表示透明。"""
    if not _rrect(u, v, 0.0, 0.0, 1.0, 1.0, 0.22):
        return None
    # 剪贴板夹子
    if _rrect(u, v, 0.385, 0.195, 0.615, 0.335, 0.045):
        return FG + (255,)
    # 纸板
    if _rrect(u, v, 0.275, 0.275, 0.725, 0.795, 0.075):
        # 三条文字线
        for y, x1 in ((0.455, 0.645), (0.545, 0.575), (0.635, 0.645)):
            if _rrect(u, v, 0.365, y - 0.018, x1, y + 0.018, 0.018):
                return BG + (255,)
        return FG + (255,)
    return BG + (255,)


def _render(size, ss=None):
    if ss is None:
        ss = 4 if size <= 64 else 2
    n = size * ss
    # 先按超采样渲染，再盒式降采样得到平滑边缘
    acc = [[0.0, 0.0, 0.0, 0.0] for _ in range(size * size)]
    for y in range(n):
        row = (y // ss) * size
        for x in range(n):
            c = _sample((x + 0.5) / n, (y + 0.5) / n)
            cell = acc[row + (x // ss)]
            if c is None:
                continue
            a = c[3] / 255.0
            cell[0] += c[0] * a
            cell[1] += c[1] * a
            cell[2] += c[2] * a
            cell[3] += a
    k = float(ss * ss)
    out = bytearray(size * size * 4)
    for i, (r, g, b, a) in enumerate(acc):
        alpha = a / k
        if alpha <= 0:
            continue
        # ICO 的 32bpp 位图是 BGRA 顺序
        out[i * 4 + 0] = min(255, int(b / a))
        out[i * 4 + 1] = min(255, int(g / a))
        out[i * 4 + 2] = min(255, int(r / a))
        out[i * 4 + 3] = min(255, int(alpha * 255 + 0.5))
    return bytes(out)


def _ico_entry(size, rgba):
    """一个 32bpp BMP 格式的 ICO 图块。"""
    header = struct.pack(
        "<IiiHHIIiiII",
        40, size, size * 2, 1, 32, 0, size * size * 4, 0, 0, 0, 0,
    )
    # BMP 是自下而上存的
    flipped = bytearray()
    for y in range(size - 1, -1, -1):
        flipped += rgba[y * size * 4:(y + 1) * size * 4]
    mask_row = ((size + 31) // 32) * 4
    mask = b"\x00" * (mask_row * size)
    return header + bytes(flipped) + mask


def build_ico(path, sizes=(16, 20, 24, 32, 40, 48, 64, 128)):
    images = [(s, _render(s)) for s in sizes]
    offset = 6 + 18 * len(images)
    head = struct.pack("<HHH", 0, 1, len(images))
    entries = b""
    blobs = b""
    for size, rgba in images:
        data = _ico_entry(size, rgba)
        entries += struct.pack(
            "<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset
        )
        offset += len(data)
        blobs += data
    with open(path, "wb") as f:
        f.write(head + entries + blobs)
    return path


def ensure_icon(path):
    if not os.path.exists(path) or os.path.getsize(path) < 1000:
        build_ico(path)
    return path


if __name__ == "__main__":
    print(build_ico(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "app.ico")))
