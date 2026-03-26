"""
Generate HTML discovery report from JSON data.
"""

import html
from pathlib import Path


def _esc(text) -> str:
    return html.escape(str(text))


def generate_html(report: dict, output_path: Path) -> Path:
    """Generate an HTML report from the discovery JSON and save to output_path."""

    inv = report.get("inventory", {})
    classification = report.get("classification", {})
    scenes = report.get("scenes", [])
    samples = report.get("content_samples", {})
    org_plan = report.get("organization_plan", {})
    clips = inv.get("clips", [])

    project_name = _esc(classification.get("project_name", "Unknown"))
    channel = _esc(report.get("channel", ""))
    source = _esc(report.get("source_folder", ""))
    generated = _esc(report.get("generated_at", "")[:19])

    # Build clip→scene lookup
    clip_scene = {}
    for s in scenes:
        for c in s.get("clips", []):
            clip_scene[c] = s["suggested_name"]

    # ── Scene cards ──────────────────────────────────────────────────────
    scene_cards = ""
    for s in scenes:
        icon = "🎬" if s["type"] == "interview" else "🎥"
        tag_class = "tag-interview" if s["type"] == "interview" else "tag-broll"

        # Clip list for this scene
        scene_clip_rows = ""
        for cname in s.get("clips", []):
            clip_data = next((c for c in clips if c["filename"] == cname), None)
            if clip_data:
                scene_clip_rows += f"""
                <tr>
                  <td class="mono">{_esc(cname)}</td>
                  <td>{clip_data['duration_sec']:.1f}s</td>
                  <td>{_esc(clip_data.get('size_human', ''))}</td>
                  <td class="dim">{_esc(clip_data.get('creation_time', '')[:19])}</td>
                </tr>"""

        # Transcript preview
        tx_preview = s.get("transcript_preview", "")
        tx_html = ""
        if tx_preview:
            tx_html = f"""
            <div class="scene-transcript">
              <div class="transcript-label">Whisper preview:</div>
              <div class="transcript-text">{_esc(tx_preview)}</div>
            </div>"""

        scene_cards += f"""
        <div class="scene-card">
          <div class="scene-header">
            <div class="scene-title">{icon} {_esc(s['suggested_name'])}</div>
            <span class="tag {tag_class}">{s['type']}</span>
          </div>
          <div class="scene-stats">
            <div class="stat">
              <span class="stat-label">Clips</span>
              <span class="stat-value">{s['clip_count']}</span>
            </div>
            <div class="stat">
              <span class="stat-label">Duration</span>
              <span class="stat-value">{_esc(s['duration_human'])}</span>
            </div>
            <div class="stat">
              <span class="stat-label">Size</span>
              <span class="stat-value">{_esc(s.get('size_human', ''))}</span>
            </div>
            <div class="stat">
              <span class="stat-label">Avg clip</span>
              <span class="stat-value">{s.get('avg_clip_sec', 0):.0f}s</span>
            </div>
          </div>
          <div class="scene-time-range">
            <span class="dim">{_esc(s.get('time_range', ''))}</span>
          </div>
          <div class="scene-reason dim">{_esc(s.get('reason', ''))}</div>
          {tx_html}
          <details class="scene-clips-details">
            <summary>{s['clip_count']} clips</summary>
            <table class="compact">
              <thead><tr><th>File</th><th>Duration</th><th>Size</th><th>Created</th></tr></thead>
              <tbody>{scene_clip_rows}</tbody>
            </table>
          </details>
        </div>"""

    # ── Clip rows (all clips table) ──────────────────────────────────────
    clip_rows = ""
    for c in clips:
        scene_name = clip_scene.get(c["filename"], "")
        clip_rows += f"""
        <tr>
          <td class="mono">{_esc(c['filename'])}</td>
          <td>{c['duration_sec']:.1f}s</td>
          <td>{_esc(c.get('size_human', ''))}</td>
          <td>{_esc(c.get('resolution', ''))}</td>
          <td>{c.get('fps', '')}</td>
          <td class="dim">{_esc(c.get('creation_time', '')[:19])}</td>
          <td class="dim">{_esc(scene_name)}</td>
        </tr>"""

    # ── Whisper section ──────────────────────────────────────────────────
    whisper_info = ""
    if samples.get("whisper_available"):
        whisper_info = f"""
        <div class="whisper-meta">
          Model: <strong>{_esc(samples.get('whisper_model', ''))}</strong> ·
          Version: {_esc(samples.get('whisper_version', ''))} ·
          Language: <strong>{_esc(samples.get('language', ''))}</strong> ·
          Samples: {len(samples.get('transcripts', []))}
        </div>"""
    elif samples.get("transcripts"):
        whisper_info = f"""
        <div class="whisper-meta">
          Language: <strong>{_esc(samples.get('language', ''))}</strong> ·
          Samples: {len(samples.get('transcripts', []))}
        </div>"""
    else:
        whisper_info = '<div class="whisper-meta dim">Whisper не запускался (--no-whisper) или недоступен</div>'

    transcript_cards = ""
    for t in samples.get("transcripts", []):
        transcript_cards += f"""
        <div class="transcript-card">
          <div class="transcript-header">{_esc(t['clip'])} · {_esc(t.get('language', ''))}</div>
          <div class="transcript-text">{_esc(t.get('text', ''))}</div>
        </div>"""

    # ── Organization plan preview ────────────────────────────────────────
    moves = org_plan.get("moves", [])
    move_preview = ""
    for m in moves[:8]:
        move_preview += f"""
        <tr>
          <td class="mono">{_esc(m['from'])}</td>
          <td class="dim">→</td>
          <td class="mono dim">{_esc(m['to'])}</td>
        </tr>"""
    if len(moves) > 8:
        move_preview += f"""
        <tr><td colspan="3" class="dim">... и ещё {len(moves) - 8} файлов</td></tr>"""

    # ── Archive info ─────────────────────────────────────────────────────
    archive = inv.get("archive", {})
    archive_html = ""
    if archive.get("has_archive"):
        archive_files = archive.get("files", [])
        archive_html = f"""
        <div class="archive-info">
          <strong>Archive/</strong> — {len(archive_files)} файлов
          <details>
            <summary>Показать</summary>
            <ul class="archive-list">
              {''.join(f'<li class="mono dim">{_esc(f)}</li>' for f in archive_files[:30])}
              {'<li class="dim">...</li>' if len(archive_files) > 30 else ''}
            </ul>
          </details>
        </div>"""

    # ── Date range ───────────────────────────────────────────────────────
    date_range = inv.get("date_range", {})
    date_html = ""
    if date_range:
        date_html = f"{_esc(date_range.get('earliest', '')[:19])} — {_esc(date_range.get('latest', '')[:19])}"

    doc = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Discovery: {project_name}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: #0d1117; color: #c9d1d9;
    padding: 2rem 2.5rem; max-width: 1300px; margin: 0 auto;
    line-height: 1.5;
  }}
  h1 {{ color: #58a6ff; font-size: 1.6rem; margin-bottom: 0.2rem; }}
  h2 {{
    color: #8b949e; font-size: 0.8rem; font-weight: 500;
    text-transform: uppercase; letter-spacing: 0.08em;
    margin: 2.2rem 0 0.8rem; padding-bottom: 0.4rem;
    border-bottom: 1px solid #21262d;
  }}
  .subtitle {{ color: #8b949e; font-size: 0.85rem; margin-bottom: 0.2rem; }}
  .generated {{ color: #484f58; font-size: 0.75rem; margin-bottom: 1.5rem; }}

  /* Cards grid */
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.8rem; margin-bottom: 1rem; }}
  .card {{
    background: #161b22; border: 1px solid #21262d; border-radius: 8px;
    padding: 0.9rem 1rem;
  }}
  .card-label {{ color: #8b949e; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; }}
  .card-value {{ color: #f0f6fc; font-size: 1.3rem; font-weight: 600; margin-top: 0.15rem; }}
  .card-detail {{ color: #8b949e; font-size: 0.78rem; margin-top: 0.15rem; }}

  /* Scene cards */
  .scene-card {{
    background: #161b22; border: 1px solid #21262d; border-radius: 8px;
    padding: 1rem 1.2rem; margin: 0.6rem 0;
  }}
  .scene-header {{ display: flex; align-items: center; gap: 0.8rem; margin-bottom: 0.5rem; }}
  .scene-title {{ font-size: 1.05rem; font-weight: 600; color: #f0f6fc; }}
  .scene-stats {{ display: flex; gap: 1.5rem; margin: 0.4rem 0; }}
  .stat {{ display: flex; flex-direction: column; }}
  .stat-label {{ font-size: 0.65rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.04em; }}
  .stat-value {{ font-size: 1rem; font-weight: 500; color: #c9d1d9; }}
  .scene-time-range {{ margin: 0.3rem 0; font-size: 0.8rem; }}
  .scene-reason {{ font-size: 0.8rem; margin: 0.2rem 0; }}
  .scene-transcript {{
    background: #0d1117; border: 1px solid #21262d; border-radius: 6px;
    padding: 0.6rem 0.8rem; margin: 0.5rem 0;
  }}
  .transcript-label {{ color: #58a6ff; font-size: 0.7rem; font-weight: 500; margin-bottom: 0.2rem; }}

  .scene-clips-details {{ margin-top: 0.5rem; }}
  .scene-clips-details summary {{
    cursor: pointer; color: #58a6ff; font-size: 0.8rem; user-select: none;
  }}
  .scene-clips-details summary:hover {{ text-decoration: underline; }}

  /* Tables */
  table {{ width: 100%; border-collapse: collapse; margin: 0.3rem 0; }}
  table.compact td, table.compact th {{ padding: 0.25rem 0.6rem; font-size: 0.78rem; }}
  th {{
    text-align: left; color: #8b949e; font-size: 0.7rem;
    text-transform: uppercase; letter-spacing: 0.04em;
    padding: 0.4rem 0.7rem; border-bottom: 1px solid #21262d;
  }}
  td {{ padding: 0.35rem 0.7rem; border-bottom: 1px solid #161b22; font-size: 0.82rem; }}
  tr:hover {{ background: #161b22; }}

  .mono {{ font-family: 'SF Mono', 'Fira Code', monospace; font-size: 0.78rem; }}
  .dim {{ color: #8b949e; }}
  .tag {{
    display: inline-block; padding: 0.12rem 0.5rem; border-radius: 12px;
    font-size: 0.72rem; font-weight: 500;
  }}
  .tag-interview {{ background: #1f3a5f; color: #58a6ff; }}
  .tag-broll {{ background: #2a1f3f; color: #bc8cff; }}

  .project-name {{
    display: inline-block; background: #0d4429; color: #3fb950;
    padding: 0.3rem 0.8rem; border-radius: 6px; font-size: 1.1rem;
    font-weight: 600; font-family: 'SF Mono', monospace;
  }}

  /* Whisper */
  .whisper-meta {{ margin: 0.3rem 0 0.8rem; font-size: 0.85rem; }}
  .transcript-card {{
    background: #161b22; border: 1px solid #21262d; border-radius: 6px;
    padding: 0.7rem 0.9rem; margin: 0.4rem 0;
  }}
  .transcript-header {{ color: #58a6ff; font-size: 0.78rem; font-weight: 500; margin-bottom: 0.2rem; }}
  .transcript-text {{ color: #c9d1d9; font-size: 0.82rem; line-height: 1.5; }}

  /* Archive */
  .archive-info {{ margin: 0.5rem 0; font-size: 0.85rem; }}
  .archive-info details summary {{ cursor: pointer; color: #58a6ff; font-size: 0.8rem; }}
  .archive-list {{ list-style: none; margin: 0.3rem 0; padding-left: 0.5rem; }}
  .archive-list li {{ font-size: 0.75rem; line-height: 1.6; }}

  /* Next steps */
  .next-steps {{
    background: #161b22; border: 1px solid #1f6feb; border-radius: 8px;
    padding: 1.2rem; margin-top: 2rem;
  }}
  .next-steps h2 {{ border: none; margin-top: 0; color: #58a6ff; }}
  code {{
    background: #0d1117; padding: 0.2rem 0.5rem; border-radius: 4px;
    font-family: 'SF Mono', monospace; font-size: 0.78rem; color: #c9d1d9;
    border: 1px solid #21262d;
  }}
  .cmd {{ display: block; margin: 0.4rem 0; }}

  details > summary {{ cursor: pointer; }}
</style>
</head>
<body>

<h1>Discovery Report</h1>
<div class="subtitle">{source}</div>
<div class="generated">{generated}</div>

<h2>Project</h2>
<div style="margin: 0.6rem 0 1.2rem;">
  <span class="project-name">{project_name}</span>
  <span style="margin-left: 0.8rem; color: #8b949e;">
    {_esc(classification.get('project_type', ''))} · Channel: {channel}
  </span>
</div>

<h2>Inventory</h2>
<div class="grid">
  <div class="card">
    <div class="card-label">Clips</div>
    <div class="card-value">{inv.get('total_files', 0)}</div>
    <div class="card-detail">Camera: {', '.join(_esc(c) for c in inv.get('cameras', [])) or 'N/A'}</div>
  </div>
  <div class="card">
    <div class="card-label">Size</div>
    <div class="card-value">{_esc(inv.get('total_size_human', ''))}</div>
  </div>
  <div class="card">
    <div class="card-label">Duration</div>
    <div class="card-value">{_esc(inv.get('total_duration_human', ''))}</div>
  </div>
  <div class="card">
    <div class="card-label">Resolution</div>
    <div class="card-value">{', '.join(inv.get('resolutions', dict()).keys()) or 'N/A'}</div>
  </div>
  <div class="card">
    <div class="card-label">Date Range</div>
    <div class="card-value" style="font-size:0.85rem;">{date_html or 'N/A'}</div>
  </div>
  <div class="card">
    <div class="card-label">DJI Audio</div>
    <div class="card-value">{inv.get('dji_audio_count', 0)}</div>
    <div class="card-detail">files</div>
  </div>
</div>
{archive_html}

<h2>Scenes ({len(scenes)})</h2>
{scene_cards}

<h2>Whisper Samples</h2>
{whisper_info}
{transcript_cards}

<details>
<summary style="cursor:pointer; color: #58a6ff; font-size: 0.85rem; margin-top: 1rem;">All Clips ({len(clips)})</summary>
<table style="margin-top: 0.5rem;">
  <thead>
    <tr><th>File</th><th>Duration</th><th>Size</th><th>Res</th><th>FPS</th><th>Created</th><th>Scene</th></tr>
  </thead>
  <tbody>{clip_rows}</tbody>
</table>
</details>

<h2>Organization Plan</h2>
<p style="margin-bottom: 0.5rem;">
  Target: <code>{_esc(org_plan.get('target_folder', ''))}</code>
  · {len(moves)} files
</p>
<table>
  <thead><tr><th>From</th><th></th><th>To</th></tr></thead>
  <tbody>{move_preview}</tbody>
</table>

<div class="next-steps">
  <h2>Next Steps</h2>
  <p>1. Переименуй сцены в <code>_discovery/discovery_report.json</code> (поле <code>suggested_name</code>)</p>
  <p style="margin-top: 0.5rem;">2. Dry run:</p>
  <code class="cmd">python scripts/00_ingest/organize.py "{source}" --dry-run</code>
  <p style="margin-top: 0.5rem;">3. Apply:</p>
  <code class="cmd">python scripts/00_ingest/organize.py "{source}"</code>
</div>

</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(doc, encoding='utf-8')
    return output_path
