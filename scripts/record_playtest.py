#!/usr/bin/env python3
import os
import subprocess
import time

ENV_PATH = "/Users/julian/gitbubble/histrategy/.env"
LOG_PATH = "/Users/julian/gitbubble/histrategy/logs/2026-05-25-playtest-log.txt"

# Read .env
env = os.environ.copy()
if os.path.exists(ENV_PATH):
    for line in open(ENV_PATH):
        line = line.strip()
        if line and '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            env[k] = v.strip("'\"")

if 'DEEPSEEK_API_KEY' in env:
    del env['DEEPSEEK_API_KEY']

env['PYTHONUNBUFFERED'] = '1'

GAME_CMD = ["./venv/bin/python3", "-m", "histrategy", "--dev", "--faction", "2", "--new"]

def run_playtest():
    # Make sure logs directory exists
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    
    print("Launching game in dev mode with faction Shu...")
    proc = subprocess.Popen(
        GAME_CMD,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
        bufsize=1
    )
    
    log_file = open(LOG_PATH, "w", encoding="utf-8")
    
    inputs = [
        "出兵联合曹操，共商讨董大计\n",
        "于平原扩军备战，操练士卒，募民为兵\n",
        "exit\n"
    ]
    
    def read_until(stream, target, log):
        buffer = ""
        while True:
            char = stream.read(1)
            if not char:
                break
            buffer += char
            print(char, end="")
            log.write(char)
            log.flush()
            if target in buffer:
                break

    try:
        # Read intro & Plan Mode 1
        print("Waiting for game intro...")
        read_until(proc.stdout, "你的决策:", log_file)
        
        # Turn 1
        print("\n>>> Sending decision 1: 联合曹操，共商讨董")
        proc.stdin.write(inputs[0])
        proc.stdin.flush()
        
        # Read result of Turn 1 & Plan Mode 2
        read_until(proc.stdout, "你的决策:", log_file)
                
        # Turn 2
        print("\n>>> Sending decision 2: 扩军备战，操练士卒")
        proc.stdin.write(inputs[1])
        proc.stdin.flush()
        
        # Read result of Turn 2 & Plan Mode 3
        read_until(proc.stdout, "你的决策:", log_file)
                
        # Exit
        print("\n>>> Sending exit")
        proc.stdin.write(inputs[2])
        proc.stdin.flush()
        
        # Read remaining output until exit
        while True:
            char = proc.stdout.read(1)
            if not char:
                break
            print(char, end="")
            log_file.write(char)
            log_file.flush()
            
    except Exception as e:
        print(f"Error during playtest: {e}")
    finally:
        proc.terminate()
        proc.wait()
        log_file.close()
        print(f"\nPlaytest completed. Log saved to: {LOG_PATH}")

if __name__ == "__main__":
    run_playtest()
