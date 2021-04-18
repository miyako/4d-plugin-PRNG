![version](https://img.shields.io/badge/version-18%2B-EB8E5F)
![platform](https://img.shields.io/static/v1?label=platform&message=mac-intel%20|%20mac-arm%20|%20win-64&color=blue)
[![license](https://img.shields.io/github/license/miyako/4d-plugin-PRNG)](LICENSE)
![downloads](https://img.shields.io/github/downloads/miyako/4d-plugin-PRNG/total)

**Note**: for v17 and earlier, move `manifest.json` to `Contents`

# 4d-plugin-PRNG

Pseudo-random number generator

## Syntax

```
number:=uniform_int_distribution (min;max)
```

Parameter|Type|Description
------------|------------|----
min|LONGINT|minimum potentially generated value 
max|LONGINT|maximum potentially generated value 
number|LONGINT|

* Using ``std::mt19937`` on both platforms.

* Using ``std::random_device`` to seed the [Mersenne Twister](https://en.wikipedia.org/wiki/Mersenne_Twister).
