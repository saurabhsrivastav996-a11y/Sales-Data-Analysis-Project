"""Validate and analyze the sample sales data, then save portfolio charts."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from html import escape
import math
from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "sales_data.csv"
VISUALS_DIR = ROOT / "visuals"
INR_PER_USD = 95.0  # Illustrative localization assumption; not a historical FX rate.

REQUIRED_COLUMNS = {
    "OrderID",
    "Date",
    "Product",
    "Category",
    "Quantity",
    "UnitPrice",
    "TotalSales",
}


def analyze_data(data_file: Path = DATA_FILE):
    """Load, validate, and aggregate the sample data.

    The source notebook labels its monetary values with ``$``. INR measures are
    therefore calculated with the documented fixed illustrative rate above.
    """
    raw = pd.read_csv(data_file)
    missing_columns = REQUIRED_COLUMNS.difference(raw.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns: {sorted(missing_columns)}")

    source_rows = len(raw)
    missing_cells = int(raw.isna().sum().sum())
    exact_duplicates = int(raw.duplicated().sum())
    df = raw.drop_duplicates().copy()

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    numeric_columns = ["OrderID", "Quantity", "UnitPrice", "TotalSales"]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    if df[sorted(REQUIRED_COLUMNS)].isna().any().any():
        raise ValueError("Required fields contain missing or invalid values.")
    if df["OrderID"].duplicated().any():
        raise ValueError("OrderID is not unique; resolve duplicate orders before analysis.")
    if (df["Quantity"] <= 0).any() or (df["UnitPrice"] <= 0).any():
        raise ValueError("Quantity and UnitPrice must both be positive.")

    expected_sales = df["Quantity"] * df["UnitPrice"]
    sales_mismatches = int((expected_sales != df["TotalSales"]).sum())
    if sales_mismatches:
        raise ValueError(f"Found {sales_mismatches} rows where TotalSales is incorrect.")

    df["UnitPriceINR"] = (df["UnitPrice"] * INR_PER_USD).round().astype("int64")
    df["TotalSalesINR"] = (df["TotalSales"] * INR_PER_USD).round().astype("int64")
    df["Month"] = df["Date"].dt.to_period("M")

    monthly_revenue = df.groupby("Month")["TotalSalesINR"].sum().sort_index()
    product_revenue = df.groupby("Product")["TotalSalesINR"].sum().sort_values(ascending=False)
    category_revenue = df.groupby("Category")["TotalSalesINR"].sum().sort_values(ascending=False)

    order_count = int(df["OrderID"].nunique())
    total_inr = int(df["TotalSalesINR"].sum())
    summary = {
        "rows": len(df),
        "orders": order_count,
        "date_start": df["Date"].min().date().isoformat(),
        "date_end": df["Date"].max().date().isoformat(),
        "total_inr": total_inr,
        "average_order_value_inr": total_inr / order_count,
        "average_units_per_order": float(df["Quantity"].sum() / order_count),
        "top_product": str(product_revenue.index[0]),
        "top_product_revenue_inr": int(product_revenue.iloc[0]),
        "top_product_share": float(product_revenue.iloc[0] / total_inr),
        "top_category": str(category_revenue.index[0]),
        "top_category_revenue_inr": int(category_revenue.iloc[0]),
        "top_category_share": float(category_revenue.iloc[0] / total_inr),
        "peak_month": monthly_revenue.idxmax().strftime("%B"),
        "peak_month_revenue_inr": int(monthly_revenue.max()),
        "lowest_month": monthly_revenue.idxmin().strftime("%B"),
        "lowest_month_revenue_inr": int(monthly_revenue.min()),
    }
    quality = {
        "source_rows": source_rows,
        "exact_duplicates_removed": exact_duplicates,
        "missing_cells": missing_cells,
        "unique_orders": order_count,
        "revenue_calculation_mismatches": sales_mismatches,
        "valid_date_range": f"{summary['date_start']} to {summary['date_end']}",
    }
    return df, monthly_revenue, product_revenue, category_revenue, quality, summary


def format_crore(value: float) -> str:
    """Format rupees as Indian crore units."""
    crore = (Decimal(str(value)) / Decimal("10000000")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return f"₹{crore} crore"


def format_inr(value: float, decimals: int = 2) -> str:
    """Format a rupee amount with Indian digit grouping."""
    quantum = Decimal("1") if decimals == 0 else Decimal("0.01")
    rounded = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    whole, _, fraction = f"{rounded:.{decimals}f}".partition(".")
    sign = "-" if whole.startswith("-") else ""
    digits = whole.lstrip("-")
    if len(digits) > 3:
        last_three, leading = digits[-3:], digits[:-3]
        pairs = []
        while leading:
            pairs.insert(0, leading[-2:])
            leading = leading[:-2]
        digits = ",".join([*pairs, last_three])
    formatted = sign + digits
    if decimals:
        formatted += "." + fraction
    return f"₹{formatted}"


def create_charts(monthly_revenue, product_revenue, category_revenue) -> list[Path]:
    """Save three dependency-light, accessible SVG charts in an India palette."""
    VISUALS_DIR.mkdir(exist_ok=True)
    saffron = "#E87524"
    green = "#16845B"
    navy = "#18324B"
    cream = "#FFF9F0"
    outputs = []

    def start_svg(width: int, height: int, title: str, description: str) -> list[str]:
        return [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(description)}">',
            f'<rect width="{width}" height="{height}" rx="24" fill="{cream}"/>',
            '<style>text{font-family:Arial,"Segoe UI",sans-serif} .title{font-size:27px;font-weight:700;fill:#18324B} .sub{font-size:14px;fill:#587083} .label{font-size:13px;fill:#35536A} .value{font-size:14px;font-weight:700;fill:#18324B}</style>',
            f'<text x="48" y="52" class="title">{escape(title)}</text>',
            f'<text x="48" y="78" class="sub">{escape(description)}</text>',
        ]

    def save_svg(filename: str, elements: list[str]) -> Path:
        path = VISUALS_DIR / filename
        path.write_text("\n".join([*elements, "</svg>"]), encoding="utf-8")
        outputs.append(path)
        return path

    # Monthly trend in crore rupees, with readable month labels and peak annotation.
    width, height = 1100, 540
    left, right, top, bottom = 105, 1055, 132, 430
    monthly_crore = monthly_revenue / 10_000_000
    max_value = float(monthly_crore.max())
    y_max = math.ceil(max_value * 2) / 2
    elements = start_svg(width, height, "Monthly Sales Trend | Sample 2023", "Monthly sample revenue in INR crore. July is the highest month.")
    for tick in range(6):
        value = y_max * tick / 5
        y = bottom - (value / y_max) * (bottom - top)
        elements.append(f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="#E8DED0" stroke-width="1"/>')
        elements.append(f'<text x="{left - 14}" y="{y + 5:.1f}" text-anchor="end" class="label">₹{value:.1f} Cr</text>')
    points = []
    values = list(monthly_crore.items())
    for index, (period, value) in enumerate(values):
        x = left + index * (right - left) / (len(values) - 1)
        y = bottom - (float(value) / y_max) * (bottom - top)
        points.append((x, y))
        elements.append(f'<text x="{x:.1f}" y="{bottom + 30}" text-anchor="middle" class="label">{period.strftime("%b")}</text>')
    line_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    fill_points = f"{left},{bottom} {line_points} {right},{bottom}"
    elements.append(f'<polygon points="{fill_points}" fill="{saffron}" opacity="0.10"/>')
    elements.append(f'<polyline points="{line_points}" fill="none" stroke="{saffron}" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>')
    peak_index = int(monthly_crore.to_numpy().argmax())
    for index, (x, y) in enumerate(points):
        color = saffron if index == peak_index else green
        radius = 7 if index == peak_index else 5
        elements.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius}" fill="{color}" stroke="{cream}" stroke-width="3"/>')
    peak_x, peak_y = points[peak_index]
    elements.append(f'<text x="{peak_x:.1f}" y="{peak_y - 18:.1f}" text-anchor="middle" class="value">Peak: ₹{monthly_crore.iloc[peak_index]:.2f} Cr</text>')
    elements.append(f'<text x="{left}" y="{height - 28}" class="sub">Source amounts localized at illustrative ₹{INR_PER_USD:.0f}/USD</text>')
    save_svg("monthly_revenue_inr.svg", elements)

    # Horizontal product bars keep all labels legible and show share of total sales.
    width, height = 1100, 560
    left, right, top, row_height = 190, 930, 126, 52
    ordered_products = product_revenue.sort_values(ascending=True)
    max_product = float(ordered_products.max())
    elements = start_svg(width, height, "Revenue by Product", "Sample product revenue in INR crore. Laptop is the highest-revenue product.")
    for index, (product, revenue) in enumerate(ordered_products.items()):
        y = top + index * row_height
        amount_crore = float(revenue) / 10_000_000
        bar_width = amount_crore / (max_product / 10_000_000) * (right - left)
        color = saffron if index == len(ordered_products) - 1 else green
        share = float(revenue) / float(product_revenue.sum())
        elements.append(f'<text x="{left - 16}" y="{y + 22}" text-anchor="end" class="label">{escape(str(product))}</text>')
        elements.append(f'<rect x="{left}" y="{y}" width="{right - left}" height="30" rx="8" fill="#EFE6D9"/>')
        elements.append(f'<rect x="{left}" y="{y}" width="{bar_width:.1f}" height="30" rx="8" fill="{color}"/>')
        elements.append(f'<text x="{right + 16}" y="{y + 21}" class="value">₹{amount_crore:.2f} Cr · {share:.1%}</text>')
    elements.append(f'<text x="{left}" y="{height - 28}" class="sub">Revenue share is calculated across the full sample.</text>')
    save_svg("product_revenue_inr.svg", elements)

    # A single stacked bar compares category shares without implying extra dimensions.
    width, height = 980, 440
    bar_x, bar_y, bar_width, bar_height = 70, 150, 840, 66
    labels = category_revenue.index.tolist()
    colors = [saffron, green, navy]
    total = float(category_revenue.sum())
    elements = start_svg(width, height, "Category Share of Sales", "Share of sample revenue by category.")
    cursor = bar_x
    for index, (category, revenue) in enumerate(category_revenue.items()):
        share = float(revenue) / total
        segment_width = bar_width * share
        color = colors[index % len(colors)]
        elements.append(f'<rect x="{cursor:.1f}" y="{bar_y}" width="{segment_width:.1f}" height="{bar_height}" fill="{color}"/>')
        if segment_width > 90:
            elements.append(f'<text x="{cursor + segment_width / 2:.1f}" y="{bar_y + 41}" text-anchor="middle" fill="#FFFFFF" font-size="17" font-weight="700">{share:.1%}</text>')
        row_y = 275 + index * 58
        elements.append(f'<rect x="{bar_x}" y="{row_y - 15}" width="14" height="14" rx="3" fill="{color}"/>')
        elements.append(f'<text x="{bar_x + 28}" y="{row_y - 2}" class="label">{escape(str(category))}</text>')
        elements.append(f'<text x="{width - bar_x}" y="{row_y - 2}" text-anchor="end" class="value">₹{float(revenue) / 10_000_000:.2f} Cr · {share:.1%}</text>')
        cursor += segment_width
    elements.append(f'<text x="{bar_x}" y="{height - 24}" class="sub">The sample contains product/category totals only; no region or customer fields are available.</text>')
    save_svg("category_mix_inr.svg", elements)

    return outputs


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    _, monthly, products, categories, quality, summary = analyze_data()
    print("DATA QUALITY")
    for metric, value in quality.items():
        print(f"{metric.replace('_', ' ').title()}: {value}")

    print("\nKEY RESULTS (INR, FIXED ILLUSTRATIVE RATE)")
    print(f"Total sales: {format_crore(summary['total_inr'])}")
    print(f"Average order value: {format_inr(summary['average_order_value_inr'])}")
    print(f"Average units per order: {summary['average_units_per_order']:.2f}")
    print(
        f"Top product: {summary['top_product']} — "
        f"{format_crore(summary['top_product_revenue_inr'])} "
        f"({summary['top_product_share']:.1%})"
    )
    print(
        f"Top category: {summary['top_category']} — "
        f"{format_crore(summary['top_category_revenue_inr'])} "
        f"({summary['top_category_share']:.1%})"
    )
    print(
        f"Peak month: {summary['peak_month']} — "
        f"{format_crore(summary['peak_month_revenue_inr'])}"
    )
    print(
        f"Lowest month: {summary['lowest_month']} — "
        f"{format_crore(summary['lowest_month_revenue_inr'])}"
    )

    charts = create_charts(monthly, products, categories)
    print("\nCharts saved:")
    for chart in charts:
        print(f"- {chart.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
