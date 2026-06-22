"""Terminal display helpers — colour codes, timestamp, log line."""

import datetime

# ANSI codes
R   = "\033[0m"   # reset
B   = "\033[1m"   # bold
DIM = "\033[2m"   # dim
CY  = "\033[36m"  # cyan    – infrastructure / init
GR  = "\033[32m"  # green   – subscriber
YL  = "\033[33m"  # yellow  – publisher
MG  = "\033[35m"  # magenta – assertion / result
RD  = "\033[31m"  # red     – errors

SEP  = f"{DIM}{'─' * 64}{R}"
SEP2 = f"{DIM}{'═' * 64}{R}"


def ts() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


def log(colour: str, role: str, msg: str) -> None:
    print(f"{DIM}[{ts()}]{R} {colour}{B}{role:<12}{R} {msg}")
