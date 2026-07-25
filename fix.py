content = open("/Users/chandan/leadflow/resolve_devices.py").read()

import re
content = re.sub(r'def ensure_connected\(target="vivo"\):', r'def ensure_connected(target="vivo"):\n    import os, subprocess, threading, re\n    from pathlib import Path', content)

with open("/Users/chandan/leadflow/resolve_devices.py", "w") as f:
    f.write(content)
