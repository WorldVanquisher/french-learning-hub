# Windows E5 runtime operations (FLH-065)

`flh-e5.ps1` starts, checks, stops and recovers the E5 service detached from
SSH, on `127.0.0.1:8765`, with `singleton_v1` batching and the pinned model.
The operator guide, with prerequisites, SSH examples, exit codes and recovery,
is [docs/WINDOWS_EMBEDDING_OPERATIONS.md](../../../../../docs/WINDOWS_EMBEDDING_OPERATIONS.md).

| File | Role |
| --- | --- |
| `flh-e5.ps1` | Entry point (Windows PowerShell 5.1+) |
| `FlhE5Ops.psm1` | Decision logic, with Windows (WMI) and POSIX test platforms |
| `runner.py` | Stdlib detached supervisor (stop request, Ctrl+Break, exit record) |
| `tests/` | Fake `flh_e5`, runner unittest and PowerShell tests (no Windows needed) |

Real Windows execution: see the
[validation report](../../../../../docs/validation/FLH-065-windows-embedding-operations.md).
