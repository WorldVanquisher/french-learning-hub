#!/usr/bin/env python3
"""Redact tool output before it is shared (an issue, a handoff, a chat): standard library, Python 3.9.

  some-command | python3 -I scripts/release/redact.py [--keep-path PREFIX]... [--name NAME=VALUE]...

Replaces, line by line:
  /home/<user>, /Users/<user> -> ~  (anywhere, even glued to other text)
  absolute and ~/ paths       -> <path>/<last component>  (repository-relative paths are kept;
                                 --keep-path PREFIX keeps a path under PREFIX as-is)
  --name NAME=VALUE           -> <NAME> for an exact value first (for example ROOT=/srv/flh-staging)
  AWS account IDs (12 digits) -> <ACCOUNT>;  ARNs keep their service and resource type
  instance / volume / ENI IDs -> <INSTANCE> / <VOLUME> / <ENI>
  s3://bucket, flh-stg-<26 digits> -> s3://<BUCKET> / <BUCKET>  (Compose projects flh-stg-<run>-<name> stay)
  IPv4 other than 127.0.0.1 and 0.0.0.0 -> <IP>;  ip-a-b-c-d, *.ec2.internal, *.compute.internal, *.ts.net -> <HOST>
  e-mail addresses            -> <EMAIL>
  https URLs with a signature or a private session (presigned S3, claude.ai) -> <PRIVATE-URL>
Prints a last line on stderr with how many replacements were made. It cannot know every secret:
read the result before sharing it.
"""
import argparse
import re
import sys

RULES = [
    (re.compile(r"https://\S*(?:X-Amz-Signature|X-Amz-Credential|claude\.ai/)\S*"), "<PRIVATE-URL>"),
    (re.compile(r"https://claude\.ai\S*"), "<PRIVATE-URL>"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "<EMAIL>"),
    (re.compile(r"/(?:home|Users)/[^/\s'\"`:<>]+(?=/|\s|$)"), "~"),        # a user's home, wherever it appears
    (re.compile(r"(arn:aws[a-z-]*:[a-z0-9-]*:[a-z0-9-]*:)[0-9]{12}(?=:)"), r"\1<ACCOUNT>"),
    (re.compile(r"(?<![0-9A-Za-z])[0-9]{12}(?![0-9A-Za-z])"), "<ACCOUNT>"),
    (re.compile(r"\bi-[0-9a-f]{8,17}\b"), "<INSTANCE>"),
    (re.compile(r"\bvol-[0-9a-f]{8,17}\b"), "<VOLUME>"),
    (re.compile(r"\beni-[0-9a-f]{8,17}\b"), "<ENI>"),
    (re.compile(r"s3://[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]"), "s3://<BUCKET>"),
    (re.compile(r"\bflh-stg-[0-9]{20,}\b"), "<BUCKET>"),         # bucket_prefix + 26 digits; not flh-stg-<run>-<name>
    (re.compile(r"\b(?:ip-[0-9]+-[0-9]+-[0-9]+-[0-9]+|[a-z0-9-]+)(?:\.[a-z0-9-]+)?\.(?:compute|ec2)\.internal\b"), "<HOST>"),
    (re.compile(r"\bip-[0-9]+-[0-9]+-[0-9]+-[0-9]+\b"), "<HOST>"),
    (re.compile(r"\b[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.ts\.net\b"), "<HOST>"),      # tailnet (MagicDNS) names
    (re.compile(r"\b(?!127\.0\.0\.1\b)(?!0\.0\.0\.0\b)(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"), "<IP>"),
]
PATH = re.compile(r"(?<![\w.:<>/~-])(~?/(?:[^\s/'\"`:,;|(){}\[\]]+/)+)([^\s/'\"`:,;|(){}\[\]]*)")


def redact(text, names=(), keep=()):
    count = 0
    for name, value in names:
        if value:
            count += text.count(value)
            text = text.replace(value, f"<{name}>")
    for rx, rep in RULES:
        text, n = rx.subn(rep, text)
        count += n

    def path(m):
        nonlocal count
        whole = m.group(0)
        if any(whole.startswith(k) for k in keep):
            return whole
        count += 1
        return f"<path>/{m.group(2)}" if m.group(2) else "<path>/"
    text = PATH.sub(path, text)
    return text, count


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keep-path", action="append", default=[])
    ap.add_argument("--name", action="append", default=[], help="NAME=VALUE: replace VALUE by <NAME>")
    a = ap.parse_args()
    names = []
    for n in a.name:
        if "=" not in n:
            print("redact: --name needs NAME=VALUE", file=sys.stderr)
            return 2
        k, v = n.split("=", 1)
        names.append((k, v))
    names.sort(key=lambda kv: -len(kv[1]))          # the longest value first
    text, count = redact(sys.stdin.read(), names, tuple(a.keep_path))
    sys.stdout.write(text)
    print(f"redact: {count} replacement(s); read the result before sharing it", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
