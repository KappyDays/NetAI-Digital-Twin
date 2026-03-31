"""Generate publication-quality architecture figure for the BranDT pipeline.

Usage:
    pip install matplotlib
    python generate_figure.py

Output:
    docs/brandt_architecture.png (300 DPI)
    docs/brandt_architecture.pdf (vector)
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np


def draw_rounded_box(ax, xy, width, height, label, sublabel=None,
                     facecolor="#E8F4FD", edgecolor="#2196F3", fontsize=9,
                     fontweight="bold", text_color="#1a1a1a", alpha=1.0,
                     linestyle="-", linewidth=1.5, sublabel_fontsize=7):
    x, y = xy
    box = FancyBboxPatch((x, y), width, height,
                         boxstyle="round,pad=0.08",
                         facecolor=facecolor, edgecolor=edgecolor,
                         linewidth=linewidth, alpha=alpha, linestyle=linestyle,
                         zorder=2)
    ax.add_patch(box)
    if sublabel:
        ax.text(x + width/2, y + height/2 + 0.15, label,
                ha="center", va="center", fontsize=fontsize,
                fontweight=fontweight, color=text_color, zorder=3)
        ax.text(x + width/2, y + height/2 - 0.2, sublabel,
                ha="center", va="center", fontsize=sublabel_fontsize,
                color="#555555", zorder=3, style="italic")
    else:
        ax.text(x + width/2, y + height/2, label,
                ha="center", va="center", fontsize=fontsize,
                fontweight=fontweight, color=text_color, zorder=3)
    return box


def draw_arrow(ax, start, end, color="#555555", style="->", lw=1.2,
               connectionstyle="arc3,rad=0.0", shrinkA=5, shrinkB=5):
    arrow = FancyArrowPatch(start, end,
                            arrowstyle=style, color=color,
                            linewidth=lw, zorder=1,
                            connectionstyle=connectionstyle,
                            shrinkA=shrinkA, shrinkB=shrinkB,
                            mutation_scale=12)
    ax.add_patch(arrow)
    return arrow


def draw_label_on_arrow(ax, pos, text, fontsize=6.5, color="#333333", bg="#FFFFFF"):
    ax.text(pos[0], pos[1], text, ha="center", va="center",
            fontsize=fontsize, color=color, zorder=4,
            bbox=dict(boxstyle="round,pad=0.15", facecolor=bg,
                      edgecolor="#CCCCCC", linewidth=0.5, alpha=0.95))


def main():
    fig, ax = plt.subplots(1, 1, figsize=(14, 9))
    ax.set_xlim(-0.5, 14)
    ax.set_ylim(-0.5, 9.5)
    ax.set_aspect("equal")
    ax.axis("off")

    # Color palette
    C_ISAAC = "#FFF3E0"       # warm orange bg
    C_ISAAC_E = "#FF9800"     # orange edge
    C_NUCLEUS = "#F3E5F5"     # purple bg
    C_NUCLEUS_E = "#9C27B0"   # purple edge
    C_PIPELINE = "#E8F5E9"    # green bg
    C_PIPELINE_E = "#4CAF50"  # green edge
    C_LAKE = "#E3F2FD"        # blue bg
    C_LAKE_E = "#1976D2"      # blue edge
    C_MINIO = "#FFF8E1"       # amber bg
    C_MINIO_E = "#FFA000"     # amber edge
    C_ICE = "#E8EAF6"         # indigo bg
    C_ICE_E = "#3F51B5"       # indigo edge
    C_DASH = "#FCE4EC"        # pink bg
    C_DASH_E = "#E91E63"      # pink edge
    C_TIME = "#E0F7FA"        # cyan bg
    C_TIME_E = "#00ACC1"      # cyan edge

    # ── Title ──
    ax.text(7, 9.2, "BranDT: OpenUSD Digital Twin Data Architecture",
            ha="center", va="center", fontsize=14, fontweight="bold",
            color="#1a1a1a")
    ax.text(7, 8.85, "Nucleus → Iceberg Lakehouse → Time Travel Pipeline",
            ha="center", va="center", fontsize=9, color="#666666", style="italic")

    # ══════════════════════════════════════════════════════════
    # Layer 1: Isaac Sim + Nucleus (Top)
    # ══════════════════════════════════════════════════════════

    # Isaac Sim
    draw_rounded_box(ax, (0.3, 7.0), 5.0, 1.5,
                     "NVIDIA Isaac Sim",
                     sublabel="USD Stage  |  Viewport  |  Extension (lakehouse.proto)",
                     facecolor=C_ISAAC, edgecolor=C_ISAAC_E,
                     fontsize=11, sublabel_fontsize=8)

    # Stage Prims inside Isaac Sim
    ax.text(1.2, 7.55, "/World", fontsize=7, fontweight="bold", color="#E65100",
            fontfamily="monospace")
    ax.text(1.5, 7.25, "├ /Robots/Jetbot", fontsize=6, color="#555",
            fontfamily="monospace")
    ax.text(1.5, 7.0, "├ /Environment/Table", fontsize=6, color="#555",
            fontfamily="monospace")
    ax.text(1.5, 6.75, "└ /Props/Block_A ...", fontsize=6, color="#555",
            fontfamily="monospace")

    # Ref/Payload indicator
    ax.text(3.8, 7.55, "Reference", fontsize=6.5, color="#BF360C",
            fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.12", facecolor="#FFCCBC",
                      edgecolor="#E64A19", linewidth=0.8))
    ax.text(4.7, 7.55, "Payload", fontsize=6.5, color="#4A148C",
            fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.12", facecolor="#E1BEE7",
                      edgecolor="#7B1FA2", linewidth=0.8))

    # Nucleus Server
    draw_rounded_box(ax, (6.5, 7.0), 4.0, 1.5,
                     "Omniverse Nucleus",
                     sublabel="USD File Server (omniverse://)",
                     facecolor=C_NUCLEUS, edgecolor=C_NUCLEUS_E,
                     fontsize=11, sublabel_fontsize=8)

    ax.text(7.3, 7.25, "scene.usd", fontsize=7, color="#4A148C",
            fontfamily="monospace", fontweight="bold")
    ax.text(7.3, 7.0, "jetbot.usd  kaya.usd", fontsize=6, color="#555",
            fontfamily="monospace")
    ax.text(7.3, 6.75, "table.usd   block.usd ...", fontsize=6, color="#555",
            fontfamily="monospace")

    # Arrow: Isaac Sim <-> Nucleus
    draw_arrow(ax, (5.3, 7.75), (6.5, 7.75), color=C_NUCLEUS_E, style="<->", lw=1.8)
    draw_label_on_arrow(ax, (5.9, 7.95), "Save / Open")

    # ══════════════════════════════════════════════════════════
    # Layer 2: Nucleus Pipeline (Middle)
    # ══════════════════════════════════════════════════════════

    # Pipeline big box
    draw_rounded_box(ax, (0.3, 4.0), 10.2, 2.5,
                     "", facecolor="#F1F8E9", edgecolor=C_PIPELINE_E,
                     linewidth=2.0, alpha=0.4)
    ax.text(5.4, 6.3, "Nucleus Pipeline (nucleus_pipeline/)",
            ha="center", fontsize=10, fontweight="bold", color="#2E7D32")
    ax.text(5.4, 6.05, "Python CLI  |  PyUSD  |  omniverseclient  |  No Isaac Sim Required",
            ha="center", fontsize=7, color="#558B2F", style="italic")

    # Step 1: Download
    draw_rounded_box(ax, (0.6, 4.3), 2.0, 1.4,
                     "1. Download",
                     sublabel="omniverseclient\n(subprocess)",
                     facecolor=C_PIPELINE, edgecolor=C_PIPELINE_E,
                     fontsize=9, sublabel_fontsize=6.5)

    # Step 2: Parse
    draw_rounded_box(ax, (3.0, 4.3), 2.2, 1.4,
                     "2. Parse USD",
                     sublabel="Entity Detection\nOverride Extraction\nAsset URL Parsing",
                     facecolor=C_PIPELINE, edgecolor=C_PIPELINE_E,
                     fontsize=9, sublabel_fontsize=6.5)

    # Step 3: Generate
    draw_rounded_box(ax, (5.6, 4.3), 2.2, 1.4,
                     "3. Generate",
                     sublabel="Generate root.usda\nRewrite Ref paths\nto ./entities/*",
                     facecolor=C_PIPELINE, edgecolor=C_PIPELINE_E,
                     fontsize=9, sublabel_fontsize=6.5)

    # Step 4: Store
    draw_rounded_box(ax, (8.2, 4.3), 2.0, 1.4,
                     "4. Store",
                     sublabel="MinIO Upload\nIceberg INSERT",
                     facecolor=C_PIPELINE, edgecolor=C_PIPELINE_E,
                     fontsize=9, sublabel_fontsize=6.5)

    # Arrows between pipeline steps
    draw_arrow(ax, (2.6, 5.0), (3.0, 5.0), color=C_PIPELINE_E, lw=1.5)
    draw_arrow(ax, (5.2, 5.0), (5.6, 5.0), color=C_PIPELINE_E, lw=1.5)
    draw_arrow(ax, (7.8, 5.0), (8.2, 5.0), color=C_PIPELINE_E, lw=1.5)

    # Arrow: Nucleus -> Pipeline Download
    draw_arrow(ax, (8.5, 7.0), (1.6, 5.7), color=C_NUCLEUS_E, lw=1.5,
               connectionstyle="arc3,rad=-0.2")
    draw_label_on_arrow(ax, (4.5, 6.55), "omni.client.read_file()")

    # ══════════════════════════════════════════════════════════
    # Layer 3: Storage (Bottom)
    # ══════════════════════════════════════════════════════════

    # MinIO
    draw_rounded_box(ax, (0.3, 1.2), 4.5, 2.3,
                     "MinIO (S3-Compatible Storage)",
                     facecolor=C_MINIO, edgecolor=C_MINIO_E,
                     fontsize=9, sublabel_fontsize=7)
    ax.text(0.7, 2.8, "backups/{timestamp}/", fontsize=7, fontweight="bold",
            color="#E65100", fontfamily="monospace")
    ax.text(0.9, 2.5, "├── root.usda", fontsize=6.5, color="#555",
            fontfamily="monospace")
    ax.text(1.2, 2.25, "Full Stage local data", fontsize=5.5, color="#888",
            style="italic")
    ax.text(0.9, 2.0, "└── entities/", fontsize=6.5, color="#555",
            fontfamily="monospace")
    ax.text(1.3, 1.75, "├ jetbot.usd   (original)", fontsize=5.5, color="#888",
            fontfamily="monospace")
    ax.text(1.3, 1.55, "├ kaya.usd", fontsize=5.5, color="#888",
            fontfamily="monospace")
    ax.text(1.3, 1.35, "└ basic_block.usd (dedup)", fontsize=5.5, color="#888",
            fontfamily="monospace")

    # Iceberg
    draw_rounded_box(ax, (5.3, 1.2), 5.2, 2.3,
                     "Apache Iceberg (via Trino SQL)",
                     facecolor=C_ICE, edgecolor=C_ICE_E,
                     fontsize=9)
    ax.text(5.7, 2.85, "entities", fontsize=7, fontweight="bold",
            color="#1A237E", fontfamily="monospace")
    ax.text(5.9, 2.6, "entity_path | type | hash | backup_source | time",
            fontsize=5.5, color="#555", fontfamily="monospace")

    ax.text(5.7, 2.25, "prim_snapshots", fontsize=7, fontweight="bold",
            color="#1A237E", fontfamily="monospace")
    ax.text(5.9, 2.0, "entity_path | properties (Override JSON) | hash",
            fontsize=5.5, color="#555", fontfamily="monospace")

    # Partition indicator
    ax.text(5.9, 1.65, "partitioned by day(backup_time)", fontsize=5.5,
            color="#3F51B5", style="italic")
    ax.text(5.9, 1.45, "Iceberg Time Travel: query any past state via SQL",
            fontsize=5.5, color="#3F51B5", style="italic")

    # Arrows: Pipeline -> Storage
    draw_arrow(ax, (8.7, 4.3), (2.5, 3.5), color=C_MINIO_E, lw=1.5,
               connectionstyle="arc3,rad=0.2")
    draw_label_on_arrow(ax, (5.0, 4.05), "USD Files Upload")

    draw_arrow(ax, (9.2, 4.3), (7.9, 3.5), color=C_ICE_E, lw=1.5,
               connectionstyle="arc3,rad=-0.1")
    draw_label_on_arrow(ax, (9.0, 3.85), "Override + Metadata")

    # ══════════════════════════════════════════════════════════
    # Right side: Time Travel + Dashboard
    # ══════════════════════════════════════════════════════════

    # Time Travel box
    draw_rounded_box(ax, (11.2, 5.5), 2.5, 2.8,
                     "Time Travel",
                     facecolor=C_TIME, edgecolor=C_TIME_E,
                     fontsize=10)

    ax.text(12.45, 7.5, "Query", fontsize=8, fontweight="bold",
            color="#006064", ha="center")
    ax.text(12.45, 7.2, "\"Where was Jetbot\n2 hours ago?\"", fontsize=6.5,
            color="#00695C", ha="center", fontfamily="serif")

    ax.text(12.45, 6.55, "Restore", fontsize=8, fontweight="bold",
            color="#006064", ha="center")
    ax.text(12.45, 6.2, "Download root.usda\nfrom MinIO\n-> Open in Isaac Sim\n-> Past Stage restored",
            fontsize=5.5, color="#00695C", ha="center")

    # Dashboard
    draw_rounded_box(ax, (11.2, 1.2), 2.5, 1.5,
                     "Web Dashboard",
                     sublabel="Entity Diff  |  SQL Query\nCongestion  |  Iceberg Hub",
                     facecolor=C_DASH, edgecolor=C_DASH_E,
                     fontsize=9, sublabel_fontsize=6.5)
    ax.text(12.45, 1.3, "React :3000", fontsize=6, color="#880E4F",
            ha="center", style="italic")

    # Arrows: Storage -> Time Travel / Dashboard
    draw_arrow(ax, (10.5, 2.35), (11.2, 1.95), color=C_DASH_E, lw=1.3)
    draw_arrow(ax, (10.5, 2.8), (11.2, 6.0), color=C_ICE_E, lw=1.3,
               connectionstyle="arc3,rad=-0.15")
    draw_label_on_arrow(ax, (10.6, 4.5), "SQL", fontsize=6)

    draw_arrow(ax, (4.8, 1.8), (11.2, 5.9), color=C_MINIO_E, lw=1.3,
               connectionstyle="arc3,rad=-0.15")
    draw_label_on_arrow(ax, (7.5, 3.2), "USD Download", fontsize=6)

    # Arrow: Time Travel -> Isaac Sim (restore)
    draw_arrow(ax, (12.45, 8.3), (5.3, 8.1), color=C_TIME_E, lw=1.8,
               style="-|>", connectionstyle="arc3,rad=0.15")
    draw_label_on_arrow(ax, (8.5, 8.55), "Restore: Open root.usda in Isaac Sim",
                        fontsize=7)

    # ══════════════════════════════════════════════════════════
    # Legend
    # ══════════════════════════════════════════════════════════
    legend_y = 0.4
    legend_items = [
        (C_ISAAC, C_ISAAC_E, "Isaac Sim (DCC)"),
        (C_NUCLEUS, C_NUCLEUS_E, "Nucleus (USD Server)"),
        (C_PIPELINE, C_PIPELINE_E, "Nucleus Pipeline (CLI)"),
        (C_MINIO, C_MINIO_E, "MinIO (Object Storage)"),
        (C_ICE, C_ICE_E, "Iceberg (Data Lakehouse)"),
        (C_TIME, C_TIME_E, "Time Travel"),
        (C_DASH, C_DASH_E, "Dashboard (Web UI)"),
    ]
    start_x = 0.5
    for i, (fc, ec, label) in enumerate(legend_items):
        x = start_x + i * 1.9
        box = FancyBboxPatch((x, legend_y), 0.3, 0.2,
                             boxstyle="round,pad=0.03",
                             facecolor=fc, edgecolor=ec, linewidth=1.0)
        ax.add_patch(box)
        ax.text(x + 0.4, legend_y + 0.1, label, fontsize=5.5,
                va="center", color="#333333")

    # ══════════════════════════════════════════════════════════
    # Save
    # ══════════════════════════════════════════════════════════
    plt.tight_layout(pad=0.5)

    import os
    out_dir = os.path.dirname(os.path.abspath(__file__))
    png_path = os.path.join(out_dir, "brandt_architecture.png")
    pdf_path = os.path.join(out_dir, "brandt_architecture.pdf")

    fig.savefig(png_path, dpi=300, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    fig.savefig(pdf_path, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    print(f"Saved: {png_path}")
    print(f"Saved: {pdf_path}")
    plt.close()


if __name__ == "__main__":
    main()
