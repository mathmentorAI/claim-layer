"""
Backward-compatibility bridge for complete_pipeline.py
"""
import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parent
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

from complete_pipeline import *

if __name__ == "__main__":
    main()
