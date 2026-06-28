import subprocess
import os

for i in range(1, 10):
    prof = f"profile{i}"
    print(f"Testing {prof} with default model...")
    env = os.environ.copy()
    env["AGY_ACTIVE_PROFILE"] = prof
    try:
        result = subprocess.run(
            ["agy", "-p", "say hello"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            print(f"  ✅ SUCCESS: {result.stdout.strip()[:60]}")
        else:
            print(f"  ❌ FAILED: {result.stderr.strip()[:100]}")
    except subprocess.TimeoutExpired:
        print(f"  ⏳ TIMEOUT (10s)")
    print("")
