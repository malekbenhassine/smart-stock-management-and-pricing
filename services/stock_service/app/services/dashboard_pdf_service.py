from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

PAGE_W, PAGE_H = landscape(A4)
MARGIN = 18

# Palette application
NAVY = colors.HexColor("#081A33")
DARK_BLUE = colors.HexColor("#102A56")
BLUE = colors.HexColor("#1E3A8A")
PURPLE = colors.HexColor("#4C1D95")
MAUVE = colors.HexColor("#7C3AED")
LILAC = colors.HexColor("#C4B5FD")
LILAC_SOFT = colors.HexColor("#EDE9FE")
CREAM = colors.HexColor("#F6F2EA")
CARD = colors.HexColor("#FFFEFC")
SOFT = colors.HexColor("#F8F6FC")
BORDER = colors.HexColor("#E7E0F2")
GRID = colors.HexColor("#ECE7F5")
TEXT = colors.HexColor("#334155")
MUTED = colors.HexColor("#64748B")
WHITE = colors.white
RED = colors.HexColor("#DC2626")
AMBER = colors.HexColor("#F59E0B")
GREEN = colors.HexColor("#059669")
SKY = colors.HexColor("#38BDF8")

PALETTE = [NAVY, BLUE, PURPLE, MAUVE, LILAC, SKY]
STATUS_COLORS = {
    "danger": PURPLE,
    "rupture": PURPLE,
    "warning": MAUVE,
    "critique": MAUVE,
    "success": BLUE,
    "normal": BLUE,
    "good": BLUE,
    "neutral": MUTED,
    "stable": MUTED,
    "info": SKY,
    "surstock": SKY,
}
TITLES = {"stock": "Dashboard Responsable Stock", "pricing": "Dashboard Pricing", "manager": "Dashboard Manager"}


def _safe_num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _fmt(value: Any, unit: str = "") -> str:
    if value is None or value == "":
        return "—"
    n = _safe_num(value)
    if unit == "%":
        return f"{n:.1f}".replace(".", ",") + "%"
    if unit == "x":
        return f"{n:.2f}".replace(".", ",") + "x"
    if unit.strip() in {"u", "j"}:
        return f"{n:,.1f}".replace(",", " ").replace(".", ",") + unit
    if unit:
        return f"{n:,.1f}".replace(",", " ").replace(".", ",") + unit
    return f"{n:,.0f}".replace(",", " ")


def _period_label(days: Any) -> str:
    days = int(_safe_num(days, 30))
    return {7: "7 jours", 30: "30 jours", 60: "2 mois", 90: "90 jours", 180: "6 mois", 365: "12 mois"}.get(days, f"{days} jours")


def _text(c: canvas.Canvas, x: float, y: float, txt: Any, size: float = 8, color=TEXT, bold: bool = False):
    c.setFillColor(color)
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    c.drawString(x, y, str(txt or ""))


def _center(c: canvas.Canvas, x: float, y: float, txt: Any, size: float = 8, color=TEXT, bold: bool = False):
    c.setFillColor(color)
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    c.drawCentredString(x, y, str(txt or ""))


def _fit(c: canvas.Canvas, txt: Any, max_w: float, size: float = 7, font: str = "Helvetica") -> str:
    s = str(txt or "—")
    if c.stringWidth(s, font, size) <= max_w:
        return s
    while s and c.stringWidth(s + "…", font, size) > max_w:
        s = s[:-1]
    return s + "…"


def _wrap(c: canvas.Canvas, txt: Any, max_w: float, size: float = 6.4, max_lines: int = 2) -> list[str]:
    words = str(txt or "—").split()
    lines: list[str] = []
    line = ""
    for word in words:
        candidate = (line + " " + word).strip()
        if c.stringWidth(candidate, "Helvetica", size) <= max_w:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = word
        if len(lines) >= max_lines:
            break
    if len(lines) < max_lines and line:
        lines.append(line)
    if len(lines) == max_lines and words:
        last = lines[-1]
        while c.stringWidth(last + "…", "Helvetica", size) > max_w and last:
            last = last[:-1]
        lines[-1] = last + ("…" if last != str(txt or "—") else "")
    return lines[:max_lines]


def _card(c: canvas.Canvas, x: float, y: float, w: float, h: float, fill=CARD, stroke=BORDER, radius: float = 16):
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(0.7)
    c.roundRect(x, y - h, w, h, radius, fill=1, stroke=1)


def _section(c: canvas.Canvas, x: float, y: float, w: float, h: float, title: str, subtitle: str | None = None):
    _card(c, x, y, w, h, CARD, BORDER, 15)
    _text(c, x + 12, y - 17, title, 9.2, NAVY, True)
    if subtitle:
        _text(c, x + 12, y - 29, subtitle, 6.4, MUTED, False)


def _status_color(key: str | None):
    return STATUS_COLORS.get(str(key or "").lower(), BLUE)


def _kpi_cards(c: canvas.Canvas, kpis: list[dict[str, Any]], x: float, y: float, w: float) -> float:
    shown = (kpis or [])[:5]
    gap = 8
    card_w = (w - gap * 4) / 5
    h = 62
    for i, item in enumerate(shown):
        cx = x + i * (card_w + gap)
        accent = _status_color(item.get("status")) if item.get("status") else PALETTE[i % len(PALETTE)]
        c.setFillColor(SOFT)
        c.setStrokeColor(BORDER)
        c.roundRect(cx, y - h, card_w, h, 14, fill=1, stroke=1)
        c.setFillColor(accent)
        c.roundRect(cx, y - h, 5, h, 3, fill=1, stroke=0)
        _text(c, cx + 13, y - 16, _fit(c, item.get("label", "KPI"), card_w - 22, 7.4, "Helvetica-Bold"), 7.4, MUTED, True)
        _text(c, cx + 13, y - 38, _fmt(item.get("value"), item.get("unit", "")), 15.5, NAVY, True)
        delta = item.get("delta")
        if delta is not None:
            if item.get("key") == "stock_levels":
                delta_txt = f"Disponible {_fmt(delta, '%')}"
            elif item.get("key") == "stock_efficiency":
                delta_txt = f"Couverture {_fmt(delta, ' j')}"
            else:
                delta_txt = str(item.get("description") or "")[:36]
            _text(c, cx + 13, y - 52, _fit(c, delta_txt, card_w - 22, 6.3), 6.3, MUTED, False)
    return y - h - 10


def _product_ref(row: dict[str, Any]) -> str:
    return str(row.get("sku") or row.get("reference") or row.get("ref") or (f"#{row.get('id')}" if row.get("id") else "—"))


def _label_from(row: dict[str, Any], product_ref_only: bool = False) -> str:
    if product_ref_only:
        return _product_ref(row)
    return str(row.get("label") or row.get("produit") or row.get("categorie") or row.get("name") or "—")


def _horizontal_bars(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    rows: list[dict[str, Any]],
    title: str,
    value_key: str,
    subtitle: str | None = None,
    color=PURPLE,
    product_ref_only: bool = False,
):
    _section(c, x, y, w, h, title, subtitle)
    rows = (rows or [])[:5]
    if not rows:
        _text(c, x + 14, y - 50, "Aucune donnée disponible", 8, MUTED, True)
        return
    max_v = max([_safe_num(r.get(value_key)) for r in rows] or [1]) or 1
    bar_x = x + 14
    bar_y = y - 45
    bar_w = w - 72
    row_h = 18
    for i, row in enumerate(rows):
        yy = bar_y - i * row_h
        val = _safe_num(row.get(value_key))
        dot_col = PALETTE[i % len(PALETTE)] if color is None else color
        label = _fit(c, _label_from(row, product_ref_only=product_ref_only), bar_w * 0.58, 6.7, "Helvetica-Bold")
        c.setFillColor(dot_col)
        c.circle(bar_x + 3, yy + 10, 3.2, fill=1, stroke=0)
        _text(c, bar_x + 10, yy + 7, label, 6.7, TEXT, True)
        c.setFillColor(colors.HexColor("#EEEAF7"))
        c.roundRect(bar_x, yy - 4, bar_w, 6, 3, fill=1, stroke=0)
        c.setFillColor(dot_col)
        c.roundRect(bar_x, yy - 4, max(2, bar_w * val / max_v), 6, 3, fill=1, stroke=0)
        _text(c, x + w - 45, yy - 3, _fmt(val, "u" if value_key in {"units", "ventes_periode", "stock"} else ""), 7, NAVY, True)


def _donut_with_legend(c: canvas.Canvas, x: float, y: float, w: float, h: float, rows: list[dict[str, Any]], title: str, value_key: str, subtitle: str | None = None):
    _section(c, x, y, w, h, title, subtitle)
    rows = (rows or [])[:5]
    if not rows:
        _text(c, x + 14, y - 50, "Aucune donnée disponible", 8, MUTED, True)
        return
    total = sum(_safe_num(r.get(value_key)) for r in rows) or 1
    cx, cy = x + w * 0.30, y - h * 0.56
    r = min(w, h) * 0.28
    start = 90
    for i, row in enumerate(rows):
        value = _safe_num(row.get(value_key))
        extent = value / total * 360
        c.setFillColor(PALETTE[i % len(PALETTE)])
        c.wedge(cx - r, cy - r, cx + r, cy + r, start, start - extent, fill=1, stroke=0)
        start -= extent
    c.setFillColor(CARD)
    c.circle(cx, cy, r * 0.60, fill=1, stroke=0)
    _center(c, cx, cy + 2, _fmt(total, "u" if value_key in {"units", "stock"} else ""), 10, NAVY, True)
    _center(c, cx, cy - 10, "total", 5.8, MUTED, False)

    lx = x + w * 0.56
    ly = y - 42
    for i, row in enumerate(rows):
        col = PALETTE[i % len(PALETTE)]
        val = _safe_num(row.get(value_key))
        c.setFillColor(col)
        c.circle(lx, ly + 4, 3.4, fill=1, stroke=0)
        _text(c, lx + 9, ly + 1, _fit(c, _label_from(row), w * 0.33, 6.4, "Helvetica-Bold"), 6.4, TEXT, True)
        _text(c, x + w - 42, ly + 1, _fmt(val, "u" if value_key in {"units", "stock"} else ""), 6.4, NAVY, True)
        ly -= 13


def _line_chart(c: canvas.Canvas, x: float, y: float, w: float, h: float, rows: list[dict[str, Any]], title: str):
    _section(c, x, y, w, h, title, "Ventes journalières et stock moyen réel sur la période")
    rows = (rows or [])[-30:]
    if not rows:
        _text(c, x + 14, y - 54, "Aucune donnée disponible", 8, MUTED, True)
        return
    ax, ay = x + 42, y - h + 34
    aw, ah = w - 72, h - 72
    vals = []
    for row in rows:
        vals.extend([_safe_num(row.get("units")), _safe_num(row.get("stock_avg"))])
    max_v = max(vals or [1]) or 1

    c.setStrokeColor(GRID)
    c.setLineWidth(0.55)
    for i in range(5):
        yy = ay + (i * ah / 4)
        c.line(ax, yy, ax + aw, yy)
        _text(c, x + 13, yy - 2, _fmt(max_v * i / 4), 5.5, MUTED, False)

    def point(idx: int, row: dict[str, Any], key: str) -> tuple[float, float]:
        px = ax + (idx / max(len(rows) - 1, 1)) * aw
        py = ay + (_safe_num(row.get(key)) / max_v) * ah
        return px, py

    for key, col in [("units", PURPLE), ("stock_avg", SKY)]:
        c.setStrokeColor(col)
        c.setLineWidth(2.2)
        prev = None
        for i, row in enumerate(rows):
            px, py = point(i, row, key)
            if prev:
                c.line(prev[0], prev[1], px, py)
            prev = (px, py)
        c.setFillColor(col)
        for i, row in enumerate(rows[:: max(1, len(rows) // 8)]):
            real_i = i * max(1, len(rows) // 8)
            px, py = point(real_i, rows[real_i], key)
            c.circle(px, py, 2.2, fill=1, stroke=0)

    # Légende
    c.setFillColor(PURPLE)
    c.roundRect(x + w - 142, y - 21, 8, 8, 4, fill=1, stroke=0)
    _text(c, x + w - 130, y - 19, "Ventes", 6.5, MUTED, True)
    c.setFillColor(SKY)
    c.roundRect(x + w - 86, y - 21, 8, 8, 4, fill=1, stroke=0)
    _text(c, x + w - 74, y - 19, "Stock moyen", 6.5, MUTED, True)

    # Dates extrêmes
    first = str(rows[0].get("date") or rows[0].get("day") or "")[:10]
    last = str(rows[-1].get("date") or rows[-1].get("day") or "")[:10]
    _text(c, ax, ay - 14, first, 5.6, MUTED, False)
    _text(c, ax + aw - 34, ay - 14, last, 5.6, MUTED, False)


def _slow_products(c: canvas.Canvas, x: float, y: float, w: float, h: float, rows: list[dict[str, Any]]):
    _section(c, x, y, w, h, "Top 5 produits slow movers", "Stock élevé, ventes faibles")
    rows = (rows or [])[:5]
    if not rows:
        _text(c, x + 14, y - 50, "Aucune donnée disponible", 8, MUTED, True)
        return
    max_stock = max([_safe_num(r.get("stock")) for r in rows] or [1]) or 1
    start_y = y - 43
    for i, row in enumerate(rows):
        yy = start_y - i * 17
        label = _fit(c, row.get("produit"), w - 86, 6.3, "Helvetica-Bold")
        stock = _safe_num(row.get("stock"))
        ventes = _safe_num(row.get("ventes_periode"))
        _text(c, x + 12, yy + 5, label, 6.3, TEXT, True)
        c.setFillColor(colors.HexColor("#EEEAF7"))
        c.roundRect(x + 12, yy - 5, w - 78, 5.5, 3, fill=1, stroke=0)
        c.setFillColor(LILAC)
        c.roundRect(x + 12, yy - 5, max(2, (w - 78) * stock / max_stock), 5.5, 3, fill=1, stroke=0)
        _text(c, x + w - 58, yy - 4, f"S {_fmt(stock)}", 5.8, NAVY, True)
        _text(c, x + w - 30, yy - 4, f"V {_fmt(ventes)}", 5.8, PURPLE, True)


def _category_slow(c: canvas.Canvas, x: float, y: float, w: float, h: float, rows: list[dict[str, Any]]):
    _section(c, x, y, w, h, "Top 5 catégories slow movers", "Nombre de produits lents par catégorie")
    rows = (rows or [])[:5]
    if not rows:
        _text(c, x + 14, y - 50, "Aucune donnée disponible", 8, MUTED, True)
        return
    max_v = max([_safe_num(r.get("produits")) for r in rows] or [1]) or 1
    base_x = x + 18
    base_y = y - h + 32
    chart_w = w - 36
    chart_h = h - 65
    bar_w = min(22, chart_w / max(len(rows), 1) * 0.45)
    # Barres à gauche + légende à droite : chaque catégorie garde exactement son code couleur.
    plot_w = chart_w * 0.55
    for i, row in enumerate(rows):
        val = _safe_num(row.get("produits"))
        bh = chart_h * val / max_v
        cx = base_x + (i + 0.5) * plot_w / max(len(rows), 1)
        col = PALETTE[i % len(PALETTE)]
        c.setFillColor(col)
        c.roundRect(cx - bar_w / 2, base_y, bar_w, max(2, bh), 5, fill=1, stroke=0)
        _center(c, cx, base_y + bh + 5, _fmt(val), 6.5, NAVY, True)

    lx = x + w * 0.58
    ly = y - 42
    for i, row in enumerate(rows):
        col = PALETTE[i % len(PALETTE)]
        c.setFillColor(col)
        c.circle(lx, ly + 4, 3.2, fill=1, stroke=0)
        _text(c, lx + 8, ly + 1, _fit(c, row.get("categorie"), w * 0.32, 6.1, "Helvetica-Bold"), 6.1, TEXT, True)
        _text(c, x + w - 28, ly + 1, _fmt(row.get("produits")), 6.1, NAVY, True)
        ly -= 12


def _stock_health(c: canvas.Canvas, x: float, y: float, w: float, h: float, rows: list[dict[str, Any]]):
    _section(c, x, y, w, h, "Santé actuelle du stock", "Rupture, critique, normal, surstock")
    rows = rows or []
    total = sum(_safe_num(r.get("value")) for r in rows) or 1
    cx, cy = x + w * 0.30, y - h * 0.57
    r = min(w, h) * 0.24
    start = 90
    for i, row in enumerate(rows):
        val = _safe_num(row.get("value"))
        col = _status_color(row.get("colorKey"))
        extent = val / total * 360
        c.setFillColor(col)
        c.wedge(cx - r, cy - r, cx + r, cy + r, start, start - extent, fill=1, stroke=0)
        start -= extent
    c.setFillColor(CARD)
    c.circle(cx, cy, r * 0.62, fill=1, stroke=0)
    _center(c, cx, cy + 1, _fmt(total), 9, NAVY, True)

    lx = x + w * 0.56
    ly = y - 44
    for row in rows[:4]:
        col = _status_color(row.get("colorKey"))
        c.setFillColor(col)
        c.circle(lx, ly + 3, 3.1, fill=1, stroke=0)
        _text(c, lx + 8, ly, _fit(c, row.get("name"), w * 0.28, 6.2, "Helvetica-Bold"), 6.2, TEXT, True)
        _text(c, x + w - 28, ly, _fmt(row.get("value")), 6.2, NAVY, True)
        ly -= 13


def _restock_table(c: canvas.Canvas, x: float, y: float, w: float, h: float, rows: list[dict[str, Any]]):
    _section(c, x, y, w, h, "Réapprovisionnement prioritaire", "Produits en rupture ou sous seuil minimum")
    rows = (rows or [])[:6]
    if not rows:
        c.setFillColor(LILAC_SOFT)
        c.roundRect(x + 14, y - 60, w - 28, 34, 12, fill=1, stroke=0)
        _text(c, x + 28, y - 42, "Aucun produit prioritaire à réapprovisionner", 8, NAVY, True)
        _text(c, x + 28, y - 54, "Tous les produits sont au-dessus du seuil critique selon les données actuelles.", 6.4, MUTED, False)
        return
    header_y = y - 40
    _text(c, x + 12, header_y, "Produit", 6.2, MUTED, True)
    _text(c, x + w - 152, header_y, "Stock", 6.2, MUTED, True)
    _text(c, x + w - 110, header_y, "Seuil", 6.2, MUTED, True)
    _text(c, x + w - 66, header_y, "À commander", 6.2, MUTED, True)
    c.setStrokeColor(GRID)
    c.line(x + 12, header_y - 5, x + w - 12, header_y - 5)
    yy = header_y - 20
    for i, row in enumerate(rows):
        if i % 2 == 0:
            c.setFillColor(SOFT)
            c.roundRect(x + 10, yy - 6, w - 20, 15, 6, fill=1, stroke=0)
        _text(c, x + 14, yy, _fit(c, row.get("produit"), w - 190, 6.3, "Helvetica-Bold"), 6.3, TEXT, True)
        _text(c, x + w - 152, yy, _fmt(row.get("stock")), 6.3, NAVY, True)
        _text(c, x + w - 110, yy, _fmt(row.get("seuil_min")), 6.3, NAVY, True)
        _text(c, x + w - 66, yy, _fmt(row.get("quantite_a_commander")), 6.3, RED if row.get("priority") == "critique" else AMBER, True)
        yy -= 17


def _draw_background(c: canvas.Canvas):
    c.setFillColor(CREAM)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(colors.Color(LILAC.red, LILAC.green, LILAC.blue, alpha=0.22))
    c.circle(120, PAGE_H - 25, 95, fill=1, stroke=0)
    c.setFillColor(colors.Color(BLUE.red, BLUE.green, BLUE.blue, alpha=0.08))
    c.circle(PAGE_W - 80, PAGE_H - 42, 110, fill=1, stroke=0)
    _card(c, MARGIN, PAGE_H - MARGIN, PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN, CARD, BORDER, 22)


def _stock_pdf(c: canvas.Canvas, data: dict[str, Any], filters: dict[str, Any] | None):
    x, y = MARGIN + 16, PAGE_H - MARGIN - 17
    w = PAGE_W - 2 * MARGIN - 32
    charts = data.get("charts", {}) or {}
    tables = data.get("tables", {}) or {}

    _text(c, x, y, "Dashboard Responsable Stock", 17, NAVY, True)
    _text(c, x, y - 13, "Export PDF fidèle à la dashboard : indicateurs, courbes et valeurs visibles", 7.4, MUTED, False)
    period = _period_label((filters or {}).get("period_days") or data.get("filters", {}).get("period_days") or 30)

    # Badges période / date
    bx = x + w - 182
    for i, label in enumerate([f"Période : {period}", datetime.now().strftime("MAJ %d/%m/%Y %H:%M")]):
        bw = 82 if i == 0 else 92
        c.setFillColor(SOFT)
        c.setStrokeColor(BORDER)
        c.roundRect(bx, y - 18, bw, 18, 9, fill=1, stroke=1)
        _center(c, bx + bw / 2, y - 12, label, 6.2, MUTED, True)
        bx += bw + 8
    y -= 34

    y = _kpi_cards(c, data.get("kpis", []), x, y, w)

    gap = 10
    top_h = 140
    half = (w - gap) / 2
    _donut_with_legend(c, x, y, half, top_h, charts.get("top_categories_sold", []), "Top 5 catégories vendues", "units", "Répartition des unités vendues")
    _horizontal_bars(c, x + half + gap, y, half, top_h, charts.get("top_products_sold", []), "Top 5 produits vendus", "units", "Références produits les plus écoulées", color=None, product_ref_only=True)
    y -= top_h + 10

    _line_chart(c, x, y, w, 128, charts.get("stock_vs_sales", []), "Courbe suivi par jour")
    y -= 138

    third = (w - 2 * gap) / 3
    _slow_products(c, x, y, third, 112, charts.get("top_products_slow_movers", []) or tables.get("slow_movers", []))
    _category_slow(c, x + third + gap, y, third, 112, charts.get("top_categories_slow_movers", []))
    _stock_health(c, x + 2 * (third + gap), y, third, 112, charts.get("stock_status_distribution", []))

    # Petite table de réappro, uniquement si assez d'espace visuel dans le PDF principal.
    restock = tables.get("restock_priorities", []) or tables.get("critical_products", [])
    if restock:
        c.showPage()
        _draw_background(c)
        x2, y2 = MARGIN + 16, PAGE_H - MARGIN - 17
        w2 = PAGE_W - 2 * MARGIN - 32
        _text(c, x2, y2, "Dashboard Responsable Stock", 17, NAVY, True)
        _text(c, x2, y2 - 13, "Détail métier — réapprovisionnement prioritaire", 7.4, MUTED, False)
        _restock_table(c, x2, y2 - 34, w2, 190, restock)



def _line_two_series(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    rows: list[dict[str, Any]],
    title: str,
    key_a: str,
    label_a: str,
    key_b: str | None = None,
    label_b: str | None = None,
    unit: str = "",
):
    _section(c, x, y, w, h, title, None)
    rows = (rows or [])[-30:]
    if not rows:
        _text(c, x + 14, y - 54, "Aucune donnée disponible", 8, MUTED, True)
        return

    ax, ay = x + 44, y - h + 34
    aw, ah = w - 74, h - 74
    keys = [key_a] + ([key_b] if key_b else [])
    vals: list[float] = []
    for row in rows:
        for key in keys:
            vals.append(abs(_safe_num(row.get(key))))
    max_v = max(vals or [1]) or 1

    c.setStrokeColor(GRID)
    c.setLineWidth(0.55)
    for i in range(5):
        yy = ay + (i * ah / 4)
        c.line(ax, yy, ax + aw, yy)
        _text(c, x + 11, yy - 2, _fmt(max_v * i / 4, unit), 5.3, MUTED, False)

    def point(idx: int, row: dict[str, Any], key: str) -> tuple[float, float]:
        px = ax + (idx / max(len(rows) - 1, 1)) * aw
        py = ay + (abs(_safe_num(row.get(key))) / max_v) * ah
        return px, py

    series = [(key_a, label_a, PURPLE), (key_b, label_b or "", SKY)] if key_b else [(key_a, label_a, PURPLE)]
    for key, label, col in series:
        if not key:
            continue
        c.setStrokeColor(col)
        c.setLineWidth(2.2)
        prev = None
        for i, row in enumerate(rows):
            px, py = point(i, row, key)
            if prev:
                c.line(prev[0], prev[1], px, py)
            prev = (px, py)
        c.setFillColor(col)
        step = max(1, len(rows) // 7)
        for real_i in range(0, len(rows), step):
            px, py = point(real_i, rows[real_i], key)
            c.circle(px, py, 2.0, fill=1, stroke=0)

    lx = x + w - 152
    for idx, (_, label, col) in enumerate(series):
        c.setFillColor(col)
        c.roundRect(lx + idx * 72, y - 21, 8, 8, 4, fill=1, stroke=0)
        _text(c, lx + idx * 72 + 12, y - 19, label, 6.2, MUTED, True)

    first = str(rows[0].get("date") or rows[0].get("day") or "")[:10]
    last = str(rows[-1].get("date") or rows[-1].get("day") or "")[:10]
    _text(c, ax, ay - 14, first, 5.4, MUTED, False)
    _text(c, ax + aw - 34, ay - 14, last, 5.4, MUTED, False)


def _mini_distribution(c: canvas.Canvas, x: float, y: float, w: float, h: float, rows: list[dict[str, Any]], title: str, value_key: str = "value"):
    _section(c, x, y, w, h, title, None)
    rows = (rows or [])[:5]
    if not rows:
        _text(c, x + 12, y - 46, "Aucune donnée disponible", 7, MUTED, True)
        return
    total = sum(_safe_num(r.get(value_key)) for r in rows) or 1
    cx, cy = x + w * 0.33, y - h * 0.55
    r = min(w, h) * 0.23
    start = 90
    for i, row in enumerate(rows):
        val = _safe_num(row.get(value_key))
        col = _status_color(row.get("colorKey")) if row.get("colorKey") else PALETTE[i % len(PALETTE)]
        extent = val / total * 360
        c.setFillColor(col)
        c.wedge(cx - r, cy - r, cx + r, cy + r, start, start - extent, fill=1, stroke=0)
        start -= extent
    c.setFillColor(CARD)
    c.circle(cx, cy, r * 0.62, fill=1, stroke=0)

    lx = x + w * 0.60
    ly = y - 42
    for i, row in enumerate(rows):
        col = _status_color(row.get("colorKey")) if row.get("colorKey") else PALETTE[i % len(PALETTE)]
        c.setFillColor(col)
        c.circle(lx, ly + 3, 3.0, fill=1, stroke=0)
        _text(c, lx + 8, ly, _fit(c, row.get("name") or row.get("categorie"), w * 0.26, 5.8, "Helvetica-Bold"), 5.8, TEXT, True)
        _text(c, x + w - 24, ly, _fmt(row.get(value_key)), 5.8, NAVY, True)
        ly -= 12


def _pricing_pdf(c: canvas.Canvas, data: dict[str, Any], filters: dict[str, Any] | None):
    x, y = MARGIN + 16, PAGE_H - MARGIN - 17
    w = PAGE_W - 2 * MARGIN - 32
    charts = data.get("charts", {}) or {}
    _text(c, x, y, "Dashboard Pricing", 17, NAVY, True)
    _text(c, x, y - 13, "Export PDF : KPI, positionnement marché et courbes pricing", 7.4, MUTED, False)
    y -= 34
    y = _kpi_cards(c, data.get("kpis", []), x, y, w)
    gap = 10
    _line_two_series(c, x, y, w, 135, charts.get("market_gap_timeline", []), "Écart moyen marché", "market_gap", "Écart", unit="%")
    y -= 145
    half = (w - gap) / 2
    _line_two_series(c, x, y, half, 150, charts.get("profit_timeline", []), "Profit au cours du temps", "profit", "Profit", unit="TND")
    _mini_distribution(c, x + half + gap, y, half, 150, charts.get("categories_vs_sales", []), "Catégories vs ventes", "value")
    y -= 160
    _mini_distribution(c, x, y, half, 130, charts.get("recommendation_distribution", []), "État recommandations", "value")
    _mini_distribution(c, x + half + gap, y, half, 130, charts.get("categories_vs_profit", []), "Catégories vs profit", "value")


def _manager_pdf(c: canvas.Canvas, data: dict[str, Any], filters: dict[str, Any] | None):
    x, y = MARGIN + 16, PAGE_H - MARGIN - 17
    w = PAGE_W - 2 * MARGIN - 32
    charts = data.get("charts", {}) or {}
    _text(c, x, y, "Dashboard Manager", 17, NAVY, True)
    _text(c, x, y - 13, "Vue consolidée stock + pricing basée sur les données réelles", 7.4, MUTED, False)
    y -= 34
    allowed = {"revenue", "estimated_profit", "products_tracked", "units_sold", "promo_rate"}
    kpis = [k for k in data.get("kpis", []) if k.get("key") in allowed]
    y = _kpi_cards(c, kpis, x, y, w)
    gap = 10
    quarter = (w - 3 * gap) / 4
    _mini_distribution(c, x, y, quarter, 135, charts.get("top_categories_slow_movers", []), "Top slow movers", "stock")
    _mini_distribution(c, x + quarter + gap, y, quarter, 135, charts.get("market_position_distribution", []), "Position prix", "value")
    _mini_distribution(c, x + 2 * (quarter + gap), y, quarter, 135, charts.get("top_categories_sold", []), "Top catégories vendues", "units")
    _mini_distribution(c, x + 3 * (quarter + gap), y, quarter, 135, charts.get("stock_status_distribution", []), "Santé actuelle stock", "value")
    y -= 145
    half = (w - gap) / 2
    _line_two_series(c, x, y, half, 170, charts.get("market_gap_timeline", []), "Écart moyen marché", "market_gap", "Écart", unit="%")
    _line_two_series(c, x + half + gap, y, half, 170, charts.get("profit_timeline", []), "CA et profit au cours du temps", "revenue", "Chiffre d’affaire", "profit", "Profit", unit="TND")

def _generic_pdf(c: canvas.Canvas, dashboard_type: str, data: dict[str, Any], filters: dict[str, Any] | None):
    x, y = MARGIN + 18, PAGE_H - MARGIN - 22
    w = PAGE_W - 2 * MARGIN - 36
    _text(c, x, y, TITLES.get(dashboard_type, "Dashboard"), 17, NAVY, True)
    _text(c, x, y - 15, f"Export généré le {datetime.now().strftime('%d/%m/%Y %H:%M')}", 8, MUTED, False)
    y -= 38
    y = _kpi_cards(c, data.get("kpis", []), x, y, w)
    charts = data.get("charts", {}) or {}
    gap = 10
    half = (w - gap) / 2
    if dashboard_type == "pricing":
        _line_chart(c, x, y, half, 180, charts.get("price_evolution", []), "Prix interne / marché")
        _stock_health(c, x + half + gap, y, half, 180, charts.get("recommendation_distribution", []))
    else:
        _line_chart(c, x, y, half, 180, charts.get("sales_trend", []), "Évolution commerciale")
        _stock_health(c, x + half + gap, y, half, 180, charts.get("stock_status_distribution", []))


def build_dashboard_pdf(dashboard_type: str, data: dict[str, Any], filters: dict[str, Any] | None = None) -> bytes:
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(A4))
    c.setTitle(TITLES.get(dashboard_type, "Dashboard"))

    _draw_background(c)
    if dashboard_type == "stock":
        _stock_pdf(c, data, filters)
    elif dashboard_type == "pricing":
        _pricing_pdf(c, data, filters)
    elif dashboard_type == "manager":
        _manager_pdf(c, data, filters)
    else:
        _generic_pdf(c, dashboard_type, data, filters)

    c.showPage()
    c.save()
    return buffer.getvalue()
