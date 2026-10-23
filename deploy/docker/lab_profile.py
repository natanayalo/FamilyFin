"""Admission guard for synthetic acceptance code, separate from runtime checks."""
import sys


def require_lab_python():
    # Acceptance harnesses use assertions as test oracles. Never let -O produce
    # a report after removing those tests, including when imported by a wrapper.
    if sys.flags.optimize:
        raise RuntimeError("Synthetic acceptance workflows require Python without -O/PYTHONOPTIMIZE")
