#!/usr/bin/env python3
"""Create asciinema cast file by running the game with automated inputs."""
import json
import os
import pty
import time
import select
import subprocess

CAST_PATH = "/opt/data/repos/histrategy/demo/histrategy-demo.cast"
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

# Game inputs (with delays for the AI to generate narrative)
demo_inputs = [
    (0.5, "1\n"),           # Select Cao Cao
    (6.0, "1\n"),           # Option 1: 响应袁绍
    (8.0, "2\n"),           # Option 2: 发展经济
    (6.0, "3\n"),           # Option 3: 外交
    (4.0, "exit\n"),        # Exit
]

def start_recording():
    """Start asciinema recording and return the process."""
    cmd = [
        "asciinema", "rec", CAST_PATH,
        "--title", "三國志略 - AI History Strategy Game",
        "--overwrite",
        "-c", f"cd /opt/data/repos/histrategy && {env.get('_', '/usr/bin/env')} python3 -m histrategy",
    ]
    # Use PTY
    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        cmd,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=env,
        pass_fds=(slave_fd,),
    )
    os.close(slave_fd)
    return proc, master_fd

def send_input(master_fd, text):
    os.write(master_fd, text.encode())

def read_output(master_fd, timeout=2):
    output = b""
    start = time.time()
    while time.time() - start < timeout:
        r, _, _ = select.select([master_fd], [], [], 0.1)
        if r:
            try:
                data = os.read(master_fd, 4096)
                if data:
                    output += data
                else:
                    break
            except OSError:
                break
    return output

print("Starting asciinema recording...")
proc, master = start_recording()

try:
    # Wait for game to initialize
    time.sleep(3)
    
    # Send inputs with proper timing
    for delay, text in demo_inputs:
        time.sleep(delay)
        read_output(master, 0.2)  # drain any pending output
        send_input(master, text)
    
    # Wait for recording to finish
    time.sleep(3)
finally:
    # Send Ctrl+D or just kill
    try:
        send_input(master, b"\x04")  # Ctrl+D
    except:
        pass
    time.sleep(1)
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except:
        proc.kill()
    os.close(master)

print(f"\nRecording saved to: {CAST_PATH}")
print(f"File size: {os.path.getsize(CAST_PATH)} bytes")
print("\nConvert to SVG:")
print(f"  svg-term --cast {CAST_PATH} --out /opt/data/repos/histrategy/demo/histrategy-demo.svg --width 80 --height 30")
