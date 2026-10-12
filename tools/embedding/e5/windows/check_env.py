"""FLH-057: read-only environment check run by check-env.ps1.

Kept in a file so PowerShell never passes Python source as a native command
argument: Windows PowerShell 5.1 (and 7 with legacy argument passing) drops
embedded double quotes from `python -c $code`, which corrupted the FLH-054
inline version. It takes no arguments and reads no paths or user text.

Exit status: 0 when CUDA computed correctly, 1 when CUDA is unavailable or the
computation is wrong, 2 when torch cannot be imported.
"""

import importlib
import sys

print("python", sys.version)
print("executable", sys.executable)
for name in ("torch", "transformers", "tokenizers", "safetensors", "huggingface_hub", "numpy"):
    try:
        print(name, importlib.import_module(name).__version__)
    except ImportError:
        print(name, "NOT INSTALLED")

try:
    import torch
except ImportError:
    print("FAIL: torch cannot be imported", file=sys.stderr)
    sys.exit(2)

print("torch.version.cuda", torch.version.cuda, "cuda available", torch.cuda.is_available())
if not torch.cuda.is_available():
    print("FAIL: CUDA not available", file=sys.stderr)
    sys.exit(1)
p = torch.cuda.get_device_properties(0)
print("device", p.name, "capability", f"{p.major}.{p.minor}", "total_memory_bytes", p.total_memory)
x = torch.ones((2, 2), device="cuda")
y = x @ x
torch.cuda.synchronize()
if not bool(y.eq(2).all().item()):
    print("FAIL: CUDA tensor computation returned a wrong result", file=sys.stderr)
    sys.exit(1)
print("cuda tensor computation ok on", y.device)
