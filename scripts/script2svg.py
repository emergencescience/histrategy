#!/usr/bin/env python3
"""Convert script output to asciinema cast and then to SVG."""
import json
import os
import subprocess
import re

SCRIPT_PATH = "/opt/data/repos/histrategy/demo/histrategy-demo.script"
CAST_PATH = "/opt/data/repos/histrategy/demo/histrategy-demo.cast"
SVG_PATH = "/opt/data/repos/histrategy/demo/histrategy-demo.svg"

# Read the script output
with open(SCRIPT_PATH, errors="replace") as f:
    raw = f.read()

# The script file has header before the actual output
# Find the actual game output (after "Script started on...")
# The format is: header lines + actual content

# Remove script header: look for the actual game content
# The script file starts with our input echo (the heredoc), then the game output
# Let's find where the actual game content begins

# Find the game title ASCII art as the start point
game_start = raw.find("/ \\")
if game_start > 0:
    # Find the beginning of that line
    while game_start > 0 and raw[game_start-1] != '\n':
        game_start -= 1

# Remove carriage returns, keep newlines
content = raw.replace('\r\n', '\n')

if game_start > 0:
    content = content[game_start:]

# Trim trailing whitespace
content = content.rstrip()

# Remove non-printable chars but keep ANSI escape sequences
# ANSI sequences: \x1b[...m for colors, \x1b[...H for cursor movement
ansi_pattern = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')
# Just keep them - they're what make the terminal output look good

# Create the asciinema cast file
cast = {
    "version": 2,
    "width": 80,
    "height": 30,
    "timestamp": int(__import__('time').time()),
    "env": {"SHELL": "/bin/bash", "TERM": "xterm-256color"},
    "title": "三國志略 - AI History Strategy Game",
}

# Events: output all content at time 0.5 (after startup)
# Split into chunks for smoother display
lines = content.split('\n')
events = []

# First event: initial blank
events.append([0.1, "o", "\n" * 5])

# Output lines in chunks
current_time = 0.5
chunk_size = 5  # lines per event

for i in range(0, len(lines), chunk_size):
    chunk = '\n'.join(lines[i:i+chunk_size])
    if chunk:
        events.append([current_time, "o", chunk])
    current_time += 0.8

with open(CAST_PATH, "w") as f:
    json.dump(cast, f, ensure_ascii=False)
    f.write('\n')
    for event in events:
        json.dump(event, f, ensure_ascii=False)
        f.write('\n')

cast_size = os.path.getsize(CAST_PATH)
print(f"Created cast file: {cast_size} bytes at {CAST_PATH}")

# Convert to SVG
result = subprocess.run([
    "svg-term", "--cast", CAST_PATH,
    "--out", SVG_PATH,
    "--width", "80", "--height", "30",
    "--padding", "8",
    "--window",  # add terminal window frame
], capture_output=True, text=True, timeout=30)

if result.returncode == 0:
    svg_size = os.path.getsize(SVG_PATH)
    print(f"Created SVG: {svg_size} bytes at {SVG_PATH}")
else:
    print(f"svg-term error: {result.stderr}")
    print("Trying without --window flag...")
    result = subprocess.run([
        "svg-term", "--cast", CAST_PATH,
        "--out", SVG_PATH,
        "--width", "80", "--height", "30",
    ], capture_output=True, text=True, timeout=30)
    if result.returncode == 0:
        svg_size = os.path.getsize(SVG_PATH)
        print(f"Created SVG: {svg_size} bytes at {SVG_PATH}")
    else:
        print(f"svg-term error again: {result.stderr}")
