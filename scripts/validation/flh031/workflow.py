#!/usr/bin/env python3
"""Run the established FLH-026 workflow with a task-owned safe Compose name."""
import uuid

# verify installs only the known local FLH-026/028 module paths.
import verify  # noqa: F401
import run as established


class TaskHarness(established.Harness):
    def __init__(self, mode):
        super().__init__(mode)
        self.project = "flh026-flh031-" + uuid.uuid4().hex
        self.image = self.project + ":local"


if __name__ == "__main__":
    established.Harness = TaskHarness
    raise SystemExit(established.main())
