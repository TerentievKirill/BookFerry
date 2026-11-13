#!/usr/bin/env python3
"""Restore SDK-internal symlinks that 7z may skip during extraction."""
from pathlib import Path
import subprocess
import sys

archive = Path(sys.argv[1]).resolve()
root = Path(sys.argv[2]).resolve()
listing = subprocess.check_output(["7z", "l", "-slt", str(archive)], text=True)
entries = []
for block in listing.split("\n\n"):
    fields = dict(line.split(" = ", 1) for line in block.splitlines() if " = " in line)
    if not fields.get("Attributes", "").startswith("A l"):
        continue
    location = root / fields["Path"]
    if not location.resolve().is_relative_to(root):
        raise SystemExit(f"Unsafe SDK archive location: {location}")
    if not location.is_symlink() and (
        not location.exists() or (location.is_file() and location.stat().st_size == 0)
    ):
        entries.append(fields)

if entries:
    names = root / ".sdk-links.txt"
    names.write_text("\n".join(e["Path"] for e in entries) + "\n")
    try:
        data = subprocess.check_output(["7z", "x", "-so", str(archive), f"-i@{names}"])
    finally:
        names.unlink(missing_ok=True)
    offset = 0
    for entry in entries:
        length = int(entry["Size"])
        destination = root / entry["Path"]
        target = data[offset:offset + length].decode()
        offset += length
        if not (destination.parent / target).resolve().is_relative_to(root):
            raise SystemExit(f"Unsafe SDK symlink: {destination} -> {target}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.unlink(missing_ok=True)
        destination.symlink_to(target)
    if offset != len(data):
        raise SystemExit("Unexpected SDK link payload length")
print(f"SDK symlinks checked; restored {len(entries)}")
