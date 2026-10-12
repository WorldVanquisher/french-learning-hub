# FLH-054: record the environment before and after installing requirements.
# Read-only: installs nothing, downloads nothing. Run inside the activated
# Conda env:  conda activate flh-embedding ; .\tools\embedding\e5\windows\check-env.ps1
$ErrorActionPreference = 'Stop'
if ($env:CONDA_DEFAULT_ENV -ne 'flh-embedding') {
    Write-Warning "CONDA_DEFAULT_ENV is '$($env:CONDA_DEFAULT_ENV)', expected 'flh-embedding'."
}
Write-Output "python: $((Get-Command python).Source)"
python -c "import sys; print('python', sys.version)"
python -m pip --version
$code = @'
import importlib
for name in ("torch", "transformers", "tokenizers", "safetensors", "huggingface_hub", "numpy"):
    try:
        print(name, importlib.import_module(name).__version__)
    except ImportError:
        print(name, "NOT INSTALLED")
import torch
print("torch.version.cuda", torch.version.cuda, "cuda available", torch.cuda.is_available())
assert torch.cuda.is_available(), "CUDA not available"
p = torch.cuda.get_device_properties(0)
print("device", p.name, "capability", f"{p.major}.{p.minor}", "total_memory_bytes", p.total_memory)
x = torch.ones((2, 2), device="cuda"); y = x @ x; torch.cuda.synchronize()
assert y.eq(2).all().item(); print("cuda tensor computation ok on", y.device)
'@
python -c $code
if ($LASTEXITCODE -ne 0) { throw "environment check failed" }
nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used --format=csv
