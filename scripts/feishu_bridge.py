#!/usr/bin/env python3
"""
Histrategy Feishu Bridge — 简化版
启动游戏进程，通过 FIFO 管道实现持久化输入/输出。

协议:
  FIFO: /opt/data/histrategy_bridge/input.fifo  — 玩家输入
  输出直接写入 stdout（JSON 格式，供 agent 捕获）
"""

import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

BRIDGE_DIR = Path("/opt/data/histrategy_bridge")
FIFO_PATH = BRIDGE_DIR / "input.fifo"
STATUS_FILE = BRIDGE_DIR / "status.txt"


def write_status(status: str):
    STATUS_FILE.write_text(status)


def main():
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)

    # Create FIFO
    if FIFO_PATH.exists():
        os.remove(FIFO_PATH)
    os.mkfifo(str(FIFO_PATH))

    force_new = "--new" in sys.argv
    faction = "1"  # 默认曹操军
    for i, arg in enumerate(sys.argv):
        if arg == "--faction" and i + 1 < len(sys.argv):
            faction = sys.argv[i + 1]

    # Start game
    cmd = [sys.executable, "-m", "histrategy", "--headless", "--faction", faction]
    if force_new:
        cmd.append("--new")

    write_status("starting")

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        cwd="/opt/data/repos/histrategy",
    )

    write_status("running")

    # Open FIFO for reading (will block until someone opens it for writing)
    # Use a thread or non-blocking approach

    # We need to:
    # 1. Read from game stdout and print to our stdout
    # 2. Read from FIFO and write to game stdin

    # Open FIFO in non-blocking read mode
    fifo_fd = os.open(str(FIFO_PATH), os.O_RDONLY | os.O_NONBLOCK)

    game_over = False
    try:
        while proc.poll() is None:
            # Check game stdout
            ready_out, _, _ = select.select([proc.stdout], [], [], 0.3)
            if ready_out:
                try:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    line = line.strip()
                    if line:
                        print(line, flush=True)
                        # Check if this is a DECISION phase (waiting for input)
                        try:
                            data = json.loads(line)
                            if data.get("phase") == "DECISION":
                                write_status("waiting")
                        except (json.JSONDecodeError, ValueError):
                            pass
                except Exception:
                    break

            # Check FIFO for player input
            try:
                data = os.read(fifo_fd, 4096)
                if data:
                    text = data.decode("utf-8").strip()
                    if text:
                        write_status("sending")
                        proc.stdin.write(text + "\n")
                        proc.stdin.flush()
                        write_status("processing")
            except BlockingIOError:
                pass
            except OSError:
                # FIFO writer disconnected, reopen
                try:
                    fifo_fd = os.open(str(FIFO_PATH), os.O_RDONLY | os.O_NONBLOCK)
                except OSError:
                    pass

    except KeyboardInterrupt:
        write_status("interrupted")
        proc.terminate()
    except Exception as e:
        write_status("error")
        print(json.dumps({"phase": "ERROR", "content": str(e)}, ensure_ascii=False), flush=True)
        proc.terminate()
    finally:
        try:
            os.close(fifo_fd)
        except OSError:
            pass

    # Drain remaining output
    if proc.stdout:
        remaining = proc.stdout.read()
        if remaining:
            for line in remaining.splitlines():
                if line.strip():
                    print(line.strip(), flush=True)

    write_status("game_over")
    print(json.dumps({"phase": "GAMEOVER", "content": "游戏进程已结束。"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
