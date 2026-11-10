# Bounded native ownership audit

Baseline: `9b96ea07fca0951f84f01aabf3ece13b00b1521d`.
Canonical guidance: `miyako/skills`, commit
`e6b492fcb81e5e1a7f7db723594b420e63bf6eb9`,
`4d-skills/skills/4dplugin/SKILL.md`.

## Inventory and reachability

Both `manifest.json` and
`test/Plugins/PRNG.bundle/Contents/Resources/manifest.json` contain just
`uniform_int_distribution(&L;&L):L`. `4DPlugin.cpp` implements the entry,
selector dispatcher, and this one command; `4DPlugin.h` declares it.
Selector 1 reaches only `C_LONGINT`, the C++ PRNG, and scalar returns.
Neither absence of a text-array declaration nor this dispatch trace excludes
the compiled helpers below from review.

All 16 first-party wrapper implementations and their matching headers under
`4D Plugin API/Classes` were inventoried, including dormant methods:

| Implementation | Ownership surface |
|---|---|
| `C_LONGINT.cpp` | Active scalar parameter/result copies; no strings |
| `C_INTEGER.cpp` | Scalar short copies |
| `C_REAL.cpp` | Scalar double copies |
| `C_DATE.cpp` | Date field copies |
| `C_TIME.cpp` | Scalar time copies |
| `C_TEXT.cpp` | Independent C++ UTF-16 copies, UTF-8 conversion, content-setting parameter/return writers, Objective-C path/string copies |
| `C_BLOB.cpp` | `CBytes`/`C_BLOB` owned byte vectors and handle outputs; hex/base64 C++ text copies, no PA string descriptor transfer |
| `C_POINTER.cpp` | Pointer metadata extraction; ambiguous `PA_GetPointerValue` union/reference semantics deferred |
| `C_PICTURE.cpp` | `CPicture`/`C_PICTURE` file-path callback argument, format conversion, picture ownership and forwarding, Objective-C image helpers |
| `ARRAY_TEXT.cpp` | Borrowed descriptors copied into C++ strings; independently created strings transferred to each output element |
| `ARRAY_BOOLEAN.cpp` | Boolean vector/array copies, no strings |
| `ARRAY_DATE.cpp` | Date vector/array copies, no strings |
| `ARRAY_INTEGER.cpp` | Short vector/array copies, no strings |
| `ARRAY_LONGINT.cpp` | Longint vector/array copies, no strings |
| `ARRAY_REAL.cpp` | Double vector/array copies, no strings |
| `ARRAY_TIME.cpp` | Time vector/array copies, no strings |

`C_TYPES.h` supplies C++ owning container aliases and platform imports; it
has no executable ownership helper. The wrapper headers contain declarations,
not additional inline implementations. `CUTF8StringReplaceString` is also in
`C_TEXT.cpp`; it operates on independent C++ strings, not PA descriptors.
No other tracked first-party native implementation exists.

`PRNG.xcodeproj/project.pbxproj`, `PRNG.vcxproj`, and legacy
`PRNG.vc10.vcxproj` all list all 16 wrappers, `4DPlugin.cpp`, and the same
bundled `4DPluginAPI.c`. `PRNG.sln` selects the current VC project.
The string/picture/array helpers are compiled but not reached by the current
exported PRNG command. Prebuilt bundle binaries and PRNG ZIP/DMG are not rebuilt
or certified by this audit.

## Exact bundled contracts

The SDK implementation Git blob is
`29788ed041effaf67269ccd93f971e8aee2ce5f8`; its header blob is
`9054b45ffc7ff6f5b8d57529a3788a55d977b314`.
The source comment says v14 and the header says v13, not a verified upstream
release identity. SDK internals and associated platform/type/entry-point
headers are evidence, not fix targets; they remain unchanged.

At the baseline SDK source:

- Lines 244-270: create/dispose/content-set operations forward to the engine;
  disposal also zeroes the local descriptor.
- Lines 3523-3659: creating a string/picture variable creates initial owning
  contents. Empty strings can have allocated storage.
- Lines 3826-3831 and 3852-3857: string/picture variable setters shallow-assign
  and do not dispose previously initialized contents.
- Lines 3729-3736: picture getter is explicitly borrowed from its variable.
  Lines 446-454: duplicate with retainOnly 1 retains the current picture.
- Lines 4264-4284: array getter returns a borrowed descriptor; lines
  4444-4459: accepted setter disposes the old element and shallow-transfers
  the supplied descriptor. Wrong type, null data, negative/out-of-range index,
  or null descriptor is rejected without consuming ownership. Index zero is
  accepted. `ARRAY_TEXT` does not dispose accepted transferred strings.
- Lines 2260-2263: `PA_ReturnString` uses `PA_SetUnistring` content replacement,
  not array descriptor transfer. `C_TEXT` uses that content-setting path too.
- Lines 4775-4792: charset conversion returns bytes, not UTF-16 units.
- Lines 5257-5290: synchronous command execution passes argument pointers and a
  separate result variable. The five picture command IDs are procedures;
  there are no first-party `PA_ExecuteMethod` or JSON Parse call sites.

## Corrections

`fromFileAtPath` previously disposed the same path through its local alias
and its argument variable. Its argument now owns the string exactly once;
the output picture is retained before both argument variables are cleared.
String/picture argument slots immediately shallow-overwritten by setters now
start Undefined, avoiding lost initial owning contents. This includes the
same picture argument pattern in grayscale/properties/thumbnail helpers.
`setBytes` releases its temporary picture after `setPicture` retains it.
`createCopy` divides the SDK conversion byte count by `sizeof(PA_Unichar)`
before constructing its independent UTF-16 string. Public signatures,
command behavior, manifests, and SDK implementation are unchanged.

## Regression and limits

Run on macOS with the existing Apple toolchain:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 .github/tests/test_ownership.py
PRNG_OWNERSHIP_SOURCE_REF=9b96ea07fca0951f84f01aabf3ece13b00b1521d \
  PYTHONDONTWRITEBYTECODE=1 python3 .github/tests/test_ownership.py
```

The second command is an intentional negative control. Both use the same
harness with actual production entry, all wrapper implementations, and the
complete unchanged bundled SDK; only `gCall4D` is mocked. Direct compiler
invocation bypasses all project build phases. ASan/UBSan are enabled. LSan
is disabled on this macOS target; explicit string/handle allocation maps
and picture reference counts must all balance.

Baseline failures identify path double disposal, `.png` conversion
heap-buffer-overread, overwritten picture-argument contents, and the
`setBytes` temporary reference leak. Fixed source must pass all six cases
with both allocated-empty and null-empty strings. Tests cover exact ASCII,
BMP and surrogate-pair UTF-16 contents/lengths and termination, repeated
calls, failed synchronous commands leaving initialized arguments intact,
unchanged/replaced picture arguments, retained/detached handoffs, borrowed
text copies after owner mutation and allocator churn, independent array
outputs, replacement/shrink/clear, and accepted/rejected setter conditions.
The actual scalar PRNG entry remains within reversed inclusive bounds.

This is not a reproduction of Poppler's Windows crash or certification in
Windows/4D. Objective-C image/path helper runtime behavior is not exhaustively
exercised. Invalid conversion inputs, engine allocation failures and the SDK's
array-resize allocation-failure count corruption are not certified by normal
array tests. The latter is SDK-internal and remains deferred. Picture-data
string output ownership and pointer metadata ownership are not established
by the bundled forwarding code; no guessed disposal was added. Failed
picture-data results are checked for errors before content is inspected.
There are no object/collection getter call sites in this SDK/wrapper set.

Both Actions workflows are manual-only. The Xcode Deployment shell phase
signs, packages and submits notarization; the manual Build workflow also
signs, packages and publishes. Neither is invoked. No signing credentials,
release dispatches, tags, archives, or binary publication are part of this fix.
