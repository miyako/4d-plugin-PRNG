![version](https://img.shields.io/badge/version-16%2B-8331AE)
![platform](https://img.shields.io/static/v1?label=platform&message=mac-intel%20|%20mac-arm%20|%20win-64&color=blue)
[![license](https://img.shields.io/github/license/miyako/4d-plugin-PRNG)](LICENSE)
![downloads](https://img.shields.io/github/downloads/miyako/4d-plugin-PRNG/total)

# 4d-plugin-PRNG

## Manual source versioning and publication

**Bump version** and **Build** are independent manual Actions. Select a branch in
the Actions branch selector. Bump offers only patch/minor/major; Build has **zero
inputs**. Neither workflow runs on a push or pull request. Every checkout uses
the immutable dispatch `github.sha`, not a moving branch or a typed tag.

The source authority is the six `MARKETING_VERSION` assignments in
`PRNG.xcodeproj/project.pbxproj`, currently **2.1.8**. The latest committed Bump
header (`99c77bc`, following `4ba8380` and the `e73b107` project move) explicitly
coordinates `MARKETING_VERSION`, `CURRENT_PROJECT_VERSION`, and plist version
fields. That later policy supersedes the earlier marketing-only/current fallback
header, despite the old body still implementing the fallback. Accordingly the
migration repairs only evidenced drift: six build versions from 2.1.6 to 2.1.8
and the copied source English display strings from 2.1.0 to 2.1.8. It does not
increment the authoritative version or add the absent optional `CFBundleVersion`.

Bump validates all source metadata before writing, updates only those version
literals, and preserves supported `$(...)` / `${...}` Xcode version references,
optional-key absence, BOM, each individual line ending, file modes, and unrelated
bytes. The three source files are the project, `Info.plist`, and
`English.lproj/InfoPlist.strings`. Prebuilt bundles, archives, dependencies,
`locversion.plist`, manifest/schema values, and 4D database counters are excluded.
Strict `X.Y.Z` versions reject leading zeros, suffixes, drift and duplicate
assignments/keys, including inline quoted or unquoted duplicates.

Bump requires a clean branch checkout at the exact selected remote SHA. Its
mandatory executable pre-push guard rechecks Git's advertised old SHA, exact
branch and literal new commit SHA, one direct parent, and exactly one update;
even a concurrent same-result update fails. The nonforce push disables followed
tags explicitly. Generated commits include the Copilot coauthor trailer.
Bump never creates a tag/release, builds, or dispatches another workflow.

Build retains Windows Release/x64/v143 and the Default macOS arm64+x86_64 build,
the existing 11.0 deployment override, signing credentials, ZIP/DMG naming, empty
release body, and DMG stapling. Cleanup targets only rebuilt outputs, retaining
bundle resources and committed Windows files during macOS cleanup. The Windows
binary comes from the exact vcxproj output, not a recursive search. The built
plist/localization must resolve to the selected source version, the required
architecture tokens must match exactly, and both successful notarization
commands must return JSON status `Accepted`.

A repository-wide publication lock serializes Build across branches without
cancelling an active publication. Before native work and again after all build,
signing, notarization and stapling gates, authenticated, fully paginated release
queries (including drafts) and an exact remote tag query must prove absence.
Authentication, 404, network, malformed-response and later-page errors abort.
Publication creates a new `vX.Y.Z` ref at the selected SHA, verifies it remotely,
then separately POSTs a new public, non-prerelease release with explicit
tag/name/target/body/draft flags. Assets upload only to that newly returned ID.
No existing publication is reused, patched, deleted, clobbered or retried.

**Recovery:** a failure may leave a tag, release, or some assets behind. The
workflow reports the error and retains all partial state; it performs no
rollback. Inspect the reported remote state manually before deciding how to
recover. A repeat Build for that version fails closed; do not assume a retry
will resume an upload. For a new publication, use a reviewed source bump and
dispatch Build separately.

The implementation was adapted from the complete workflows, helpers and tests at
these immutable prior-art commits:

| Repository | Commit | Policy used |
|---|---|---|
| `miyako/4d-plugin-native-encoding-detection` | `c42ca565857f674bde5ea6ed3435c87375eda4a7` | Coordinated source versions and native gates |
| `miyako/4d-plugin-file-information` | `19848973601acfd3a2b5070230fa40cdc7e4edb2` | Source-only commits and create-only publication |
| `miyako/4d-plugin-common-string-algorithm` | `2606a68201866ec9fcbb38b51462d79215f504ef` | Marketing-only comparison; not PRNG's later policy |
| `miyako/4d-plugin-window-button` | `3f14facb9aaaaff0e22eeb8e07531163680c3a8a` | Independent build metadata comparison; not PRNG's later policy |
| `miyako/4d-plugin-raw-picture-data` | `8144537fdc8dcc3d0c053dfe97aff0a8c0c3a6f9` | Lexical pbx assignment counting, duplicate rejection and lifecycle regression tests |

Offline validation: `actionlint` and
`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s .github/tests`.
The suites use disposable local Git/bare-origin repositories, mocked GitHub
responses, and closed-PATH native/PowerShell stubs. They do not execute native
builds, signing, notarization or 4D, or publish to GitHub.

**PRNG** is a 4D plugin (project ID `20000`) that exposes a fast, high-quality pseudo-random number generator to 4D code, built on the C++ standard library's Mersenne Twister engine (`std::mt19937`). It currently provides one command, grouped under the theme **MT19937**.

> **Not for security use.** `mt19937` is a statistical PRNG, not a cryptographically secure one — its output is predictable from a modest number of observed samples. Don't use this command to generate tokens, passwords, session IDs, or anything else where unpredictability matters for security. It's well suited to simulations, sampling, games, and general randomization.

---

## uniform_int_distribution

Returns a random integer, uniformly distributed over an inclusive range.

### Syntax

```
uniform_int_distribution ( min ; max ) -> Result
```

| Parameter | Type | Description |
|---|---|---|
| `min` | Longint | Lower bound of the range |
| `max` | Longint | Upper bound of the range |
| `Result` | Longint | A random integer `n` such that `min <= n <= max` |

Both bounds are **inclusive** — a call with `min = 1` and `max = 6` can return `1` or `6`, not just values strictly between them.

### Parameter order

`min` and `max` are normalized internally, so which one you pass first doesn't matter — `uniform_int_distribution(1; 6)` and `uniform_int_distribution(6; 1)` produce numbers from the same range.

> **Forward-looking note:** this order-independence, along with the thread-safety behavior described below, is true of the plugin's source as corrected during code review, not necessarily of whatever compiled binary you currently have installed. Before this fix, passing `min > max` triggered undefined behavior in the underlying C++ distribution — build and ship the corrected source before relying on this guarantee.

### Thread safety

The command is declared thread-safe in the plugin's manifest, and — as of the corrected source — genuinely is: each calling thread uses its own independent random engine, so concurrent calls from multiple 4D processes/threads don't interfere with each other's results.

> **Forward-looking note (same caveat as above):** the original shipped implementation used a single generator shared across all threads with no synchronization, which was an actual data race despite being declared thread-safe. This is only fixed in the corrected source from this review.

### Example

```4d
ARRAY LONGINT:C221($numbers; 0)

For ($i; 1; 100)
	APPEND TO ARRAY:C911($numbers; uniform_int_distribution(50000; 100000))
End for
```

This fills `$numbers` with 100 random integers, each between 50,000 and 100,000 inclusive.

A single value, e.g. a six-sided die roll:

```4d
$roll:=uniform_int_distribution(1; 6)
```

### Notes

- If you need reproducible sequences (e.g. for testing), be aware this command doesn't currently expose a way to seed the generator explicitly — each call draws from the plugin's own internally-seeded engine. There's no `set_seed`-style command in this plugin as of this writing.
- Every random draw advances the underlying engine's internal state, so repeated calls in a loop (as in the example above) will not repeat the same value on every iteration.

---

## Command index

| Command | Theme | Description |
|---|---|---|
| [`uniform_int_distribution`](#uniform_int_distribution) | MT19937 | Random integer, uniformly distributed over an inclusive range |
