#!/usr/bin/env python3
"""Record a 12-round gameplay log with proper PTY interactions."""
import os, sys, pty, select, time, subprocess

LOG_PATH = "/opt/data/repos/histrategy/logs/2026-05-23-12rounds-playtest.txt"
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

# Strip API keys to force offline mode
for key in list(env.keys()):
    if "API_KEY" in key or "API_BASE" in key:
        del env[key]

GAME_CMD = [".venv/bin/python3", "-m", "histrategy"]

# Players decisions for 12+ rounds
# Each: (decision_text, expected_wait_time)
ROUNDS = [
    "\n",                          # Press Enter to skip offline notice
    "1\n",                        # Select Cao Cao
    "联合袁绍讨伐董卓\n",          # Round 1
    "发展经济屯田养兵\n",          # Round 2
    "派使者联络孙坚\n",            # Round 3
    "扩军备战\n",                  # Round 4
    "加固城防\n",                  # Round 5
    "侦查敌情\n",                  # Round 6
    "联孙攻曹\n",                  # Round 7
    "发展经济\n",                  # Round 8
    "征兵训练\n",                  # Round 9
    "外交结盟\n",                  # Round 10
    "修水利\n",                   # Round 11
    "出征讨伐\n",                  # Round 12
    "exit\n",                     # Exit
]

master_fd, slave_fd = pty.openpty()
proc = subprocess.Popen(
    GAME_CMD, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
    env=env, cwd="/opt/data/repos/histrategy", close_fds=True,
)
os.close(slave_fd)

all_output = bytearray()
start = time.time()

def flush(deadline=2.0):
    end = time.time() + deadline
    while time.time() < end:
        r, _, _ = select.select([master_fd], [], [], 0.1)
        if r:
            try:
                data = os.read(master_fd, 32768)
                if data:
                    all_output.extend(data)
                else:
                    break
            except OSError:
                break

try:
    # Wait for game to start
    flush(4.0)
    
    for i, inp in enumerate(ROUNDS):
        # Send input
        os.write(master_fd, inp.encode())
        # Wait for processing
        flush(6.0 if i > 0 else 8.0)  # More time for first turn (AI intro)
        
except Exception as e:
    print(f"Error: {e}")
finally:
    try:
        os.write(master_fd, b"\x03")
    except:
        pass
    flush(1)
    try:
        proc.terminate()
        proc.wait(3)
    except:
        proc.kill()
    os.close(master_fd)

# Write log
output = all_output.decode('utf-8', errors='replace')
output = output.replace('\r\n', '\n')
output = output.replace('\r', '\n')

with open(LOG_PATH, 'w') as f:
    f.write(f"=== 三國志略 12-Round Playtest ===\n")
    f.write(f"Date: 2026-05-23\n")
    f.write(f"Faction: Cao Cao\n")
    f.write(f"Inputs: {[r.strip() for r in ROUNDS]}\n")
    f.write(f"Output size: {len(output)} chars\n")
    f.write(f"{'='*60}\n\n")
    f.write(output)

print(f"\nLog saved: {LOG_PATH}")
print(f"Size: {os.path.getsize(LOG_PATH)} bytes")

# Check for key content
checks = ["决策后果", "军师来报", "联合袁绍", "孙坚", "⚡", "190年", "191年", "兵力"]
for c in checks:
    count = output.count(c)
    print(f"  '{c}': {count} occurrences")
