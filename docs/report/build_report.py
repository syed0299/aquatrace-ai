"""Build the AquaTrace AI technical report (PDF) from the project's own result files.

    cd backend && ../.venv/bin/python ../docs/report/build_report.py
"""
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import matplotlib
from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, XPreformatted, Image, KeepTogether, NextPageTemplate, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(HERE))
import charts  # noqa: E402
from aquatrace.route import plan  # noqa: E402

OUT = HERE / "AquaTrace_AI_Technical_Report.pdf"
IMG = HERE / "img"
IMG.mkdir(exist_ok=True)

# ---------------------------------------------------------------- fonts & colours
FONTS = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
for name, file in [("Sans", "DejaVuSans.ttf"), ("Sans-Bold", "DejaVuSans-Bold.ttf"), ("Sans-It", "DejaVuSans-Oblique.ttf"),
                   ("Sans-BoldIt", "DejaVuSans-BoldOblique.ttf"), ("Mono", "DejaVuSansMono.ttf"), ("Mono-Bold", "DejaVuSansMono-Bold.ttf")]:
    pdfmetrics.registerFont(TTFont(name, str(FONTS / file)))
pdfmetrics.registerFontFamily("Sans", normal="Sans", bold="Sans-Bold", italic="Sans-It", boldItalic="Sans-BoldIt")
pdfmetrics.registerFontFamily("Mono", normal="Mono", bold="Mono-Bold", italic="Mono", boldItalic="Mono-Bold")

INK = colors.HexColor("#0B1F3A")
INK2 = colors.HexColor("#3E5069")
INK3 = colors.HexColor("#7B8A9E")
LINE = colors.HexColor("#E2E8F0")
MIST = colors.HexColor("#F3F6F9")
BLUE = colors.HexColor("#2453FF")
RED = colors.HexColor("#E5383B")
AMBER = colors.HexColor("#F5A30B")
GREEN = colors.HexColor("#16A36A")
VIOLET = colors.HexColor("#7C3AED")
SOFT_BLUE = colors.HexColor("#E7ECFF")

# ---------------------------------------------------------------- styles
S = {
    "body": ParagraphStyle("body", fontName="Sans", fontSize=9.4, leading=14, textColor=INK, spaceAfter=6),
    "small": ParagraphStyle("small", fontName="Sans", fontSize=8, leading=11, textColor=INK2),
    "caption": ParagraphStyle("caption", fontName="Sans-It", fontSize=8, leading=11, textColor=INK3, spaceBefore=3, spaceAfter=10),
    "h1": ParagraphStyle("h1", fontName="Sans-Bold", fontSize=18, leading=22, textColor=INK, spaceBefore=10, spaceAfter=10, keepWithNext=1),
    "title": ParagraphStyle("title", fontName="Sans-Bold", fontSize=18, leading=22, textColor=INK, spaceAfter=12),
    "h2": ParagraphStyle("h2", fontName="Sans-Bold", fontSize=12.5, leading=16, textColor=INK, spaceBefore=12, spaceAfter=6, keepWithNext=1),
    "h3": ParagraphStyle("h3", fontName="Sans-Bold", fontSize=10, leading=13, textColor=INK2, spaceBefore=8, spaceAfter=4, keepWithNext=1),
    "bullet": ParagraphStyle("bullet", fontName="Sans", fontSize=9.4, leading=13.5, textColor=INK, leftIndent=12, bulletIndent=2, spaceAfter=3),
    "code": ParagraphStyle("code", fontName="Mono", fontSize=7.4, leading=11, textColor=INK, backColor=MIST, borderPadding=(5, 6, 5, 6),
                           leftIndent=6, rightIndent=6, spaceBefore=4, spaceAfter=9),
    "cell": ParagraphStyle("cell", fontName="Sans", fontSize=8, leading=10.5, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="Sans-Bold", fontSize=8, leading=10.5, textColor=INK),
    "cellh": ParagraphStyle("cellh", fontName="Sans-Bold", fontSize=7.8, leading=10, textColor=colors.white),
    "toc1": ParagraphStyle("toc1", fontName="Sans-Bold", fontSize=9.6, leading=14.5, textColor=INK, spaceBefore=3),
    "toc2": ParagraphStyle("toc2", fontName="Sans", fontSize=8.6, leading=11.8, leftIndent=14, textColor=INK2),
}


def p(text, style="body"):
    return Paragraph(text, S[style])


def bullets(items):
    return [Paragraph(t, S["bullet"], bulletText="•") for t in items]


def code(text):
    for line in text.split("\n"):
        assert len(line) <= 98, f"code line too long ({len(line)}): {line}"
    return XPreformatted(text, S["code"])


def table(rows, widths, header=True, zebra=True, align_right=()):
    data = []
    for i, r in enumerate(rows):
        st = "cellh" if header and i == 0 else "cell"
        data.append([c if not isinstance(c, str) else Paragraph(c, S[st]) for c in r])
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    cmds = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE)]
    if header:
        cmds += [("BACKGROUND", (0, 0), (-1, 0), INK)]
    if zebra:
        for i in range(1 if header else 0, len(rows)):
            if i % 2 == 0:
                cmds.append(("BACKGROUND", (0, i), (-1, i), MIST))
    t.setStyle(TableStyle(cmds))
    t.spaceAfter = 8
    return KeepTogether([t]) if len(rows) <= 9 else t


def figure(path, width_mm, caption):
    from PIL import Image as PI
    w, h = PI.open(path).size
    img = Image(str(path), width=width_mm * mm, height=width_mm * mm * h / w)
    return KeepTogether([img, p(caption, "caption")])


def kpis(items, cols=4):
    """Stat tiles: (value, label)."""
    kv = ParagraphStyle("kv", fontName="Sans-Bold", fontSize=17, leading=21, textColor=INK)
    kl = ParagraphStyle("kl", fontName="Sans", fontSize=7.6, leading=9.8, textColor=colors.HexColor("#52514E"))
    cells = [[[Paragraph(v, kv), Paragraph(l, kl)] for v, l in items[i:i + cols]] for i in range(0, len(items), cols)]
    t = Table(cells, colWidths=[174 * mm / cols] * cols)
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.6, LINE),
                           ("BACKGROUND", (0, 0), (-1, -1), colors.white), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 8),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("LEFTPADDING", (0, 0), (-1, -1), 9)]))
    return t


def note(text, bg=SOFT_BLUE, fg="#1A3AB8"):
    t = Table([[Paragraph(text, ParagraphStyle("n", parent=S["body"], textColor=colors.HexColor(fg), spaceAfter=0))]], colWidths=[174 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    return t


# ---------------------------------------------------------------- pipeline diagram
def pipeline_diagram():
    W, H = 174 * mm, 52 * mm
    d = Drawing(W, H)
    stages = [("Observe", "PACE + Sentinel-2"), ("Detect", "FDI anomaly + AI"), ("Fuse", "currents + wind"),
              ("Forecast", "drift, now, source"), ("Prioritize", "risk + action"), ("Act", "map, route, what-if")]
    bw, gap, y = 70, 13.6, 92
    for i, (t, s) in enumerate(stages):
        x = i * (bw + gap)
        d.add(Rect(x, y, bw, 46, rx=6, ry=6, fillColor=colors.HexColor("#EEEDFE"), strokeColor=colors.HexColor("#534AB7"), strokeWidth=0.6))
        d.add(String(x + bw / 2, y + 28, t, fontName="Sans-Bold", fontSize=8.6, fillColor=colors.HexColor("#26215C"), textAnchor="middle"))
        d.add(String(x + bw / 2, y + 14, s, fontName="Sans", fontSize=6.4, fillColor=colors.HexColor("#3C3489"), textAnchor="middle"))
        if i < len(stages) - 1:
            x1, x2, yy = x + bw + 1.5, x + bw + gap - 2, y + 23
            d.add(Line(x1, yy, x2, yy, strokeColor=INK2, strokeWidth=0.9))
            d.add(Polygon([x2, yy, x2 - 4, yy + 2.6, x2 - 4, yy - 2.6], fillColor=INK2, strokeColor=INK2))
    # offline inputs feeding Detect and Forecast
    for idx, (t, s) in ((1, ("Trained AI model", "MARIDA labels")), (3, ("Buoy validation", "NOAA drifters"))):
        x = idx * (bw + gap)
        d.add(Rect(x, 14, bw, 40, rx=6, ry=6, fillColor=MIST, strokeColor=INK3, strokeWidth=0.6, strokeDashArray=(2, 2)))
        d.add(String(x + bw / 2, 36, t, fontName="Sans-Bold", fontSize=7.4, fillColor=INK, textAnchor="middle"))
        d.add(String(x + bw / 2, 24, s, fontName="Sans", fontSize=6.4, fillColor=INK2, textAnchor="middle"))
        d.add(Line(x + bw / 2, 55, x + bw / 2, y - 3, strokeColor=INK3, strokeWidth=0.8, strokeDashArray=(2, 2)))
        d.add(Polygon([x + bw / 2, y - 1, x + bw / 2 - 2.6, y - 5, x + bw / 2 + 2.6, y - 5], fillColor=INK3, strokeColor=INK3))
    d.add(String(0, 2, "Solid: one pipeline run.  Dashed: built once, offline (training and validation).",
                 fontName="Sans-It", fontSize=6.6, fillColor=INK3))
    return d


# ---------------------------------------------------------------- page templates
class Report(BaseDocTemplate):
    def __init__(self, path):
        super().__init__(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=20 * mm, bottomMargin=18 * mm,
                         title="AquaTrace AI: Technical Report", author="AquaTrace AI team (Innothon'26)",
                         subject="Marine-debris detection and drift forecasting for the Bay of Bengal")
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="f")
        self.addPageTemplates([PageTemplate("cover", [frame], onPage=self.cover_bg),
                               PageTemplate("body", [frame], onPage=self.chrome)])

    def cover_bg(self, c, doc):
        c.saveState()
        c.setFillColor(INK)
        c.rect(0, A4[1] - 88 * mm, A4[0], 88 * mm, stroke=0, fill=1)
        c.restoreState()

    def chrome(self, c, doc):
        c.saveState()
        c.setFont("Sans", 7.5)
        c.setFillColor(INK3)
        c.drawString(18 * mm, A4[1] - 12 * mm, "AquaTrace AI · Technical report")
        c.drawRightString(A4[0] - 18 * mm, A4[1] - 12 * mm, "Innothon'26 · Bay of Bengal pilot")
        c.setStrokeColor(LINE)
        c.setLineWidth(0.5)
        c.line(18 * mm, A4[1] - 14 * mm, A4[0] - 18 * mm, A4[1] - 14 * mm)
        c.drawRightString(A4[0] - 18 * mm, 10 * mm, f"{doc.page}")
        c.restoreState()

    def afterFlowable(self, f):
        if isinstance(f, Paragraph) and f.style.name in ("h1", "h2"):
            level = 0 if f.style.name == "h1" else 1
            text = f.getPlainText()
            key = f"h{id(f)}"
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=level, closed=level > 0)
            self.notify("TOCEntry", (level, text, self.page, key))


def h1(t):
    return p(t, "h1")


def h2(t):
    return p(t, "h2")


def h3(t):
    return p(t, "h3")


# ================================================================ data
M = json.loads((ROOT / "models/marida_metrics.json").read_text())
CAL = json.loads((ROOT / "models/calibration.json").read_text())
EXP = json.loads((ROOT / "models/experiments_val.json").read_text())
VAL = json.loads((ROOT / "outputs/drift_validation.json").read_text())
VAL_OM = json.loads((ROOT / "outputs/drift_validation_openmeteo.json").read_text())
EXP2 = json.loads((ROOT / "models/experiments_v2_val.json").read_text())
TUNE = json.loads((ROOT / "outputs/drift_tuning.json").read_text())
EVD = json.loads((ROOT / "docs/evidence/evidence.json").read_text())
EVIMG = ROOT / "docs/evidence"
CONE_BEFORE = [TUNE["baseline_holdout"][h]["cone90_coverage"] for h in ("24", "48")]
CONE_AFTER = [VAL["summary"][h]["cone90_coverage"] for h in ("24", "48")]
BEST_WIND = min((r for r in TUNE["stage1"][1:] if r["cscale"] == 1.0),
                key=lambda r: r["24"]["median_km"] + r["48"]["median_km"])["windage"][0]
N_CAL = TUNE["chosen_calibration"]["n"]
RUNS = {r: json.loads((ROOT / f"outputs/runs/{r}/run.json").read_text()) for r in json.loads((ROOT / "outputs/runs/index.json").read_text())}
LIVE = next(r for r in RUNS.values() if r.get("live"))
REPLAY = RUNS["20260314_pace"]
ROUTE_LIVE = plan(LIVE, "Chennai", max_stops=4, include_low=True)
ROUTE_REPLAY = plan(REPLAY, "Port Blair", max_stops=4, include_low=True)
FIRST = (79.5, 89.1, 62.0, 57.6)  # first model on the test split (pixel features, Random Forest)
ROUND1 = (91.9, 93.6, 75.4, 73.6)  # round-1 final model (texture features, Extra Trees), test split
FINAL = (M["accuracy"] * 100, M["floating_material"]["f1"] * 100, M["debris"]["f1"] * 100, M["macro_f1"] * 100)

charts.model_improvement([("First model (pixels, RF)", FIRST), ("Round 1 (texture, ET)", ROUND1),
                          ("Round 2 (two experts)", FINAL)], IMG / "c_model.png")
charts.per_class_f1([(k, v["f1-score"]) for k, v in M["per_class"].items()], IMG / "c_perclass.png",
                    {"Marine Debris", "Dense Sargassum", "Sparse Sargassum"})
charts.reliability(CAL, IMG / "c_calibration.png")
charts.drift_errors(VAL, IMG / "c_drift.png")
charts.windage_tuning(TUNE, IMG / "c_windage.png")
charts.cone_coverage([x * 100 for x in CONE_BEFORE], [x * 100 for x in CONE_AFTER], IMG / "c_cone.png")

pct = lambda x: f"{x * 100:.1f}%"  # noqa: E731
km = lambda x: f"{x:.1f} km"  # noqa: E731

story = []
add = story.extend

# ================================================================ cover
cover_title = ParagraphStyle("ct", fontName="Sans-Bold", fontSize=34, leading=38, textColor=colors.white)
cover_sub = ParagraphStyle("cs", fontName="Sans", fontSize=13, leading=18, textColor=colors.HexColor("#C9D6EA"))
cover_kick = ParagraphStyle("ck", fontName="Mono", fontSize=8.5, leading=12, textColor=colors.HexColor("#8FB3E8"))
add([
    Spacer(1, 6 * mm),
    Paragraph("INNOTHON'26 · TECHNICAL REPORT", cover_kick), Spacer(1, 4 * mm),
    Paragraph("AquaTrace AI", cover_title), Spacer(1, 3 * mm),
    Paragraph("From detecting marine debris to predicting its next move: satellite detection, 24–48 hour drift "
              "forecasting and cleanup prioritisation for the Bay of Bengal", cover_sub),
    Spacer(1, 30 * mm),
    figure(IMG / "ui_overview.jpg", 174, "The AquaTrace AI dashboard: 17 hotspots from the 14 March 2026 NASA replay over animated ocean "
           "currents, ranked by cleanup risk."),
    kpis([(pct(M["accuracy"]), "detection accuracy (15 classes,\nunseen test data)"),
          (f"{M['floating_material']['f1']:.2f}", "F1 score for floating\nmaterial"),
          (f"{VAL['summary']['24']['median_km']:.1f} km", f"median forecast error at +24 h ({VAL['summary']['48']['median_km']:.1f} km at +48 h), {VAL['cases']} held-out buoy tests"),
          (f"{VAL['skill_vs_persistence']['48'] * 100:.0f}%", "more accurate than assuming\ndebris stays where seen")]),
    Spacer(1, 7 * mm),
    p("<b>Team</b>: Akshitha B (team leader), Tharun Vignessh S, Mohammed Faiz, Tanishka M, Dhanaishwariya R (2nd year)", "small"),
    p(f"<b>Date</b>: {date(2026, 10, 1).strftime('%d %B %Y')}  ·  <b>Region</b>: Bay of Bengal and Andaman Sea "
      "(4°–23°N, 79°–96°E)  ·  <b>Data</b>: NASA PACE, OSCAR, MERRA-2; ESA Sentinel-2; MARIDA; NOAA drifters", "small"),
    NextPageTemplate("body"), PageBreak(),
])

# ================================================================ contents
toc = TableOfContents()
toc.levelStyles = [S["toc1"], S["toc2"]]
toc.dotsMinLevel = 0
toc.tableStyle = TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 0)])
add([p("Contents", "title"), toc, PageBreak()])

# ================================================================ 1 executive summary
add([
    h1("1. Executive summary"),
    p("Marine debris does not stay where a satellite sees it. Currents and wind keep moving it, cleanup boats are few, "
      "and a daily satellite image is only a snapshot. <b>AquaTrace AI</b> turns free NASA and ESA satellite data into a "
      "ranked, forecast-aware cleanup plan for the Bay of Bengal. It answers four questions: <i>where is floating debris "
      "likely now, where will it be in 24–48 hours, where did it come from, and how should a boat reach it?</i>"),
    p("The system runs as a pipeline with six stages: <b>Observe → Detect → Fuse → Forecast → Prioritize → Act</b>. "
      "It reads hyperspectral imagery from NASA's PACE satellite and higher-resolution Sentinel-2 imagery near the coast. "
      "Floating material is flagged with a spectral index (the Floating Debris Index) plus an AI classifier trained on "
      "the MARIDA marine-debris benchmark. Each hotspot is moved forward with a 300-particle Lagrangian drift model driven "
      "by NASA OSCAR currents and MERRA-2 wind (or forecast currents and wind in live mode). It is then scored for "
      "cleanup risk and shown on an interactive map with recommended actions and boat routes."),
    h3("Key results"),
    table([["Result", "Value", "How it was measured"],
           ["Detection accuracy (15 classes)", pct(M["accuracy"]), f"MARIDA official test split, {M['test_pixels']:,} unseen labelled pixels"],
           ["F1, floating material", f"{M['floating_material']['f1']:.3f}", f"precision {M['floating_material']['precision']:.2f}, recall {M['floating_material']['recall']:.2f}"],
           ["F1, marine debris", f"{M['debris']['f1']:.3f}", f"precision {M['debris']['precision']:.2f}, recall {M['debris']['recall']:.2f}"],
           ["Confidence calibration error", pct(CAL["floating_material"]["ece"]), "expected calibration error, floating material"],
           ["Drift forecast error, +24 h", km(VAL["summary"]["24"]["median_km"]), f"median of {VAL['cases']} forecasts vs real NOAA buoys (held-out month)"],
           ["Drift forecast error, +48 h", km(VAL["summary"]["48"]["median_km"]), f"vs {km(VAL['persistence']['48']['median_km'])} for a static snapshot"],
           ["Skill over a snapshot, +48 h", f"{VAL['skill_vs_persistence']['48'] * 100:.0f}%", "1 − (model error / persistence error)"],
           ["Real buoy inside the 90% cone", f"{pct(CONE_AFTER[0])} / {pct(CONE_AFTER[1])}", f"+24 h / +48 h, held-out month (before: {pct(CONE_BEFORE[0])} / {pct(CONE_BEFORE[1])})"],
           ["Wind drag (windage)", "2–3%", f"tuned on January 2025 buoys (lowest error at {BEST_WIND * 100:.1f}%)"]],
          [55 * mm, 26 * mm, 93 * mm]),
    Spacer(1, 6),
    h3("What is new"),
    *bullets([
        "<b>Closes the whole loop</b>: detection, 48-hour forecast, risk ranking and a boat route in one tool.",
        "<b>Near-real-time nowcasting</b>: detections from the latest passes (online about 3 hours after each daily PACE pass) "
        "are moved to their likely position <i>now</i>, so the map stays useful between passes and under clouds.",
        "<b>Source tracking</b>: the drift model runs backwards 72 hours to point at likely river or coastal sources.",
        "<b>Moving-target cleanup routes</b>: boats are sent to where each patch <i>will be</i> when they arrive.",
        "<b>One AI model for two satellites</b>: background-relative features let a model trained on Sentinel-2 labels run on PACE.",
        "<b>Two-expert classifier</b>: Extra Trees decides <i>floating material or not</i>; a vote with gradient boosting names "
        "everything else. Accuracy rose from 91.9% to 94.1% without losing debris detection.",
        "<b>Honest uncertainty</b>: the 90% forecast cone is checked against real buoys. It used to contain them 5% of the time; "
        f"with a per-particle current error it now contains them {CONE_AFTER[0] * 100:.0f}–{CONE_AFTER[1] * 100:.0f}% of the time "
        "on a month of buoys not used for tuning.",
    ]),
    PageBreak(),
])

# ================================================================ 2 problem & objectives
add([
    h1("2. Problem and objectives"),
    h2("2.1 Problem statement"),
    p("More than 11 million tonnes of plastic enter the ocean every year (UNEP, 2021). Most comes from land through rivers "
      "and coastal cities, and the Bay of Bengal receives the outflow of some of the world's largest river systems "
      "(Ganga–Brahmaputra–Meghna, Godavari, Krishna, Mahanadi, Irrawaddy). Monitoring it is hard for three reasons:"),
    *bullets(["The ocean is far too large for continuous manual or ship-based monitoring.",
              "Satellite observations are snapshots. They show where floating material was, not where it is going.",
              "Surface currents and wind move floating material tens of kilometres a day, and cleanup resources are limited, "
              "so priority zones must be chosen in advance."]),
    note("<b>Core question</b>: how can we detect potential floating-debris hotspots early and forecast where they will move, "
         "so cleanup teams can act before debris reaches sensitive coasts?"),
    Spacer(1, 8),
    h2("2.2 Objectives and status"),
    table([["#", "Objective", "Status"],
           ["1", "Detect potential floating-debris hotspots from NASA PACE OCI surface reflectance, with a confidence score", "Done (plus Sentinel-2 coastal layer)"],
           ["2", "Forecast hotspot movement over 24–48 h by fusing NASA OSCAR currents and MERRA-2 wind", "Done, validated on held-out buoy tracks"],
           ["3", "Compute a cleanup risk score from confidence, predicted location, recurrence, proximity to sensitive areas and forecast uncertainty", "Done"],
           ["4", "Deliver an interactive cleanup-priority map (FastAPI + React + Leaflet)", "Done (redesigned dashboard)"],
           ["5", "Measure detection precision/recall/F1, 24/48 h forecast error and confidence calibration", "Done"],
           ["+", "Near-real-time live mode, source back-tracking, moving-target route planner, what-if simulator", "Added beyond the original plan"]],
          [8 * mm, 118 * mm, 48 * mm]),
    CondPageBreak(120 * mm),
])

# ================================================================ 3 system overview
add([
    h1("3. System overview"),
    p("AquaTrace AI is a Python pipeline that writes one self-contained result file per run, plus a web dashboard that "
      "displays it. The figure shows the six stages of a run and the two components built once, offline."),
    pipeline_diagram(),
    p("Figure 1. The AquaTrace AI workflow.", "caption"),
    table([["Stage", "What happens", "Output", "Code"],
           ["Observe", "Download the latest PACE pass (whole Bay, ~1.2 km) and Sentinel-2 scenes (20 m, 5 coastal sites); mask land, cloud, glint", "Clean reflectance scenes", "sources/nasa.py, sources/sentinel2.py"],
           ["Detect", "Floating Debris Index anomaly against local water background; AI classifier rejects ships, wakes, waves, clouds; group pixels", "Hotspots with confidence", "detect.py, marida.py"],
           ["Fuse", "Load currents and 10 m wind on a common grid (NASA OSCAR + MERRA-2, or Open-Meteo forecasts for live runs)", "Velocity fields", "forcing.py, sources/"],
           ["Forecast", "300-particle Lagrangian ensemble; nowcast to the present (live); 72 h back-track to the source", "Tracks, cones, beaching, source", "drift.py, source.py"],
           ["Prioritize", "Weighted risk score and tier; plain-language recommended action", "Ranked list", "risk.py"],
           ["Act", "Interactive map, what-if simulator and moving-target vessel routes", "Dashboard", "api.py, route.py, frontend/"]],
          [20 * mm, 78 * mm, 34 * mm, 42 * mm]),
    h2("3.1 Two ways to run"),
    table([["Mode", "Command", "Satellite data", "Currents and wind", "Use"],
           ["Live", "pipeline --live", "Best 3 PACE near-real-time passes from the last 3 days + latest Sentinel-2", "Open-Meteo forecasts (Mercator SMOC currents, GFS/ECMWF wind)", "Today's map, forecast from now"],
           ["Replay", "pipeline --date YYYY-MM-DD", "PACE standard product + Sentinel-2 around that date", "NASA OSCAR v2.0 + MERRA-2", "Proof: compare with what happened"]],
          [16 * mm, 30 * mm, 46 * mm, 46 * mm, 36 * mm]),
    h2("3.2 Daily operation (live mode)"),
    *bullets(["~12:00–13:00 IST: PACE passes over the Bay of Bengal.",
              "~3 hours later: NASA publishes the near-real-time Level-2 product (for example, the 06:26 UTC pass on 30 September 2026 was online at 09:11 UTC).",
              "~16:00 IST: run <font name='Mono'>pipeline --live</font>: about 9 minutes of processing, plus the time to download ~2 GB of PACE data (around 10–15 minutes on a typical connection).",
              "The dashboard checks for new runs every 5 minutes and switches to the newest live run automatically.",
              "On cloudy days the nowcast keeps earlier detections moving, so the map never goes blank."]),
    CondPageBreak(120 * mm),
])

# ================================================================ 4 data sources
mar_counts = M["train_pixels_by_class"]
add([
    h1("4. Data sources"),
    p("All datasets are free. Only the three NASA products need an (also free) Earthdata login. The table summarises "
      "them; details follow."),
    table([["Dataset", "Provider", "Resolution", "Used for"],
           ["PACE OCI L2 SFREFL (standard + NRT), v3.1", "NASA Ocean Biology DAAC", "~1.2 km, 122 bands, daily", "Regional detection across the Bay"],
           ["Sentinel-2 L2A", "ESA Copernicus (via Earth Search STAC)", "10–20 m, every 2–5 days", "Coastal detection at 5 sites"],
           ["OSCAR v2.0 (final / interim / NRT)", "NASA PO.DAAC", "0.25°, daily", "Ocean currents (replays, validation)"],
           ["MERRA-2 M2T1NXSLV v5.12.4", "NASA GES DISC (GMAO)", "0.5° × 0.625°, hourly", "10 m wind (replays, validation)"],
           ["MARIDA", "Kikaki et al. (2022), Zenodo", "Sentinel-2, 10 m, 15 classes", "Training and testing the AI model"],
           ["Global Drifter Program, 6-hourly QC", "NOAA AOML (ERDDAP)", "buoy positions every 6 h", "Validating the drift forecast"],
           ["Open-Meteo Marine / Archive / Forecast APIs", "Open-Meteo (Mercator SMOC, ERA5, GFS/ECMWF)", "sampled on a 0.5° grid, hourly", "Live forecasts; no-login fallback"],
           ["Natural Earth 10 m land + coastline", "Natural Earth", "1:10 million", "Land mask, beaching, coast distance, routing"]],
          [50 * mm, 46 * mm, 36 * mm, 42 * mm]),
    h2("4.1 NASA PACE OCI surface reflectance"),
    p("PACE (Plankton, Aerosol, Cloud, ocean Ecosystem), launched in February 2024, carries the Ocean Color Instrument (OCI), "
      "a hyperspectral imager with near-daily coverage. We use the Level-2 surface-reflectance product "
      "<font name='Mono'>PACE_OCI_L2_SFREFL</font> (and its near-real-time twin <font name='Mono'>_NRT</font>, version 3.1)."),
    table([["Property", "Value"],
           ["Bands", "122: 346–895 nm (hyperspectral) plus SWIR at 1038, 1249, 1618, 2131 and 2258 nm"],
           ["Pixel size", "about 1.2 km at nadir; granule of 1710 lines × 1272 pixels"],
           ["File size", "about 730 MB per 5-minute granule (netCDF-4)"],
           ["Variables read", "geophysical_data/rhos, geophysical_data/l2_flags, navigation_data/latitude and longitude, sensor_band_parameters/wavelength_3d"],
           ["Quality flags masked", "LAND, CLDICE, HIGLINT, STRAYLIGHT, ATMFAIL, HILT, NAVFAIL, PRODFAIL, HISATZEN, HISOLZEN"],
           ["Granule selection", "ranked by (share of the Bay covered) × (1 − cloud cover)"],
           ["Passes used", "Replay: 14 Mar 2026 06:59 UTC (56% cloud). Live: 28 Sep 06:55, 29 Sep 07:29 and 30 Sep 06:26 UTC (82%, 69%, 95% cloud)"],
           ["Access", "earthaccess (Python) with an Earthdata login stored in ~/.netrc"]],
          [38 * mm, 136 * mm]),
    h2("4.2 ESA Sentinel-2 L2A"),
    p("Sentinel-2's Multispectral Instrument provides 13 bands at 10, 20 and 60 m. We read 11 bands (B1–B8A, B11, B12) and "
      "the scene classification layer (SCL) as cloud-optimised GeoTIFFs from the open Earth Search STAC catalogue. Each "
      "site is read as a 30 × 30 km window at 20 m (1500 × 1500 pixels), choosing the pass closest in time within ±6 days "
      "with under 20% cloud. Water pixels come from SCL class 6; clouds, cirrus and shadows (classes 3, 8, 9, 10) are "
      "masked with a 5-pixel buffer. Note: when <font name='Mono'>earthsearch:boa_offset_applied</font> is true, the −0.1 "
      "offset must not be added again (doing so gives negative reflectance)."),
    p("Coastal sites: Chennai, Hooghly estuary / Sagar Island, Visakhapatnam, Cox's Bazar and Port Blair (Andaman)."),
    h2("4.3 NASA OSCAR v2.0 surface currents"),
    p("OSCAR (Ocean Surface Current Analyses Real-time) combines satellite sea-surface height, wind and temperature into "
      "daily 0.25° surface currents (u, v in m/s). Three versions are searched in order of quality: final (available until "
      "January 2026), interim and near-real-time. The final version was used for the January–February 2025 buoy validation "
      "and the interim version for the March 2026 replays. Each daily file (~33 MB, global) is subset to the Bay; daily "
      "means are time-stamped at 12:00 UTC."),
    h2("4.4 NASA MERRA-2 10 m wind"),
    p("MERRA-2 is NASA GMAO's atmospheric reanalysis. From the hourly single-level collection M2T1NXSLV we read the 10 m "
      "wind components U10M and V10M on a 0.5° × 0.625° grid. Only the Bay of Bengal subset is requested through NASA's cloud "
      "OPeNDAP service (DAP4 constraint expressions), about 240 KB per day instead of the 396 MB global daily file."),
    h2("4.5 MARIDA (Marine Debris Archive)"),
    p("MARIDA is a public benchmark of Sentinel-2 image patches (256 × 256 pixels at 10 m, 11 bands) with pixel labels in 15 "
      "classes and an annotator confidence level (high, moderate, low). It has official splits of 694 training, 328 "
      "validation and 359 test patches (1,381 in total). The pixel counts below are for training plus validation."),
    table([["Class", "Pixels", "Class", "Pixels", "Class", "Pixels"]] +
          [[a, f"{mar_counts.get(a, 0):,}", b, f"{mar_counts.get(b, 0):,}", c, f"{mar_counts.get(c, 0):,}"]
           for a, b, c in [("Marine Debris", "Ship", "Sediment-Laden Water"), ("Dense Sargassum", "Clouds", "Foam"),
                           ("Sparse Sargassum", "Marine Water", "Turbid Water"), ("Natural Organic Material", "Cloud Shadows", "Shallow Water"),
                           ("Waves", "Wakes", "Mixed Water")]],
          [36 * mm, 22 * mm, 30 * mm, 22 * mm, 40 * mm, 24 * mm]),
    h2("4.6 NOAA Global Drifter Program"),
    p("Surface drifting buoys tracked by satellite. We use the quality-controlled, 6-hourly interpolated dataset "
      "(<font name='Mono'>drifter_6hour_qc</font>, NOAA AOML ERDDAP), available until mid-2025. Seven drifters were in the Bay "
      f"during January–June 2025. Five were active over {VAL['window'][0]} to {VAL['window'][1]}, giving {VAL['cases']} "
      "buoy-day test cases (each with a known position at the start, +24 h and +48 h). All five had lost their drogue, so "
      "they float at the surface and are closer in behaviour to floating debris."),
    h2("4.7 Open-Meteo (live forecasts and fallback)"),
    p("NASA OSCAR and MERRA-2 are published days to weeks after the fact, so live runs use forecasts from Open-Meteo: the "
      "Marine API (Mercator / Météo-France SMOC ocean model currents, hourly), the Forecast API (GFS/ECMWF 10 m wind) and "
      "the Archive API (ERA5 reanalysis wind for past dates). Points are requested on a 0.5° grid (about 1,365 points over "
      "the Bay), cached as netCDF, and converted from speed and direction to u/v components."),
    h2("4.8 Natural Earth and curated reference lists"),
    p("Natural Earth 10 m land polygons and coastlines provide the land mask (beaching, inland-water removal, route "
      "checks) and distance to the coast. Three hand-entered lists with approximate coordinates support the analysis: "
      "<b>19 sensitive coastal sites</b> (mangroves such as the Sundarbans and Bhitarkanika, olive-ridley nesting beaches, "
      "Ramsar lagoons, Andaman coral reefs and major ports), <b>12 river mouths</b> for source attribution, and <b>8 port "
      "anchorages</b> for route planning."),
    CondPageBreak(120 * mm),
])

# ================================================================ 5 methods
add([
    h1("5. Methods: how each model works"),
    p("This section describes every processing step and model with its parameters, exactly as implemented. "
      "Settings live in <font name='Mono'>backend/aquatrace/config.py</font> and the module named in each heading."),
    h2("5.1 Pre-processing and masking"),
    p("<b>One spectral language for two sensors.</b> PACE is hyperspectral, so each Sentinel-2-equivalent band is the mean "
      "of the PACE bands inside that band's wavelength range. The detector and classifier then see the same 11 bands from "
      "either satellite."),
    table([["Sentinel-2 band", "B1", "B2", "B3", "B4", "B5", "B6"],
           ["Range (nm)", "433–453", "458–523", "543–578", "650–680", "698–713", "733–748"],
           ["Sentinel-2 band", "B7", "B8", "B8A", "B11", "B12", ""],
           ["Range (nm)", "773–793", "785–899", "855–875", "1565–1660", "2100–2280", ""]],
          [30 * mm] + [24 * mm] * 6, zebra=False),
    Spacer(1, 6),
    *bullets(["<b>PACE masks</b>: the L2 quality flags listed in 4.1; an extra haze test marks pixels with B8A reflectance "
              "above 0.06 as cloud; the cloud mask is grown by 3 pixels because cloud edges cause most false alarms.",
              "<b>Sentinel-2 masks</b>: only SCL water (class 6); clouds, cirrus and shadows are removed with a 5-pixel buffer.",
              "<b>Candidate exclusions</b>: very bright objects (B2 more than 0.06 above the local background, or B11 above 0.10: "
              "ships, platforms, cloud fragments); a shoreline strip (2.5 km for PACE, 0.4 km for Sentinel-2) where mixed "
              "land/water pixels mimic floating material; and inland water (backwaters, lakes), since this is a <i>marine</i> product."]),
    h2("5.2 Spectral anomaly detection (detect.py)"),
    p("Floating material raises near-infrared reflectance above the dark water around it. We use the Floating Debris Index "
      "(Biermann et al., 2020) and, as diagnostics, the Floating Algae Index (Hu, 2009) and NDVI:"),
    code("FDI  = R(B8) − [ R(B6) + (R(B11) − R(B6)) × ((λ8 − λ4) / (λ11 − λ4)) × 10 ]\n"
         "FAI  = R(B8) − [ R(B4) + (R(B11) − R(B4)) × (λ8 − λ4) / (λ11 − λ4) ]\n"
         "NDVI = (R(B8) − R(B4)) / (R(B8) + R(B4))\n"
         "band centres: λ4 = 664.8, λ6 = 740.5, λ8 = 832.8, λ11 = 1612 nm"),
    p("Each pixel's FDI is compared with its local open-water background, the median of valid pixels in blocks of 41 pixels "
      "(PACE, about 50 km) or 101 pixels (Sentinel-2 at 20 m, about 2 km), upsampled smoothly. The difference becomes a robust "
      "z-score using the median absolute deviation (MAD):"),
    code("z = (FDI − background) / (1.4826 × MAD)\ncandidate pixel:  z ≥ 3.5  and  FDI above its background"),
    h2("5.3 AI classifier (marida.py)"),
    p("A pixel classifier separates real floating material from look-alikes (ships, wakes, waves, clouds, turbid or shallow "
      "water). It uses 44 features per pixel:"),
    *bullets(["<b>15 background-relative spectral features</b>: the 11 bands minus the local water background, FDI and FAI of "
              "those differences, and normalised ΔNDVI = (ΔB8 − ΔB4) / (|ΔB8| + |ΔB4| + 0.001) and ΔNDWI = (ΔB3 − ΔB8) / (|ΔB3| + |ΔB8| + 0.001). "
              "Subtracting the background removes most of the difference between processing levels (MARIDA vs Sentinel-2 L2A vs PACE).",
              "<b>29 texture features</b>: for ΔFDI, ΔNDVI, ΔB8 and ΔB2, the mean and standard deviation in 3 × 3 and 7 × 7 "
              "windows, plus local contrast (value − 7 × 7 mean); added in round 2: the 15 × 15 mean and standard deviation of ΔFDI "
              "and ΔNDVI, edge strength (Sobel gradient) of ΔFDI, ΔB8 and ΔB2, and the 7 × 7 standard deviation of ΔB4 and ΔB11. "
              "Debris lines, ships, waves and foam differ in shape as much as in colour; windrows are thin lines with sharp edges."]),
    table([["Setting", "Value"],
           ["Algorithm", "Two experts (scikit-learn). Extra Trees (extremely randomised trees; Geurts et al., 2006) decides "
                         "floating material or not; a 50/50 soft vote of Extra Trees and histogram gradient boosting names every other class"],
           ["Settings", "Extra Trees: 500 trees, minimum 2 samples per leaf. Gradient boosting: 400 rounds, learning rate 0.08, "
                        "63 leaves, L2 regularisation 1.0"],
           ["Class imbalance", "balanced class weights (per bootstrap sample for Extra Trees); at most 40,000 training pixels per class"],
           ["Training data", "MARIDA train + validation splits (choices made on validation only; see 6.1)"],
           ["Evaluation", "MARIDA test split, scored once per development round"],
           ["At inference", "pixels classed as Ship, Clouds, Waves, Cloud Shadows or Wakes are rejected; "
                            "P(floating) = P(Marine Debris) + P(Dense Sargassum) + P(Sparse Sargassum) from Extra Trees; on Sentinel-2 a candidate needs P(floating) ≥ 0.5"]],
          [38 * mm, 136 * mm]),
    h2("5.4 Hotspots and confidence"),
    p("Candidate pixels are grouped into hotspots (8-connected components after a 1-pixel dilation; at least 2 pixels). "
      "Each hotspot gets a confidence between 0 and 1:"),
    code("A  = clip( log10(mean z / 3.5) / 1.5, 0, 1 )      anomaly strength (log scale)\n"
         "Sz = clip( ln(1 + pixels) / ln(41), 0, 1 )      hotspot size\n"
         "Sentinel-2:  conf = 0.45·A + 0.15·Sz + 0.40·P(floating)\n"
         "PACE:        conf = 0.65·A + 0.15·Sz + 0.20·P(floating)\n"
         "             (a 10 m-trained model on ~1 km pixels is supporting evidence only)\n"
         "then         conf × (1 − 0.5 × cloud share)\n"
         "             cloud share = part of the hotspot plus a 4-pixel margin that is cloud or invalid"),
    p("A run keeps the 10 most confident hotspots per PACE scene and 3 per Sentinel-2 site (25 at most). Hotspot radius is "
      "max(pixel size, √(area / π))."),
    h2("5.5 Fusing currents and wind (forcing.py)"),
    p("Every current or wind source is converted to one structure: u and v (m/s, east and north) on a (time, latitude, "
      "longitude) grid. Land gaps are filled with the nearest valid value so interpolation near the coast stays finite. The "
      "land polygon, not the grid, decides beaching. Values are interpolated linearly in time and space. Outside the time "
      "window the nearest time is used (persistence). Replays load 3 days before to 3 days after the pass. Live runs load "
      "4 days before the oldest pass to 3 days after now, which allows back-tracking."),
    h2("5.6 Lagrangian drift model (drift.py)"),
    p("Each hotspot is released as an ensemble of 300 virtual particles, spread in a Gaussian cloud of the hotspot's radius "
      "(at least 0.5 km), plus one central particle with average windage and no randomness. Every hour each particle moves with:"),
    code("dx/dt = u_current(x, t) + α · u_wind10m(x, t) + e        (4th-order Runge–Kutta, Δt = 1 h)\n"
         "      + random walk  N(0, 1) · √(2 K Δt)       K = 20 m²/s  →  σ ≈ 380 m per step\n"
         "α ~ Uniform(2%, 3%) per particle (unknown debris type)\n"
         "e ~ N(0, 0.16 m/s) per particle and axis, constant in time, in ± pairs (current error)\n"
         "Δlat = Δy / 111,320 m,   Δlon = Δx / (111,320 m · cos lat)"),
    *bullets(["<b>Beaching</b>: a particle that moves from sea onto land (Natural Earth 10 m) stops and is counted as beached. "
              "Particles that start inside the coarse land polygon near the shore are not counted at t = 0.",
              "<b>Outputs</b>: the hourly central track; particle snapshots every 3 h; and at +24 h and +48 h the mean position, spread "
              "(root-mean-square distance from the mean), distance travelled, share beached and a 90% uncertainty polygon "
              "(convex hull of the 90% of particles nearest the median), plus the time by which half the particles are ashore.",
              "<b>Current error</b>: daily 25 km current maps miss tides, inertial motion and small eddies. Against real buoys the "
              "forecast error grows in proportion to time, the signature of a velocity error, which diffusion (growing with √t) "
              "cannot reproduce. Each particle therefore carries its own constant current error; the ± pairs widen the cone "
              "without moving its centre.",
              f"<b>Tuned on a held-out design</b>: windage and current error were chosen on January 2025 buoys and scored on "
              f"February 2025 (6.3). Windage {BEST_WIND * 100:.1f}% gave the lowest January error, so the ensemble samples 2–3%."]),
    h2("5.7 Nowcasting (live mode)"),
    p("A detection seen h hours ago is drifted forward h hours to the issue time. Its new position is the mean of the "
      "particles still afloat. If 80% or more have beached, the hotspot is flagged as <i>likely already ashore</i> and the "
      "recommendation becomes a beach survey. Its radius grows to the nowcast spread, and the 48-hour forecast then starts "
      "from <i>now</i>."),
    h2("5.8 Source back-tracking (source.py)"),
    p("The same particle model runs with time reversed for 72 hours. Back-tracked particles that reach land mark a coastal "
      "source. Each is assigned to the nearest of 12 river mouths if one is within 60 km. If at least 30% of particles reach "
      "the coast, the summary names the dominant river mouth (land-based source) or <i>local coastline</i>. Otherwise it "
      "reports where the patch was 72 hours earlier, at sea."),
    h2("5.9 Recurrence"),
    p("In live mode, detections from different passes within 15 km of each other are merged and the newest is kept. "
      "Recurrence = (passes in which it was seen − 1) / (passes − 1). Replays compare with hotspots from earlier runs."),
    h2("5.10 Cleanup risk score (risk.py)"),
    code("risk = 100 × ( 0.35·confidence + 0.25·proximity + 0.15·beaching\n"
         "             + 0.15·recurrence + 0.10·certainty )\n"
         "proximity = 0.75 · max over sites( weight · e^(−d_site / 60 km) )\n"
         "          + 0.25 · e^(−d_coast / 20 km)                 (closest along the 48 h track)\n"
         "beaching  = share of particles ashore by +48 h\n"
         "certainty = 1 − min( flow spread at 48 h / 25 km, 1 )\n"
         "            flow spread = spread without the current-error and diffusion terms\n"
         "            (those are the same for every hotspot, so they carry no ranking information)\n"
         "tiers: High ≥ 60,  Medium ≥ 40,  Low < 40"),
    p("Site weights are 0.6–1.0: 1.0 for the Sundarbans, Bhitarkanika–Gahirmatha, Mahatma Gandhi Marine National Park and "
      "St. Martin's Island; 0.8–0.9 for other mangroves, lagoons and reefs; 0.6–0.7 for ports and busy beaches. "
      "Recommended actions follow simple rules:"),
    *bullets(["Nowcast says ashore → send a beach cleanup or survey team.",
              "Half of the particles ashore within 24 h → send a shoreline team and alert the nearest sensitive site.",
              "High tier → deploy a vessel within 24 h and intercept at the forecast +24 h position.",
              "Medium tier → schedule a patrol and re-check the next satellite pass.  Low tier → monitor."]),
    h2("5.11 Moving-target route planner (route.py)"),
    p("From a port anchorage, the planner repeatedly picks the next hotspot that minimises <i>travel time × (1.6 − risk/100)</i>, "
      "favouring hotspots that are close <i>and</i> high-risk. Debris keeps moving while the boat travels, so each stop is aimed "
      "at the hotspot's forecast position at the boat's arrival time, found by fixed-point iteration (6 steps) on the forecast "
      "track. Defaults: 10 knots, 2 hours of cleanup per stop, candidates within 450 km. A leg that would cross land detours "
      "through the shortest single offshore waypoint (offsets of 10–110 km at 25%, 50% and 75% of the leg). Stops beyond the "
      "48 h forecast or already ashore are skipped."),
    CondPageBreak(120 * mm),
])

# ================================================================ 6 accuracy & validation
labels = M["confusion_matrix"]["labels"]
cm = M["confusion_matrix"]["matrix"]
di = labels.index("Marine Debris")
true_debris = sorted(((labels[j], cm[di][j]) for j in range(len(labels)) if cm[di][j] and j != di), key=lambda x: -x[1])[:4]
pred_debris = sorted(((labels[i], cm[i][di]) for i in range(len(labels)) if cm[i][di] and i != di), key=lambda x: -x[1])[:5]
exp_rows = [["Features", "Model", "Labels", "Accuracy", "Macro F1", "Debris F1", "Floating F1", "Train (s)"]]
for r in EXP:
    chosen = r["features"] == "pixel+texture" and r["model"] == "ExtraTrees" and not r["conf_weighted"]
    b = (lambda t: f"<b>{t}</b>") if chosen else (lambda t: t)
    exp_rows.append([b(r["features"]), b(r["model"] + (" ✓ chosen" if chosen else "")), b("confidence" if r["conf_weighted"] else "equal"),
                     b(pct(r["accuracy"])), b(f"{r['macro_f1']:.3f}"), b(f"{r['debris']['f1']:.3f}"), b(f"{r['floating']['f1']:.3f}"), b(f"{r['seconds']:.0f}")])
fi = list(M["feature_importance"].items())[:10]


def _exp2_name(r):
    n = r["name"]
    if n.startswith("Hybrid"):
        w = r["ensemble_weight"]
        return f"Two experts: ET decides floating, vote {w:.1f} ET + {1 - w:.1f} GB" + (" ✓ chosen" if w == 0.5 else "")
    if n.startswith("Ensemble"):
        return "Soft vote " + n.split()[1] + " ET + " + f"{1 - float(n.split()[1]):.1f}" + " GB"
    if "debris>=" in n:
        return f"Extra Trees v2, debris if P(debris) ≥ {r['debris_threshold']}"
    return {"ET500 v1 cap40k": "Extra Trees, features v1 (round-1 model)", "ET500 v2 cap40k": "Extra Trees, features v2",
            "ET500 v2 cap100k": "Extra Trees v2, 100,000 px per class", "ET500 v2 capallk": "Extra Trees v2, all pixels",
            "HistGB v2 cap40k": "Gradient boosting (GB), features v2"}.get(n, n)


exp2_rows = [["Candidate (validation split)", "Accuracy", "Macro F1", "Debris F1", "Floating F1"]]
for r in EXP2:
    if "|" in r["name"] and not r["name"].startswith("ET500"):
        continue  # threshold sweeps on the soft vote: same conclusion as for Extra Trees
    if r.get("debris_threshold") not in (None, 0.25, 0.35):
        continue
    b = (lambda t: f"<b>{t}</b>") if r.get("ensemble_weight") == 0.5 else (lambda t: t)
    exp2_rows.append([b(_exp2_name(r)), b(pct(r["accuracy"])), b(f"{r['macro_f1']:.3f}"), b(f"{r['debris']['f1']:.3f}"),
                      b(f"{r['floating']['f1']:.3f}")])
mid = min(CAL["floating_material"]["curve"], key=lambda c: abs(c["confidence"] - 0.65))

add([
    h1("6. Accuracy and validation"),
    h2("6.1 Detection: the AI classifier"),
    p(f"The final model was trained on MARIDA's training and validation splits and scored on the official test split "
      f"({M['test_pixels']:,} labelled pixels it never saw). All model and feature choices were made on the validation split. "
      "The test split was scored once per development round (twice in total), and the round-2 model was kept whatever its "
      "test score, so the numbers are not tuned to the test data."),
    kpis([(pct(M["accuracy"]), "overall accuracy, 15 classes"), (f"{M['macro_f1']:.3f}", "macro F1 (all classes equal)"),
          (f"{M['floating_material']['f1']:.3f}", f"floating-material F1 (P {M['floating_material']['precision']:.2f}, R {M['floating_material']['recall']:.2f})"),
          (f"{M['debris']['f1']:.3f}", f"marine-debris F1 (P {M['debris']['precision']:.2f}, R {M['debris']['recall']:.2f})")]),
    Spacer(1, 8),
    figure(IMG / "c_model.png", 160, "Figure 2. First model (pixel features, Random Forest), round 1 (texture features, Extra Trees) "
           "and round 2 (current: two experts, features v2) on the MARIDA test split."),
    p("<b>How to read these numbers.</b> Most labelled pixels are water or cloud, so overall accuracy is flattered by easy "
      f"classes. The F1 scores for the classes that matter are more informative. <i>Recall</i> {M['debris']['recall']:.2f} for debris "
      f"means the model finds {M['debris']['recall'] * 100:.0f} of every 100 debris pixels; <i>precision</i> {M['debris']['precision']:.2f} "
      f"means about {M['debris']['precision'] * 10:.0f} in 10 pixels it calls debris really are. "
      "In the full pipeline, clouds are masked and ships, wakes and waves are rejected before the model's vote counts, so "
      "operational false alarms are lower than the raw precision suggests."),
    h3("Evidence: how a satellite can see floating debris"),
    p("No satellite can see a bottle: Sentinel-2 pixels are 20 m (10 m for some bands) and PACE pixels about 1.2 km. "
      "What a satellite measures is how much sunlight each pixel reflects in each colour band. A patch or line of floating "
      "material changes that light in a recognisable way. The clear map in the dashboard is a background basemap, and the "
      "dots on it are forecast particles; the detections themselves come from pixels like the ones below."),
    figure(EVIMG / "e_pixels.png", 150, f"Figure 2b. Hotspot {EVD['debris_hotspot']['id']}, 9 km off Visakhapatnam (Sentinel-2, "
           f"{EVD['debris_hotspot']['time'][:10]}): {EVD['debris_hotspot']['pixels']} pixels stand out from the water around them "
           f"(up to {EVD['debris_hotspot']['z_max']:.0f} robust standard deviations)."),
    p("<b>The physics.</b> Water absorbs near-infrared light, so open sea is dark in the near-infrared bands. Anything "
      "floating on the surface reflects near-infrared light back. The Floating Debris Index (FDI; Biermann et al., 2020) "
      "measures that excess against a baseline drawn between the red-edge and short-wave infrared bands. The shape of the "
      "reflection across bands is a fingerprint: floating algae and vegetation jump sharply at the red edge (chlorophyll); "
      "plastic debris is flatter and bright; ships are bright even in the short-wave infrared."),
    figure(EVIMG / "e_spectra.png", 150, "Figure 2c. Reflectance fingerprints. Solid: average of expert-labelled MARIDA pixels "
           f"(water {EVD['marida_reference']['Marine Water']['pixels']:,}, debris {EVD['marida_reference']['Marine Debris']['pixels']:,}, "
           f"dense algae {EVD['marida_reference']['Dense Sargassum']['pixels']:,} pixels). Dashed: our Bay of Bengal hotspots."),
    p("Our Visakhapatnam hotspot follows the flat debris shape; the large Hooghly patch follows the vegetation shape "
      "(most likely floating water hyacinth), and the classifier labels them accordingly. This is why AquaTrace reports "
      "<i>potential</i> floating material with a type and a confidence: a spectrum can rule things in or out, but only a "
      "boat or drone can confirm plastic. Independent field experiments support the approach: plastic targets placed at sea "
      "were detected in Sentinel-2 imagery (Topouzelis et al., 2019), and FDI-based classification separated plastics from "
      "algae, driftwood and foam in several coastal waters (Biermann et al., 2020)."),
    figure(EVIMG / "e_marida.png", 150, f"Figure 2d. A MARIDA test scene from the Gulf of Honduras ({EVD['marida_patch_check']['lat']:.1f}°N, "
           f"{abs(EVD['marida_patch_check']['lon']):.1f}°W), never used in training: the model found "
           f"{EVD['marida_patch_check']['debris_found']} of {EVD['marida_patch_check']['debris_labelled']} expert-labelled debris pixels "
           f"and flagged {EVD['marida_patch_check']['water_flagged_floating']} of {EVD['marida_patch_check']['water_labelled']} labelled "
           "water pixels. Across the whole test split it finds 89% of the labelled debris."),
    h3("Model selection, round 1 (validation split)"),
    table(exp_rows, [27 * mm, 32 * mm, 21 * mm, 19 * mm, 17 * mm, 18 * mm, 22 * mm, 18 * mm]),
    p("Texture features gave the largest gain (about 8 points of accuracy; floating-material F1 from ≈0.40 to ≈0.85). "
      "Gradient boosting reached the highest validation accuracy (90.0%) but found less debris (F1 0.77 vs 0.84), so Extra "
      "Trees was chosen: the system optimises for the class that matters. Confidence weighting did not help Extra Trees.", "small"),
    h3("Model selection, round 2 (validation split)"),
    table(exp2_rows, [94 * mm, 18 * mm, 18 * mm, 20 * mm, 22 * mm]),
    p("The extended texture features (v2) improved accuracy and floating-material F1. More training pixels and a lower debris "
      "threshold did not help. Gradient boosting again had the best overall accuracy but weaker debris detection, so the two "
      "were combined as experts: Extra Trees decides floating material, the vote names everything else. That kept Extra "
      "Trees' debris and floating-material F1 exactly and raised validation accuracy from 89.6% to 94.1%. On the test split "
      "12 of 15 classes improved, most for Wakes, Mixed Water and Waves.", "small"),
    Spacer(1, 6),
    p("<b>Why background-relative features.</b> A model trained on raw reflectance scored higher on MARIDA itself (debris F1 "
      "0.75 with pixel features) but labelled ordinary Bay of Bengal water as clouds and wakes, because MARIDA patches and "
      "Sentinel-2 L2A scenes are processed differently. Subtracting the local water background fixed this: on the "
      "Sentinel-2 scenes, normal water is classed as marine, turbid or sediment-laden water, and only 0.00–0.13% of water "
      "pixels are flagged as floating material."),
    figure(IMG / "c_perclass.png", 150, "Figure 3. F1 score per class on the MARIDA test split. Blue: the floating-material classes "
           "used by AquaTrace."),
    h3("Where the model goes wrong"),
    table([["True marine-debris pixels predicted as", "Pixels", "Pixels predicted as debris that were really", "Pixels"]] +
          [[a[0] if a else "", str(a[1]) if a else "", b[0] if b else "", str(b[1]) if b else ""]
           for a, b in zip(true_debris + [None] * (5 - len(true_debris)), pred_debris + [None] * (5 - len(pred_debris)))],
          [58 * mm, 18 * mm, 76 * mm, 22 * mm]),
    p(f"Correctly classified debris pixels: {cm[di][di]} of {sum(cm[di])}. The weakest classes (Foam, Natural Organic Material, "
      "Mixed Water, Wakes) have very few training pixels.", "small"),
    h3("Most important features"),
    table([["Feature", "Importance", "Feature", "Importance"]] +
          [[fi[i][0], f"{fi[i][1]:.3f}", fi[i + 5][0], f"{fi[i + 5][1]:.3f}"] for i in range(5)],
          [55 * mm, 32 * mm, 55 * mm, 32 * mm]),
    p("_m3/_m7/_m15 = mean in a 3 × 3 / 7 × 7 / 15 × 15 window, _s = standard deviation, _grad = edge strength (Extra Trees "
      "importances). Neighbourhood statistics of ΔNDVI, ΔFDI and the blue "
      "and near-infrared bands dominate, confirming that texture carries much of the signal.", "small"),
    h2("6.2 Confidence calibration"),
    p("A useful confidence must mean what it says: of all pixels given 80%, about 80% should be floating material. The "
      "reliability diagram compares stated confidence with observed frequency on the test split."),
    figure(IMG / "c_calibration.png", 112, "Figure 4. Reliability diagram (bins with at least 20 pixels)."),
    table([["Target", "Expected calibration error (ECE)", "Brier score", "Positive pixels / total"],
           ["Floating material", pct(CAL["floating_material"]["ece"]), f"{CAL['floating_material']['brier']:.4f}", f"{CAL['floating_material']['positives']:,} / {CAL['floating_material']['n']:,}"],
           ["Marine debris", pct(CAL["marine_debris"]["ece"]), f"{CAL['marine_debris']['brier']:.4f}", f"{CAL['marine_debris']['positives']:,} / {CAL['marine_debris']['n']:,}"]],
          [40 * mm, 52 * mm, 30 * mm, 52 * mm]),
    p("ECE is the average gap between stated confidence and observed frequency. The small values are helped by the many "
      "easy water pixels. The curve is S-shaped: pixels given 20–45% are floating material less often than stated "
      f"(over-confident), while pixels given 60–90% are right more often than stated (under-confident: about {mid['observed'] * 100:.0f}% "
      f"at a stated {mid['confidence'] * 100:.0f}%). "
      "On Sentinel-2 AquaTrace only acts on pixels above 50%, so the part of the curve it uses errs on the safe side.", "small"),
    h2("6.3 Drift forecast: validation against real buoys"),
    p(f"<b>Design.</b> For every buoy and every day at 00:00 UTC with a full 48-hour track ahead, the model released particles "
      "at the buoy's true position and forecast its position at +24 h and +48 h. Drift settings were tuned on January 2025 "
      f"({N_CAL} cases) and are scored here, once, on February 2025 ({VAL['cases']} cases, {VAL['drifters']} drifters, "
      f"{VAL['window'][0]} to {VAL['window'][1]}), which was not used for tuning. The error is the great-circle distance between the "
      "forecast ensemble mean and where the buoy really went. Two references: <b>persistence</b> (the buoy stays where it was "
      "seen, which is what a single satellite snapshot implies) and <b>currents only</b> (the same model without wind)."),
    figure(IMG / "c_drift.png", 160, f"Figure 5. Median forecast error with NASA OSCAR currents and MERRA-2 wind ({VAL['cases']} forecasts)."),
    table([["Method (NASA OSCAR + MERRA-2)", "+24 h median", "+24 h mean", "+24 h 90th pct", "+48 h median", "+48 h mean", "+48 h 90th pct"]] +
          [[name] + [km(VAL[k][h][s]) for h in ("24", "48") for s in ("median_km", "mean_km", "p90_km")]
           for name, k in (("Snapshot (debris stays put)", "persistence"), ("Currents only", "currents_only"), ("AquaTrace: currents + wind", "summary"))],
          [46 * mm, 21 * mm, 21 * mm, 21 * mm, 22 * mm, 21 * mm, 22 * mm]),
    p(f"<b>Skill over a snapshot</b> (1 − model error / persistence error): {VAL['skill_vs_persistence']['24'] * 100:.0f}% at +24 h and "
      f"{VAL['skill_vs_persistence']['48'] * 100:.0f}% at +48 h. Adding wind to currents cut the 48-hour median error from "
      f"{km(VAL['currents_only']['48']['median_km'])} to {km(VAL['summary']['48']['median_km'])}, direct evidence for the "
      f"wind + current fusion in the project's design. For a cleanup boat, a {VAL['summary']['48']['median_km']:.0f} km search radius "
      f"instead of {VAL['persistence']['48']['median_km']:.0f} km is about "
      f"{(VAL['persistence']['48']['median_km'] / VAL['summary']['48']['median_km']) ** 2:.0f} times less sea to search."),
    h3("Is the uncertainty cone honest?"),
    p("The map draws a cone that should contain 90% of outcomes. We checked whether the real buoy ended up inside it. "
      "With diffusion alone the cone was far too narrow: it held the buoy only "
      f"{CONE_BEFORE[0] * 100:.0f}% of the time at +24 h and {CONE_BEFORE[1] * 100:.0f}% at +48 h. Adding a per-particle current "
      f"error (σ = 0.16 m/s, chosen on January) raised this to {CONE_AFTER[0] * 100:.0f}% and {CONE_AFTER[1] * 100:.0f}% on the "
      "held-out month, close to the 90% target. Uncertainty in the ensemble is now a measured quantity, not a decoration."),
    figure(IMG / "c_cone.png", 150, "Figure 6. Share of real buoys inside the 90% cone on the held-out month (February 2025)."),
    table([["Setting (held-out month)", "+24 h median", "+48 h median", "Inside cone +24 h", "Inside cone +48 h", "Cone area +48 h"],
           ["Before: 1–3% wind, diffusion only", km(TUNE["baseline_holdout"]["24"]["median_km"]), km(TUNE["baseline_holdout"]["48"]["median_km"]),
            pct(CONE_BEFORE[0]), pct(CONE_BEFORE[1]), f"{TUNE['baseline_holdout']['48']['cone_area_km2']:,.0f} km²"],
           ["After: 2–3% wind + current error", km(VAL["summary"]["24"]["median_km"]), km(VAL["summary"]["48"]["median_km"]),
            pct(CONE_AFTER[0]), pct(CONE_AFTER[1]), f"{TUNE['chosen_holdout']['48']['cone_area_km2']:,.0f} km²"]],
          [50 * mm, 22 * mm, 22 * mm, 26 * mm, 26 * mm, 28 * mm]),
    p("The median position error barely changed (about 1 km, within the noise of five buoys): it is set by the daily, "
      "25 km resolution of the current data. Scaling the currents up or down made it worse. What changed is that the cone "
      "now tells a cleanup crew honestly how wide to search.", "small"),
    h3("Effect of the current and wind source"),
    table([["Forcing", "Window", "Cases", "+24 h median", "+48 h median", "Skill +48 h"],
           ["NASA OSCAR v2.0 + MERRA-2", f"{VAL['window'][0]} – {VAL['window'][1]}", str(VAL["cases"]), km(VAL["summary"]["24"]["median_km"]), km(VAL["summary"]["48"]["median_km"]), f"{VAL['skill_vs_persistence']['48'] * 100:.0f}%"],
           ["Open-Meteo (Mercator SMOC + ERA5)", f"{VAL_OM['window'][0]} – {VAL_OM['window'][1]}", str(VAL_OM["cases"]), km(VAL_OM["summary"]["24"]["median_km"]), km(VAL_OM["summary"]["48"]["median_km"]), f"{VAL_OM['skill_vs_persistence']['48'] * 100:.0f}%"]],
          [52 * mm, 44 * mm, 14 * mm, 22 * mm, 22 * mm, 20 * mm]),
    p("The open fallback, sampled on a coarser 0.5° grid, was less accurate. NASA forcing is preferred whenever it is "
      "available; live runs must use forecasts, because OSCAR and MERRA-2 arrive days to weeks late.", "small"),
    h3("Windage calibration"),
    figure(IMG / "c_windage.png", 160, "Figure 7. Median buoy error on the January tuning month as a function of windage, the share of "
           "10 m wind speed added to the current."),
    p(f"On the January buoys the error was lowest at {BEST_WIND * 100:.1f}% of wind speed and rose for less or more wind. The "
      "operational ensemble samples 2–3% per particle around this optimum, so the spread also expresses uncertainty "
      "about debris type. The undrogued buoys float at the surface, the closest available proxy for debris, but their "
      "windage is not identical to that of plastic items."),
    CondPageBreak(120 * mm),
])

# ================================================================ 7 runs & examples
def tiers(r):
    c = Counter(h["risk"]["tier"] for h in r["hotspots"])
    return f"{c.get('High', 0)} / {c.get('Medium', 0)} / {c.get('Low', 0)}"


NICE = {"live_20260930_1900": "Live, 30 Sep 2026", "20260314_pace": "Replay, 14 Mar 2026", "20260305_s2": "Replay, 5 Mar 2026"}
run_rows = [["Run", "Detection", "Currents / wind", "Scenes", "Hotspots", "High / Med / Low", "Runtime"]]
for rid, r in sorted(RUNS.items(), reverse=True):
    run_rows.append([NICE[rid], r["sources"]["detection"].replace(" (L2 SFREFL)", "").replace(" L2A (MSI)", ""),
                     ("OSCAR + MERRA-2" if "OSCAR" in r["sources"]["currents"]["source"] else "Open-Meteo forecasts"),
                     str(len(r["detection"])), str(len(r["hotspots"])), tiers(r), f"{r['runtime_s']:.0f} s"])
scene_rows = [["Run", "Sensor / site", "Observed (UTC)", "Usable water pixels", "Candidate pixels", "Hotspots", "Cloud"]]
for rid in ("live_20260930_1900", "20260314_pace"):
    for d in RUNS[rid]["detection"]:
        scene_rows.append([NICE[rid].replace(" 2026", ""), ("PACE" if "PACE" in d["sensor"] else "S2 · " + d.get("target", "")),
                           d["observed"].replace("T", " ")[:16], f"{d['valid_pixels']:,}", f"{d['candidate_pixels']:,}", str(d["hotspots"]),
                           pct(d["cloud_fraction"]) if d.get("cloud_fraction") is not None else "–"])
hs07 = next(h for h in REPLAY["hotspots"] if h["id"] == "HS-07")
fc07 = next(f for f in REPLAY["forecasts"] if f["id"] == "HS-07")
add([
    h1("7. Results from pipeline runs"),
    p("Three runs are included with the project: a live run issued 30 September 2026 19:00 UTC and two replays (14 March "
      "2026 with all NASA datasets, and 5 March 2026 with Sentinel-2 detection). Runtimes are with downloads already cached."),
    table(run_rows, [32 * mm, 36 * mm, 28 * mm, 16 * mm, 18 * mm, 26 * mm, 18 * mm]),
    Spacer(1, 6),
    table(scene_rows, [28 * mm, 42 * mm, 27 * mm, 24 * mm, 20 * mm, 19 * mm, 14 * mm]),
    p("The live run reflects post-monsoon conditions: the 30 September pass was 95% cloud, so most candidates come from the "
      f"28–29 September passes and were nowcast 36–86 hours forward. Live tiers (High / Medium / Low): {tiers(LIVE)}, an honest "
      "result for a cloudy period: old detections carry wide cones, which lowers their certainty.", "small"),
    h2("7.1 Example: a hotspot off Chennai (replay, 14 March 2026)"),
    figure(IMG / "ui_drawer.jpg", 174, "Figure 8. Hotspot HS-07 at +30 h: the forecast cone runs north along the coast, the purple "
           "back-track shows where it came from, and the drawer explains the recommendation."),
    p(f"HS-07 was detected by Sentinel-2 on {hs07['observed'][:10]} with confidence {hs07['confidence']:.2f}. The forecast takes it "
      f"{fc07['horizons']['48']['displacement_km']:.0f} km north in 48 h, with {fc07['beached_fraction'] * 100:.0f}% of particles "
      f"reaching the shore (first after {fc07['first_beaching_h']:.0f} h, half by +{fc07['half_beached_h']:.0f} h). "
      f"Risk {hs07['risk']['risk_score']:.0f} ({hs07['risk']['tier']}). "
      f"Recommended action: “{hs07['risk']['action']}” Source tracking: “{hs07['source']['summary']}”"),
    h2("7.2 Example: live map and cleanup route (30 September 2026)"),
    figure(IMG / "ui_route.jpg", 174, f"Figure 9. Live run with a cleanup route from {ROUTE_LIVE['port']['name']}: "
           f"{len(ROUTE_LIVE['stops'])} stops, {ROUTE_LIVE['total_km']} km, {ROUTE_LIVE['total_h']} h at 10 knots."),
    table([["Stop", "Hotspot", "Tier", "Arrive", "Leg", "Drift before the boat arrives"]] +
          [[str(i + 1), s["id"], s["tier"], f"+{s['arrive_h']} h", f"{s['leg_km']} km", f"{s['drift_since_seen_km']} km"]
           for i, s in enumerate(ROUTE_LIVE["stops"])],
          [14 * mm, 24 * mm, 22 * mm, 22 * mm, 24 * mm, 68 * mm]),
    p(f"A second example from the replay: departing {ROUTE_REPLAY['port']['name']}, {len(ROUTE_REPLAY['stops'])} stops, "
      f"{ROUTE_REPLAY['total_km']} km, {ROUTE_REPLAY['total_h']} h. In both cases patches move up to "
      f"{max(s['drift_since_seen_km'] for s in ROUTE_LIVE['stops'] + ROUTE_REPLAY['stops']):.0f} km before the boat "
      "arrives, which is why the planner targets the forecast position, not the last sighting. High-risk patches that are "
      "forecast to wash ashore go to shoreline teams instead.", "small"),
    figure(IMG / "ui_live_night.jpg", 174, "Figure 10. Night basemap with animated currents (cyan) and wind (amber), the debris-signal layer, "
           "and the Model trust panel."),
    CondPageBreak(120 * mm),
])

# ================================================================ 8 software
add([
    h1("8. Software and architecture"),
    h2("8.1 Technology stack"),
    table([["Layer", "Technology"],
           ["Language / runtime", "Python 3.14 (backend, pipeline), JavaScript (React) for the dashboard"],
           ["Scientific", "NumPy, SciPy, pandas, xarray, netCDF4 / h5netcdf, rasterio, pyproj, GeoPandas, Shapely"],
           ["Machine learning", "scikit-learn 1.9 (Extra Trees, histogram gradient boosting), joblib"],
           ["Data access", "earthaccess (NASA Earthdata), pystac-client (Earth Search STAC), requests (ERDDAP, Open-Meteo, OPeNDAP)"],
           ["API", "FastAPI + uvicorn"],
           ["Dashboard", "React 19, Vite 8, Leaflet 1.9 / react-leaflet 5, lucide-react icons, custom canvas layers for animated flow and particles"],
           ["Reporting", "matplotlib, ReportLab (this report), python-pptx (pitch deck)"]],
          [38 * mm, 136 * mm]),
    h2("8.2 Backend API"),
    p("There is no database. The pipeline writes files; the API reads and serves them, and computes what-if forecasts and "
      "routes on demand."),
    table([["Endpoint", "Returns"],
           ["GET /api/runs", "list of runs (from outputs/runs/index.json)"],
           ["GET /api/runs/{id}", "one run: hotspots, forecasts, overlays, sources, current/wind samples"],
           ["GET /api/runs/{id}/files/{path}", "satellite true-colour and debris-anomaly PNG overlays"],
           ["GET /api/metrics", "classifier metrics, calibration, buoy validation"],
           ["POST /api/forecast", "what-if: 48 h ensemble forecast and risk score for any sea point (not stored)"],
           ["GET /api/runs/{id}/route", "moving-target cleanup route from a chosen port (not stored)"],
           ["GET /api/ports", "port anchorages for the route planner"],
           ["GET /", "the dashboard (frontend/dist)"]],
          [58 * mm, 116 * mm]),
    h2("8.3 Where data is stored"),
    table([["Folder", "Contents", "Size"],
           ["data/raw/", "downloaded inputs: PACE granules, OSCAR, MERRA-2 subsets, MARIDA, NOAA drifters, Natural Earth", "≈10 GB"],
           ["data/processed/", "caches: current/wind grids (.nc), Sentinel-2 scenes (.npz)", "≈0.5 GB"],
           ["models/", "trained classifier (marida_rf.joblib, ~630 MB), metrics, calibration, experiments (.json)", "≈0.65 GB"],
           ["outputs/runs/&lt;id&gt;/", "run.json (all results of one run) + overlay PNGs; index.json lists runs", "≈14 MB"],
           ["outputs/", "drift_validation.json (held-out month), drift_tuning.json", "small"],
           ["~/.netrc (home folder)", "the user's Earthdata login, deliberately outside the project", "–"]],
          [40 * mm, 110 * mm, 24 * mm]),
    h2("8.4 Dashboard"),
    p("The dashboard is designed as a maritime operations chart. A bathymetric ocean basemap carries animated ocean "
      "currents, and risk tiers use the international signal-flag colours (red, yellow, green). Main elements:"),
    *bullets(["<b>Top bar</b>: switch between the live run and replays, see which datasets the run used, open Model trust.",
              "<b>Briefing</b>: headline count, first landfall, fastest drift, latest pass; tier filters, sorting, and a ranked list linked to the map by hover.",
              "<b>Map</b>: pulsing priority pins, 48 h tracks and uncertainty cones, drifting particles, nowcast trails, back-tracks, routes.",
              "<b>Detail drawer</b>: recommended action, risk gauge and breakdown, drift compass, source, evidence, copyable coordinates.",
              "<b>Time bar</b>: smooth 48 h playback (Space), arrow-key scrubbing, 1×/2×/4× speed, night bands (IST).",
              "<b>Toolbar</b>: Ocean / Satellite / Night basemaps, seven layers, what-if simulator, route planner. Views are shareable as links."]),
    h2("8.5 Performance"),
    table([["Task", "Time"],
           ["Detect one PACE granule (1.8 million pixels in the Bay window)", "≈13 s"],
           ["Replay run with cached data (17 hotspots, forecasts, back-tracks)", f"≈{REPLAY['runtime_s']:.0f} s"],
           ["Live run (3 PACE + 3 Sentinel-2 scenes, forecast forcing; PACE already downloaded)", f"≈{LIVE['runtime_s'] / 60:.0f} min"],
           ["Train the final classifier (500 Extra Trees + 400 boosting rounds)", f"≈{M['train_seconds']:.0f} s"],
           ["What-if forecast (300 particles, 48 h)", "≈1 s"]],
          [130 * mm, 44 * mm]),
    CondPageBreak(120 * mm),
])

# ================================================================ 9 operations
add([
    h1("9. How to run it"),
    code("./setup.sh                      # one-time: Python environment (+ dashboard build if npm exists)\n"
         "./run_demo.sh                   # API + dashboard on http://localhost:8000\n\n"
         "cd backend\n"
         "../.venv/bin/python -m aquatrace.pipeline --live                    # near-real-time run\n"
         "../.venv/bin/python -m aquatrace.pipeline --date 2026-03-14         # replay with NASA data\n"
         "../.venv/bin/python -m aquatrace.marida                             # retrain the classifier\n"
         "../.venv/bin/python -m aquatrace.experiments                        # model selection (validation)\n"
         "../.venv/bin/python -m aquatrace.calibration                        # reliability / ECE\n"
         "../.venv/bin/python -m aquatrace.experiments_v2                     # round-2 selection\n"
         "../.venv/bin/python -m aquatrace.tune_drift                         # tune drift (Jan buoys)\n"
         "../.venv/bin/python -m aquatrace.validate --holdout                 # score on Feb buoys"),
    *bullets(["<b>Earthdata login</b> (free) is needed for PACE, OSCAR and MERRA-2. Approve <i>NASA GESDISC DATA ARCHIVE</i> in the "
              "Earthdata profile for MERRA-2, then save the login once with earthaccess (stored in ~/.netrc).",
              "<b>Without a login</b>, runs fall back to Sentinel-2 and Open-Meteo automatically, and the dashboard reports which sources were used.",
              "<b>Sharing</b>: the full project zip (≈475 MB) contains code, saved runs, cached forcing and the trained model. "
              "The dashboard can be updated on its own with a ~200 KB frontend package.",
              "<b>Shareable views</b>: e.g. <font name='Mono'>?run=20260314_pace&amp;select=HS-07&amp;hour=24</font> or "
              "<font name='Mono'>?basemap=dark&amp;show=wind&amp;trust=1</font>."]),
    h1("10. Limitations and responsible use"),
    *bullets(["<b>Not a live video of debris.</b> PACE passes once a day at about 1.2 km, Sentinel-2 every few days near the "
              "coast, and clouds block both. AquaTrace shows <i>potential</i> floating-material hotspots with a confidence, "
              "carried forward by a validated drift model.",
              "<b>Sub-pixel detection on PACE.</b> Individual items are far smaller than a 1.2 km pixel; PACE flags regions "
              "where floating material (debris, algae, foam) changes the spectrum. Sentinel-2 is the higher-resolution check.",
              "<b>Training data are not from India.</b> MARIDA scenes come from other seas; detection scores are on MARIDA's test "
              "split. Local ground truth (drones, beach surveys, fishers' reports) is needed to measure accuracy in the Bay.",
              "<b>Reanalysis latency.</b> OSCAR and MERRA-2 arrive days to weeks late, so NASA runs are replays; live runs use "
              "forecast currents and wind, which were less accurate in our comparison.",
              "<b>Validation proxy.</b> Buoys test the current and wind field and windage of surface drifters, not of plastic items; "
              f"five drifters over eight weeks is a modest sample ({VAL['cases']} held-out forecasts). The current error is "
              "isotropic, so for patches within a few kilometres of the shore it may overstate how many particles land.",
              "<b>Approximate reference data.</b> Sensitive sites, river mouths and port anchorages are hand-entered with approximate "
              "coordinates; routes are straight legs with simple detours, not navigational charts.",
              "<b>Decision support, not automation.</b> Recommendations should be confirmed by people before deploying vessels."]),
    h1("11. Roadmap"),
    table([["Phase", "Next steps"],
           ["1 · Pilot (done)", "Bay of Bengal prototype: detection, 48 h forecast, risk, routes, live mode, validation"],
           ["2 · Validate on the ground", "Fishers' and citizens' geotagged reports and drone surveys as local labels; retrain and re-score; add Sentinel-1 radar for cloudy days"],
           ["3 · Expand across India", "Arabian Sea and Lakshadweep; integrate INCOIS ocean forecasts; automated daily runs with alerts to coastal authorities"],
           ["4 · Scale beyond borders", "Full hyperspectral PACE unmixing; cyclone scenario mode; spatial database (PostGIS) and cloud storage for operations"]],
          [44 * mm, 130 * mm]),
    CondPageBreak(120 * mm),
])

# ================================================================ 12 references + appendices
refs = [
    "Biermann, L., Clewley, D., Martinez-Vicente, V. and Topouzelis, K. (2020). Finding plastic patches in coastal waters using optical satellite data. <i>Scientific Reports</i>, 10, 5364.",
    "Kikaki, K., Kakogeorgiou, I., Mikeli, P., Raitsos, D. E. and Karantzalos, K. (2022). MARIDA: A benchmark for Marine Debris detection from Sentinel-2 remote sensing data. <i>PLOS ONE</i>, 17(1), e0262247.",
    "Hu, C. (2009). A novel ocean color index to detect floating algae in the global oceans. <i>Remote Sensing of Environment</i>, 113(10), 2118–2129.",
    "Geurts, P., Ernst, D. and Wehenkel, L. (2006). Extremely randomized trees. <i>Machine Learning</i>, 63(1), 3–42.",
    "van Sebille, E. et al. (2018). Lagrangian ocean analysis: Fundamentals and practices. <i>Ocean Modelling</i>, 121, 49–75.",
    "Gelaro, R. et al. (2017). The Modern-Era Retrospective Analysis for Research and Applications, Version 2 (MERRA-2). <i>Journal of Climate</i>, 30(14), 5419–5454.",
    "Drusch, M. et al. (2012). Sentinel-2: ESA's Optical High-Resolution Mission for GMES Operational Services. <i>Remote Sensing of Environment</i>, 120, 25–36.",
    "Guo, C., Pleiss, G., Sun, Y. and Weinberger, K. Q. (2017). On calibration of modern neural networks. <i>Proceedings of ICML 2017</i>.",
    "Pedregosa, F. et al. (2011). Scikit-learn: Machine learning in Python. <i>Journal of Machine Learning Research</i>, 12, 2825–2830.",
    "NASA Ocean Biology DAAC. PACE OCI Level-2 Surface Reflectance (PACE_OCI_L2_SFREFL and _NRT), version 3.1.",
    "NASA JPL PO.DAAC. OSCAR (Ocean Surface Current Analyses Real-time) version 2.0, 0.25° daily (final, interim, NRT).",
    "NASA GMAO / GES DISC. MERRA-2 tavg1_2d_slv_Nx (M2T1NXSLV), version 5.12.4.",
    "NOAA AOML Global Drifter Program. Quality-controlled 6-hour interpolated drifter data (drifter_6hour_qc), ERDDAP.",
    "Open-Meteo. Marine, Forecast and Historical Weather APIs (open-meteo.com).",
    "Natural Earth. 1:10m physical vectors: land and coastline (naturalearthdata.com).",
    "UNEP (2021). From Pollution to Solution: A global assessment of marine litter and plastic pollution. Nairobi: United Nations Environment Programme.",
    "Topouzelis, K., Papakonstantinou, A. and Garaba, S. P. (2019). Detection of floating plastics from satellite and unmanned aerial systems (Plastic Litter Project 2018). <i>Int. J. Appl. Earth Obs. Geoinf.</i>, 79, 175–183.",
]
add([h1("12. References")] + [Paragraph(f"[{i + 1}] {r}", ParagraphStyle("ref", parent=S["body"], fontSize=8.4, leading=11.2, leftIndent=16, firstLineIndent=-16))
                               for i, r in enumerate(refs)])
add([
    PageBreak(),
    h1("Appendix A. Key parameters"),
    table([["Parameter", "Value", "Where"],
           ["Pilot region", "4°–23°N, 79°–96°E", "config.py"],
           ["Particles per hotspot / time step / horizon", "300 / 1 h (RK4) / 48 h", "config.py, drift.py"],
           ["Windage / diffusivity / current error", "2–3% (uniform per particle) / 20 m²/s / σ = 0.16 m/s (± pairs)", "config.py"],
           ["Anomaly threshold", "z ≥ 3.5 (robust, MAD-based)", "detect.py"],
           ["Background block", "41 px (PACE) / 101 px (Sentinel-2 at 20 m)", "detect.py"],
           ["Shoreline strip excluded", "2.5 km (PACE) / 0.4 km (Sentinel-2)", "detect.py"],
           ["Cloud buffer", "3 px (PACE) / 5 px (Sentinel-2)", "detect.py, sentinel2.py"],
           ["Sentinel-2 window / resolution / search", "30 × 30 km / 20 m / ±6 days, < 20% cloud", "sentinel2.py"],
           ["Classifier", "Extra Trees (500 trees) decides floating; 50/50 vote with gradient boosting (400 rounds) names the "
                          "rest; ≤ 40,000 px per class", "marida.py"],
           ["Risk weights", "confidence 35, proximity 25, beaching 15, recurrence 15, certainty 10", "risk.py"],
           ["Tiers", "High ≥ 60, Medium ≥ 40", "risk.py"],
           ["Back-track / recurrence radius", "72 h / 15 km", "source.py, pipeline.py"],
           ["Route defaults", "10 kn, 2 h per stop, 450 km range, detour offsets 10–110 km", "route.py"],
           ["Live look-back", "3 days, best 3 PACE NRT passes", "pipeline.py"]],
          [58 * mm, 82 * mm, 34 * mm]),
    h1("Appendix B. Project files"),
    table([["Path", "Purpose"],
           ["backend/aquatrace/sources/", "nasa.py (PACE, OSCAR, MERRA-2), sentinel2.py, openmeteo.py, coast.py"],
           ["backend/aquatrace/forcing.py", "common velocity field and interpolation"],
           ["backend/aquatrace/detect.py", "band synthesis, masks, indices, texture features, anomaly, hotspots, overlays"],
           ["backend/aquatrace/marida.py, experiments.py, experiments_v2.py, calibration.py", "classifier training, model selection (two rounds), calibration"],
           ["backend/aquatrace/drift.py, source.py", "Lagrangian forecast (forward and backward), source attribution"],
           ["backend/aquatrace/risk.py, route.py", "risk score and actions; moving-target route planner"],
           ["backend/aquatrace/validate.py, tune_drift.py", "buoy validation; drift tuning on one month, scoring on the next"],
           ["backend/aquatrace/pipeline.py, api.py", "replay and live runs; FastAPI service"],
           ["frontend/src/", "dashboard: App, components (briefing, drawer, timeline, toolbar), map (flow and particle layers)"],
           ["README.md, CLAUDE.md, DEMO.md", "setup and results; developer guide; demo script and judge Q&amp;A"]],
          [70 * mm, 104 * mm]),
    h1("Appendix C. Glossary"),
    table([["Term", "Meaning"],
           ["Hotspot", "a group of pixels with a strong floating-material signal; a <i>potential</i> debris patch"],
           ["FDI", "Floating Debris Index: near-infrared reflectance above a red-edge/SWIR baseline"],
           ["Lagrangian model", "tracks individual particles as they are carried by currents and wind"],
           ["Ensemble", "many particles with slightly different properties; their spread is the uncertainty"],
           ["Windage", "the share of wind speed that pushes a floating object in addition to the current"],
           ["Nowcast", "estimate of where a past detection is now"],
           ["Replay (hindcast)", "a run on a past date that can be checked against what happened"],
           ["Precision / recall / F1", "share of flagged pixels that are right / share of true pixels found / their harmonic mean"],
           ["ECE", "expected calibration error: gap between stated confidence and observed frequency"],
           ["Persistence", "the baseline forecast that nothing moves (what a single snapshot implies)"],
           ["Cone coverage", "share of real outcomes that fall inside the forecast's 90% uncertainty cone (ideal: 90%)"],
           ["RK4", "fourth-order Runge–Kutta, an accurate way to step a particle through a velocity field"]],
          [38 * mm, 136 * mm]),
])

# ================================================================ build
HEADS = ("h1", "h2", "h3")


def is_head(f):
    return isinstance(f, Paragraph) and f.style.name in HEADS


def merge_headings(flows):
    """Keep headings (and a short intro paragraph) on the same page as the table/figure block that follows:
    ReportLab's keepWithNext does not attach to a KeepTogether block."""
    out = []
    for f in flows:
        if isinstance(f, KeepTogether) and out and (is_head(out[-1]) or (
                len(out) > 1 and isinstance(out[-1], Paragraph) and out[-1].style.name == "body" and is_head(out[-2]))):
            lead = []
            while out and (is_head(out[-1]) or (not lead and isinstance(out[-1], Paragraph) and out[-1].style.name == "body"
                                               and len(out) > 1 and is_head(out[-2]))):
                lead.insert(0, out.pop())
            f = KeepTogether(lead + list(f._content))
        out.append(f)
    return out


doc = Report(OUT)
doc.multiBuild(merge_headings(story))
print("wrote", OUT, f"{OUT.stat().st_size / 1e6:.1f} MB")
