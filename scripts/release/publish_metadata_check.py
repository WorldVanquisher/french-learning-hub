#!/usr/bin/env python3
"""Check publishable metadata (commit messages, PR bodies) before it is pushed.

  publish_metadata_check.py [--label TEXT] [--kind commit|pr-body|text] FILE...   (FILE may be -)
  publish_metadata_check.py --redact < text > text

Findings (exit 1; each printed as `LABEL:LINE: RULE: excerpt`, with private
links redacted):

  ai-coauthor-trailer   a `Co-authored-by:` line naming Claude or Anthropic
                        (name containing "Claude" or "Anthropic", or an
                        anthropic.com address)
  session-trailer       a `Claude-Session:` line, whatever its value
  private-session-link  a claude.ai conversation, Claude Code session, project
                        or share URL
  ai-identity           (--kind commit) an `Author:` or `Committer:` header
                        naming Claude or Anthropic

Not findings: prose about using AI ("drafted with Claude Code"), the public
"Generated with [Claude Code](https://claude.com/claude-code)" line, and
`Co-authored-by:` trailers for people. Exit 0 when nothing is found, 2 on bad
usage or an unreadable file.

`--redact` copies stdin to stdout with every private link replaced, so error
output can be shown without leaking a session URL.

The interface is deliberately small so a shared check (for example a future
PAI command) can replace it: the publisher calls
`<check> --label TEXT --kind commit|pr-body FILE` and only reads the exit code
and the printed lines.
"""
import argparse
import re
import sys

AI_NAME = re.compile(r"\b(claude|anthropic)\b", re.I)
AI_EMAIL = re.compile(r"@(?:[a-z0-9-]+\.)*anthropic\.com\b", re.I)
COAUTHOR = re.compile(r"^\s*co-authored-by\s*:\s*(?P<value>.*)$", re.I)
SESSION_TRAILER = re.compile(r"^\s*claude-session\s*:", re.I)
IDENTITY = re.compile(r"^(?:author|committer)\s*:\s*(?P<value>.*)$", re.I)
# claude.ai links that point at a private conversation, Claude Code session,
# project or share; the identifier is what gets redacted.
PRIVATE_LINK = re.compile(
    r"(?P<prefix>https?://(?:www\.)?claude\.ai/(?:code/(?:session[_/-]?|sessions/)|chat/|project/|share/))"
    r"(?P<id>[A-Za-z0-9][A-Za-z0-9_-]*)",
    re.I,
)


def redact(text):
    return PRIVATE_LINK.sub(lambda m: m.group("prefix") + "[REDACTED]", text)


def is_ai_identity(value):
    return bool(AI_NAME.search(value) or AI_EMAIL.search(value))


def findings(text, kind):
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        m = COAUTHOR.match(line)
        if m and is_ai_identity(m.group("value")):
            out.append((n, "ai-coauthor-trailer", line))
        if SESSION_TRAILER.match(line):
            out.append((n, "session-trailer", line))
        if PRIVATE_LINK.search(line):
            out.append((n, "private-session-link", line))
        if kind == "commit":
            m = IDENTITY.match(line)
            if m and is_ai_identity(m.group("value")):
                out.append((n, "ai-identity", line))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check commit messages and PR bodies before publishing.")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--label", default="")
    ap.add_argument("--kind", choices=("commit", "pr-body", "text"), default="text")
    ap.add_argument("--redact", action="store_true", help="copy stdin to stdout with private links redacted")
    a = ap.parse_args(argv)
    if a.redact:
        sys.stdout.write(redact(sys.stdin.read()))
        return 0
    if not a.files:
        ap.print_usage(sys.stderr)
        return 2
    found = 0
    for f in a.files:
        try:
            text = sys.stdin.read() if f == "-" else open(f, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError) as e:
            print(f"cannot read {redact(f)}: {e.__class__.__name__}", file=sys.stderr)
            return 2
        label = a.label or f
        for n, rule, line in findings(text, a.kind):
            found += 1
            excerpt = redact(line.strip())
            if len(excerpt) > 120:
                excerpt = excerpt[:117] + "..."
            print(f"{label}:{n}: {rule}: {excerpt}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
