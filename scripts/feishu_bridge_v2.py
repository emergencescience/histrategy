#!/usr/bin/env python3
"""
Histrategy Feishu Bridge — 文件通道版
启动游戏进程，通过文件进行双向通信。

协议:
  /opt/data/histrategy_bridge/game_output.json  — 最新游戏输出
  /opt/data/histrategy_bridge/player_input.txt  — 玩家输入（写入后自动删除）
  /opt/data/histrategy_bridge/status.txt        — 状态: ready|waiting|processing|error
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

BRIDGE_DIR = Path("/opt/data/histrategy_bridge")
LOG_FILE = BRIDGE_DIR / "game_log.jsonl"
OUTPUT_FILE = BRIDGE_DIR / "game_output.json"
INPUT_FILE = BRIDGE_DIR / "player_input.txt"
STATUS_FILE = BRIDGE_DIR / "status.txt"


def write_status(status: str):
    STATUS_FILE.write_text(status)


def write_output(phase: str, content: str, meta: dict | None = None):
    block = {
        "phase": phase,
        "content": content.strip() if content else "",
        "timestamp": time.strftime("%H:%M:%S"),
    }
    if meta:
        block["meta"] = meta
    # Append to log
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(block, ensure_ascii=False) + "\n")
    # Update current output
    OUTPUT_FILE.write_text(json.dumps(block, ensure_ascii=False, indent=2))


def read_player_input() -> str | None:
    if INPUT_FILE.exists():
        try:
            text = INPUT_FILE.read_text().strip()
            INPUT_FILE.unlink()
            return text if text else None
        except Exception:
            pass
    return None


def main():
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)

    # Clear stale files
    for f in [OUTPUT_FILE, INPUT_FILE]:
        if f.exists():
            f.unlink()

    force_new = "--new" in sys.argv
    faction = "1"
    for i, arg in enumerate(sys.argv):
        if arg == "--faction" and i + 1 < len(sys.argv):
            faction = sys.argv[i + 1]

    # Source .env for API keys
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"  # Force unbuffered output
    env_file = Path("/opt/data/.env")
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                if key and val:
                    env[key] = val

    cmd = [
        sys.executable, "-m", "histrategy",
        "--headless", "--faction", faction,
    ]
    if force_new:
        cmd.append("--new")

    write_status("starting")

    # Start game with stdin=subprocess.PIPE so we can write to it later
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,  # Line buffered
        cwd="/opt/data/repos/histrategy",
        env=env,
    )

    write_status("running")

    # Track current output block
    current_phase = None
    current_content_lines = []
    current_meta = None

    import select
    import io

    # We'll collect all output and write each block to OUTPUT_FILE
    # The bridge runs continuously, checking for player input when in DECISION phase

    try:
        while proc.poll() is None:
            # Check if there's stdout available
            ready = False
            if proc.stdout:
                try:
                    ready = select.select([proc.stdout], [], [], 0.5)[0]
                except (ValueError, OSError):
                    break

            if ready:
                try:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    line = line.strip()
                    if not line:
                        continue

                    # Check for END_BLOCK marker
                    if line == "[END_BLOCK]":
                        # Save the completed block
                        content = "\n".join(current_content_lines)
                        write_output(current_phase or "UNKNOWN", content, current_meta)
                        if current_phase == "DECISION":
                            write_status("waiting")
                        elif current_phase == "GAMEOVER":
                            write_status("game_over")
                        else:
                            write_status("processing")
                        current_content_lines = []
                        current_phase = None
                        current_meta = None
                        continue

                    # Try to parse JSON (phase marker)
                    try:
                        data = json.loads(line)
                        if "phase" in data:
                            current_phase = data["phase"]
                            current_content_lines = [data.get("content", "")]
                            if "meta" in data:
                                current_meta = data["meta"]
                            continue
                    except (json.JSONDecodeError, ValueError):
                        pass

                    # Regular text — append to current block
                    if current_content_lines is not None:
                        current_content_lines.append(line)
                    else:
                        current_phase = "UNKNOWN"
                        current_content_lines = [line]

                except (ValueError, OSError):
                    break

            # No game output — check for player input
            if current_phase == "DECISION" or write_status.__dict__.get("last_status") == "waiting":
                player_input = read_player_input()
                if player_input:
                    try:
                        if proc.stdin:
                            proc.stdin.write(player_input + "\n")
                            proc.stdin.flush()
                            write_status("processing")
                    except (BrokenPipeError, OSError):
                        write_status("error")
                        break
            else:
                # Even if not waiting, check for input (e.g., faction selection)
                player_input = read_player_input()
                if player_input:
                    try:
                        if proc.stdin:
                            proc.stdin.write(player_input + "\n")
                            proc.stdin.flush()
                    except (BrokenPipeError, OSError):
                        break

    except KeyboardInterrupt:
        write_status("interrupted")
        proc.terminate()
    except Exception as e:
        write_status("error")
        write_output("ERROR", f"桥接发生错误: {e}")
        proc.terminate()
    finally:
        # Drain remaining output
        try:
            if proc.stdout:
                remaining = proc.stdout.read()
                if remaining:
                    for line in remaining.splitlines():
                        line = line.strip()
                        if line == "[END_BLOCK]":
                            content = "\n".join(current_content_lines)
                            write_output(current_phase or "UNKNOWN", content, current_meta)
                            current_content_lines = []
                        else:
                            if current_content_lines is not None:
                                current_content_lines.append(line)
                            else:
                                write_output("UNKNOWN", line)
        except Exception:
            pass

    write_status("game_over")


if __name__ == "__main__":
    main()
