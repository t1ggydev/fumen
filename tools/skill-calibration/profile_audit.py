"""Render profile audit JSONs without changing the rating model."""
import argparse, json, html
from pathlib import Path

def render(folder):
    profiles = []
    for p in sorted(folder.glob("*.json"), key=lambda p: (p.stem != "own", p.stem)):
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "skills" in data and "plays" in data:
            profiles.append((p.stem, data))
    if not profiles:
        raise ValueError("No profile exports found")
    lines = ["# Skill profile audit", "", "Current curve applied before the play quality multiplier. Top five maps per skill; missing maps contribute zero.", ""]
    ids = [s["id"] for s in profiles[0][1]["skills"]]
    for skill in ids:
        lines += ["## " + skill, "", "| Profile | Skill | Mean raw | Mean calibrated | Mean quality | Mean stars |", "|---|---:|---:|---:|---:|---:|"]
        for name, profile in profiles:
            s = next(s for s in profile["skills"] if s["id"] == skill)
            ds = [e["details"] for e in s["evidence"]]
            avg = lambda key: sum(d[key] for d in ds)/len(ds) if ds else 0
            lines.append(f"| {name} | {s['value']:.2f} | {avg('rawDemand'):.3f} | {avg('calibratedDemand'):.2f} | {avg('performance'):.3f} | {avg('stars'):.2f} |")
        lines.append("")
        for name, profile in profiles:
            s = next(s for s in profile["skills"] if s["id"] == skill)
            maps = {m["map"]:m for m in profile.get("maps",[])}
            lines += ["### " + name, "", "| Map | Mods | Raw | Curve | Quality | Result | Stars |", "|---|---|---:|---:|---:|---:|---:|"]
            for e in s["evidence"]:
                p = profile["plays"][e["play"]]; d = e["details"]
                m = maps.get(p.get("map"),p)
                title = f"{m.get('artist','')} - {m.get('title',p.get('map',''))} [{m.get('version','')}]".replace("|","/")
                lines.append(f"| {title} | {','.join(p.get('mods') or [])} | {d['rawDemand']:.3f} | {d['calibratedDemand']:.2f} | {d['performance']:.3f} | {e['worth']:.2f} | {d['stars']:.2f} |")
            lines.append("")
    (folder/"audit.md").write_text("\n".join(lines),encoding="utf-8")
    body = []
    in_table = False
    for line in lines:
        if line.startswith("|"):
            if line.startswith("|---"):
                continue
            cells = [html.escape(c.strip()) for c in line.strip("|").split("|")]
            tag = "td" if in_table else "th"
            if not in_table:
                body.append("<table>"); in_table = True
            body.append("<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>")
        else:
            if in_table:
                body.append("</table>"); in_table = False
            if line.startswith("#"):
                level = len(line) - len(line.lstrip("#"))
                body.append(f"<h{level}>{html.escape(line.lstrip('# '))}</h{level}>")
            elif line:
                body.append("<p>" + html.escape(line) + "</p>")
    if in_table: body.append("</table>")
    (folder/"audit.html").write_text('<!doctype html><meta charset="utf-8"><title>Skill audit</title><style>body{background:#141819;color:#eee;margin:30px;font:15px/1.5 system-ui}table{border-collapse:collapse;width:100%;margin-bottom:24px}td,th{padding:8px;text-align:right;border-bottom:1px solid #394344}td:first-child,th:first-child{text-align:left}th{color:#b8df7a}h2{margin-top:60px}</style>'+"".join(body),encoding="utf-8")

if __name__ == "__main__":
    ap=argparse.ArgumentParser();ap.add_argument("directory",type=Path);render(ap.parse_args().directory)
