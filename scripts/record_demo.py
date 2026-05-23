#!/usr/bin/env python3
"""Record an asciinema demo of Histrategy."""
import subprocess
import os
import sys

# Set up API key for the demo
os.environ.setdefault("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
os.environ.setdefault("OPENAI_API_BASE", os.environ.get("OPENAI_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
os.environ.setdefault("LLM_MODEL", os.environ.get("LLM_MODEL", "deepseek-v4-flash"))

# Demo script: player choices
demo_input = """1
1
1
联合袁绍讨伐董卓
3
派使者结盟孙坚
2
发展经济休养生息
4
巩固城防
exit
"""

# Run with asciinema
cmd = [
    "asciinema", "rec",
    "/opt/data/repos/histrategy/demo/histrategy-demo.cast",
    "--title", "三國志略 - AI History Strategy Game",
    "--command", f"cd /opt/data/repos/histrategy && set -a && source .env && set +a && echo '{demo_input}' | timeout 45 .venv/bin/python3 -m histrategy",
    "-y",
]

print("Recording demo...")
subprocess.run(cmd, timeout=60)
print("Demo recorded!")
