"""Exercise literal workflow blocks with closed-PATH native and PowerShell stubs."""

import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github/workflows/release.yml").read_text()
sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location(
    "native_source_version", ROOT / ".github/scripts/source_version.py"
)
source = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(source)


def step(name):
    """Extract the actual run block, never a separately maintained shell copy."""
    matches = re.findall(
        rf"^      - name: {re.escape(name)}\n"
        r"(?:(?!      - ).*\n)*?        run: \|\n"
        r"((?:          .*(?:\n|$)|[ \t]*\n)+)",
        WORKFLOW, re.MULTILINE,
    )
    if len(matches) != 1:
        raise AssertionError(f"Expected one shell block for {name!r}")
    return textwrap.dedent(matches[0])


STUB = r'''
import json
import os
from pathlib import Path
import plistlib
import re
import sys

tool = Path(sys.argv[0]).name
args = sys.argv[1:]
root = Path.cwd()
with open(os.environ["CALL_LOG"], "a") as log:
    log.write(json.dumps([tool, *args]) + "\n")
bundle = root / os.environ["TEST_BUNDLE"]
contents = bundle / "Contents"
mode = os.environ.get("BUILD_MODE", "complete")

if tool == "xcodebuild":
    for path in (
        contents / "MacOS/PRNG", contents / "Info.plist",
        contents / "Resources/English.lproj/InfoPlist.strings",
        contents / "_CodeSignature", bundle.parent / "Default",
        bundle.parent / "PRNG.build",
    ):
        assert not path.exists(), "stale output survived: " + str(path)
    if mode == "failed-build":
        sys.exit(70)
    if mode != "missing-binary":
        (contents / "MacOS").mkdir(parents=True, exist_ok=True)
        (contents / "MacOS/PRNG").write_bytes(b"rebuilt-universal")
    if mode != "missing-plist":
        data = plistlib.loads((root / "Info.plist").read_bytes())
        for key in ("CFBundleShortVersionString", "CFBundleVersion"):
            if key in data:
                data[key] = re.sub(
                    r"\$\([^)]+\)|\$\{[^}]+\}", os.environ["SOURCE_VERSION"], data[key]
                )
        if mode == "stale-plist":
            data["CFBundleShortVersionString"] = os.environ["STALE_VERSION"]
        if mode == "stale-build-version":
            data["CFBundleVersion"] = os.environ["STALE_VERSION"]
        (contents / "Info.plist").write_bytes(plistlib.dumps(data))
    if mode != "missing-localized":
        target = contents / "Resources/English.lproj/InfoPlist.strings"
        target.parent.mkdir(parents=True, exist_ok=True)
        data = (root / "English.lproj/InfoPlist.strings").read_bytes()
        if mode == "stale-localized":
            data = data.replace(
                os.environ["SOURCE_VERSION"].encode(), os.environ["STALE_VERSION"].encode()
            )
        target.write_bytes(data)
elif tool == "lipo":
    assert args == ["-info", os.environ["TEST_BUNDLE"] + "/Contents/MacOS/PRNG"]
    assert Path(args[-1]).is_file()
    print("Architectures in the fat file: " + os.environ.get("ARCHS", "arm64 x86_64"))
elif tool == "python3":
    assert args == [".github/scripts/source_version.py", "--verify-bundle",
                    os.environ["TEST_BUNDLE"]]
    os.execv(os.environ["REAL_PYTHON"], [os.environ["REAL_PYTHON"], *args])
elif tool == "security":
    assert args == ["find-identity", "-v", "-p", "codesigning", os.environ["KEYCHAIN_PATH"]]
    if os.environ.get("SIGN_MODE") != "missing-identity":
        print('1) FAKE "Developer ID Application: Fixture (TEST)"')
elif tool == "codesign":
    verify = args[0] == "--verify"
    if verify:
        assert args == ["--verify", "--deep", "--strict", "--verbose=2",
                        os.environ["BUNDLE_PATH"]]
    else:
        assert args == ["--verbose", "--deep", "--timestamp", "--force", "--options=runtime",
                        "--sign", "Developer ID Application: Fixture (TEST)",
                        os.environ["BUNDLE_PATH"]]
    if os.environ.get("SIGN_MODE") == ("verify" if verify else "sign"):
        sys.exit(76)
elif tool in ("ditto", "hdiutil"):
    assert Path(os.environ["BUNDLE_PATH"]).is_dir()
    if tool == "ditto":
        assert args[:-1] == ["-c", "-k", "--keepParent", os.environ["BUNDLE_PATH"]]
    else:
        assert args[:-1] == ["create", "-format", "UDBZ", "-volname", "PRNG",
                            "-srcfolder", os.environ["BUNDLE_PATH"]]
    if os.environ.get("PACKAGE_MODE") == tool:
        sys.exit(77)
    Path(args[-1]).write_bytes(b"stub archive")
elif tool == "xcrun":
    scenario = os.environ.get("NOTARY_MODE", "accepted")
    if args[:2] == ["notarytool", "submit"]:
        assert args[3:] == [
            "--keychain-profile", "notarytool-profile", "--keychain",
            os.environ["KEYCHAIN_PATH"], "--wait", "--output-format", "json"
        ]
        assert Path(args[2]).is_file()
        second = args[2].endswith(".dmg")
        if scenario in ("transport", "accepted-nonzero") or (
            scenario in ("second-transport", "second-accepted-nonzero") and second
        ):
            if scenario.endswith("accepted-nonzero"):
                print(json.dumps({"id": "misleading", "status": "Accepted"}))
            sys.exit(71)
        if scenario == "malformed":
            print("this is not JSON")
        elif scenario == "missing-status":
            print(json.dumps({"id": "missing-status"}))
        else:
            status = "Invalid" if (
                scenario == "invalid" or (scenario == "second-invalid" and second)
            ) else "Accepted"
            print(json.dumps({"id": "submission-dmg" if second else "submission-zip",
                              "status": status}))
    elif args[:2] == ["notarytool", "log"]:
        assert args[3:] == ["--keychain-profile", "notarytool-profile",
                            "--keychain", os.environ["KEYCHAIN_PATH"]]
        sys.exit(72)
    elif args[:2] == ["stapler", "staple"]:
        assert len(args) == 3 and args[2].endswith(".dmg")
        if scenario == "staple":
            sys.exit(73)
    else:
        raise AssertionError(args)
elif tool == "plutil":
    assert args[0] == "-extract" and args[2:] == ["raw", "-o", "-", "-"]
    try:
        value = json.load(sys.stdin)[args[1]]
        assert isinstance(value, str)
        print(value)
    except (ValueError, KeyError, AssertionError):
        sys.exit(74)
else:
    raise AssertionError("Unexpected tool: " + tool)
'''


class NativeShellTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".native-tests-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for path in (*source.SOURCE_PATHS, Path(".github/scripts/source_version.py")):
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / path, target)
        self.version = source.read(self.root)
        major, minor, patch = map(int, self.version.split("."))
        self.stale = f"{major}.{minor}.{patch + 1}"
        self.relative_bundle = "test/Plugins/PRNG.bundle"
        self.bundle = self.root / self.relative_bundle
        self.contents = self.bundle / "Contents"
        self.log = self.root / "calls.jsonl"
        self.env_file = self.root / "github-env"
        self.env_file.touch()
        self.bin = self.root / "stub-bin"
        self.bin.mkdir()
        for name in ("xcodebuild", "lipo", "python3", "ditto", "hdiutil", "xcrun", "plutil",
                     "security", "codesign"):
            executable = self.bin / name
            executable.write_text(f"#!{sys.executable}\n" + textwrap.dedent(STUB))
            executable.chmod(0o755)
        # No fallback to installed Apple/native executables.
        for name in ("rm", "ls", "grep", "head", "sed", "mkdir", "cp"):
            executable = shutil.which(name)
            self.assertIsNotNone(executable)
            (self.bin / name).symlink_to(executable)
        self.env = {
            "PATH": str(self.bin), "CALL_LOG": str(self.log),
            "REAL_PYTHON": sys.executable, "PYTHONDONTWRITEBYTECODE": "1",
            "SOURCE_VERSION": self.version, "STALE_VERSION": self.stale,
            "TEST_BUNDLE": self.relative_bundle, "BUNDLE_PATH": self.relative_bundle,
            "KEYCHAIN_PATH": str(self.root / "fake.keychain-db"),
            "GITHUB_ENV": str(self.env_file),
        }
        self.preserved = {}
        for relative in (
            "QuickLook/Thumbnail.png", "Windows64/PRNG.4DX",
            "Resources/manifest.json", "Resources/constants.xlf",
            "Resources/Documentation/index.html",
        ):
            data = (ROOT / self.relative_bundle / "Contents" / relative).read_bytes()
            self.write(relative, data)
            self.preserved[relative] = data
        for relative in (
            "MacOS/Dependency.dylib",
            "Frameworks/Dependency.framework/Versions/A/Dependency",
            "Frameworks/Dependency.framework/Versions/A/Resources/dependency.dat",
        ):
            self.write(relative, b"preserved dependency")
            self.preserved[relative] = b"preserved dependency"
        (self.contents / "Frameworks/Dependency.framework/Versions/Current").symlink_to("A")
        for relative in (
            "MacOS/PRNG", "Info.plist", "Resources/English.lproj/InfoPlist.strings",
            "_CodeSignature/CodeResources",
        ):
            self.write(relative, b"stale build output")
        for relative in ("Default/stale", "PRNG.build/stale"):
            path = self.bundle.parent / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"stale intermediate")

    def write(self, relative, data):
        path = self.contents / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def run_step(self, name, prefix="", **env):
        script = step(name)
        values = {
            "env.PRODUCT_NAME": "PRNG", "env.BASE_DIR": "test",
            "env.MACOS_DEPLOYMENT_TARGET": "11.0",
            "needs.version.outputs.version": self.version,
        }
        for key, value in values.items():
            script = script.replace("${{ " + key + " }}", value)
        self.assertNotIn("${{", script)
        return subprocess.run(
            ["/bin/bash", "-c", prefix + "\n" + script],
            cwd=self.root, env={**self.env, **env}, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def calls(self, tool):
        if not self.log.exists():
            return []
        return [call[1:] for line in self.log.read_text().splitlines()
                if (call := json.loads(line))[0] == tool]

    def build(self, **env):
        self.assert_ok(self.run_step("build macOS plugin (universal)", **env))

    def test_fresh_universal_build_preserves_resources_and_dependencies(self):
        self.build()
        self.assertEqual((self.contents / "MacOS/PRNG").read_bytes(), b"rebuilt-universal")
        for relative, data in self.preserved.items():
            self.assertEqual((self.contents / relative).read_bytes(), data, relative)
        link = self.contents / "Frameworks/Dependency.framework/Versions/Current"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.readlink(), Path("A"))
        for path in (self.contents / "_CodeSignature", self.bundle.parent / "Default",
                     self.bundle.parent / "PRNG.build"):
            self.assertFalse(path.exists())
        source.verify_bundle(self.bundle, self.root)
        self.assert_ok(self.run_step("verify universal binary"))
        self.assertEqual(len(self.calls("python3")), 1)
        self.assertEqual(len(self.calls("lipo")), 1)
        self.assertEqual(self.calls("xcodebuild"), [[
            "-project", "PRNG.xcodeproj", "-target", "PRNG",
            "-configuration", "Default", "ARCHS=arm64 x86_64", "ONLY_ACTIVE_ARCH=NO",
            "MACOSX_DEPLOYMENT_TARGET=11.0", "CODE_SIGNING_ALLOWED=NO",
            f"CONFIGURATION_BUILD_DIR={self.root}/test/Plugins", "build",
        ]])

    def test_cleanup_error_blocks_build(self):
        result = self.run_step(
            "build macOS plugin (universal)",
            prefix="rm() { echo 'fixture cleanup failure' >&2; return 79; }",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fixture cleanup failure", result.stderr)
        self.assertEqual(self.calls("xcodebuild"), [])
        self.assertEqual((self.contents / "MacOS/PRNG").read_bytes(), b"stale build output")

    def test_failed_build_is_fatal(self):
        result = self.run_step("build macOS plugin (universal)", BUILD_MODE="failed-build")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.calls("xcodebuild")), 1)

    def test_missing_rebuilt_binary_is_rejected(self):
        self.build(BUILD_MODE="missing-binary")
        self.assertFalse((self.contents / "MacOS/PRNG").exists())
        result = self.run_step("verify universal binary")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Expected binary not found", result.stdout)
        self.assertEqual(self.calls("lipo"), [])
        self.assertEqual(self.calls("python3"), [])

    def test_missing_rebuilt_metadata_is_rejected(self):
        for mode, relative in (
            ("missing-plist", "Info.plist"),
            ("missing-localized", "Resources/English.lproj/InfoPlist.strings"),
        ):
            with self.subTest(mode=mode):
                self.build(BUILD_MODE=mode)
                self.assertFalse((self.contents / relative).exists())
                result = self.run_step("verify universal binary")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("FileNotFoundError", result.stderr)

    def test_stale_rebuilt_metadata_is_rejected(self):
        for mode in ("stale-plist", "stale-build-version", "stale-localized"):
            with self.subTest(mode=mode):
                self.build(BUILD_MODE=mode)
                result = self.run_step("verify universal binary")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("differs from selected source", result.stderr)

    def test_each_architecture_requires_an_exact_token(self):
        self.build()
        for architectures in (
            "arm64", "x86_64", "arm64e x86_64", "arm64 x86_64h",
            "notarm64 x86_64", "arm64 x86_64_extra",
        ):
            with self.subTest(architectures=architectures):
                self.assertNotEqual(
                    self.run_step("verify universal binary", ARCHS=architectures).returncode, 0
                )
        self.assertEqual(self.calls("python3"), [])

    def test_no_invented_slice_count_or_i386_restriction(self):
        self.build()
        self.assert_ok(self.run_step("verify universal binary", ARCHS="arm64 x86_64 i386"))
        self.assertEqual(len(self.calls("python3")), 1)

    def test_exact_windows_artifact_merge_not_recursive_first_match(self):
        artifact = self.root / "winbuild/PRNG.4DX"
        artifact.parent.mkdir()
        nested = artifact.parent / "stale/PRNG.4DX"
        nested.parent.mkdir()
        nested.write_bytes(b"stale recursive match")
        for data in (None, b""):
            if data is not None:
                artifact.write_bytes(data)
            result = self.run_step("merge Windows binaries into the bundle")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exact artifact path", result.stdout)
            self.assertEqual(self.env_file.read_text(), "")
        artifact.write_bytes(b"fresh selected-source Windows binary")
        self.assert_ok(self.run_step("merge Windows binaries into the bundle"))
        self.assertEqual((self.contents / "Windows64/PRNG.4DX").read_bytes(),
                         artifact.read_bytes())
        self.assertEqual(self.env_file.read_text(), f"BUNDLE_PATH={self.relative_bundle}\n")

    def test_signing_requires_identity_sign_and_strict_verification(self):
        self.assert_ok(self.run_step("codesign"))
        self.assertEqual(len(self.calls("codesign")), 2)
        for scenario, expected in (("missing-identity", 0), ("sign", 1), ("verify", 2)):
            with self.subTest(scenario=scenario):
                self.log.unlink()
                result = self.run_step("codesign", SIGN_MODE=scenario)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(len(self.calls("codesign")), expected)
                self.assertEqual(self.calls("ditto"), [])
                self.assertEqual(self.calls("xcrun"), [])

    def compiled_localization(self):
        localized = source.text(self.root / source.LOCALIZED)
        values = dict(re.findall(r'(?m)^(\w+)\s*=\s*"([^"]*)";', localized))
        self.assertEqual(values["CFBundleShortVersionString"], self.version)
        self.assertIn(self.version, values["CFBundleGetInfoString"])
        return values

    def test_binary_and_xml_built_metadata_are_verified(self):
        self.build()
        values = self.compiled_localization()
        plist = plistlib.loads((self.contents / "Info.plist").read_bytes())
        for serialization in (plistlib.FMT_BINARY, plistlib.FMT_XML):
            with self.subTest(serialization=serialization):
                self.write("Info.plist", plistlib.dumps(plist, fmt=serialization))
                self.write("Resources/English.lproj/InfoPlist.strings",
                           plistlib.dumps(values, fmt=serialization))
                self.assert_ok(self.run_step("verify universal binary"))
        self.assertEqual(len(self.calls("python3")), 2)

    def test_stale_compiled_localization_is_rejected(self):
        self.build()
        values = self.compiled_localization()
        for serialization in (plistlib.FMT_BINARY, plistlib.FMT_XML):
            for key in ("CFBundleShortVersionString", "CFBundleGetInfoString"):
                with self.subTest(serialization=serialization, key=key):
                    stale = {**values, key: values[key].replace(self.version, self.stale)}
                    self.write("Resources/English.lproj/InfoPlist.strings",
                               plistlib.dumps(stale, fmt=serialization))
                    result = self.run_step("verify universal binary")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("Built localized display differs from selected source",
                                  result.stderr)
        self.assertEqual(len(self.calls("python3")), 4)

    def test_xcode_utf16_localization_is_verified(self):
        self.build()
        original = source.text(self.root / source.LOCALIZED)
        for encoding in ("utf-16", "utf-16-be"):
            with self.subTest(encoding=encoding):
                prefix = b"\xfe\xff" if encoding == "utf-16-be" else b""
                for stale in (False, True):
                    text = original.replace(self.version, self.stale) if stale else original
                    self.write("Resources/English.lproj/InfoPlist.strings",
                               prefix + text.encode(encoding))
                    result = self.run_step("verify universal binary")
                    if stale:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("differs from selected source", result.stderr)
                    else:
                        self.assert_ok(result)

    def assert_package_calls(self, submissions, staple=False, diagnostic=None):
        zip_path = f"PRNG-{self.version}.zip"
        dmg_path = f"PRNG-{self.version}.dmg"
        self.assertEqual(len(self.calls("ditto")), 1)
        self.assertEqual(len(self.calls("hdiutil")), 1)
        calls = self.calls("xcrun")
        self.assertEqual(
            [call[2] for call in calls if call[:2] == ["notarytool", "submit"]],
            [zip_path, dmg_path][:submissions],
        )
        self.assertEqual(
            [call for call in calls if call[:2] == ["stapler", "staple"]],
            [["stapler", "staple", dmg_path]] if staple else [],
        )
        self.assertEqual(
            [call[2] for call in calls if call[:2] == ["notarytool", "log"]],
            [diagnostic] if diagnostic else [],
        )
        if staple:
            self.assertEqual(calls[-1], ["stapler", "staple", dmg_path])

    def test_both_accepted_submissions_then_staple_publish_paths(self):
        self.assert_ok(self.run_step("package, notarize & staple"))
        self.assert_package_calls(2, staple=True)
        self.assertEqual(self.env_file.read_text().splitlines(), [
            f"ZIP_PATH=PRNG-{self.version}.zip", f"DMG_PATH=PRNG-{self.version}.dmg",
        ])

    def test_invalid_zero_exit_status_blocks_staple_and_publication(self):
        result = self.run_step("package, notarize & staple", NOTARY_MODE="invalid")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("returned 'Invalid'", result.stdout)
        self.assert_package_calls(1, diagnostic="submission-zip")
        self.assertEqual(self.env_file.read_text(), "")

    def test_transport_failure_blocks_staple_and_publication(self):
        result = self.run_step("package, notarize & staple", NOTARY_MODE="transport")
        self.assertNotEqual(result.returncode, 0)
        self.assert_package_calls(1)
        self.assertEqual(self.env_file.read_text(), "")

    def test_nonzero_command_rejects_even_accepted_payload(self):
        result = self.run_step("package, notarize & staple", NOTARY_MODE="accepted-nonzero")
        self.assertNotEqual(result.returncode, 0)
        self.assert_package_calls(1)
        self.assertEqual(self.calls("plutil"), [])
        self.assertEqual(self.env_file.read_text(), "")

    def test_malformed_or_incomplete_json_blocks_staple_and_publication(self):
        for mode in ("malformed", "missing-status"):
            with self.subTest(mode=mode):
                self.log.unlink(missing_ok=True)
                result = self.run_step("package, notarize & staple", NOTARY_MODE=mode)
                self.assertNotEqual(result.returncode, 0)
                self.assert_package_calls(1)
                self.assertTrue(self.calls("plutil"))
                self.assertEqual(self.env_file.read_text(), "")

    def test_second_submission_failure_blocks_staple_and_publication(self):
        for mode, diagnostic in (
            ("second-transport", None), ("second-invalid", "submission-dmg"),
            ("second-accepted-nonzero", None),
        ):
            with self.subTest(mode=mode):
                self.log.unlink(missing_ok=True)
                result = self.run_step("package, notarize & staple", NOTARY_MODE=mode)
                self.assertNotEqual(result.returncode, 0)
                self.assert_package_calls(2, diagnostic=diagnostic)
                self.assertEqual(self.env_file.read_text(), "")

    def test_staple_failure_blocks_publication(self):
        result = self.run_step("package, notarize & staple", NOTARY_MODE="staple")
        self.assertNotEqual(result.returncode, 0)
        self.assert_package_calls(2, staple=True)
        self.assertEqual(self.env_file.read_text(), "")

    def test_packaging_failure_blocks_notarization_and_publication(self):
        for tool in ("ditto", "hdiutil"):
            with self.subTest(tool=tool):
                self.log.unlink(missing_ok=True)
                result = self.run_step("package, notarize & staple", PACKAGE_MODE=tool)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.calls("xcrun"), [])
                self.assertEqual(self.env_file.read_text(), "")


class NativeConfigurationTests(unittest.TestCase):
    def test_manual_immutable_source_and_serial_publication(self):
        self.assertRegex(WORKFLOW, r"(?m)^name: Build$")
        trigger = WORKFLOW.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertEqual(trigger.strip(), "workflow_dispatch:")
        self.assertIn("group: release-publication\n  cancel-in-progress: false", WORKFLOW)
        self.assertEqual(WORKFLOW.count("uses: actions/checkout@v4"), 3)
        self.assertEqual(WORKFLOW.count("ref: ${{ github.sha }}"), 3)
        self.assertIn('release.py check --sha "$SELECTED_SHA"',
                      step("validate source and publication availability"))
        self.assertIn('release.py publish --sha "$SELECTED_SHA" "$ZIP_PATH" "$DMG_PATH"',
                      step("create GitHub Release"))
        self.assertEqual(WORKFLOW.count("GH_TOKEN: ${{ github.token }}"), 2)
        self.assertEqual(WORKFLOW.count("SELECTED_SHA: ${{ github.sha }}"), 2)
        self.assertIn("tag: ${{ steps.set.outputs.tag }}", WORKFLOW)
        self.assertIn("version: ${{ steps.set.outputs.version }}", WORKFLOW)
        self.assertIn("needs: version", WORKFLOW)
        self.assertIn("needs: [version, build-windows]", WORKFLOW)
        names = [
            "validate source and publication availability", "build x64",
            "build macOS plugin (universal)", "verify universal binary",
            "merge Windows binaries into the bundle", "codesign",
            "package, notarize & staple", "create GitHub Release",
        ]
        positions = [WORKFLOW.index(f"- name: {name}\n") for name in names]
        self.assertEqual(positions, sorted(positions))
        self.assertLess(WORKFLOW.index("--verify-bundle"), WORKFLOW.index("- name: codesign"))
        self.assertNotIn("always()", WORKFLOW)
        self.assertNotIn("continue-on-error:", WORKFLOW)
        self.assertNotIn("softprops/", WORKFLOW)

    def test_windows_exact_output_matches_release_x64_project(self):
        project = ET.parse(ROOT / "PRNG.vcxproj")
        ns = {"m": "http://schemas.microsoft.com/developer/msbuild/2003"}
        condition = "'$(Configuration)|$(Platform)'=='Release|x64'"
        outdirs = [node.text for node in project.findall(".//m:OutDir", ns)
                   if node.get("Condition") == condition]
        extensions = [node.text for node in project.findall(".//m:TargetExt", ns)
                      if node.get("Condition") == condition]
        self.assertEqual(len(outdirs), 1)
        self.assertEqual(extensions, [".4DX"])
        actual = (outdirs[0].replace("$(ProjectDir)", "")
                  .replace("$(ProjectName)", "PRNG").replace("\\", "/")
                  + "PRNG" + extensions[0])
        normalize = step("normalize windows output to canonical case")
        match = re.search(r'^\$source = "([^"]+)"$', normalize, re.MULTILINE)
        self.assertIsNotNone(match)
        expected = match[1].replace("$base", "test").replace("$product", "PRNG")
        self.assertEqual(actual, expected)
        canonical = "test/Plugins/PRNG.bundle/Contents/Windows64/PRNG.4DX"
        self.assertEqual(actual.casefold(), canonical.casefold())
        self.assertIn("Test-Path -LiteralPath $source -PathType Leaf", normalize)
        self.assertIn("throw ", normalize)
        self.assertNotIn("-Recurse", normalize)
        self.assertIn("$sourceResolved -ieq $destResolved", normalize)
        self.assertIn("Copy-Item -LiteralPath $source $destination -Force", normalize)

    def test_windows_fresh_invalidation_and_original_platform_settings(self):
        clean = step("clean stale outputs")
        for path in ('"$base/plugins/$product.bundle/contents/windows64/$product.4DX"',
                     '"$base/Plugins/Default"', '"Objs"'):
            self.assertIn(path, clean)
        self.assertIn('if (Test-Path -LiteralPath $path)', clean)
        self.assertIn('Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction Stop', clean)
        self.assertNotIn('SilentlyContinue', clean)
        self.assertLess(WORKFLOW.index("- name: clean stale outputs"),
                        WORKFLOW.index("- name: build x64"))
        self.assertIn("/p:Configuration=Release /p:Platform=x64", step("build x64"))
        self.assertIn("/p:PlatformToolset=v143 /p:WindowsTargetPlatformVersion=10.0",
                      step("build x64"))
        project = ET.parse(ROOT / "PRNG.vcxproj")
        ns = {"m": "http://schemas.microsoft.com/developer/msbuild/2003"}
        self.assertEqual(
            {node.get("Include") for node in project.findall(".//m:ProjectConfiguration", ns)},
            {"Debug|Win32", "Debug|x64", "Release|Win32", "Release|x64"},
        )
        self.assertEqual({node.text for node in project.findall(".//m:PlatformToolset", ns)},
                         {"v143"})

    def test_original_macos_settings_and_release_secrets(self):
        project = (ROOT / source.PROJECT).read_text()
        for setting, value, count in (
            ("SDKROOT", "macosx", 6), ("MACOSX_DEPLOYMENT_TARGET", "11.5", 3),
            ("MACOSX_DEPLOYMENT_TARGET", "10.13", 3),
            ("CLANG_CXX_LIBRARY", '"libc++"', 3),
            ("INFOPLIST_FILE", "Info.plist", 3), ("WRAPPER_EXTENSION", "bundle", 3),
        ):
            self.assertEqual(len(re.findall(
                rf"(?m)^\s*{setting} = {re.escape(value)};", project
            )), count)
        for name in ("Default", "Development", "Deployment"):
            self.assertEqual(len(re.findall(rf"(?m)^\s*name = {name};", project)), 2)
        self.assertIn("English.lproj/InfoPlist.strings", project)
        for resource in ("manifest.json in CopyFiles", "constants.xlf in CopyFiles",
                         "Cocoa.framework in Frameworks", "InfoPlist.strings in Resources"):
            self.assertIn(resource, project)
        self.assertEqual(set(re.findall(r"\$\{\{ secrets\.([A-Z_]+) \}\}", WORKFLOW)), {
            "APPLE_DEVELOPER_ID_CERTIFICATE", "APPLE_DEVELOPER_ID_CERTIFICATE_PASSWORD",
            "KEYCHAIN_PASSWORD", "NOTARYTOOL_APPLE_ID", "NOTARYTOOL_TEAM_ID",
            "NOTARYTOOL_PASSWORD",
        })
        self.assertIn("MACOS_DEPLOYMENT_TARGET: '11.0'", WORKFLOW)
        self.assertIn("runs-on: windows-latest", WORKFLOW)
        self.assertIn("runs-on: macos-latest", WORKFLOW)


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell required for Windows shell harness")
class WindowsShellTests(unittest.TestCase):
    def setUp(self):
        self.pwsh = shutil.which("pwsh")
        self.temp = tempfile.TemporaryDirectory(prefix=".windows-tests-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "empty-path"
        self.bin.mkdir()
        self.binary = self.root / "test/plugins/PRNG.bundle/contents/windows64/PRNG.4DX"
        self.binary.parent.mkdir(parents=True)

    def run_step(self, name, prefix=""):
        script = step(name)
        for key, value in (("PRODUCT_NAME", "PRNG"), ("BASE_DIR", "test")):
            script = script.replace("${{ env." + key + " }}", value)
        self.assertNotIn("${{", script)
        return subprocess.run(
            [self.pwsh, "-NoLogo", "-NoProfile", "-NonInteractive",
             "-Command", prefix + "\n" + script], cwd=self.root, text=True,
            env={**os.environ, "PATH": str(self.bin)},
            capture_output=True, timeout=30,
        )

    def test_clean_invalidates_binary_only_and_preserves_resources(self):
        self.binary.write_bytes(b"stale Windows binary")
        resources = {
            "QuickLook/Thumbnail.png": b"resource",
            "MacOS/PRNG": b"committed mac binary",
            "Resources/manifest.json": b"manifest",
        }
        for relative, data in resources.items():
            path = self.binary.parent.parent / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        for relative in ("test/Plugins/Default/stale", "Objs/stale"):
            path = self.root / relative
            path.parent.mkdir(parents=True)
            path.write_bytes(b"stale intermediate")
        for _ in range(2):
            result = self.run_step("clean stale outputs")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.binary.exists())
        self.assertFalse((self.root / "test/Plugins/Default").exists())
        self.assertFalse((self.root / "Objs").exists())
        for relative, data in resources.items():
            self.assertEqual((self.binary.parent.parent / relative).read_bytes(), data)

    def test_exact_output_required_then_normalized_without_self_copy(self):
        stale = self.root / "stale/Plugins/PRNG.4DX"
        stale.parent.mkdir(parents=True)
        stale.write_bytes(b"wrong recursive match")
        result = self.run_step("normalize windows output to canonical case")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exact MSBuild output", result.stderr)
        self.binary.write_bytes(b"rebuilt Windows binary")
        result = self.run_step("normalize windows output to canonical case")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        canonical = self.root / "test/Plugins/PRNG.bundle/Contents/Windows64/PRNG.4DX"
        self.assertEqual(canonical.read_bytes(), b"rebuilt Windows binary")
        if self.binary.samefile(canonical):
            self.assertIn("skipping copy", result.stdout)

    def test_cleanup_error_is_fatal_and_preserves_binary(self):
        self.binary.write_bytes(b"stale Windows binary")
        result = self.run_step(
            "clean stale outputs",
            "function Remove-Item { Write-Error 'fixture cleanup failure' }",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fixture cleanup failure", result.stderr)
        self.assertEqual(self.binary.read_bytes(), b"stale Windows binary")

    def test_canonical_directory_failure_is_fatal(self):
        self.binary.write_bytes(b"rebuilt Windows binary")
        result = self.run_step(
            "normalize windows output to canonical case",
            "function New-Item { Write-Error 'fixture directory failure' }",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fixture directory failure", result.stderr)


if __name__ == "__main__":
    unittest.main()
