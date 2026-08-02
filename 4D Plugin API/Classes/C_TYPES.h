#ifndef C_TYPES_H
#define C_TYPES_H

#if __APPLE__
#import <CoreFoundation/CoreFoundation.h>
#import <Cocoa/Cocoa.h>
#import <AppKit/AppKit.h>
#endif

#if _WIN32
// Without this, <windows.h> auto-includes the legacy <winsock.h>. If
// anything else in a project's include chain (e.g. 4DPlugin-JSON.h) later
// includes <winsock2.h>, the two collide -- duplicate sockaddr/fd_set/
// accept/bind/... declarations with different linkage (MSVC C2011/C2375).
// This has already hit two different projects that include C_TEXT.h (and
// therefore this file) before 4DPlugin-JSON.h, via two different upstream
// culprits (msime.h in one case, this file in another) -- guarding it here
// closes the root cause regardless of what else pulls in <windows.h> first.
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#endif

#include <string>
#include <vector>

#ifndef uint8_t
typedef unsigned char uint8_t;
#endif
#ifndef uint16_t
typedef unsigned short uint16_t;
#endif
#ifndef uint32_t
typedef unsigned int uint32_t;
#endif

typedef uint8_t * BytePtr;
typedef BytePtr *PackagePtr;

typedef std::basic_string<PA_Unichar> CUTF16String;
typedef std::basic_string<uint8_t> CUTF8String;
typedef std::vector<CUTF16String> CUTF16StringArray;
typedef std::vector<CUTF8String> CUTF8StringArray;

#endif /* C_TYPES_H */
