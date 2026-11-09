"""Offline publication tests: no GitHub calls or mutations."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import call, patch
from uuid import uuid4

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".github/scripts"))
SPEC = importlib.util.spec_from_file_location("publication_release", ROOT / ".github/scripts/release.py")
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)
SHA = "a" * 40
TAG = "v1.2.3"
REPO = "owner/repo"


def entry(tag="v0.0.1", draft=False):
    return {"id": 9, "tag_name": tag, "draft": draft, "prerelease": False}


class AvailabilityTests(unittest.TestCase):
    def test_all_pages_and_drafts(self):
        for draft in (True, False):
            with self.subTest(draft=draft), \
                    patch.object(release, "remote_ref", return_value=None), \
                    patch.object(release, "api", side_effect=[
                        [entry()] * 100, [entry(TAG, draft)],
                    ]) as api:
                with self.assertRaisesRegex(ValueError, "draft or published"):
                    release.available(REPO, TAG)
                self.assertEqual(api.call_args_list, [
                    call(f"repos/{REPO}/releases?per_page=100&page=1"),
                    call(f"repos/{REPO}/releases?per_page=100&page=2"),
                ])
        with patch.object(release, "remote_ref", return_value=None), \
                patch.object(release, "api", side_effect=[
                    [entry()] * 100, [entry()] * 100, [],
                ]) as api:
            release.available(REPO, TAG)
            self.assertEqual(api.call_count, 3)

    def test_every_page_errors_and_malformed_fail_closed(self):
        errors = [
            *(subprocess.CalledProcessError(1, ["gh", str(code)])
              for code in (401, 403, 404, 422, 500)),
            OSError("network"), json.JSONDecodeError("bad", "?", 0),
        ]
        malformed = [
            {}, None, "[]", [None], [{}], [dict(entry(), id=True)],
            [dict(entry(), id=0)], [dict(entry(), id=-1)],
            [dict(entry(), tag_name=None)], [dict(entry(), tag_name="")],
            [dict(entry(), draft=0)], [dict(entry(), prerelease="false")],
            [entry()] * 101,
        ]
        for page in (1, 2, 3):
            for response in errors + malformed:
                with self.subTest(page=page, response=response), \
                        patch.object(release, "remote_ref", return_value=None), \
                        patch.object(release, "api", side_effect=(
                            [[entry()] * 100] * (page - 1) + [response]
                        )) as api:
                    with self.assertRaises((ValueError, OSError, subprocess.CalledProcessError)):
                        release.available(REPO, TAG)
                    self.assertEqual(api.call_count, page)

    def test_exact_remote_tag_and_malformed_remote(self):
        ref = f"refs/tags/{TAG}"
        with patch.object(release, "run", return_value=f"{SHA}\t{ref}") as run:
            self.assertEqual(release.remote_ref(ref), SHA)
            run.assert_called_once_with("git", "ls-remote", "--refs", "origin", ref)
        for output in ("invalid", f"{SHA}\t{ref}-other", f"bad\t{ref}",
                       f"{SHA}\t{ref}\n{SHA}\t{ref}"):
            with self.subTest(output=output), patch.object(release, "run", return_value=output):
                with self.assertRaises(ValueError):
                    release.remote_ref(ref)
        with patch.object(release, "remote_ref", return_value=SHA), \
                patch.object(release, "api") as api:
            with self.assertRaisesRegex(ValueError, "already exists"):
                release.available(REPO, TAG)
            api.assert_not_called()
        with patch.object(release, "run", side_effect=OSError("network")), \
                patch.object(release, "api") as api:
            with self.assertRaises(OSError):
                release.available(REPO, TAG)
            api.assert_not_called()

    def test_transport_explicit_methods_no_retry(self):
        with patch.object(release, "run", return_value="[]") as run:
            release.api("repos/o/r/releases?per_page=100&page=2")
            run.assert_called_once_with(
                "gh", "api", "--method", "GET",
                "repos/o/r/releases?per_page=100&page=2", input=None,
            )
            payload = {"ref": f"refs/tags/{TAG}", "sha": SHA}
            release.api("repos/o/r/git/refs", payload)
            self.assertIn("POST", run.call_args.args)
            self.assertEqual(json.loads(run.call_args.kwargs["input"]), payload)
            release.api("https://uploads.github.com/repos/o/r/releases/123/assets",
                        asset=Path("asset.zip"))
            self.assertEqual(run.call_args.args[-4:], (
                "--header", "Content-Type: application/octet-stream", "--input", "asset.zip",
            ))
        with patch.object(release, "run", side_effect=subprocess.CalledProcessError(1, "gh")) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                release.api("repos/o/r/releases")
            self.assertEqual(run.call_count, 1)

    def test_context_validates_selected_checkout_repository_and_source(self):
        with patch.dict(os.environ, GITHUB_REPOSITORY=REPO), \
                patch.object(release, "run", side_effect=[SHA, ""]), \
                patch.object(release, "read", return_value="1.2.3"):
            self.assertEqual(release.context(SHA), (REPO, "1.2.3", TAG))
        for sha in ("main", SHA.upper(), "a" * 39):
            with self.subTest(sha=sha), self.assertRaises(ValueError):
                release.selected_sha(sha)
        for repo in ("owner", "owner/../repo", "owner/repo?x"):
            with patch.dict(os.environ, GITHUB_REPOSITORY=repo), \
                    patch.object(release, "run", side_effect=[SHA, ""]), \
                    patch.object(release, "read", return_value="1.2.3"), \
                    self.assertRaises(ValueError):
                release.context(SHA)
        with patch.dict(os.environ, GITHUB_REPOSITORY=REPO), \
                patch.object(release, "run", return_value="b" * 40):
            with self.assertRaisesRegex(ValueError, "Checkout"):
                release.context(SHA)
        with patch.object(release, "run", side_effect=[SHA, "Info.plist"]):
            with self.assertRaisesRegex(ValueError, "metadata differs"):
                release.context(SHA)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        # All fixture files stay under the worktree, never a system temp directory.
        self.directory = ROOT / ".github/tests" / (".release-fixture-" + uuid4().hex)
        self.directory.mkdir()
        self.addCleanup(shutil.rmtree, self.directory)
        previous = Path.cwd()
        os.chdir(self.directory)
        self.addCleanup(os.chdir, previous)
        self.assets = [Path("PRNG-1.2.3.zip"), Path("PRNG-1.2.3.dmg")]
        for asset in self.assets:
            asset.write_bytes(b"fixture asset")
        self.calls = []
        self.tag = None
        self.published = None
        self.uploaded = []
        self.fail = None
        self.race = None
        self.bad_kind = None
        self.bad_result = None
        self.pages = [[]]
        self.start_patch(patch.object(release, "context", return_value=(REPO, "1.2.3", TAG)))
        self.start_patch(patch.object(release, "run", return_value=""))
        self.start_patch(patch.object(release, "remote_ref", side_effect=lambda ref: self.tag))
        self.start_patch(patch.object(release, "api", side_effect=self.api))
        self.start_patch(patch("sys.stdout", new_callable=io.StringIO))

    def start_patch(self, patcher):
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def api(self, endpoint, payload=None, asset=None):
        self.calls.append((endpoint, payload, asset))
        if "/releases?" in endpoint:
            page = int(endpoint.rsplit("=", 1)[1])
            result = self.pages[page - 1]
            if isinstance(result, Exception):
                raise result
            return result
        if endpoint.endswith("/git/refs"):
            kind = "tag"
            if self.race:
                self.tag = self.race
            if self.tag is not None or self.fail == kind:
                raise subprocess.CalledProcessError(1, ["gh", "api", "422"])
            self.tag = payload["sha"]
            result = {"ref": payload["ref"], "object": {"sha": self.tag, "type": "commit"}}
        elif endpoint.endswith("/releases"):
            kind = "release"
            if self.fail == kind:
                raise subprocess.CalledProcessError(1, ["gh", "api"])
            self.published = {"id": 123, **payload}
            result = self.published
        elif asset is not None:
            kind = asset.suffix
            if self.fail == kind:
                raise subprocess.CalledProcessError(1, ["gh", "api"])
            self.uploaded.append(asset.name)
            result = {"id": 456, "name": asset.name, "size": asset.stat().st_size,
                      "state": "uploaded"}
        else:
            raise AssertionError(endpoint)
        return self.bad_result if self.bad_kind == kind else result

    def publish(self):
        release.publish(SHA, self.assets)

    def test_create_only_order_payload_and_returned_release_id(self):
        self.publish()
        self.assertEqual(self.tag, SHA)
        self.assertEqual(len(self.calls), 5)
        self.assertEqual(self.calls[1], (
            f"repos/{REPO}/git/refs", {"ref": f"refs/tags/{TAG}", "sha": SHA}, None,
        ))
        self.assertEqual(self.calls[2], (f"repos/{REPO}/releases", {
            "tag_name": TAG, "target_commitish": SHA, "name": TAG,
            "draft": False, "prerelease": False, "body": "",
        }, None))
        for endpoint, payload, asset in self.calls[3:]:
            self.assertTrue(endpoint.startswith(
                f"https://uploads.github.com/repos/{REPO}/releases/123/assets?name="))
            self.assertNotIn(" ", endpoint)
            self.assertNotIn("#", endpoint)
            self.assertIsNone(payload)
            self.assertIn(asset, self.assets)
        self.assertEqual(self.uploaded, [asset.name for asset in self.assets])

    def test_same_and_different_sha_tag_races_fail_without_reuse(self):
        for sha in (SHA, "b" * 40):
            with self.subTest(sha=sha):
                self.calls.clear()
                self.tag = None
                self.race = sha
                with self.assertRaises(subprocess.CalledProcessError):
                    self.publish()
                self.assertEqual(self.tag, sha)
                self.assertEqual(len(self.calls), 2)
                self.assertIsNone(self.published)
                self.assertEqual(self.uploaded, [])

    def test_each_post_failure_retains_all_prior_state_without_retry(self):
        for kind, count, tag, published, uploaded in (
            ("tag", 2, None, False, []),
            ("release", 3, SHA, False, []),
            (".zip", 4, SHA, True, []),
            (".dmg", 5, SHA, True, [self.assets[0].name]),
        ):
            with self.subTest(kind=kind):
                self.calls.clear()
                self.tag, self.published, self.uploaded = None, None, []
                self.fail = kind
                with self.assertRaises(subprocess.CalledProcessError):
                    self.publish()
                self.assertEqual(len(self.calls), count)
                self.assertEqual(self.tag, tag)
                self.assertEqual(self.published is not None, published)
                self.assertEqual(self.uploaded, uploaded)

    def test_final_recheck_rejects_new_draft_and_later_page_errors(self):
        for result in ([entry(TAG, True)], {"message": "bad"},
                       subprocess.CalledProcessError(1, ["gh", "404"])):
            with self.subTest(result=result):
                self.calls.clear()
                self.pages = [[]]
                release.preflight(SHA)
                self.calls.clear()
                self.pages = [[entry()] * 100, result]
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    self.publish()
                self.assertEqual(len(self.calls), 2)
                self.assertIsNone(self.tag)
                self.assertIsNone(self.published)

    def test_final_recheck_rejects_new_remote_tag(self):
        release.preflight(SHA)
        self.calls.clear()
        self.tag = SHA
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.publish()
        self.assertEqual(self.calls, [])

    def test_remote_verification_failure_never_creates_release(self):
        for response in (None, "b" * 40, OSError("network"), ValueError("malformed")):
            with self.subTest(response=response):
                self.tag = None
                self.calls.clear()
                with patch.object(release, "remote_ref", side_effect=[None, response]):
                    with self.assertRaises((ValueError, OSError)):
                        self.publish()
                self.assertEqual(self.tag, SHA)
                self.assertEqual(len(self.calls), 2)
                self.assertIsNone(self.published)

    def test_malformed_mutation_responses_stop_and_retain_created_state(self):
        tag_response = {"ref": f"refs/tags/{TAG}", "object": {"sha": SHA, "type": "commit"}}
        release_response = {"id": 123, "tag_name": TAG, "target_commitish": SHA,
                            "name": TAG, "draft": False, "prerelease": False, "body": ""}
        asset_response = {"id": 456, "name": self.assets[0].name, "size": 13, "state": "uploaded"}
        for kind, responses, count in (
            ("tag", [None, {}, dict(tag_response, ref="refs/tags/wrong"),
                     dict(tag_response, object={"sha": "b" * 40, "type": "commit"})], 2),
            ("release", [None, {}, dict(release_response, id=True),
                         dict(release_response, id=0), dict(release_response, draft=True),
                         dict(release_response, prerelease=True),
                         dict(release_response, tag_name="v9.9.9")], 3),
            (".zip", [None, {}, dict(asset_response, id=True), dict(asset_response, size=True),
                      dict(asset_response, size=1), dict(asset_response, name="wrong"),
                      dict(asset_response, state="new")], 4),
        ):
            for response in responses:
                with self.subTest(kind=kind, response=response):
                    self.tag, self.published, self.uploaded = None, None, []
                    self.calls.clear()
                    self.bad_kind, self.bad_result = kind, response
                    with self.assertRaises(ValueError):
                        self.publish()
                    self.assertEqual(len(self.calls), count)
                    self.assertEqual(self.tag, SHA)
                    self.assertEqual(self.published is not None, kind != "tag")
                    self.assertEqual(self.uploaded, [self.assets[0].name] if kind == ".zip" else [])

    def test_invalid_assets_fail_before_remote_operations(self):
        for assets in ([], [self.assets[0], self.assets[0]], [self.directory / "missing.zip"],
                       [self.directory]):
            with self.subTest(assets=assets), patch.object(release, "remote_ref") as remote:
                with self.assertRaises(ValueError):
                    release.publish(SHA, assets)
                remote.assert_not_called()
                self.assertEqual(self.calls, [])
        self.assets[0].write_bytes(b"")
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(self.calls, [])

    def test_boolean_upload_size_is_not_an_integer(self):
        self.assets[0].write_bytes(b"x")
        self.bad_kind = ".zip"
        self.bad_result = {"id": 456, "name": self.assets[0].name,
                           "size": True, "state": "uploaded"}
        with self.assertRaisesRegex(ValueError, "Malformed upload response"):
            self.publish()
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(self.tag, SHA)
        self.assertIsNotNone(self.published)
        self.assertEqual(self.uploaded, [self.assets[0].name])


class CLITests(unittest.TestCase):
    def test_preflight_check_publish_and_bump_interfaces(self):
        for command in ("preflight", "check"):
            with self.subTest(command=command), \
                    patch.object(release, "preflight", return_value=("1.2.3", TAG)) as preflight, \
                    patch.dict(os.environ, GITHUB_OUTPUT="fixture-output"), \
                    patch("builtins.open", unittest.mock.mock_open()) as output:
                release.main([command, "--sha", SHA])
                preflight.assert_called_once_with(SHA)
                output.assert_called_once_with("fixture-output", "a")
                output().write.assert_called_once_with(f"version=1.2.3\ntag={TAG}\n")
        with patch.object(release, "publish") as publish:
            release.main(["publish", "--sha", SHA, "first.zip", "second.dmg"])
            publish.assert_called_once_with(SHA, [Path("first.zip"), Path("second.dmg")])
        with patch.object(release, "bump_branch") as bump:
            release.main(["bump", "--sha", SHA, "--branch", "selected", "--mode", "patch"])
            bump.assert_called_once_with(SHA, "selected", "patch")
        for args in (["bump", "--sha", SHA], ["bump", "--sha", SHA, "--branch", "selected"]):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    release.main(args)

    def test_explicit_error_retention_message_and_nonzero_status(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / ".github/scripts/release.py"),
             "publish", "--sha", "invalid"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Stopped without rollback/retry", result.stderr)
        self.assertIn("remote tag, release and uploaded assets are retained", result.stderr)


if __name__ == "__main__":
    unittest.main()
