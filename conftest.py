"""
Make the project root importable so tests can do `from tools import ...`
and `from utils.data_loader import ...` regardless of where pytest is invoked.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
