#!/usr/bin/env python3
"""Run isolated Atlas agent tasks; fixture is the safe, network-free default."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.agent.evaluation import main

if __name__ == "__main__":
    raise SystemExit(main())
