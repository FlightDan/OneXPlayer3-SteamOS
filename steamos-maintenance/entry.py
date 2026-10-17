#!/usr/bin/python3
"""Explicit module path also works with Python's isolated (-I) mode."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oxp3_maintenance.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
