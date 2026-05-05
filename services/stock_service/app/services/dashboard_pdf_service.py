from __future__ import annotations

from datetime import datetime
from io import BytesIO
from math import cos, sin, pi
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

PAGE_W, PAGE_H = landscape(A4)
MARGIN = 22
NAVY = colors.HexColor("#0F172A")
SKY = colors.HexColor("#38BDF8")
BLUE = colors.HexColor("#1D4ED8")
PETROL = colors.HexColor("#0E7490")
RED = colors.HexColor("#DC2626")
SLATE = colors.HexColor("#64748B")
BORDER = colors.HexColor("#DBEAFE")
BG = colors.HexColor("#F8FAFC")
WHITE = colors.white
SUCCESS = colors.HexColor("#0284C7")
MUTED = colors.HexColor("#EAF1FB")

COLOR_MAP = {
    "danger": RED,
    "rupture": RED,
    "warning": PETROL,
    "critique": PETROL,
    "success": SUCCESS,
    "normal": SUCCESS,
    "good": SUCCESS,
    "neutral": SLATE,
    "stable": SLATE,
    "info": BLUE,
    "surstock": BLUE,
}

DESCRIPTIONS = {
    "pricing": {
        "price_evolution": "Suivi des prix internes par rapport aux prix concurrents collectés.",
        "recommendation_distribution": "Répartition des recommandations pricing : hausse, baisse et stabilité.",
        "market_position_by_category": "Comparaison des catégories selon leur positionnement marché.",
        "discount_by_category": "Lecture des remises moyennes appliquées par catégorie.",
    },
    "stock": {
        "top_restock": "Produits prioritaires classés selon la quantité à commander.",
        "stock_status_distribution": "Répartition actuelle des produits : rupture, critique, normal ou surstock.",
        "category_risk": "Catégories les plus exposées aux ruptures et aux stocks critiques.",
        "sales_by_category": "Volume des ventes regroupé par catégorie sur la période sélectionnée.",
    },
    "manager": {
        "sales_trend": "Suivi du chiffre d’affaires et des unités vendues sur la période.",
        "stock_status_distribution": "Vue globale de l’état du stock pour détecter les risques opérationnels.",
        "finance_by_category": "Comparaison du chiffre d’affaires et du profit estimé par catégorie.",
        "stock_sales": "Relation entre le stock moyen disponible et les ventes réalisées.",
    },
}

TITLES = {
    "stock": "Dashboard Stock",
    "pricing": "Dashboard Pricing",
    "manager": "Dashboard Manager",
}


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
    n = _safe_num(value, None)
    if n is None:
        return str(value)
    if unit == "TND":
        return f"{n / 1_000_000:.1f}".replace(".", ",") + " MTND"
    if unit == "%":
        return f"{round(n):,}".replace(",", " ") + " %"
    return f"{round(n):,}".replace(",", " ")


def _period_label(days: Any) -> str:
    days = int(_safe_num(days, 30))
    return {7: "7 jours", 30: "1 mois", 60: "2 mois", 180: "6 mois", 365: "12 mois"}.get(days, f"{days} jours")


def _filter_summary(data: dict[str, Any], filters: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    filters = filters or {}
    api_filters = data.get("filters") or {}
    return [
        ("Période", _period_label(filters.get("period_days") or api_filters.get("period_days") or 30)),
        ("Catégorie", filters.get("categorie") or "Toutes"),
        ("Marque", filters.get("marque") or "Toutes"),
        ("Statut stock", filters.get("statut_stock") or "Tous"),
        ("Position marché", filters.get("position_marche") or "Toutes"),
    ]


def _round_rect(c: canvas.Canvas, x: float, y: float, w: float, h: float, fill=WHITE, stroke=BORDER, radius: float = 10):
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(0.8)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1)


def _text(c: canvas.Canvas, x: float, y: float, txt: str, size: int = 9, color=NAVY, bold: bool = False):
    c.setFillColor(color)
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    c.drawString(x, y, str(txt))


def _fit_text(c: canvas.Canvas, txt: str, max_width: float, font="Helvetica", size=8) -> str:
    txt = str(txt or "")
    if c.stringWidth(txt, font, size) <= max_width:
        return txt
    while txt and c.stringWidth(txt + "…", font, size) > max_width:
        txt = txt[:-1]
    return txt + "…"


def _kpi_cards(c: canvas.Canvas, kpis: list[dict[str, Any]], x: float, y: float, w: float) -> float:
    shown = kpis[:6]
    gap = 7
    card_w = (w - gap * (len(shown) - 1)) / max(len(shown), 1)
    card_h = 48
    for i, item in enumerate(shown):
        cx = x + i * (card_w + gap)
        status = item.get("status", "neutral")
        _round_rect(c, cx, y - card_h, card_w, card_h, fill=WHITE)
        _text(c, cx + 8, y - 15, _fit_text(c, item.get("label", "KPI").upper(), card_w - 35, size=6), 6, SLATE, True)
        badge = "OK" if status == "good" else "Alerte" if status == "danger" else "Info" if status == "neutral" else "À suivre"
        badge_color = COLOR_MAP.get(status, PETROL)
        c.setFillColor(colors.Color(badge_color.red, badge_color.green, badge_color.blue, alpha=0.12))
        c.roundRect(cx + card_w - 36, y - 18, 28, 10, 5, fill=1, stroke=0)
        _text(c, cx + card_w - 32, y - 15, badge, 5.2, badge_color, True)
        _text(c, cx + 8, y - 35, _fmt(item.get("value"), item.get("unit", "")), 14, NAVY, True)
    return y - card_h - 12


def _panel(c: canvas.Canvas, x: float, y: float, w: float, h: float, title: str, description: str = ""):
    _round_rect(c, x, y - h, w, h, fill=WHITE)
    _text(c, x + 10, y - 16, title, 9, NAVY, True)
    if description:
        c.setFillColor(BG)
        c.setStrokeColor(BORDER)
        c.roundRect(x + 8, y - h + 8, w - 16, 14, 5, fill=1, stroke=1)
        _text(c, x + 13, y - h + 13, _fit_text(c, description, w - 30, size=6), 6, SLATE, True)


def _line_chart(c: canvas.Canvas, x: float, y: float, w: float, h: float, rows: list[dict[str, Any]], keys: list[tuple[str, Any]], title: str, desc: str):
    _panel(c, x, y, w, h, title, desc)
    area_x, area_y = x + 32, y - h + 34
    area_w, area_h = w - 52, h - 62
    if not rows:
        _text(c, x + 12, y - 40, "Aucune donnée", 8, SLATE)
        return
    vals = []
    for r in rows:
        for k, _ in keys:
            if r.get(k) is not None:
                vals.append(_safe_num(r.get(k)))
    max_v = max(vals or [1])
    min_v = min(vals or [0])
    if max_v == min_v:
        max_v += 1
    c.setStrokeColor(colors.HexColor("#E2E8F0"))
    c.setLineWidth(0.5)
    for i in range(4):
        yy = area_y + i * area_h / 3
        c.line(area_x, yy, area_x + area_w, yy)
    for key, col in keys:
        c.setStrokeColor(col)
        c.setLineWidth(1.6)
        prev = None
        for i, r in enumerate(rows[:24]):
            val = _safe_num(r.get(key), None)
            if val is None:
                continue
            px = area_x + (i / max(len(rows[:24]) - 1, 1)) * area_w
            py = area_y + ((val - min_v) / (max_v - min_v)) * area_h
            if prev:
                c.line(prev[0], prev[1], px, py)
            prev = (px, py)
    c.setStrokeColor(colors.HexColor("#CBD5E1"))
    c.rect(area_x, area_y, area_w, area_h, stroke=1, fill=0)


def _bar_chart(c: canvas.Canvas, x: float, y: float, w: float, h: float, rows: list[dict[str, Any]], key: str, label_key: str, title: str, desc: str, color=BLUE):
    _panel(c, x, y, w, h, title, desc)
    rows = rows[:8]
    if not rows:
        _text(c, x + 12, y - 40, "Aucune donnée", 8, SLATE)
        return
    area_x, area_y = x + 100, y - h + 36
    area_w, area_h = w - 120, h - 66
    max_v = max([_safe_num(r.get(key)) for r in rows] or [1]) or 1
    bar_h = min(12, area_h / max(len(rows), 1) - 3)
    for i, r in enumerate(rows):
        yy = area_y + area_h - (i + 1) * (bar_h + 4)
        label = _fit_text(c, r.get(label_key) or r.get("categorie") or r.get("name") or "—", 82, size=6)
        _text(c, x + 10, yy + 3, label, 6, SLATE, True)
        bw = (_safe_num(r.get(key)) / max_v) * area_w
        c.setFillColor(color)
        c.roundRect(area_x, yy, bw, bar_h, 4, fill=1, stroke=0)
        _text(c, area_x + bw + 4, yy + 3, str(round(_safe_num(r.get(key)))), 6, NAVY, True)


def _stacked_chart(c: canvas.Canvas, x: float, y: float, w: float, h: float, rows: list[dict[str, Any]], keys: list[tuple[str, Any]], title: str, desc: str):
    _panel(c, x, y, w, h, title, desc)
    rows = rows[:8]
    if not rows:
        _text(c, x + 12, y - 40, "Aucune donnée", 8, SLATE)
        return
    area_x, area_y = x + 42, y - h + 36
    area_w, area_h = w - 62, h - 70
    max_v = max([sum(_safe_num(r.get(k)) for k, _ in keys) for r in rows] or [1]) or 1
    gap = 6
    bar_w = max(10, (area_w - gap * (len(rows)-1)) / max(len(rows), 1))
    for i, r in enumerate(rows):
        bx = area_x + i * (bar_w + gap)
        current_y = area_y
        for k, col in keys:
            val = _safe_num(r.get(k))
            bh = (val / max_v) * area_h
            c.setFillColor(col)
            c.rect(bx, current_y, bar_w, bh, fill=1, stroke=0)
            current_y += bh
        _text(c, bx, area_y - 10, _fit_text(c, r.get("categorie", ""), bar_w + 8, size=5), 5, SLATE)


def _donut(c: canvas.Canvas, x: float, y: float, w: float, h: float, rows: list[dict[str, Any]], title: str, desc: str):
    _panel(c, x, y, w, h, title, desc)
    if not rows:
        _text(c, x + 12, y - 40, "Aucune donnée", 8, SLATE)
        return
    cx, cy = x + w / 2, y - h / 2 + 6
    r = min(w, h) * 0.18
    total = sum(_safe_num(row.get("value")) for row in rows) or 1
    start = 90
    for row in rows:
        value = _safe_num(row.get("value"))
        extent = value / total * 360
        col = COLOR_MAP.get(row.get("colorKey"), COLOR_MAP.get(row.get("name"), BLUE))
        c.setFillColor(col)
        c.wedge(cx-r, cy-r, cx+r, cy+r, start, start - extent, fill=1, stroke=0)
        start -= extent
    c.setFillColor(WHITE)
    c.circle(cx, cy, r * 0.55, fill=1, stroke=0)
    legend_x = x + w - 92
    ly = y - 38
    for row in rows[:5]:
        col = COLOR_MAP.get(row.get("colorKey"), COLOR_MAP.get(row.get("name"), BLUE))
        c.setFillColor(col)
        c.circle(legend_x, ly + 3, 3, fill=1, stroke=0)
        _text(c, legend_x + 8, ly, f"{row.get('name')} {round(_safe_num(row.get('value')))}", 6, SLATE, True)
        ly -= 11


def _top_restock(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = data.get("tables", {}).get("restock_priorities", []) or []
    out = []
    for row in rows:
        qty = _safe_num(row.get("quantite_a_commander"), None)
        if qty is None:
            qty = max(0, _safe_num(row.get("seuil_min")) - _safe_num(row.get("stock")))
        if qty > 0:
            out.append({"produit": row.get("produit") or row.get("sku"), "qty": qty, "statut": row.get("statut")})
    return sorted(out, key=lambda r: r["qty"], reverse=True)[:8]


def build_dashboard_pdf(dashboard_type: str, data: dict[str, Any], filters: dict[str, Any] | None = None) -> bytes:
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(A4))
    c.setTitle(TITLES.get(dashboard_type, "Dashboard"))

    # Background
    c.setFillColor(colors.HexColor("#F8FAFC"))
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    _round_rect(c, MARGIN, PAGE_H - MARGIN, PAGE_W - 2*MARGIN, PAGE_H - 2*MARGIN, fill=WHITE, stroke=BORDER, radius=14)

    x = MARGIN + 14
    y = PAGE_H - MARGIN - 18
    content_w = PAGE_W - 2*MARGIN - 28

    _text(c, x, y, TITLES.get(dashboard_type, "Dashboard"), 16, NAVY, True)
    updated = data.get("updated_at")
    _text(c, x + 175, y + 1, f"MAJ {datetime.now().strftime('%d/%m/%Y %H:%M')}", 7, SLATE, True)
    y -= 20

    # filters
    fx = x
    for label, value in _filter_summary(data, filters):
        pill_w = 96 if label == "Position marché" else 84
        c.setFillColor(BG)
        c.setStrokeColor(BORDER)
        c.roundRect(fx, y - 10, pill_w, 14, 6, fill=1, stroke=1)
        _text(c, fx + 5, y - 6, f"{label}: {value}", 5.6, SLATE, True)
        fx += pill_w + 5
    y -= 20

    y = _kpi_cards(c, data.get("kpis", []), x, y, content_w)

    gap = 10
    col_w = (content_w - gap) / 2
    row_h = 178
    charts = data.get("charts", {}) or {}

    if dashboard_type == "pricing":
        _line_chart(c, x, y, col_w, row_h, charts.get("price_evolution", []), [("prix_interne_moyen", BLUE), ("prix_concurrent_moyen", SKY)], "Prix interne / marché", DESCRIPTIONS["pricing"]["price_evolution"])
        _donut(c, x + col_w + gap, y, col_w, row_h, charts.get("recommendation_distribution", []), "État des recommandations", DESCRIPTIONS["pricing"]["recommendation_distribution"])
        y -= row_h + 10
        _stacked_chart(c, x, y, content_w, 155, charts.get("market_position_by_category", []), [("sous_marche", SUCCESS), ("aligne", SLATE), ("au_dessus", RED)], "Positionnement par catégorie", DESCRIPTIONS["pricing"]["market_position_by_category"])

    elif dashboard_type == "stock":
        _bar_chart(c, x, y, col_w, row_h, _top_restock(data), "qty", "produit", "Top produits à commander", DESCRIPTIONS["stock"]["top_restock"], PETROL)
        _donut(c, x + col_w + gap, y, col_w, row_h, charts.get("stock_status_distribution", []), "Santé actuelle du stock", DESCRIPTIONS["stock"]["stock_status_distribution"])
        y -= row_h + 10
        _stacked_chart(c, x, y, col_w, 155, charts.get("category_risk", []), [("rupture", RED), ("critique", PETROL), ("normal", SUCCESS), ("surstock", BLUE)], "Risques par catégorie", DESCRIPTIONS["stock"]["category_risk"])
        _bar_chart(c, x + col_w + gap, y, col_w, 155, charts.get("sales_by_category", []), "units", "categorie", "Ventes par catégorie", DESCRIPTIONS["stock"]["sales_by_category"], SKY)

    else:
        _line_chart(c, x, y, col_w, row_h, charts.get("sales_trend", []), [("revenue", BLUE), ("units", SKY)], "Évolution commerciale", DESCRIPTIONS["manager"]["sales_trend"])
        _donut(c, x + col_w + gap, y, col_w, row_h, charts.get("stock_status_distribution", []), "Santé actuelle du stock", DESCRIPTIONS["manager"]["stock_status_distribution"])
        y -= row_h + 10
        _stacked_chart(c, x, y, col_w, 155, charts.get("finance_by_category", []), [("revenue", BLUE), ("profit", PETROL)], "CA / profit par catégorie", DESCRIPTIONS["manager"]["finance_by_category"])
        _line_chart(c, x + col_w + gap, y, col_w, 155, charts.get("sales_trend", []), [("stock_avg", PETROL), ("units", SKY)], "Stock moyen / ventes", DESCRIPTIONS["manager"]["stock_sales"])

    c.showPage()
    c.save()
    return buffer.getvalue()
