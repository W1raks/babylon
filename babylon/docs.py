"""Перевод документов с сохранением оформления: docx, pdf, txt/md, srt.

- docx (python-docx): каждый абзац (и в таблицах, колонтитулах) переводится целиком, перевод
  ставится в самый длинный кусок текста абзаца — стиль, шрифт, размер, таблицы и картинки остаются.
- pdf (PyMuPDF): строки собираются в абзацы (как для фото), исходный текст убирается без
  затирания фона, перевод вписывается в ту же рамку тем же цветом и размером (уменьшается, если длиннее).
- srt: время каждой реплики сохраняется, переводится только текст.
translate_many(список текстов) → список переводов — передаёт программа (параллельно и с памятью).
"""
import os
import re

from .ocr import Line

EXT = (".docx", ".pdf", ".txt", ".md", ".srt")


class DocError(Exception):
    pass


def out_name(path: str, tgt: str) -> str:
    base, ext = os.path.splitext(path)
    return f"{base} (перевод {tgt}){ext}"


def translate_file(path: str, out: str, translate_many, progress=None) -> int:
    """Перевести файл; вернуть, сколько фрагментов переведено."""
    ext = os.path.splitext(path)[1].lower()
    fn = {".docx": _docx, ".pdf": _pdf, ".txt": _text, ".md": _text, ".srt": _srt}.get(ext)
    if fn is None:
        raise DocError("такой файл не умею: подойдут docx, pdf, txt, md, srt")
    return fn(path, out, translate_many, progress or (lambda d, t: None))


def _batch(texts: list[str], translate_many, progress) -> dict[str, str]:
    """Уникальные тексты → переводы, порциями (чтобы показывать прогресс)."""
    uniq = list(dict.fromkeys(t for t in texts if t.strip()))
    done: dict[str, str] = {}
    step = 16
    for i in range(0, len(uniq), step):
        part = uniq[i:i + step]
        for src, tr in zip(part, translate_many(part)):
            done[src] = tr or src
        progress(min(i + step, len(uniq)), len(uniq))
    return done


# ---------------- docx ----------------
def _docx_paragraphs(doc):
    def from_container(c):
        for p in c.paragraphs:
            yield p
        for t in getattr(c, "tables", []):
            for row in t.rows:
                for cell in row.cells:
                    yield from from_container(cell)

    yield from from_container(doc)
    for s in doc.sections:
        for part in (s.header, s.footer, s.first_page_header, s.first_page_footer):
            try:
                if not part.is_linked_to_previous:
                    yield from from_container(part)
            except Exception:
                pass


def _docx(path, out, translate_many, progress) -> int:
    import docx

    try:
        doc = docx.Document(path)
    except Exception as e:
        raise DocError(f"не открылся документ: {e}") from e
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
    paras, seen = [], set()
    for p in _docx_paragraphs(doc):
        if id(p._p) in seen:  # объединённые ячейки таблицы повторяются
            continue
        seen.add(id(p._p))
        nodes = [n for n in p._p.iter(W)]
        text = "".join(n.text or "" for n in nodes)
        if text.strip() and re.search(r"[^\W\d_]", text):
            paras.append((nodes, text))
    tr = _batch([t for _, t in paras], translate_many, progress)
    n = 0
    for nodes, text in paras:
        out_text = tr.get(text)
        if not out_text or out_text == text:
            continue
        main = max(nodes, key=lambda x: len(x.text or ""))  # оформление самого длинного куска
        lead = text[: len(text) - len(text.lstrip())]
        for x in nodes:
            x.text = ""
        main.text = lead + out_text.strip()
        main.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        n += 1
    doc.save(out)
    return n


# ---------------- pdf ----------------
def _pdf(path, out, translate_many, progress) -> int:
    import pymupdf as fitz

    from . import lens

    try:
        doc = fitz.open(path)
    except Exception as e:
        raise DocError(f"не открылся pdf: {e}") from e
    pages = []
    for page in doc:
        lines, style = [], {}
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") != 0:
                continue
            for ln in b["lines"]:
                spans = [s for s in ln["spans"] if s["text"].strip()]
                if not spans:
                    continue
                text = "".join(s["text"] for s in ln["spans"]).strip()
                x0, y0, x1, y1 = ln["bbox"]
                obj = Line(text, x0, y0, x1 - x0, y1 - y0)
                big = max(spans, key=lambda s: len(s["text"]))
                style[id(obj)] = (big["size"], big["color"], bool(big["flags"] & 16), ln["dir"])
                lines.append(obj)
        blocks = [b for b in lens.group(lines) if re.search(r"[^\W\d_]", b.text)]
        pages.append((page, blocks, style))
    if not any(b for _, b, _ in pages):
        raise DocError("в этом pdf нет текста, только картинки (скан) — переведите страницы как фото")
    texts = [" ".join(b.text.split("\n")) for _, blocks, _ in pages for b in blocks]
    tr = _batch(texts, translate_many, progress)
    n = 0
    for page, blocks, style in pages:
        todo = []
        for b in blocks:
            src = " ".join(b.text.split("\n"))
            out_text = tr.get(src)
            if not out_text or out_text == src:
                continue
            size, color, bold, d = style[id(b.lines[0])]
            if abs(d[1]) > 0.1:  # повёрнутый текст оставляем как есть
                continue
            rect = fitz.Rect(b.x, b.y, b.x + b.w, b.y + b.h)
            if len(b.lines) == 1:  # одна строка: даём переводу место правее, если там пусто
                right = min(page.rect.width - 30, rect.x1 + rect.width * 0.6)
                for o in blocks:
                    if o is not b and o.x >= rect.x1 - 1 and o.y < rect.y1 and o.y + o.h > rect.y0:
                        right = min(right, o.x - 6)
                rect.x1 = max(rect.x1, right)
            page.add_redact_annot(rect, fill=False)  # убрать текст, не трогая фон и рисунки
            todo.append((rect, out_text, size, color, bold, b.centered))
        if not todo:
            continue
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
        for rect, text, size, color, bold, centered in todo:
            css = (f"* {{ font-family: sans-serif; font-size: {size:.1f}px; color: #{color:06x}; "
                   f"font-weight: {'bold' if bold else 'normal'}; text-align: {'center' if centered else 'left'}; "
                   f"line-height: 1.15; margin: 0; }}")
            box = fitz.Rect(rect.x0, rect.y0, rect.x1 + 2, rect.y1 + size * 0.6)
            page.insert_htmlbox(box, _html(text), css=css)
            n += 1
    doc.save(out, garbage=3, deflate=True)
    return n


def _html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------- txt / md ----------------
def _text(path, out, translate_many, progress) -> int:
    raw = _read(path)
    parts = re.split(r"(\n\s*\n)", raw)  # абзацы и пустые строки между ними
    key = lambda p: " ".join(p.split())  # noqa: E731  абзац одной строкой
    paras = [p for p in parts if p.strip() and not re.fullmatch(r"\n\s*\n", p)]
    tr = _batch([key(p) for p in paras], translate_many, progress)
    res, n = [], 0
    for p in parts:
        if p.strip() and key(p) in tr:
            lead, trail = p[: len(p) - len(p.lstrip())], p[len(p.rstrip()):]
            res.append(lead + tr[key(p)] + trail)
            n += 1
        else:
            res.append(p)
    with open(out, "w", encoding="utf-8") as f:
        f.write("".join(res))
    return n


# ---------------- srt ----------------
_CUE = re.compile(r"(\d+)\s*\n(\d\d:\d\d:\d\d[,.]\d+\s*-->\s*\d\d:\d\d:\d\d[,.]\d+[^\n]*)\n(.*?)(?=\n\s*\n|\Z)", re.S)


def _srt(path, out, translate_many, progress) -> int:
    raw = _read(path).replace("\r\n", "\n")
    cues = _CUE.findall(raw)
    if not cues:
        raise DocError("в файле не нашлось субтитров srt")
    clean = lambda t: re.sub(r"<[^>]+>", "", " ".join(t.split("\n"))).strip()  # noqa: E731
    tr = _batch([clean(t) for _, _, t in cues], translate_many, progress)
    with open(out, "w", encoding="utf-8") as f:
        for num, when, text in cues:
            f.write(f"{num}\n{when}\n{tr.get(clean(text), text)}\n\n")
    return len(cues)


def _read(path: str) -> str:
    for enc in ("utf-8-sig", "cp1251", "latin-1"):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise DocError("не удалось прочитать текст файла")
