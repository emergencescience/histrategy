#!/usr/bin/env python3
"""
Histrategy Feishu Bridge v3 — 文件轮询版
启动游戏进程，输出到文件，桥接轮询文件。

协议:
  /opt/data/histrategy_bridge/game_output.json  — 最新游戏输出
  /opt/data/histrategy_bridge/game_log.jsonl    — 完整日志
  /opt/data/histrategy_bridge/player_input.txt  — 玩家输入
  /opt/data/histrategy_bridge/game_stdout.txt   — 游戏原始输出
  /opt/data/histrategy_bridge/status.txt        — 状态
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

BRIDGE_DIR = Path("/opt/data/histrategy_bridge")
OUTPUT_FILE = BRIDGE_DIR / "game_output.json"
LOG_FILE = BRIDGE_DIR / "game_log.jsonl"
INPUT_FILE = BRIDGE_DIR / "player_input.txt"
STATUS_FILE = BRIDGE_DIR / "status.txt"
STDOUT_FILE = BRIDGE_DIR / "game_stdout.txt"


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
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(block, ensure_ascii=False) + "\n")
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
    for f in [OUTPUT_FILE, INPUT_FILE, STDOUT_FILE, LOG_FILE, STATUS_FILE]:
        if f.exists():
            f.unlink()

    force_new = "--new" in sys.argv
    faction = "1"
    for i, arg in enumerate(sys.argv):
        if arg == "--faction" and i + 1 < len(sys.argv):
            faction = sys.argv[i + 1]

    # Source .env for API keys
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
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

    # Redirect game stdout to a file
    stdout_f = open(STDOUT_FILE, "w")
    stderr_f = open(BRIDGE_DIR / "game_stderr.txt", "w")

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=stdout_f,
        stderr=stderr_f,
        text=True,
        bufsize=1,
        cwd="/opt/data/repos/histrategy",
        env=env,
    )
    stdout_f.close()  # Close our reference, let the subprocess own it

    write_status("running")

    # Tail the stdout file
    current_phase = None
    current_content_lines = []
    current_meta = None
    file_pos = 0

    try:
        while proc.poll() is None:
            # Read new lines from the stdout file
            try:
                with open(STDOUT_FILE, "r") as f:
                    f.seek(file_pos)
                    new_data = f.read()
                    file_pos = f.tell()
            except Exception:
                new_data = ""

            if new_data:
                for line in new_data.splitlines():
                    line = line.strip()
                    if not line:
                        continue

                    if line == "[END_BLOCK]":
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

                    if current_content_lines is not None:
                        current_content_lines.append(line)
                    else:
                        current_phase = "UNKNOWN"
                        current_content_lines = [line]

            # Check for player input when waiting
            status = STATUS_FILE.read_text() if STATUS_FILE.exists() else ""
            if status == "waiting":
                player_input = read_player_input()
                if player_input:
                    try:
                        proc.stdin.write(player_input + "\n")
                        proc.stdin.flush()
                        write_status("processing")
                    except (BrokenPipeError, OSError):
                        break
            elif status == "running":
                # Check for input even during initial phases (faction selection)
                player_input = read_player_input()
                if player_input:
                    try:
                        proc.stdin.write(player_input + "\n")
                        proc.stdin.flush()
                    except (BrokenPipeError, OSError):
                        break

            time.sleep(0.3)

    except KeyboardInterrupt:
        write_status("interrupted")
        proc.terminate()
    except Exception as e:
        write_status("error")
        write_output("ERROR", f"桥接发生错误: {e}")
        proc.terminate()

    # Drain remaining
    try:
        with open(STDOUT_FILE, "r") as f:
            f.seek(file_pos)
            remaining = f.read()
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
