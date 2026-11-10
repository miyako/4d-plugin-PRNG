"""Compile actual native sources and the complete SDK; mock only Call4D.

PRNG_OWNERSHIP_SOURCE_REF selects an immutable Git revision for negative controls.
No project build, plugin packaging, signing, or release workflow is invoked.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(sys.platform == "darwin", "native macOS compiler/frameworks required")
class OwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="prng-ownership-")
        cls.addClassCleanup(cls.temp.cleanup)
        work = Path(cls.temp.name)
        source = ROOT
        ref = os.environ.get("PRNG_OWNERSHIP_SOURCE_REF")
        if ref:
            source = work / "source"
            files = subprocess.check_output(
                ["git", "ls-tree", "-r", "--name-only", ref, "--",
                 "4D Plugin API", "4DPlugin.cpp", "4DPlugin.h"], cwd=ROOT, text=True,
            ).splitlines()
            for name in files:
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(subprocess.check_output(
                    ["git", "show", f"{ref}:{name}"], cwd=ROOT,
                ))
        compiler = shutil.which("clang++")
        if not compiler:
            raise RuntimeError("clang++ is required for native ownership regression")
        sdk = source / "4D Plugin API"
        cls.binary = work / "ownership"
        command = [
            compiler, "-x", "objective-c++", "-std=c++11", "-g", "-O1",
            "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
            "-Wno-deprecated-declarations", "-Wno-parentheses",
            "-include", "Carbon/Carbon.h", "-I", str(sdk),
            "-I", str(sdk / "Classes"), "-I", str(source),
            str(ROOT / ".github/tests/native_ownership.cpp"),
            str(source / "4DPlugin.cpp"), str(sdk / "4DPluginAPI.c"),
            *map(str, sorted((sdk / "Classes").glob("*.cpp"))),
            "-framework", "Cocoa", "-framework", "Carbon", "-o", str(cls.binary),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def run_case(self, case):
        for empty in ("allocated", "null"):
            with self.subTest(case=case, empty=empty):
                result = subprocess.run(
                    [str(self.binary), case, empty], capture_output=True, text=True,
                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0",
                         "UBSAN_OPTIONS": "halt_on_error=1"}, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(f"PASS {case} {empty}", result.stdout)

    def test_file_path_single_owner(self):
        self.run_case("file-path")

    def test_conversion_bytes_not_units(self):
        self.run_case("conversion")

    def test_picture_argument_reference_balances(self):
        self.run_case("picture-arguments")

    def test_picture_bytes_temporary_owner(self):
        self.run_case("picture-bytes")

    def test_borrowed_text_and_conditional_array_transfer(self):
        self.run_case("text")

    def test_scalar_command_unchanged(self):
        self.run_case("command")


if __name__ == "__main__":
    unittest.main()
