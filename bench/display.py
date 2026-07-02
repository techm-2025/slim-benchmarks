"""Minimal colored log helpers."""

from __future__ import annotations

R  = "\033[0m"
B  = "\033[1m"
GR = "\033[32m"
YL = "\033[33m"
CY = "\033[36m"
MG = "\033[35m"
RD = "\033[31m"

SEP  = "=" * 72
SEP2 = "-" * 72


def log(color: str, role: str, msg: str) -> None:
    print(f"{color}{B}[{role}]{R} {msg}")
