// Only the engine boundary is simulated; all PA_* and wrapper code is compiled unchanged.
#include "4DPluginAPI.h"
#include "PrivateTypes.h"
#include "EntryPoints.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>

static bool allocatedEmpty;
static bool replacePicture;
static bool failCommand;
static CUTF16String expectedText;
static std::map<PA_Unichar*, size_t> strings;
static std::map<PA_Picture, int> pictures;
static std::map<PA_Handle, size_t> handles;

static void check(bool condition, const char* message)
{
    if (!condition) {
        std::fprintf(stderr, "ownership regression: %s\n", message);
        std::exit(1);
    }
}

static PA_Unistring makeString(const PA_Unichar* text)
{
    PA_Unistring result = {};
    result.fLength = PA_GetUnicharsLength(const_cast<PA_Unichar*>(text));
    if (result.fLength || allocatedEmpty) {
        const size_t size = (result.fLength + 1) * sizeof(PA_Unichar);
        result.fString = static_cast<PA_Unichar*>(std::malloc(size));
        check(result.fString != NULL, "test allocator failed");
        PA_Unichar* storage = result.fString;
        strings[storage] = size;
        if (result.fLength)
            std::memcpy(result.fString, text, size - sizeof(PA_Unichar));
        result.fString[result.fLength] = 0;
    }
    return result;
}

static void disposeString(PA_Unistring value)
{
    PA_Unichar* storage = value.fString;
    if (!storage)
        return;
    check(strings.erase(storage) == 1, "string disposed twice or borrowed string freed");
    std::free(storage);
}

static void expectString(PA_Unistring value, const CUTF16String& expected)
{
    PA_Unichar* storage = value.fString;
    check(value.fLength == expected.size(), "wrong UTF-16 code-unit count");
    if (storage) {
        check(strings.count(storage) == 1, "string used after disposal");
        check(strings.at(storage) >= (value.fLength + 1) * sizeof(PA_Unichar),
              "UTF-16 allocation/terminator boundary");
        check(value.fString[value.fLength] == 0, "missing UTF-16 terminator");
        check(CUTF16String(value.fString, value.fLength) == expected, "wrong UTF-16 content");
    } else {
        check(expected.empty(), "nonempty string has null storage");
    }
}

static PA_Picture makePicture()
{
    void* value = std::malloc(1);
    check(value != NULL, "picture allocator failed");
    pictures[value] = 1;
    return value;
}

static void disposePicture(PA_Picture value)
{
    if (!value)
        return;
    check(pictures.count(value) == 1, "invalid or already disposed picture");
    if (--pictures[value] == 0) {
        pictures.erase(value);
        std::free(value);
    }
}

static void clearVariable(PA_Variable* variable)
{
    if (variable->fType == eVK_Unistring)
        disposeString(variable->uValue.fString);
    else if (variable->fType == eVK_Picture)
        disposePicture(variable->uValue.fPicture);
    else if (variable->fType == eVK_ArrayUnicode) {
        auto handle = variable->uValue.fArray.fData;
        check(handles.count(handle) == 1, "invalid array handle");
        check(handles[handle] >= (variable->uValue.fArray.fNbElements + 1) * sizeof(PA_Unistring),
              "array count exceeds allocation");
        auto elements = reinterpret_cast<PA_Unistring*>(*handle);
        for (PA_long32 i = 0; i <= variable->uValue.fArray.fNbElements; ++i)
            disposeString(elements[i]);
        handles.erase(handle);
        std::free(*handle);
        std::free(handle);
    }
    *variable = {};
    variable->fType = eVK_Undefined;
}

static void engine(short selector, EngineBlock* eb)
{
    switch (selector) {
        case EX_CREATE_UNISTRING:
            eb->fUniString1 = makeString(reinterpret_cast<PA_Unichar*>(eb->fHandle));
            break;
        case EX_DISPOSE_UNISTRING:
            disposeString(eb->fUniString1);
            break;
        case EX_SET_UNISTRING: {
            auto text = reinterpret_cast<PA_Unichar*>(eb->fHandle);
            PA_Unistring replacement = makeString(text);
            disposeString(eb->fUniString1);
            eb->fUniString1 = replacement;
            break;
        }
        case EX_CREATE_PICTURE:
            eb->fPicture = makePicture();
            eb->fError = 0;
            break;
        case EX_DISPOSE_PICTURE:
            disposePicture(eb->fPicture);
            break;
        case EX_DUPLICATE_PICTURE: {
            PA_Picture picture = eb->fPicture;
            check(pictures.count(picture) == 1, "retaining invalid picture");
            if (eb->fParam1 == 0)
                ++pictures[picture];
            else
                eb->fPicture = makePicture();
            break;
        }
        case EX_GET_PICTURE_DATA:
            // No representations. The failed output is deliberately not initialized.
            eb->fError = eER_IdxPgOutOfRange;
            break;
        case EX_CLEAR_VARIABLE:
            clearVariable(static_cast<PA_Variable*>(eb->fPtr1));
            break;
        case EX_HANDLE_MANAGER: {
            auto handle = eb->fHandle;
            eb->fError = 0;
            if (eb->fParam1 == 1) {
                handle = static_cast<PA_Handle>(std::malloc(sizeof(char*)));
                *handle = static_cast<char*>(std::calloc(1, eb->fParam2 ? eb->fParam2 : 1));
                handles[handle] = eb->fParam2;
                eb->fHandle = handle;
            } else {
                check(handles.count(handle) == 1, "invalid handle");
                switch (eb->fParam1) {
                    case 2:
                        handles.erase(handle);
                        std::free(*handle);
                        std::free(handle);
                        break;
                    case 3: {
                        size_t oldSize = handles[handle];
                        *handle = static_cast<char*>(std::realloc(*handle, eb->fParam2));
                        check(*handle != NULL, "test handle resize failed");
                        if (eb->fParam2 > oldSize)
                            std::memset(*handle + oldSize, 0, eb->fParam2 - oldSize);
                        handles[handle] = eb->fParam2;
                        break;
                    }
                    case 4: eb->fParam2 = handles[handle]; break;
                    case 5: eb->fParam3 = reinterpret_cast<sLONG_PTR>(*handle); break;
                    case 6: break;
                    default: check(false, "unexpected handle operation");
                }
            }
            break;
        }
        case EX_CONVERT_CHARSET_TO_CHARSET: {
            check(eb->fParam2 == eVTC_UTF_8 && eb->fParam4 == eVTC_UTF_16,
                  "unexpected charset conversion");
            CFStringRef text = CFStringCreateWithBytes(
                kCFAllocatorDefault, static_cast<const UInt8*>(eb->fPtr1), eb->fParam1,
                kCFStringEncodingUTF8, false);
            check(text != NULL, "invalid test conversion input");
            CFIndex units = CFStringGetLength(text);
            const size_t bytes = units * sizeof(PA_Unichar);
            check(bytes + sizeof(PA_Unichar) <= eb->fParam3,
                  "conversion capacity must include UTF-16 terminator");
            CFStringGetCharacters(text, CFRangeMake(0, units),
                                  static_cast<UniChar*>(eb->fPtr2));
            static_cast<PA_Unichar*>(eb->fPtr2)[units] = 0;
            eb->fParam3 = bytes; // Bundled SDK contract: bytes, not UTF-16 units.
            eb->fError = 0;
            CFRelease(text);
            break;
        }
        case EX_EXECUTE_COMMAND_BY_ID: {
            auto args = static_cast<PA_Variable**>(eb->fPtr1);
            auto result = static_cast<PA_Variable*>(eb->fPtr2);
            result->fType = eVK_Undefined; // These five commands have no function result.
            eb->fError = failCommand ? eER_IncompatibleTypes : eER_NoErr;
            const int id = eb->fParam1;
            if (id == 678)
                expectString(args[0]->uValue.fString, expectedText);
            else if (id == 1002)
                expectString(args[1]->uValue.fString, expectedText);
            else
                check(id == 988 || id == 457 || id == 679, "unexpected command");
            if (!failCommand && (id == 678 || id == 679 || (replacePicture && id != 457))) {
                int output = (id == 678 || id == 679) ? 1 : 0;
                check(args[output]->fType == eVK_Picture, "picture argument type changed");
                disposePicture(args[output]->uValue.fPicture);
                args[output]->uValue.fPicture = makePicture();
            }
            if (id == 457) {
                PA_SetLongintVariable(args[1], 12);
                PA_SetLongintVariable(args[2], 34);
            }
            break;
        }
        default:
            std::fprintf(stderr, "unexpected engine selector: %d\n", selector);
            std::exit(1);
    }
}

static void balanced()
{
    check(strings.empty(), "leaked owning string (including allocated empty)");
    check(pictures.empty(), "leaked picture reference or overwritten initial picture");
    check(handles.empty(), "leaked handle");
}

static void filePath()
{
    const char* utf8[] = {"ASCII.png", "\xE6\x97\xA5.png", "\xF0\x9F\x98\x80.png", ""};
    const PA_Unichar bmp[] = {0x65e5, '.', 'p', 'n', 'g', 0};
    const PA_Unichar supplementary[] = {0xd83d, 0xde00, '.', 'p', 'n', 'g', 0};
    const PA_Unichar ascii[] = {'A', 'S', 'C', 'I', 'I', '.', 'p', 'n', 'g', 0};
    const CUTF16String expected[] = {ascii, bmp, supplementary, CUTF16String()};
    for (bool failure : {false, true}) {
        failCommand = failure;
        for (int i = 0; i < 4; ++i) {
            {
                CPicture picture;
                CUTF8String path(reinterpret_cast<const uint8_t*>(utf8[i]));
                expectedText = expected[i];
                for (int repeat = 0; repeat < 3; ++repeat) {
                    picture.fromFileAtPath(&path);
                    check(pictures.count(picture.getPicture()) == 1,
                          "loaded picture did not survive argument cleanup");
                    check(pictures[picture.getPicture()] == 1, "file output reference leaked");
                }
            }
            balanced();
        }
    }
}

static void conversion()
{
    const char* utf8[] = {".png", "\xE6\x97\xA5", "\xF0\x9F\x98\x80", ""};
    const PA_Unichar png[] = {'.', 'p', 'n', 'g', 0};
    const PA_Unichar bmp[] = {0x65e5, 0};
    const PA_Unichar supplementary[] = {0xd83d, 0xde00, 0};
    const CUTF16String expected[] = {png, bmp, supplementary, CUTF16String()};
    for (bool replacement : {false, true}) {
        replacePicture = replacement;
        for (bool failure : {false, true}) {
            failCommand = failure;
            {
                CPicture picture;
                for (int repeat = 0; repeat < 3; ++repeat) {
                    for (int i = 0; i < 4; ++i) {
                        expectedText = expected[i];
                        auto copy = picture.createCopy(utf8[i]);
                        check(pictures.count(copy) == 1, "returned picture was cleared");
                        PA_DisposePicture(copy);
                        check(pictures[picture.getPicture()] == 1, "source picture retain leaked");
                    }
                }
            }
            balanced();
        }
    }
}

static void pictureArguments()
{
    for (bool replacement : {false, true}) {
        replacePicture = replacement;
        {
            CPicture picture;
            for (int repeat = 0; repeat < 3; ++repeat) {
                auto gray = picture.createGrayScale();
                check(pictures.count(gray) == 1, "grayscale handoff invalid");
                PA_DisposePicture(gray);
                auto thumb = picture.createThumbnail(10, 20);
                check(pictures.count(thumb) == 1, "thumbnail handoff invalid");
                PA_DisposePicture(thumb);
                unsigned int width = 0, height = 0;
                picture.getSize(&width, &height);
                check(width == 12 && height == 34, "picture dimensions changed");
                check(pictures[picture.getPicture()] == 1, "borrowed picture disposed or leaked");
            }
        }
        balanced();
    }
}

static void pictureBytes()
{
    {
        CPicture picture;
        const uint8_t bytes[] = {1, 2, 3};
        for (int repeat = 0; repeat < 3; ++repeat) {
            picture.setBytes(bytes, sizeof(bytes));
            check(pictures[picture.getPicture()] == 1, "setBytes temporary picture leaked");
        }
    }
    balanced();
}

static void churn()
{
    const PA_Unichar text[] = {'c', 'h', 'u', 'r', 'n', 0};
    for (int i = 0; i < 32; ++i) {
        auto temporary = PA_CreateUnistring(const_cast<PA_Unichar*>(text));
        PA_DisposeUnistring(&temporary);
    }
}

static void text()
{
    const PA_Unichar fixture[] = {'A', 0x65e5, 0xd83d, 0xde00, 0};
    PA_Variable array = PA_CreateVariable(eVK_ArrayUnicode);
    PA_ResizeArray(&array, 2);
    for (int repeat = 0; repeat < 3; ++repeat) {
        for (int i = 0; i <= 2; ++i) {
            auto owned = PA_CreateUnistring(const_cast<PA_Unichar*>(fixture));
            PA_SetStringInArray(array, i, &owned);
            auto borrowed = PA_GetStringInArray(array, i);
            check(borrowed.fString == owned.fString, "array setter must shallow transfer");
        }
        ARRAY_TEXT copy;
        BytePtr params[] = {reinterpret_cast<BytePtr>(&array)};
        copy.fromParamAtIndex(params, 1);
        auto replacement = PA_CreateUnistring(NULL);
        PA_SetStringInArray(array, 1, &replacement);
        CUTF16String independent;
        copy.copyUTF16StringAtIndex(&independent, 1);
        check(independent == CUTF16String(fixture), "wrapper retained borrowed storage");
        copy.toParamAtIndex(params, 1);
        PA_Variable second = PA_CreateVariable(eVK_Undefined);
        BytePtr secondParams[] = {reinterpret_cast<BytePtr>(&second)};
        copy.toParamAtIndex(secondParams, 1);
        check(PA_GetStringInArray(array, 1).fString != PA_GetStringInArray(second, 1).fString,
              "each array output needs an independent string owner");
        PA_ClearVariable(&second);
        churn();
        expectString(PA_GetStringInArray(array, 1), fixture);
    }
    auto callerOwned = PA_CreateUnistring(const_cast<PA_Unichar*>(fixture));
    PA_Variable wrongType = PA_CreateVariable(eVK_Longint);
    PA_SetStringInArray(wrongType, 0, &callerOwned);
    PA_SetStringInArray(array, -1, &callerOwned);
    PA_SetStringInArray(array, 3, &callerOwned);
    PA_Variable noData = {};
    noData.fType = eVK_ArrayUnicode;
    PA_SetStringInArray(noData, 0, &callerOwned);
    PA_SetStringInArray(array, 0, NULL);
    expectString(callerOwned, fixture);
    PA_DisposeUnistring(&callerOwned);
    PA_ResizeArray(&array, 0);
    PA_ClearVariable(&array);
    auto owned = PA_CreateUnistring(const_cast<PA_Unichar*>(fixture));
    C_TEXT scalar;
    scalar.setUTF16String(&owned);
    PA_DisposeUnistring(&owned);
    churn();
    check(scalar.getUTF16Length() == 4, "scalar must independently copy borrowed content");
    auto output = PA_CreateUnistring(NULL);
    BytePtr params[] = {reinterpret_cast<BytePtr>(&output)};
    scalar.toParamAtIndex(params, 1);
    expectString(output, fixture);
    PA_DisposeUnistring(&output);
    balanced();
}

static void command()
{
    for (int i = 0; i < 100; ++i) {
        int lower = 9, upper = -4;
        BytePtr args[] = {reinterpret_cast<BytePtr>(&lower), reinterpret_cast<BytePtr>(&upper)};
        sLONG_PTR result = 0;
        PluginBlock params = {args, &result, NULL};
        PluginMain(1, &params);
        check(static_cast<int>(result) >= -4 && static_cast<int>(result) <= 9,
              "exported scalar range changed");
    }
    balanced();
}

int main(int argc, char** argv)
{
    check(argc == 3, "expected case and empty representation");
    allocatedEmpty = std::strcmp(argv[2], "allocated") == 0;
    gCall4D = engine;
    if (std::strcmp(argv[1], "file-path") == 0) filePath();
    else if (std::strcmp(argv[1], "conversion") == 0) conversion();
    else if (std::strcmp(argv[1], "picture-arguments") == 0) pictureArguments();
    else if (std::strcmp(argv[1], "picture-bytes") == 0) pictureBytes();
    else if (std::strcmp(argv[1], "text") == 0) text();
    else if (std::strcmp(argv[1], "command") == 0) command();
    else check(false, "unknown test");
    std::printf("PASS %s %s\n", argv[1], argv[2]);
}
