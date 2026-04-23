"""
Side-by-side comparison report
- Reads captures/slim_hexdump.txt and captures/nats_hexdump.txt
- Extracts the payload-carrying frames from each
- Saves captures/comparison_report.txt  (text)
- Saves captures/comparison.png          (matplotlib figure)
"""

import os
import re

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch

PLAINTEXT    = "SLIM_SECURITY_DEMO_PLAINTEXT_2026"
CAPTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "captures")
SLIM_DUMP    = os.path.join(CAPTURES_DIR, "slim_hexdump.txt")
NATS_DUMP    = os.path.join(CAPTURES_DIR, "nats_hexdump.txt")
REPORT_TXT   = os.path.join(CAPTURES_DIR, "comparison_report.txt")
REPORT_PNG   = os.path.join(CAPTURES_DIR, "comparison.png")


# ── Frame parser ───────────────────────────────────────────────────────────────
def parse_frames(path: str) -> list[dict]:
    """Return list of {direction, size, hex_lines, raw_bytes} dicts."""
    frames = []
    current = None
    with open(path) as fh:
        for line in fh:
            line = line.rstrip()
            m = re.match(r"^\s+\[(.+?)\]\s+(\d+) bytes", line)
            if m:
                if current:
                    frames.append(current)
                current = {"direction": m.group(1),
                           "size": int(m.group(2)),
                           "hex_lines": [],
                           "raw_bytes": b""}
                continue
            if current and re.match(r"^\s+[0-9a-f]{4}\s+", line):
                current["hex_lines"].append(line)
                # extract hex bytes: split on "  |" separator, take hex area after offset
                parts = line.split("  |")
                if parts:
                    hex_area = parts[0][8:].replace(" ", "")  # skip "  XXXX  "
                    try:
                        current["raw_bytes"] += bytes.fromhex(hex_area)
                    except ValueError:
                        pass
    if current:
        frames.append(current)
    return frames


def find_payload_frame(frames: list[dict], needle: bytes) -> dict | None:
    """Return first frame whose raw bytes contain needle."""
    for f in frames:
        if needle in f["raw_bytes"]:
            return f
    return None


def largest_client_frame(frames: list[dict]) -> dict | None:
    """For SLIM: pick the largest CLIENT→RELAY frame (the encrypted message)."""
    client_frames = [f for f in frames if "CLIENT" in f["direction"]
                     and f["size"] > 50]
    return max(client_frames, key=lambda f: f["size"]) if client_frames else None


# ── Text report ────────────────────────────────────────────────────────────────
def build_text_report(slim_frame: dict, nats_frame: dict) -> str:
    sep  = "═" * 72
    sep2 = "─" * 72
    lines = [
        sep,
        "  SLIM vs NATS — Security Comparison (wire-level capture)",
        f"  Plaintext under test: {PLAINTEXT!r}",
        sep,
        "",
        "VERDICT",
        sep2,
        f"  SLIM relay  → plaintext NOT present in {slim_frame['size']} bytes  ✓  (ciphertext only)",
        f"  NATS broker → plaintext FOUND verbatim in {nats_frame['size']} bytes  ✗  (unencrypted)",
        "",
        sep,
        "SLIM — CLIENT→RELAY payload frame  "
        f"({slim_frame['size']} bytes)  [encrypted / opaque]",
        sep2,
    ]
    lines += slim_frame["hex_lines"]
    lines += [
        "",
        "  → ASCII column: only dots (non-printable). No readable text.",
        "",
        sep,
        "NATS — CLIENT→BROKER publish frame  "
        f"({nats_frame['size']} bytes)  [plaintext exposed]",
        sep2,
    ]
    lines += nats_frame["hex_lines"]
    lines += [
        "",
        f"  → ASCII column: plaintext '{PLAINTEXT}' visible in full.",
        "",
        sep,
    ]
    return "\n".join(lines)


# ── Matplotlib figure ──────────────────────────────────────────────────────────
_MONO = {"fontfamily": "monospace", "fontsize": 7.5}
_BG   = "#0d1117"
_SLIM_ACCENT = "#238636"   # green
_NATS_ACCENT = "#da3633"   # red


def _hex_lines_to_display(hex_lines: list[str], max_lines: int = 22) -> list[str]:
    """Trim to max_lines; strip leading spaces for display."""
    return [ln.strip() for ln in hex_lines[:max_lines]]


def make_figure(slim_frame: dict, nats_frame: dict) -> None:
    fig, (ax_slim, ax_nats) = plt.subplots(
        1, 2, figsize=(16, 9),
        facecolor=_BG,
    )
    fig.suptitle(
        "Wire-level capture: SLIM relay vs NATS broker\n"
        f"Plaintext under test: '{PLAINTEXT}'",
        color="white", fontsize=12, fontweight="bold", y=0.97,
    )

    panels = [
        (ax_slim, slim_frame, _SLIM_ACCENT, "CLIENT→RELAY",
         "✓  Plaintext NOT FOUND  →  relay sees ciphertext only"),
        (ax_nats, nats_frame, _NATS_ACCENT, "CLIENT→BROKER",
         "✗  Plaintext FOUND verbatim  →  broker sees full message"),
    ]
    for ax, frame, accent, direction_label, verdict in panels:
        label = f"{('SLIM relay' if 'RELAY' in direction_label else 'NATS broker')}  —  {frame['size']} bytes  [{direction_label}]"
        ax.set_facecolor("#161b22")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

        # panel title
        ax.text(0.5, 0.97, label, transform=ax.transAxes,
                color=accent, fontsize=9, fontweight="bold",
                ha="center", va="top", **{k: v for k, v in _MONO.items()
                                          if k != "fontsize"})

        # verdict banner
        ax.text(0.5, 0.92, verdict, transform=ax.transAxes,
                color=accent, fontsize=8.5, fontweight="bold",
                ha="center", va="top",
                bbox=dict(boxstyle="round,pad=0.3", facecolor=accent + "22",
                          edgecolor=accent, linewidth=1.2))

        # hex dump lines
        display_lines = _hex_lines_to_display(frame["hex_lines"], max_lines=22)
        y_start = 0.87
        line_h  = 0.038
        for i, ln in enumerate(display_lines):
            y = y_start - i * line_h
            if y < 0.04:
                break
            # highlight rows that contain the plaintext in ASCII column
            if any(c in ln for c in ["SLIM_S", "ECURI", "DEMO_", "PLAIN", "TEXT_", "2026"]):
                ax.add_patch(FancyBboxPatch(
                    (0.01, y - 0.005), 0.98, line_h * 0.95,
                    boxstyle="square,pad=0", transform=ax.transAxes,
                    facecolor=_NATS_ACCENT + "33", edgecolor="none", zorder=0,
                ))
            ax.text(0.02, y, ln, transform=ax.transAxes,
                    color="#e6edf3", va="top", zorder=1, **_MONO)

        if len(frame["hex_lines"]) > 22:
            ax.text(0.5, 0.04,
                    f"… {len(frame['hex_lines']) - 22} more lines (see comparison_report.txt)",
                    transform=ax.transAxes, color="#8b949e",
                    fontsize=7, ha="center", va="bottom", style="italic")

    plt.tight_layout(rect=[0, 0, 1, 0.94])
    plt.savefig(REPORT_PNG, dpi=150, bbox_inches="tight", facecolor=_BG)
    plt.close()
    print(f"  Chart saved  →  {REPORT_PNG}")


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    print("Reading hex dumps …")
    slim_frames = parse_frames(SLIM_DUMP)
    nats_frames = parse_frames(NATS_DUMP)

    print(f"  SLIM: {len(slim_frames)} frames parsed")
    print(f"  NATS: {len(nats_frames)} frames parsed")

    # Pick the most illustrative frames
    slim_frame = largest_client_frame(slim_frames)
    nats_frame = find_payload_frame(nats_frames, PLAINTEXT.encode())

    if not slim_frame:
        raise RuntimeError("Could not find a large CLIENT→RELAY frame in SLIM dump")
    if not nats_frame:
        raise RuntimeError("Could not find the plaintext frame in NATS dump")

    print(f"  SLIM payload frame : {slim_frame['direction']}  {slim_frame['size']} bytes")
    print(f"  NATS payload frame : {nats_frame['direction']}  {nats_frame['size']} bytes")

    # Text report
    report = build_text_report(slim_frame, nats_frame)
    with open(REPORT_TXT, "w") as fh:
        fh.write(report)
    print(f"  Report saved →  {REPORT_TXT}")

    # Chart
    make_figure(slim_frame, nats_frame)

    # Print to stdout too
    print()
    print(report)


if __name__ == "__main__":
    main()
