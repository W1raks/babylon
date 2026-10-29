"""Генератор SVG иконки: круглая башня Вавилона (ярусы-цилиндры, арки, огонь на вершине).

    python dev/icon_svg.py  (пишет babylon.svg и babylon_small.svg в текущую папку)
"""
import math

CX = 128

def halfw(t, W, k=0.70, p=1.6):
    """Полуширина башни на относительной высоте t (0 низ, 1 верх): выпуклая дуга-«улей»."""
    return W * (1 - k * t ** p)

def tower(n, W, y_bottom, y_top, ry_k=0.16, arches=True, ramp=False, setback=0.07):
    parts = []
    H = y_bottom - y_top
    th = H / n
    for i in range(n):
        t0, t1 = i / n, (i + 1) / n
        yb, yt = y_bottom - i * th, y_bottom - (i + 1) * th
        ab = halfw(t0, W) * (1 - (setback if i else 0) * 0)  # низ яруса
        at = halfw(t1, W) * (1 + setback)                    # верх яруса чуть шире следующего: карниз
        rb, rt = ab * ry_k, at * ry_k
        # тело яруса: низ по передней дуге эллипса, верх по передней дуге
        d = (f"M{CX-ab:.2f} {yb:.2f} A{ab:.2f} {rb:.2f} 0 0 0 {CX+ab:.2f} {yb:.2f} "
             f"L{CX+at:.2f} {yt:.2f} A{at:.2f} {rt:.2f} 0 0 1 {CX-at:.2f} {yt:.2f} Z")
        parts.append(f'<path d="{d}" fill="url(#cyl)"/>')
        # тень под карнизом (верхний край яруса)
        parts.append(f'<path d="M{CX-at:.2f} {yt:.2f} A{at:.2f} {rt:.2f} 0 0 0 {CX+at:.2f} {yt:.2f}" '
                     f'fill="none" stroke="#000" stroke-opacity=".35" stroke-width="{max(1.3, th*0.11):.2f}" '
                     f'transform="translate(0 {th*0.06:.2f})"/>')
        if arches:
            am = (ab + at) / 2
            rm = am * ry_k
            n_a = max(3, int(am / 8.5))
            ah = th * 0.6
            for k in range(n_a):
                th_ang = -1.25 + 2.5 * (k + (0.5 if i % 2 else 0)) / (n_a - 1)  # от -72° до +72°, ярусы через один со сдвигом
                if abs(th_ang) > 1.3:
                    continue
                x = CX + am * math.sin(th_ang)
                c = math.cos(th_ang)
                w = 6.0 * c * (am / 50) ** 0.35
                if w < 1.4:
                    continue
                ybase = yb - th * 0.14 + rb * c  # низ арки идёт по дуге яруса
                ytop = ybase - ah
                op = 0.35 + 0.45 * c  # к краям светлее: уходят от взгляда
                parts.append(f'<path d="M{x-w/2:.2f} {ybase:.2f} V{ytop+w/2:.2f} a{w/2:.2f} {w/2:.2f} 0 0 1 {w:.2f} 0 V{ybase:.2f}Z" '
                             f'fill="#141414" fill-opacity="{op:.2f}"/>')
        # площадка-карниз сверху (видимая часть эллипса), её перекроет следующий ярус
        if i == n - 1:
            parts.append(f'<ellipse cx="{CX}" cy="{yt:.2f}" rx="{at:.2f}" ry="{rt:.2f}" fill="url(#top)"/>')
        else:
            parts.append(f'<ellipse cx="{CX}" cy="{yt:.2f}" rx="{at:.2f}" ry="{rt:.2f}" fill="url(#top)" data-ledge="1"/>')
    return parts

def svg(small=False):
    if small:
        n, W, yb, yt, arches = 4, 60, 232, 80, False
        r = 23
    else:
        n, W, yb, yt, arches = 9, 60, 240, 70, True
        r = 11
    # рисуем ярусы снизу вверх, но каждый следующий должен перекрыть площадку предыдущего:
    parts = tower(n, W, yb, yt, arches=arches)
    top_a = halfw(1, W) * 1.07
    cy = yt - top_a * 0.16 - r - (4 if small else 8)
    swirl = ""
    if not small:
        rings = []
        for j, (rx, op) in enumerate(((34, .16), (52, .10), (72, .06))):
            rings.append(f'<ellipse cx="128" cy="{cy:.1f}" rx="{rx}" ry="{rx*0.30:.1f}" fill="none" stroke="#ff3b3b" stroke-opacity="{op}" stroke-width="2" stroke-dasharray="{rx*1.6:.0f} {rx*0.9:.0f}" transform="rotate({-8+j*6} 128 {cy:.1f})"/>')
        swirl = "\n".join(rings)
    glow = '' if small else f'<circle cx="128" cy="{cy:.1f}" r="{r*3.6:.1f}" fill="url(#glow)"/>'
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
<defs>
<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#191919"/><stop offset="1" stop-color="#040404"/></linearGradient>
<linearGradient id="cyl" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#cfcfcf"/><stop offset=".22" stop-color="#ffffff"/><stop offset=".55" stop-color="#e6e6e6"/><stop offset="1" stop-color="#7d7d7d"/></linearGradient>
<linearGradient id="top" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#f2f2f2"/><stop offset="1" stop-color="#a9a9a9"/></linearGradient>
<radialGradient id="glow"><stop offset="0" stop-color="#ff3b3b" stop-opacity=".6"/><stop offset=".4" stop-color="#ff3b3b" stop-opacity=".18"/><stop offset="1" stop-color="#ff3b3b" stop-opacity="0"/></radialGradient>
<clipPath id="sq"><rect x="2" y="2" width="252" height="252" rx="58"/></clipPath>
</defs>
<rect x="2" y="2" width="252" height="252" rx="58" fill="url(#bg)"/>
<g clip-path="url(#sq)">{swirl}{glow}</g>
<g clip-path="url(#sq)">{chr(10).join(parts)}</g>
<rect x="2.5" y="2.5" width="251" height="251" rx="57.5" fill="none" stroke="#ffffff" stroke-opacity=".12" stroke-width="{4 if small else 2}"/>
<circle cx="128" cy="{cy:.1f}" r="{r}" fill="#ff3b3b"/>
</svg>'''

open("babylon.svg", "w").write(svg())
open("babylon_small.svg", "w").write(svg(True))
