#!/usr/bin/env python3
"""
三國志略 — 录制管线脚本 (Record Pipeline)

Headless playthrough → HTML frame rendering → Playwright PNG screenshots → ffmpeg MP4.

Usage:
    python record.py                          # Default: 刘备 207, 10 turns
    python record.py --faction cao --turns 15  # Custom
    python record.py --output demo/v2-gameplay.mp4

Dependencies:
    pip install histrategy[web] playwright
    python -m playwright install chromium
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ─── Config ──────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

# Default decision script for 刘备 207 scenario (三顾茅庐 → 赤壁 → 入蜀)
DEFAULT_DECISIONS = [
    "派关羽张飞去卧龙岗三顾茅庐，务必请诸葛亮出山相助",
    "诸葛亮既出，请军师分析天下形势，制定隆中对策",
    "趁曹操北征乌桓无暇南顾，发展新野农业民生",
    "练兵备战，招募乡勇，扩充军力以备将来",
    "联络江东孙权，商议共抗曹操之策",
    "曹操南下，携民渡江，保护百姓撤退至江陵",
    "与孙权结盟，联合周瑜在赤壁迎战曹操",
    "赤壁大胜后，趁势夺取荆南四郡作为根基",
    "西进入蜀，以助刘璋拒张鲁为名取益州",
    "定都成都，休养生息，准备北伐汉中",
]


def main():
    parser = argparse.ArgumentParser(description="三國志略 — 录制管线")
    parser.add_argument("--faction", default="shu")  # dynamic from scenario
    parser.add_argument("--scenario", default="207")
    parser.add_argument("--turns", type=int, default=10, help="录制回合数")
    parser.add_argument("--output", default=None, help="输出视频路径")
    parser.add_argument("--fps", type=float, default=0.5, help="帧率 (秒/帧)")
    parser.add_argument("--frames-dir", default=None, help="帧输出目录")
    parser.add_argument("--dry-run", action="store_true", help="只生成帧，不合成视频")
    args = parser.parse_args()

    output = (
        Path(args.output) if args.output else REPO_ROOT / "demo" / f"v2-{args.faction}-{args.turns}t.mp4"
    ).resolve()
    frames_dir = Path(args.frames_dir) if args.frames_dir else Path(tempfile.mkdtemp(prefix="histrategy-frames-"))

    print("🎬 三國志略 录制管线")
    print(f"   势力: {args.faction}  剧本: {args.scenario}  回合: {args.turns}")
    print(f"   输出: {output}")
    print(f"   帧目录: {frames_dir}")
    print()

    # ─── Step 1: Run headless game ───────────────────────────
    print("📜 第1步: 执行 Headless 游戏…")
    turns_data = run_headless_game(args.faction, args.scenario, args.turns)
    print(f"   ✅ 完成 {len(turns_data)} 回合")

    # ─── Step 2: Render frames ───────────────────────────────
    print("🎨 第2步: 渲染帧…")
    html_template = load_html_template()
    frames = render_frames(turns_data, html_template, frames_dir)
    print(f"   ✅ 生成 {len(frames)} 帧 → {frames_dir}")

    if args.dry_run:
        print(f"\n🖼️ 帧已生成（dry-run），查看: {frames_dir}")
        return

    # ─── Step 3: Composite video ─────────────────────────────
    print("🎥 第3步: 合成视频 (ffmpeg)…")
    output.parent.mkdir(parents=True, exist_ok=True)
    success = composite_video(frames_dir, output, fps=args.fps)
    if success:
        size_mb = output.stat().st_size / (1024 * 1024)
        print(f"   ✅ 视频已生成: {output} ({size_mb:.1f} MB)")

        # Cleanup temp frames
        shutil.rmtree(frames_dir, ignore_errors=True)
        print("   🧹 已清理临时帧目录")
    else:
        print(f"   ❌ 视频合成失败! 帧保留在: {frames_dir}")


# ─── Headless Game Engine ────────────────────────────────────────


def run_headless_game(faction: str, scenario: str, turns: int) -> list[dict]:
    """Run a full game headlessly, returning turn-by-turn data."""
    sys.path.insert(0, str(REPO_ROOT))
    from histrategy.engine.game import GameEngine, _suppress_stderr

    engine = GameEngine(scenario=scenario, new_game=True)
    engine.set_player_faction(faction)

    turns_data = []

    # Intro scene
    with _suppress_stderr():
        intro = engine.get_intro_scene()
        plan = engine.get_plan_data()

    turns_data.append(
        {
            "turn": 0,
            "phase": "intro",
            "narrative": intro.get("narrative", ""),
            "suggestions": plan.get("suggestions", []),
            "season_summary": plan.get("season_summary", ""),
            "faction_status": _extract_status(engine),
            "all_factions": _extract_all_factions(engine),
        }
    )

    # Decision sequence
    decisions = DEFAULT_DECISIONS[:turns]
    if len(decisions) < turns:
        decisions += ["继续发展"] * (turns - len(decisions))

    for i, decision in enumerate(decisions):
        with _suppress_stderr():
            result = engine.process_turn(decision)

        # Get updated plan for next turn
        with _suppress_stderr():
            plan_data = engine.get_plan_data()

        turns_data.append(
            {
                "turn": i + 1,
                "phase": "command",
                "decision": decision,
                "narrative": result.get("aftermath", result.get("narrative", "")),
                "state_changes": result.get("state_changes", {}),
                "events": result.get("events_occurred", []),
                "suggestions": plan_data.get("suggestions", []),
                "season_summary": plan_data.get("season_summary", ""),
                "faction_status": _extract_status(engine),
                "all_factions": _extract_all_factions(engine),
                "game_over": result.get("game_over"),
            }
        )

        if result.get("game_over"):
            print(f"   ⚠️ 游戏在第{i + 1}回合结束: {result['game_over'].get('type', '?')}")
            break

    return turns_data


def _extract_status(engine) -> dict:
    """Extract player faction status from engine."""
    if engine._use_v2:
        ws = engine.world_state_v2
        player = ws.factions.get(ws.player_faction_id)
        if not player:
            return {}
        return {
            "name": player.name,
            "capital": player.capital,
            "strength": player.strength_actual,
            "food": player.food,
            "treasury": player.treasury,
            "morale": player.morale_actual,
            "territories": len(player.territories),
            "territory_names": player.territories,
            "year": ws.year,
            "season": ws.season.cn,
            "turn_number": ws.turn_number,
        }
    return {}


def _extract_all_factions(engine) -> list[dict]:
    """Extract all faction states for the map."""
    if not engine._use_v2:
        return []
    ws = engine.world_state_v2
    factions = []
    for fid, f in ws.factions.items():
        if f.is_active and f.strength_actual > 0:
            factions.append(
                {
                    "id": fid,
                    "name": f.name,
                    "strength": f.strength_actual,
                    "territories": f.territories,
                    "is_player": fid == ws.player_faction_id,
                }
            )
    return factions


# ─── HTML Frame Rendering ────────────────────────────────────────


def load_html_template() -> str:
    """Load the frame rendering HTML template."""
    template_path = REPO_ROOT / "histrategy" / "web" / "frame.html"
    if template_path.exists():
        return template_path.read_text()

    # Use the web client HTML as fallback, but simplified for recording
    web_path = REPO_ROOT / "histrategy" / "web" / "index.html"
    if web_path.exists():
        html = web_path.read_text()
        # Replace interactive elements with static rendering
        html = html.replace('class="modal-overlay"', 'class="modal-overlay hidden"')
        html = html.replace('id="info-panel"', 'id="info-panel" style="max-width:500px"')
        return html

    return DEFAULT_FRAME_TEMPLATE


def render_frames(turns_data: list[dict], template: str, output_dir: Path) -> list[Path]:
    """Render each turn as an HTML page and screenshot it."""
    output_dir.mkdir(parents=True, exist_ok=True)
    frames = []

    for i, turn in enumerate(turns_data):
        html = render_turn_html(turn, template)
        html_path = output_dir / f"frame_{i:04d}.html"
        html_path.write_text(html)
        frames.append(html_path)

    # Try Playwright screenshotting
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            png_frames = []

            for i, html_path in enumerate(frames):
                page.goto(f"file://{html_path}", wait_until="networkidle")
                png_path = output_dir / f"frame_{i:04d}.png"
                page.screenshot(path=str(png_path), full_page=False)
                png_frames.append(png_path)
                if (i + 1) % 3 == 0:
                    print(f"   📸 {i + 1}/{len(frames)} 帧已截图")

            browser.close()
            return png_frames
    except ImportError:
        print("   ⚠️ Playwright 未安装 — 将使用 HTML 帧 + 占位 PNG")
        print("   💡 安装: pip install playwright && python -m playwright install chromium")

        # Fallback: generate simple colored PNGs using PIL
        return _render_fallback_pngs(turns_data, output_dir)


def _render_fallback_pngs(turns_data: list[dict], output_dir: Path) -> list[Path]:
    """Fallback: generate text-overlay PNGs using PIL with Chinese fonts."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("   ⚠️ PIL 也未安装 — 无法生成 PNG")
        return []

    # Find a Chinese font
    font_paths = [
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    ]
    font_path = None
    for fp in font_paths:
        if os.path.exists(fp):
            font_path = fp
            break

    frames = []
    for i, turn in enumerate(turns_data):
        img = Image.new("RGB", (1280, 720), (26, 26, 46))
        draw = ImageDraw.Draw(img)

        try:
            font_title = ImageFont.truetype(font_path, 28) if font_path else ImageFont.load_default()
            font_body = ImageFont.truetype(font_path, 18) if font_path else ImageFont.load_default()
            font_small = ImageFont.truetype(font_path, 14) if font_path else ImageFont.load_default()
        except Exception:
            font_title = font_body = font_small = ImageFont.load_default()

        # Background panels
        draw.rectangle([0, 0, 1280, 70], fill=(22, 33, 62))  # Header bg
        draw.line([0, 70, 1280, 70], fill=(212, 160, 23), width=2)

        # Header
        status = turn.get("faction_status", {})
        header = f"三國志略 · 第{turn.get('turn', 0)}回合"
        draw.text((24, 16), header, fill=(212, 160, 23), font=font_title)

        # Stats
        stats = (
            f"{status.get('year', '?')}年{status.get('season', '?')}  │  "
            f"兵力 {status.get('strength', 0):,}  │  "
            f"粮草 {status.get('food', 0):,}  │  "
            f"资金 {status.get('treasury', 0):,}  │  "
            f"领地 {status.get('territories', 0)}城"
        )
        draw.text((24, 48), stats, fill=(200, 200, 200), font=font_small)

        # Narrative panel background
        narrative = turn.get("narrative", "")
        draw.rectangle([20, 90, 780, 650], fill=(22, 33, 62), outline=(42, 42, 74))

        # Narrative text
        y = 100
        for line in narrative.split("\n")[:22]:
            if line.strip():
                clean = line.strip()
                # Color headings differently
                if clean.startswith("#"):
                    draw.text((36, y), clean.lstrip("# "), fill=(212, 160, 23), font=font_body)
                elif clean.startswith("###"):
                    draw.text((36, y), clean.lstrip("# "), fill=(41, 128, 185), font=font_body)
                else:
                    draw.text((36, y), clean[:100], fill=(224, 216, 200), font=font_small)
                y += 22

        # Decision panel on the right
        draw.rectangle([800, 90, 1260, 200], fill=(22, 33, 62), outline=(42, 42, 74))
        draw.text((816, 100), "君主决策", fill=(212, 160, 23), font=font_body)
        decision = turn.get("decision", "—")
        # Word-wrap decision text
        words = decision
        y2 = 130
        for chunk in [words[i : i + 18] for i in range(0, len(words), 18)]:
            draw.text((816, y2), chunk, fill=(245, 230, 200), font=font_small)
            y2 += 22

        # Suggestions panel
        draw.rectangle([800, 220, 1260, 450], fill=(22, 33, 62), outline=(42, 42, 74))
        draw.text((816, 230), "廷议方向", fill=(41, 128, 185), font=font_body)
        suggestions = turn.get("suggestions", [])
        y3 = 260
        for s in suggestions[:4]:
            text = s
            for chunk in [text[i : i + 20] for i in range(0, len(text), 20)]:
                draw.text((816, y3), chunk, fill=(200, 200, 200), font=font_small)
                y3 += 20
            y3 += 4

        # Footer
        draw.line([0, 700, 1280, 700], fill=(42, 42, 74))
        draw.text((24, 705), "三國志略 v2 · Emergence Science · 录制管线", fill=(100, 100, 100), font=font_small)

        png_path = output_dir / f"frame_{i:04d}.png"
        img.save(str(png_path))
        frames.append(png_path)

    return frames


def render_turn_html(turn: dict, template: str) -> str:
    """Inject turn data into the HTML template."""
    status = turn.get("faction_status", {})
    narrative = turn.get("narrative", "").replace("\n", "<br>")
    suggestions = turn.get("suggestions", [])

    # Build suggestions HTML
    sugg_html = ""
    for s in suggestions[:4]:
        tag = ""
        text = s
        s[:12]
        if "【" in s and "】" in s:
            parts = s.split("】", 1)
            tag = parts[0][1:]
            text = parts[1].strip()
        sugg_html += f'<div class="suggestion-item"><span class="tag">{tag}</span>{text}</div>\n'

    # Simple data injection into template or standalone frame
    if "<!--FRAME-DATA-->" in template:
        html = template.replace("<!--FRAME-DATA-->", json.dumps(turn, ensure_ascii=False))
    else:
        # Build a self-contained frame HTML
        html = FRAME_HTML.format(
            year=status.get("year", "?"),
            season=status.get("season", "?"),
            strength=status.get("strength", 0),
            food=status.get("food", 0),
            treasury=status.get("treasury", 0),
            morale=status.get("morale", 0),
            territories=status.get("territories", 0),
            narrative=narrative,
            suggestions=sugg_html,
            turn=turn.get("turn", 0),
            decision=turn.get("decision", "—"),
        )

    return html


FRAME_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#1a1a2e;color:#e0d8c8;font-family:'Noto Sans SC',sans-serif;
      width:1280px;height:720px;overflow:hidden;display:flex;flex-direction:column}}
header{{background:linear-gradient(180deg,#2c1810,#16213e);padding:12px 24px;
        border-bottom:2px solid #3a2020;display:flex;justify-content:space-between}}
header h1{{color:#d4a017;font-size:1.4em;letter-spacing:3px}}
.stats{{display:flex;gap:20px;font-size:.9em;align-items:center}}
.stat{{text-align:center}}.stat label{{color:#8a8a7a;font-size:.7em;display:block}}
.stat value{{color:#f5e6c8;font-weight:bold}}
main{{display:flex;flex:1;min-height:0}}
.map{{flex:1.2;background:#16213e;display:flex;align-items:center;justify-content:center}}
.map svg{{width:100%;height:100%}}
.info{{flex:0.8;padding:16px 20px;overflow-y:auto;max-width:480px}}
.panel{{background:#16213e;border:1px solid #2a2a4a;border-radius:6px;
        padding:14px 16px;margin-bottom:12px}}
.panel-title{{color:#d4a017;font-size:.8em;text-transform:uppercase;
              border-bottom:1px solid #2a2a4a;padding-bottom:4px;margin-bottom:8px}}
.narrative{{font-size:.88em;line-height:1.7;max-height:280px;overflow-y:auto}}
.suggestions{{display:flex;flex-direction:column;gap:5px}}
.suggestion-item{{background:#0f3460;border:1px solid #2a2a4a;border-radius:4px;
                  padding:8px 12px;font-size:.85em}}
.suggestion-item .tag{{background:#e74c3c;color:#fff;font-size:.7em;
                       padding:1px 6px;border-radius:3px;margin-right:6px}}
.decision{{background:#0f3460;border-left:3px solid #d4a017;padding:8px 12px;
           margin-top:8px;font-size:.85em;color:#d4a017}}
footer{{text-align:center;color:#8a8a7a;font-size:.65em;padding:6px;
        border-top:1px solid #2a2a4a}}
</style></head>
<body>
<header>
<h1>三國志略 · 第{turn}回合</h1>
<div class="stats">
<div class="stat"><label>年份</label><value>{year}年{season}</value></div>
<div class="stat"><label>兵力</label><value style="color:#5dade2">{strength:,}</value></div>
<div class="stat"><label>粮草</label><value style="color:#f0c27a">{food:,}</value></div>
<div class="stat"><label>资金</label><value style="color:#d4a017">{treasury:,}</value></div>
<div class="stat"><label>民心</label><value>{morale}</value></div>
<div class="stat"><label>领地</label><value>{territories}城</value></div>
</div>
</header>
<main>
<div class="map">
<svg viewBox="0 0 800 500">
  <rect width="800" height="500" fill="#1a1a2e"/>
  <g stroke="#222244" stroke-width="0.5" opacity="0.3">
    <line x1="200" y1="0" x2="200" y2="500"/>
    <line x1="400" y1="0" x2="400" y2="500"/>
    <line x1="600" y1="0" x2="600" y2="500"/>
    <line x1="0" y1="125" x2="800" y2="125"/>
    <line x1="0" y1="250" x2="800" y2="250"/>
    <line x1="0" y1="375" x2="800" y2="375"/>
  </g>
  <g stroke="#2a4a6a" stroke-width="2" fill="none" opacity="0.4">
    <path d="M0,100 Q200,90 350,120 Q500,150 650,110 Q750,90 800,80"/>
    <path d="M0,300 Q200,290 400,320 Q550,340 650,300 Q750,280 800,290"/>
  </g>
  <text x="400" y="480" fill="#8a8a7a" font-size="14" text-anchor="middle">
    三國地图 · 东汉十三州
  </text>
</svg>
</div>
<div class="info">
<div class="panel">
  <div class="panel-title">📜 军师来报</div>
  <div class="narrative">{narrative}</div>
</div>
<div class="decision">🎯 君主决策: {decision}</div>
<div class="panel">
  <div class="panel-title">📋 廷议方向</div>
  <div class="suggestions">{suggestions}</div>
</div>
</div>
</main>
<footer>三國志略 v2 · Emergence Science · 录制管线自动生成</footer>
</body></html>"""


# ─── FFmpeg Video Composition ───────────────────────────────────


def composite_video(frames_dir: Path, output: Path, fps: float = 0.5) -> bool:
    """Compose PNG frames into MP4 video using ffmpeg."""
    png_files = sorted(frames_dir.glob("frame_*.png"))
    if not png_files:
        print("   ❌ 没有找到PNG帧文件")
        # Try generating from HTML files
        return _try_composite_from_html(frames_dir, output, fps)

    # Create ffmpeg input file
    concat_file = frames_dir / "frames.txt"
    with open(concat_file, "w") as f:
        for png in png_files:
            f.write(f"file '{png.name}'\n")
            f.write(f"duration {1.0 / fps}\n")
        # Last frame needs a final duration entry
        f.write(f"file '{png_files[-1].name}'\n")

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-vf",
                "fps=30,format=yuv420p",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-pix_fmt",
                "yuv420p",
                str(output),
            ],
            check=True,
            capture_output=True,
            timeout=120,
            cwd=str(frames_dir),
        )
        return output.exists()
    except FileNotFoundError:
        print("   ⚠️ ffmpeg 未安装 — 无法合成视频")
        return False
    except subprocess.CalledProcessError as e:
        print(f"   ❌ ffmpeg 错误: {e.stderr.decode()[-200:] if e.stderr else '?'}")
        return False


def _try_composite_from_html(frames_dir: Path, output: Path, fps: float) -> bool:
    """Try generating PNGs from HTML frames first, then composite."""
    print("   尝试从HTML帧生成PNG…")
    html_files = sorted(frames_dir.glob("frame_*.html"))
    if not html_files:
        return False

    # Try Playwright first
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 720})

            for i, html_path in enumerate(html_files):
                page.goto(f"file://{html_path}", wait_until="networkidle")
                png_path = frames_dir / f"frame_{i:04d}.png"
                page.screenshot(path=str(png_path), full_page=False)

            browser.close()
            return composite_video(frames_dir, output, fps)
    except ImportError:
        pass

    return False


# ─── Default Template (fallback) ─────────────────────────────────

DEFAULT_FRAME_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>三國志略 录制帧</title>
<style>
body{{background:#1a1a2e;color:#e0d8c8;font-family:sans-serif;padding:20px}}
h1{{color:#d4a017}}.panel{{background:#16213e;border:1px solid #2a2a4a;
border-radius:6px;padding:14px;margin:10px 0}}
.stats{{display:flex;gap:15px}}.stat{{text-align:center}}
.stat label{{color:#8a8a7a;font-size:.8em;display:block}}
</style></head>
<body>
<h1>三國志略 · 第{TURN}回合</h1>
<div class="stats">
<div class="stat"><label>年份</label><span>{YEAR}年{SEASON}</span></div>
<div class="stat"><label>兵力</label><span>{STRENGTH:,}</span></div>
<div class="stat"><label>粮草</label><span>{FOOD:,}</span></div>
<div class="stat"><label>资金</label><span>{TREASURY:,}</span></div>
</div>
<div class="panel">
<h3>📜 {DECISION}</h3>
<p>{NARRATIVE}</p>
</div>
<footer>三國志略 v2</footer>
</body></html>"""


def generate_video(session_id: str) -> str:
    """Generate replay video for a session from PNG frames.

    Reads PNG frames from 'frames/' directory in current directory or ~/.histrategy/sessions/{session_id}/frames/
    """
    import os
    import subprocess
    from pathlib import Path

    # Look for frames in potential directories
    data_dir = Path(os.environ.get("HISTRATEGY_DATA_DIR", os.path.expanduser("~/.histrategy")))
    possible_dirs = [
        Path("frames"),
        data_dir / "sessions" / session_id / "frames",
        data_dir / "sessions" / session_id,
        data_dir / "frames",
    ]

    frames_dir = None
    for d in possible_dirs:
        if d.is_dir() and (list(d.glob("*.png"))):
            frames_dir = d
            break

    if not frames_dir:
        frames_dir = Path("frames")
        if not frames_dir.exists():
            raise FileNotFoundError(f"Frames directory not found for session {session_id}")

    # Ensure there are PNG files
    png_files = sorted(frames_dir.glob("*.png"))
    if not png_files:
        raise FileNotFoundError(f"No PNG frames found in {frames_dir}")

    # Output video path
    output_dir = data_dir / "sessions" / session_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_video = (output_dir / "out.mp4").resolve()

    # Determine pattern: frame_%04d.png or %04d.png
    first_file = png_files[0].name
    if first_file.startswith("frame_"):
        pattern = "frame_%04d.png"
    else:
        # Check if first file matches a 4-digit number (e.g. 0000.png)
        base = Path(first_file).stem
        pattern = "%04d.png" if base.isdigit() and len(base) == 4 else first_file.replace(base, "%04d")

    input_pattern = str(frames_dir / pattern)

    # Invoke ffmpeg with exact command parameters requested:
    # ffmpeg -y -framerate 0.5 -i frames/%04d.png -c:v libx264 -r 30 out.mp4
    cmd = [
        "ffmpeg",
        "-y",
        "-framerate",
        "0.5",
        "-i",
        input_pattern,
        "-c:v",
        "libx264",
        "-r",
        "30",
        "-pix_fmt",
        "yuv420p",
        str(output_video),
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        # Re-raise or fallback to composite_video
        success = composite_video(frames_dir, output_video, fps=0.5)
        if not success:
            raise RuntimeError("ffmpeg executable not found on system. Please install ffmpeg.") from None
    except subprocess.CalledProcessError as e:
        # Fallback to concat demuxer if direct pattern match fails
        success = composite_video(frames_dir, output_video, fps=0.5)
        if not success:
            raise RuntimeError(f"ffmpeg failed: {e.stderr}") from None

    return str(output_video)


if __name__ == "__main__":
    main()
