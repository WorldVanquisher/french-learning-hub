"""FLH-063 bounded AWS backup/restore and Bedrock embedding tools.

Nothing in this package contacts AWS on import. Live commands need an explicit
profile, region and --allow-live; every billable call is reserved in a
persistent ledger before it is sent.
"""

TOOL_VERSION = "flh063-aws-tools-v1"
TASK_TAG = "FLH-063"
