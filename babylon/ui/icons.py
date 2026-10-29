"""Линейные иконки (SVG, рисуются в нужном цвете)."""
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_P = {
    "copy": '<rect x="9" y="9" width="12" height="12" rx="2.5"/><path d="M5 15H4.5A1.5 1.5 0 0 1 3 13.5v-9A1.5 1.5 0 0 1 4.5 3h9A1.5 1.5 0 0 1 15 4.5V5"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "pin": '<path d="M12 17v5"/><path d="M8 3h8l-1 6 3 4H6l3-4z"/>',
    "expand": '<path d="M14 4h6v6"/><path d="M20 4l-7 7"/><path d="M10 20H4v-6"/><path d="M4 20l7-7"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "swap": '<path d="M7 7h13l-4-4"/><path d="M17 17H4l4 4"/>',
    "scan": '<path d="M4 8V5.5A1.5 1.5 0 0 1 5.5 4H8M16 4h2.5A1.5 1.5 0 0 1 20 5.5V8M20 16v2.5a1.5 1.5 0 0 1-1.5 1.5H16M8 20H5.5A1.5 1.5 0 0 1 4 18.5V16"/><path d="M8 10h8M8 14h5"/>',
    "download": '<path d="M12 4v11"/><path d="M7 10.5l5 5 5-5"/><path d="M5 20h14"/>',
    "trash": '<path d="M4 7h16"/><path d="M9 7V4.5h6V7"/><path d="M6.5 7l1 13h9l1-13"/>',
    "star": '<path d="M12 3.5l2.6 5.3 5.9.9-4.25 4.1 1 5.8L12 16.9l-5.25 2.7 1-5.8L3.5 9.7l5.9-.9z"/>',
    "star-fill": '<path fill="currentColor" d="M12 3.5l2.6 5.3 5.9.9-4.25 4.1 1 5.8L12 16.9l-5.25 2.7 1-5.8L3.5 9.7l5.9-.9z"/>',
    "translate": '<path d="M4 5h9M8.5 3v2M6 5c.6 3 2.4 5.4 5 6.5M11 5c-.8 3.6-3.3 6.4-7 7.5"/><path d="M12.5 20l4-9 4 9M14 17h5"/>',
    "book": '<path d="M5 4.5h9.5a2 2 0 0 1 2 2V20H7a2 2 0 0 1-2-2z"/><path d="M5 18a2 2 0 0 1 2-2h9.5"/><path d="M9 8.5h4"/>',
    "clock": '<circle cx="12" cy="12" r="8"/><path d="M12 7.5V12l3 2"/>',
    "globe": '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.4 2.4 3.4 5.3 3.4 8.5s-1 6.1-3.4 8.5c-2.4-2.4-3.4-5.3-3.4-8.5s1-6.1 3.4-8.5z"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 3.5v2M12 18.5v2M3.5 12h2M18.5 12h2M6 6l1.4 1.4M16.6 16.6L18 18M6 18l1.4-1.4M16.6 7.4L18 6"/>',
    "search": '<circle cx="11" cy="11" r="6"/><path d="M15.5 15.5L20 20"/>',
    "chevron": '<path d="M7 10l5 5 5-5"/>',
    "replace": '<path d="M4 7h11l-3-3M20 17H9l3 3"/>',
    "mic": '<rect x="9" y="3.5" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v2.5"/>',
    "doc": '<path d="M6.5 3.5h7l4 4v13h-11z"/><path d="M13.5 3.5v4h4M9 12h6M9 15.5h6"/>',
    "palette": '<path d="M12 3.5a8.5 8.5 0 1 0 0 17c1.2 0 1.8-.8 1.8-1.7 0-1.4-1.3-1.6-1.3-2.8 0-1 .8-1.7 1.8-1.7h2.2a3.9 3.9 0 0 0 4-4c0-3.8-3.8-6.8-8.5-6.8z"/><circle cx="7.8" cy="11" r="1.1"/><circle cx="10.5" cy="7.5" r="1.1"/><circle cx="15" cy="7.8" r="1.1"/>',
    "play": '<path fill="currentColor" d="M8 5.5v13l10.5-6.5z"/>',
    "pause": '<path d="M9 6v12M15 6v12"/>',
    "film": '<rect x="3.5" y="5" width="17" height="14" rx="2.5"/><path d="M3.5 9.5h17M3.5 14.5h17M8 5v4.5M8 14.5V19M16 5v4.5M16 14.5V19"/>',
    "image": '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><circle cx="9" cy="10" r="1.8"/><path d="M4 17l5-4.5 4 3.5 3-2.5 4 3.5"/>',
    "subs": '<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="M7 15h4M13 15h4M7 11.5h7"/>',
    "minimize": '<path d="M6 12h12"/>',
    "eye-off": '<path d="M3.5 12s3-6 8.5-6c1.6 0 3 .5 4.2 1.2M20.5 12s-3 6-8.5 6c-1.6 0-3-.5-4.2-1.2"/><path d="M10 10a3 3 0 0 0 4 4M4 4l16 16"/>',
    "speaker": '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>',
}


def icon(name: str, color: str = "#f5f5f5", size: int = 18) -> QIcon:
    body = _P[name].replace("currentColor", color)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
    r = QSvgRenderer(QByteArray(svg.encode()))
    ic = QIcon()
    for scale in (1, 2):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        r.render(p, QRectF(0, 0, size * scale, size * scale))
        p.end()
        pm.setDevicePixelRatio(scale)
        ic.addPixmap(pm)
    return ic
