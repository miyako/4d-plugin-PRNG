![version](https://img.shields.io/badge/version-16%2B-8331AE)
![platform](https://img.shields.io/static/v1?label=platform&message=mac-intel%20|%20mac-arm%20|%20win-64&color=blue)
[![license](https://img.shields.io/github/license/miyako/4d-plugin-PRNG)](LICENSE)
![downloads](https://img.shields.io/github/downloads/miyako/4d-plugin-PRNG/total)

# 4d-plugin-PRNG

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
