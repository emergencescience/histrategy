#!/usr/bin/env python3
"""Generate demo SVG and recording for Histrategy."""
import subprocess, os, sys, time, json

cast_path = "/opt/data/repos/histrategy/demo/histrategy-demo.cast"
demo_script = """#!/usr/bin/env python3
import subprocess, os
import sys
sys.stdout.write('Starting 三國志略 demo...\\n')
sys.stdout.flush()
os.chdir('/opt/data/repos/histrategy')
os.environ.update({k:v for k,v in [l.split('=',1) for l in open('.env').read().splitlines() if l and '=' in l and not l.startswith('#')]})
os.environ['TERM'] = 'xterm-256color'
proc = subprocess.Popen(
    ['.venv/bin/python3', '-m', 'histrategy'],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    env=os.environ,
    text=True
)
# Wait for game to start
import time
time.sleep(2)
# Send inputs with delays
for inp in ['1\\n', '1\\n', '2\\n', '3\\n', 'exit\\n']:
    proc.stdin.write(inp)
    proc.stdin.flush()
    time.sleep(2)
    # Read any available output
    import select
    while True:
        r, _, _ = select.select([proc.stdout], [], [], 0.1)
        if r:
            line = proc.stdout.readline()
            if line:
                sys.stdout.write(line)
                sys.stdout.flush()
        else:
            break
proc.wait()
"""

# Write helper script
with open("/tmp/demo_helper.py", "w") as f:
    f.write(demo_script)

print("To record demo video run:")
print()
print("  step 1: Record terminal session")
print("  asciinema rec /opt/data/repos/histrategy/demo/histrategy-demo.cast \\")
print("    --title '三國志略 - AI History Strategy Game' \\")
print("    --command 'python3 /tmp/demo_helper.py'")
print()
print("  step 2: Convert to SVG for README")
print("  svg-term --cast /opt/data/repos/histrategy/demo/histrategy-demo.cast \\")
print("    --out /opt/data/repos/histrategy/demo/histrategy-demo.svg \\")
print("    --width 80 --height 24")
print()
print("  step 3: To share on asciinema.org:")
print("  asciinema upload /opt/data/repos/histrategy/demo/histrategy-demo.cast")
