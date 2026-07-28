"""
Dependency-free SVG chart helpers.

WeasyPrint renders inline SVG natively, so we generate crisp vector charts
without matplotlib. Everything returns an SVG string that can be dropped
straight into the report HTML.
"""

import html

# A calm, professional palette for a "sellable" report.
PALETTE = ["#2c6fbb", "#e08e0b", "#3aa76d", "#c0504d", "#8064a2",
           "#4bacc6", "#f79646", "#9bbb59", "#7f7f7f", "#264478"]


def _svg_open(width, height):
    # display:block avoids WeasyPrint's inline-replaced-box layout bug.
    return (f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
            f'preserveAspectRatio="xMidYMid meet" '
            f'style="display:block;max-width:100%;height:auto;'
            f'font-family:Tahoma,Arial,sans-serif" '
            f'xmlns="http://www.w3.org/2000/svg">')


def _fmt(n):
    """Human-friendly number formatting (1,234 or 1.2M)."""

    try:
        n = float(n)
    except (TypeError, ValueError):
        return str(n)
    if abs(n) >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if abs(n) >= 1_000:
        return f"{n/1_000:.0f}K"
    return f"{n:.0f}"


def bar_chart(data, width=560, bar_height=26, gap=12, pad_left=150,
              pad_right=60, pad_top=20, pad_bottom=20, color=None, title=None):
    """
    Horizontal bar chart.
    `data` is a list of (label, value) tuples.
    """
    data = [(str(l), float(v or 0)) for l, v in data]
    if not data:
        return "<p style='color:#888'>No data available.</p>"

    max_val = max((v for _, v in data), default=1) or 1
    plot_w = width - pad_left - pad_right
    height = pad_top + pad_bottom + len(data) * (bar_height + gap)
    if title:
        height += 30
        y0 = pad_top + 30
    else:
        y0 = pad_top

    parts = [_svg_open(width, height)]

    if title:
        parts.append(
            f'<text x="{width/2}" y="20" text-anchor="middle" '
            f'font-size="14" font-weight="bold" fill="#2c3e50">{html.escape(title)}</text>'
        )

    for i, (label, val) in enumerate(data):
        y = y0 + i * (bar_height + gap)

        bar_w = (val / max_val) * plot_w if max_val else 0
        fill = color or PALETTE[i % len(PALETTE)]
        # label
        parts.append(
            f'<text x="{pad_left - 8}" y="{y + bar_height*0.7}" text-anchor="end" '
            f'font-size="12" fill="#333">{html.escape(label[:24])}</text>'
        )
        # bar
        parts.append(
            f'<rect x="{pad_left}" y="{y}" width="{bar_w:.1f}" height="{bar_height}" '
            f'rx="4" fill="{fill}"><title>{html.escape(label)}: {_fmt(val)}</title></rect>'
        )
        # value
        parts.append(
            f'<text x="{pad_left + bar_w + 6:.1f}" y="{y + bar_height*0.7}" '
            f'font-size="11" fill="#555">{_fmt(val)}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


def grouped_bar_chart(categories, series, width=620, height=320,
                      pad_left=60, pad_right=20, pad_top=40, pad_bottom=70,
                      title=None):
    """
    Vertical grouped bar chart for comparisons.
    `categories`: list of category labels (x axis).
    `series`: list of (name, [values]) — one group per category.
    """
    if not categories or not series:
        return "<p style='color:#888'>No data available.</p>"

    all_vals = [v for _, vals in series for v in vals if v is not None]
    max_val = max(all_vals, default=1) or 1
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom
    n_cat = len(categories)
    n_ser = len(series)
    group_w = plot_w / n_cat
    bar_w = group_w / (n_ser + 1)

    parts = [_svg_open(width, height)]

    if title:
        parts.append(
            f'<text x="{width/2}" y="22" text-anchor="middle" '

            f'font-size="14" font-weight="bold" fill="#2c3e50">{html.escape(title)}</text>'
        )

    base_y = pad_top + plot_h
    # axis
    parts.append(f'<line x1="{pad_left}" y1="{base_y}" x2="{pad_left+plot_w}" '
                 f'y2="{base_y}" stroke="#ccc" stroke-width="1"/>')

    for ci, cat in enumerate(categories):
        gx = pad_left + ci * group_w
        for si, (name, vals) in enumerate(series):
            val = vals[ci] if ci < len(vals) and vals[ci] is not None else 0
            bh = (val / max_val) * plot_h if max_val else 0
            x = gx + (si + 0.5) * bar_w
            y = base_y - bh
            fill = PALETTE[si % len(PALETTE)]
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w*0.9:.1f}" height="{bh:.1f}" '
                f'rx="3" fill="{fill}"><title>{html.escape(name)} - {html.escape(cat)}: {_fmt(val)}</title></rect>'
            )
        # category label
        parts.append(
            f'<text x="{gx + group_w/2:.1f}" y="{base_y + 16}" text-anchor="middle" '
            f'font-size="10" fill="#333" transform="rotate(0 {gx + group_w/2:.1f} {base_y + 16})">'
            f'{html.escape(str(cat)[:14])}</text>'
        )

    # legend
    lx = pad_left
    ly = height - 20
    for si, (name, _) in enumerate(series):
        fill = PALETTE[si % len(PALETTE)]
        parts.append(f'<rect x="{lx}" y="{ly-9}" width="11" height="11" rx="2" fill="{fill}"/>')
        parts.append(f'<text x="{lx+16}" y="{ly}" font-size="11" fill="#333">{html.escape(name)}</text>')
        lx += 20 + len(name) * 7 + 24

    parts.append("</svg>")
    return "".join(parts)


def donut_chart(data, width=300, height=240, title=None):
    """
    Donut chart. `data`: list of (label, value).
    """
    import math
    data = [(str(l), float(v or 0)) for l, v in data if (v or 0) > 0]
    if not data:
        return "<p style='color:#888'>No data available.</p>"

    total = sum(v for _, v in data) or 1
    cx, cy, r, inner = width * 0.35, height / 2, 80, 45

    parts = [_svg_open(width, height)]
    if title:
        parts.append(f'<text x="{width/2}" y="16" text-anchor="middle" '

                     f'font-size="13" font-weight="bold" fill="#2c3e50">{html.escape(title)}</text>')

    angle = -math.pi / 2
    for i, (label, val) in enumerate(data):
        frac = val / total
        end = angle + frac * 2 * math.pi
        large = 1 if frac > 0.5 else 0
        x1, y1 = cx + r * math.cos(angle), cy + r * math.sin(angle)
        x2, y2 = cx + r * math.cos(end), cy + r * math.sin(end)
        fill = PALETTE[i % len(PALETTE)]
        parts.append(
            f'<path d="M {cx} {cy} L {x1:.1f} {y1:.1f} '
            f'A {r} {r} 0 {large} 1 {x2:.1f} {y2:.1f} Z" fill="{fill}">'
            f'<title>{html.escape(label)}: {frac*100:.0f}%</title></path>'
        )
        angle = end

    # inner hole
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{inner}" fill="#ffffff"/>')

    # legend
    lx = width * 0.62
    ly = height * 0.28
    for i, (label, val) in enumerate(data):
        fill = PALETTE[i % len(PALETTE)]
        pct = val / total * 100
        parts.append(f'<rect x="{lx}" y="{ly-9}" width="11" height="11" rx="2" fill="{fill}"/>')
        parts.append(f'<text x="{lx+16}" y="{ly}" font-size="10" fill="#333">'
                     f'{html.escape(label[:16])} ({pct:.0f}%)</text>')
        ly += 20

    parts.append("</svg>")
    return "".join(parts)


def line_chart(points, width=560, height=240, pad=40, title=None, color="#2c6fbb"):
    """
    Simple line chart. `points`: list of (x_label, y_value).
    """
    points = [(str(x), float(y or 0)) for x, y in points]
    if len(points) < 2:
        return "<p style='color:#888'>Not enough data points.</p>"

    ys = [y for _, y in points]
    max_y = max(ys) or 1
    min_y = min(ys)
    span = (max_y - min_y) or 1
    plot_w = width - 2 * pad
    plot_h = height - 2 * pad
    n = len(points)

    parts = [_svg_open(width, height)]
    if title:
        parts.append(f'<text x="{width/2}" y="20" text-anchor="middle" '

                     f'font-size="14" font-weight="bold" fill="#2c3e50">{html.escape(title)}</text>')

    base_y = height - pad
    parts.append(f'<line x1="{pad}" y1="{base_y}" x2="{width-pad}" y2="{base_y}" stroke="#ccc"/>')

    def coords(i, y):
        x = pad + (i / (n - 1)) * plot_w
        yy = base_y - ((y - min_y) / span) * plot_h
        return x, yy

    path = "M " + " L ".join(f"{coords(i,y)[0]:.1f} {coords(i,y)[1]:.1f}"
                             for i, (_, y) in enumerate(points))
    parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.5"/>')

    for i, (label, y) in enumerate(points):
        x, yy = coords(i, y)
        parts.append(f'<circle cx="{x:.1f}" cy="{yy:.1f}" r="3.5" fill="{color}">'
                     f'<title>{html.escape(label)}: {_fmt(y)}</title></circle>')

    parts.append("</svg>")
    return "".join(parts)
