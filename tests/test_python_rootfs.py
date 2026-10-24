"""Dependency parsing must not silently lose an unresolved shared library."""
import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/docker"))
rootfs = importlib.import_module("python_rootfs")


class PythonRootfs(unittest.TestCase):
    def test_ldd_resolved_missing_and_virtual_entries(self):
        paths, missing = rootfs.dependencies("""
 linux-vdso.so.1 (0x123)
 libpython3.12.so.1.0 => /usr/local/lib/libpython3.12.so.1.0 (0x456)
 libssl.so.3 => /lib/aarch64-linux-gnu/libssl.so.3 (0x789)
 libtk8.6.so => not found
 /lib/ld-linux-aarch64.so.1 (0xabc)
""")
        self.assertEqual(paths, [Path("/usr/local/lib/libpython3.12.so.1.0"),
                                 Path("/lib/aarch64-linux-gnu/libssl.so.3")])
        self.assertEqual(missing, ["libtk8.6.so"])

    def test_usrmerge_normalizes_library_aliases(self):
        self.assertEqual(rootfs.canonical_library(Path("/lib/x86_64-linux-gnu/libc.so.6")),
                         Path("/usr/lib/x86_64-linux-gnu/libc.so.6"))
        self.assertEqual(rootfs.canonical_library(Path("/lib64/ld-linux-x86-64.so.2")),
                         Path("/usr/lib64/ld-linux-x86-64.so.2"))
        self.assertEqual(rootfs.canonical_library(Path("/usr/local/lib/libpython.so")),
                         Path("/usr/local/lib/libpython.so"))


if __name__ == "__main__":
    unittest.main()
