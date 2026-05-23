#!/usr/bin/env python3
"""Direct PTY-based recording for asciinema cast generation.

Runs the game in a PTY, feeds inputs, captures all output with ANSI codes,
then converts to SVG via svg-term.
"""
import json
import os
import pty
import select
import subprocess
import time
import re

CAST_PATH = "/opt/data/repos/histrategy/demo/histrategy-demo.cast"
SVG_PATH = "/opt/data/repos/histrategy/demo/histrategy-demo.svg"
ENV_PATH = "/opt/data/repos/histrategy/.env"

# Read .env
env = os.environ.copy()
for line in open(ENV_PATH):
    line = line.strip()
    if line and '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        env[k] = v.strip("'\"")
env['TERM'] = 'xterm-256color'
env['PYTHONUNBUFFERED'] = '1'
env['PATH'] = os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')

GAME_CMD = [".venv/bin/python3", "-m", "histrategy", "--new"]

# Demo inputs: (delay_after_previous, text)
# Longer delays for AI generation
DEMO = [
    (3.0, "1\n"),     # Select Cao Cao (wait for AI intro)
    (8.0, "1\n"),     # 响应袁绍
    (8.0, "2\n"),     # 发展经济
    (6.0, "3\n"),     # 外交
    (5.0, "exit\n"),  # Exit
]

def capture_demo():
    """Run game in PTY, capture all output with timing."""
    master_fd, slave_fd = pty.openpty()
    
    proc = subprocess.Popen(
        GAME_CMD,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=env,
        cwd="/opt/data/repos/histrategy",
        close_fds=True,
    )
    os.close(slave_fd)
    
    output_buffer = bytearray()
    events = []
    start_time = time.time()
    
    def flush_output():
        nonlocal output_buffer
        if output_buffer:
            elapsed = time.time() - start_time
            text = output_buffer.decode('utf-8', errors='replace')
            # Clean up control characters but keep ANSI escapes
            text = text.replace('\r\n', '\n')
            if text.strip():
                events.append([round(elapsed, 3), "o", text])
            output_buffer.clear()
    
    try:
        for delay, inp in DEMO:
            # Read any pending output
            poll_start = time.time()
            while time.time() - poll_start < delay:
                r, _, _ = select.select([master_fd], [], [], 0.05)
                if r:
                    try:
                        data = os.read(master_fd, 8192)
                        if data:
                            output_buffer.extend(data)
                        else:
                            break
                    except OSError:
                        break
                else:
                    time.sleep(0.05)
            
            # Flush accumulated output
            flush_output()
            
            # Send input
            inp_bytes = inp.encode()
            os.write(master_fd, inp_bytes)
            events.append([round(time.time() - start_time, 3), "i", inp])
        
        # Read remaining output
        time.sleep(3)
        r, _, _ = select.select([master_fd], [], [], 2)
        if r:
            try:
                data = os.read(master_fd, 32768)
                if data:
                    output_buffer.extend(data)
            except OSError:
                pass
        flush_output()
        
    finally:
        # Clean up
        try:
            os.write(master_fd, b"\x03")  # Ctrl+C
        except:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except:
            proc.kill()
        os.close(master_fd)
    
    return events

print("Recording demo...")
events = capture_demo()
print(f"Captured {len(events)} events")

if not events:
    print("ERROR: No events captured!")
    exit(1)

# Create asciinema cast file
cast = {
    "version": 2,
    "width": 100,
    "height": 35,
    "timestamp": int(time.time()),
    "env": {"SHELL": "/bin/bash", "TERM": "xterm-256color"},
    "title": "三國志略 - AI History Strategy Game",
}

with open(CAST_PATH, "w") as f:
    json.dump(cast, f, ensure_ascii=False)
    f.write('\n')
    for event in events:
        json.dump(event, f, ensure_ascii=False)
        f.write('\n')

cast_size = os.path.getsize(CAST_PATH)
print(f"Cast file: {cast_size} bytes")

# Convert to SVG
print("Converting to SVG...")
result = subprocess.run([
    "svg-term", "--in", CAST_PATH,
    "--out", SVG_PATH,
    "--width", "100", "--height", "35",
    "--padding", "10",
], capture_output=True, text=True, timeout=30)

if result.returncode == 0:
    svg_size = os.path.getsize(SVG_PATH)
    print(f"SVG created: {svg_size} bytes at {SVG_PATH}")
else:
    print(f"svg-term failed: {result.stderr}")
    # Try without padding
    result = subprocess.run([
        "svg-term", "--in", CAST_PATH,
        "--out", SVG_PATH,
        "--width", "100", "--height", "35",
    ], capture_output=True, text=True, timeout=30)
    if result.returncode == 0:
        svg_size = os.path.getsize(SVG_PATH)
        print(f"SVG created (no padding): {svg_size} bytes")
    else:
        print(f"svg-term still failed: {result.stderr}")
