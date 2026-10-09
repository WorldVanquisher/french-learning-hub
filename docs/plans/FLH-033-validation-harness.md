# FLH-033 — validation harness reliability

Owner: NAS Codex. Working directory: supplied flh-nas-codex workspace.
Branch supplied by human: fix/flh-033-validation-harness; no Git inspection.
One writer for the nine files listed in the task handoff; Claude owns FLH-032.

Acceptance: correct only FLH-029 compiler attribution; record native compiler
selection/version/hash and server metadata/hash under the unchanged isolated
environment. Generate independent hexadecimal Docker names with deterministic
underscore-directory coverage. Preserve duplicate end-to-end header pairs,
reject ambiguous framing, and prove server rejection leaves every table and local
provider counter unchanged. No production, schema, dependency or shared README
changes. README.zh-CN.md exists; neither root README changes in this task.

Validation: FLH-026 safety tests, FLH-028 proxy tests (including owned-server
probes), established FLH-026 native/container workflows, and FLH-028 keyed
response-loss matrix. Read-only FLH-031 adapters may supply container matrix
checks. Every database, port, source copy, provider and application image is owned
and temporary; evidence logs/reports live under /tmp/flh033-*. Initial failures
remain distinct from final evidence. No paid calls, secrets or daily databases.
