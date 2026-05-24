#!/usr/bin/env python3
"""E2E game experience: run all 4 factions, play 2 turns each, save logs."""
import subprocess, sys, os
from pathlib import Path

REPO = "/opt/data/repos/histrategy"
LOGS_DIR = Path(REPO) / "logs"
os.chdir(REPO)

factions = {
    1: "曹操",
    2: "刘备", 
    3: "孙坚",
    4: "袁绍",
}

# For each faction: select faction, then make 2 decisions, then exit
# Decision inputs: choose option 1, then option 2
inputs_plan = {
    1: "1\n1\n2\nexit\n",    # 曹操
    2: "2\n1\n2\nexit\n",    # 刘备
    3: "3\n1\n2\nexit\n",    # 孙坚
    4: "4\n1\n2\nexit\n",    # 袁绍
}

# Also try with some free-text decisions
inputs_free = {
    1: "1\n联合袁绍讨伐董卓\n派细作潜入洛阳\n2\nexit\n",
    2: "2\n联合公孙瓒共抗袁绍\n在平原开仓放粮\n3\nexit\n",
    3: "3\n北上讨董\n联合刘表\n4\nexit\n",
    4: "4\n以盟主身份号令诸侯\n先巩固河北四州\n5\nexit\n",
}

env = dict(os.environ)
# Strip API keys for offline mode test
for key in list(env.keys()):
    if "API_KEY" in key or "API_BASE" in key:
        del env[key]
env["TERM"] = "xterm-256color"

for fid, fname in factions.items():
    # Plan mode test (menu choices)
    logfile = LOGS_DIR / f"e2e-{fid}-{fname}-plan.txt"
    print(f"\n{'='*60}")
    print(f"Running {fname} (plan mode)...")
    
    proc = subprocess.run(
        [sys.executable, "-m", "histrategy", "--dev", "--new", "--faction", str(fid)],
        input=inputs_plan[fid],
        capture_output=True, text=True, timeout=120,
        cwd=REPO, env=env,
    )
    output = f"=== {fname} PLAN MODE ===\nINPUT: {inputs_plan[fid]!r}\n\nSTDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}\nEXIT: {proc.returncode}"
    logfile.write_text(output)
    print(f"  Logged to {logfile} ({len(output)} bytes)")

    # Free text test
    logfile2 = LOGS_DIR / f"e2e-{fid}-{fname}-free.txt"
    print(f"Running {fname} (free text mode)...")
    
    proc = subprocess.run(
        [sys.executable, "-m", "histrategy", "--dev", "--new", "--faction", str(fid)],
        input=inputs_free[fid],
        capture_output=True, text=True, timeout=180,
        cwd=REPO, env=env,
    )
    output2 = f"=== {fname} FREE TEXT MODE ===\nINPUT: {inputs_free[fid]!r}\n\nSTDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}\nEXIT: {proc.returncode}"
    logfile2.write_text(output2)
    print(f"  Logged to {logfile2} ({len(output2)} bytes)")

print(f"\n\nAll 8 runs complete. Logs in {LOGS_DIR}/")
print(f"Total: {sum(f.stat().st_size for f in LOGS_DIR.glob('e2e-*.txt'))} bytes")
