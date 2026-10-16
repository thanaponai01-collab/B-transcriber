// Loads the real compiled plugin against a synthetic SDK host, not Premiere.
// Pass an empty scratch folder: TMP points there, so no request reaches a running Premiere.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>
#include <algorithm>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include <adobesdk/AdobesdkStringSuite.h>
#include <adobesdk/controlsurface/host/ControlSurfaceHostCommandSuite.h>
#include <adobesdk/controlsurface/host/ControlSurfaceHostSuite.h>
#include <adobesdk/controlsurface/host/ControlSurfaceHostTransportSuite.h>
#include <adobesdk/controlsurface/plugin/ControlSurfacePluginSuite.h>
#include <adobesdk/controlsurface/plugin/ControlSurfaceCommandSuite.h>
#include <adobesdk/controlsurface/plugin/ControlSurfaceTransportSuite.h>

namespace {
std::map<std::string, int> acquisitions;
std::map<std::string, const void*> registrations;
int liveStrings = 0, lists = 0;
std::vector<std::pair<std::string, std::string>> executed;
std::string scenario;
std::filesystem::path spike;
ADOBESDK_StringSuite1 stringSuite{};
SPSuitesSuite suites{};
ADOBESDK_ControlSurfaceHostSuite2 hostSuite{};
ADOBESDK_ControlSurfaceHostCommandSuite1 commands{};
ADOBESDK_ControlSurfaceHostTransportSuite1 transport{};
void check(bool condition, const std::string& message) { if (!condition) throw std::runtime_error(scenario + ": " + message); }
SPErr allocate(const ADOBESDK_UTF8Char* text, ADOBESDK_String* out) {
    out->opaque[0] = reinterpret_cast<int64_t>(new std::string(reinterpret_cast<const char*>(text)));
    ++liveStrings;
    return kSPNoError;
}
SPErr dispose(const ADOBESDK_String* value) {
    if (value->opaque[0]) { delete reinterpret_cast<std::string*>(value->opaque[0]); --liveStrings; }
    return kSPNoError;
}
SPErr copyString(const ADOBESDK_String* value, ADOBESDK_UTF8Char* out, uint32_t* count) {
    const std::string text = value->opaque[0] ? *reinterpret_cast<std::string*>(value->opaque[0]) : "";
    uint32_t needed = static_cast<uint32_t>(text.size()) + 1;
    if (*count < needed) { *count = needed; return kADOBESDK_Error_StringBufferTooSmall; }
    memcpy(out, text.c_str(), needed);
    *count = needed;
    return kSPNoError;
}
std::string text(const ADOBESDK_String* value) { return value && value->opaque[0] ? *reinterpret_cast<std::string*>(value->opaque[0]) : ""; }
SPErr getCount(ADOBESDK_ControlSurfaceHostCommandRef, uint32_t* out) { *out = scenario == "empty" ? 0 : 130; return kSPNoError; }
SPErr getCommand(ADOBESDK_ControlSurfaceHostCommandRef, uint32_t index, ADOBESDK_String* context,
                 ADOBESDK_String* contextName, ADOBESDK_String* command, ADOBESDK_String* name) {
    if (scenario == "row-failure" && index == 70) return kSPBadParameterError;
    allocate(reinterpret_cast<const ADOBESDK_UTF8Char*>("context.timeline"), context);
    allocate(reinterpret_cast<const ADOBESDK_UTF8Char*>("Timeline"), contextName);
    const std::string id = index == 3 ? "cmd.sequence.razorateditline.all" : "test.command." + std::to_string(index);
    allocate(reinterpret_cast<const ADOBESDK_UTF8Char*>(id.c_str()), command);
    // Exercise UTF-8 preservation, JSON escaping and SDK size negotiation.
    const std::string label = std::string(280, 'x') + "\n\"\\" + "\xe0\xb8\x81";
    allocate(reinterpret_cast<const ADOBESDK_UTF8Char*>(label.c_str()), name);
    return kSPNoError;
}
SPErr execute(ADOBESDK_ControlSurfaceHostCommandRef, const ADOBESDK_String* context, const ADOBESDK_String* command) {
    executed.emplace_back(text(context), text(command));
    return kSPNoError;
}
SPErr getCommandRef(ADOBESDK_ControlSurfaceHostRef, ADOBESDK_ControlSurfaceHostCommandRef* out) {
    if (scenario == "command-ref-failure") return kSPBadParameterError;
    *out = reinterpret_cast<ADOBESDK_ControlSurfaceHostCommandRef>(&commands); return kSPNoError;
}
SPErr getTransportRef(ADOBESDK_ControlSurfaceHostRef, ADOBESDK_ControlSurfaceHostTransportRef* out) {
    if (scenario == "no-transport") return kSPBadParameterError;
    *out = reinterpret_cast<ADOBESDK_ControlSurfaceHostTransportRef>(&transport); return kSPNoError;
}
SPErr timeDisplay(ADOBESDK_ControlSurfaceHostTransportRef, uint32_t* mode, uint32_t, ADOBESDK_String* out) {
    *mode = scenario == "decimal-mode" ? kADOBESDK_ControlSurfaceTimeDisplayMode_Decimal : kADOBESDK_ControlSurfaceTimeDisplayMode_SMPTE;
    return allocate(reinterpret_cast<const ADOBESDK_UTF8Char*>("00:00:04:00"), out);
}
SPErr playState(ADOBESDK_ControlSurfaceHostTransportRef, ADOBESDK_Boolean* out) {
    *out = static_cast<ADOBESDK_Boolean>(scenario == "playing" ? kAdobesdk_True : kAdobesdk_False); return kSPNoError;
}
SPErr allocateList(SPStringPoolRef, SPPluginListRef, SPSuiteListRef* out) {
    *out = reinterpret_cast<SPSuiteListRef>(new int(1)); ++lists; return kSPNoError;
}
SPErr freeList(SPSuiteListRef ref) { delete reinterpret_cast<int*>(ref); --lists; registrations.clear(); return kSPNoError; }
SPErr addSuite(SPSuiteListRef, SPPluginRef, const char* name, int version, int, const void* methods, SPSuiteRef* out) {
    registrations[std::string(name) + std::to_string(version)] = methods;
    *out = reinterpret_cast<SPSuiteRef>(&suites); return kSPNoError;
}
SPErr acquire(const char* name, int, const void** out) {
    *out = nullptr;
    if (scenario == "connect-failure" && strcmp(name, kADOBESDK_ControlSurfaceHostCommandSuite) == 0) return kSPCantAcquirePluginError;
    if (scenario == "startup-failure" && strcmp(name, kSPSuitesSuite) == 0) return kSPCantAcquirePluginError;
    if (strcmp(name, kADOBESDK_StringSuite) == 0) *out = &stringSuite;
    if (strcmp(name, kSPSuitesSuite) == 0) *out = &suites;
    if (strcmp(name, kADOBESDK_ControlSurfaceHostSuite) == 0) *out = &hostSuite;
    if (strcmp(name, kADOBESDK_ControlSurfaceHostCommandSuite) == 0) *out = &commands;
    if (strcmp(name, kADOBESDK_ControlSurfaceHostTransportSuite) == 0) *out = &transport;
    if (!*out) return kSPCantAcquirePluginError;
    ++acquisitions[name]; return kSPNoError;
}
SPErr release(const char* name, int) { --acquisitions[name]; return kSPNoError; }
void clean(size_t expectedExecutions) {
    check(liveStrings == 0 && lists == 0, "SDK objects leaked");
    for (const auto& entry : acquisitions) check(entry.second == 0, "Suite acquisitions unbalanced");
    check(executed.size() == expectedExecutions, "Executed " + std::to_string(executed.size()) + " commands, expected " + std::to_string(expectedExecutions));
    for (const auto& call : executed)
        check(call.first == "global" && call.second == "cmd.sequence.razorateditline.all", "Executed an unexpected command " + call.second);
}

int64_t unixMs() {
    FILETIME now{};
    GetSystemTimeAsFileTime(&now);
    const uint64_t t = (uint64_t(now.dwHighDateTime) << 32) | now.dwLowDateTime;
    return int64_t(t / 10000) - 11644473600000LL;
}
const std::string kNonce = "0123456789abcdef0123456789abcdef";
std::filesystem::path requestPath(const std::string& nonce = kNonce) { return spike / ("request-" + nonce + ".txt"); }
std::filesystem::path resultPath() { return spike / ("result-" + kNonce + ".json"); }
void writeRequest(const std::string& body, const std::string& nonce = kNonce) {
    std::ofstream out(requestPath(nonce), std::ios::binary);
    out << body;
}
std::string request(const std::string& expected, int64_t created) { return kNonce + "\n" + expected + "\n" + std::to_string(created) + "\n"; }
std::string readResult() {
    std::ifstream in(resultPath(), std::ios::binary);
    std::stringstream buffer; buffer << in.rdbuf();
    return buffer.str();
}
void poll(const ADOBESDK_ControlSurfaceSuite2* surface, ADOBESDK_ControlSurfaceRef ref) {
    Sleep(120);  // the plugin polls at most every 100 ms
    check(surface->Update(ref) == kSPNoError, "Update failed");
}

// One request kind against a connected plugin whose catalog is already finished.
void runRequest(const ADOBESDK_ControlSurfaceSuite2* surface, ADOBESDK_ControlSurfaceRef ref, int64_t beforeConnect) {
    const int64_t now = unixMs();
    std::string reason;
    if (scenario == "idle") {
        for (int i = 0; i < 3; ++i) poll(surface, ref);
        check(!std::filesystem::exists(resultPath()), "Result written without a request");
        return;
    }
    if (scenario == "locked") {
        writeRequest(request("00:00:04:00", now));
        // Open without FILE_SHARE_DELETE: the plugin can read but cannot consume the request.
        HANDLE hold = CreateFileW(requestPath().c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
        check(hold != INVALID_HANDLE_VALUE, "Could not hold request open");
        poll(surface, ref);
        CloseHandle(hold);
        check(std::filesystem::exists(requestPath()) && !std::filesystem::exists(resultPath()), "Unconsumed request was acted on");
        std::filesystem::remove(requestPath());
        return;
    }
    if (scenario == "match") writeRequest(request("00:00:04:00", now));
    else if (scenario == "mismatch") { writeRequest(request("00:00:05:00", now)); reason = "timecode_mismatch"; }
    else if (scenario == "future") { writeRequest(request("00:00:04:00", now + 5000)); reason = "stale"; }
    else if (scenario == "before-connect") { writeRequest(request("00:00:04:00", beforeConnect - 1000)); reason = "before_connect"; }
    else if (scenario == "playing") { writeRequest(request("00:00:04:00", now)); reason = "playing"; }
    else if (scenario == "decimal-mode") { writeRequest(request("00:00:04:00", now)); reason = "display_mode"; }
    else if (scenario == "no-transport") { writeRequest(request("00:00:04:00", now)); reason = "no_transport"; }
    else if (scenario == "extra-line") { writeRequest(request("00:00:04:00", now) + "cmd.sequence.lift\n"); reason = "malformed"; }
    else if (scenario == "wrong-nonce") { writeRequest("fedcba9876543210fedcba9876543210\n00:00:04:00\n" + std::to_string(now) + "\n"); reason = "malformed"; }
    poll(surface, ref);
    check(!std::filesystem::exists(requestPath()), "Request not consumed");
    const std::string result = readResult();
    if (scenario == "match") {
        check(result.find("\"status\":\"executed\"") != std::string::npos, "Matching request not executed: " + result);
        check(result.find("\"timeAfter\":\"00:00:04:00\"") != std::string::npos, "Time after not recorded");
    } else {
        check(result.find("\"status\":\"refused\"") != std::string::npos, "Request not refused: " + result);
        check(result.find("\"reason\":\"" + reason + "\"") != std::string::npos, "Wrong refusal reason: " + result);
    }
    // The same request must never run twice, and later polls with nothing pending do nothing.
    std::filesystem::remove(resultPath());
    poll(surface, ref);
    check(!std::filesystem::exists(resultPath()), "A second result appeared");
}
}

int wmain(int argc, wchar_t** argv) {
    try {
        check(argc == 3, "Pass the compiled .acsrf path and an empty scratch folder");
        // Before the plugin loads: its GetTempPathW must resolve to the scratch folder.
        check(SetEnvironmentVariableW(L"TMP", argv[2]) && SetEnvironmentVariableW(L"TEMP", argv[2]), "Could not redirect TMP");
        spike = std::filesystem::path(argv[2]) / L"CutDeckCutterSpike";
        std::filesystem::create_directories(spike);
        HMODULE module = LoadLibraryW(argv[1]);
        check(module != nullptr, "Windows loader rejected plugin");
        auto entry = reinterpret_cast<ADOBESDK_ControlSurfaceEntryPoint>(GetProcAddress(module, "EntryPoint"));
        check(entry != nullptr, "EntryPoint export missing");
        stringSuite.AllocateFromUTF8 = allocate; stringSuite.DisposeString = dispose; stringSuite.CopyToUTF8String = copyString;
        suites.AllocateSuiteList = allocateList; suites.FreeSuiteList = freeList; suites.AddSuite = addSuite;
        hostSuite.GetCommandRef = getCommandRef; hostSuite.GetTransportRef = getTransportRef;
        commands.GetCommandCount = getCount; commands.GetCommand = getCommand; commands.ExecuteCommand = execute;
        transport.GetTimeDisplayString = timeDisplay; transport.GetPlayState = playState;
        SPBasicSuite basic{}; basic.AcquireSuite = acquire; basic.ReleaseSuite = release;
        ADOBESDK_ControlSurfacePluginFuncs funcs{};
        check(entry(nullptr, 1, 0, 1, &funcs) != kSPNoError, "Null host accepted");
        check(entry(&basic, 1, 0, kADOBESDK_ControlSurfaceHost_Audition, &funcs) != kSPNoError, "Wrong host accepted");
        check(entry(&basic, 1, 0, kADOBESDK_ControlSurfaceHost_PremierePro, &funcs) == kSPNoError, "Premiere identity rejected");
        const char* catalogs[] = { "startup-failure", "connect-failure", "command-ref-failure", "normal", "row-failure", "partial", "empty" };
        const char* requests[] = { "idle", "match", "mismatch", "future", "before-connect", "playing", "decimal-mode",
                                   "no-transport", "extra-line", "wrong-nonce", "locked" };
        std::vector<std::string> all(std::begin(catalogs), std::end(catalogs));
        all.insert(all.end(), std::begin(requests), std::end(requests));
        for (const auto& test : all) {
            scenario = test;
            executed.clear();
            const bool isRequest = std::find(std::begin(requests), std::end(requests), test) != std::end(requests);
            auto error = funcs.Startup();
            if (scenario == "startup-failure") { check(error != kSPNoError, "Startup failure hidden"); clean(0); continue; }
            check(error == kSPNoError, "Startup failed");
            auto* plugin = static_cast<const ADOBESDK_ControlSurfacePluginSuite1*>(registrations.at(std::string(kADOBESDK_ControlSurfacePluginSuite) + "1"));
            auto* surface = static_cast<const ADOBESDK_ControlSurfaceSuite2*>(registrations.at(std::string(kADOBESDK_ControlSurfaceSuite) + "2"));
            check(registrations.count(std::string(kADOBESDK_ControlSurfaceTransportSuite) + "1") == 1, "Plugin transport suite not registered");
            ADOBESDK_ControlSurfacePluginRef instance = nullptr;
            check(funcs.CreatePluginInstance(&instance) == kSPNoError && instance, "Create instance failed");
            ADOBESDK_ControlSurfaceRef ref = nullptr;
            const int64_t beforeConnect = unixMs();
            error = plugin->Connect(instance, reinterpret_cast<ADOBESDK_ControlSurfaceHostRef>(&hostSuite), &ref);
            if (scenario == "connect-failure" || scenario == "command-ref-failure") check(error != kSPNoError && ref == nullptr, "Connection failure hidden");
            else {
                check(error == kSPNoError && ref, "Connect failed");
                auto* buttonSuite = static_cast<const ADOBESDK_ControlSurfaceCommandSuite1*>(registrations.at(std::string(kADOBESDK_ControlSurfaceCommandSuite) + "1"));
                ADOBESDK_ControlSurfaceCommandRef pluginCommands = nullptr;
                check(surface->GetCommandRef(ref, &pluginCommands) == kSPNoError && pluginCommands, "Plugin command interface missing");
                ADOBESDK_ControlSurfaceTransportRef pluginTransport = nullptr;
                check(surface->GetTransportRef(ref, &pluginTransport) == kSPNoError && pluginTransport, "Plugin transport interface missing");
                uint32_t buttonTotal = 99;
                check(buttonSuite->GetUserButtonCount(pluginCommands, &buttonTotal) == kSPNoError && buttonTotal == 0, "Interface exposed buttons");
                ADOBESDK_String invalidButton{};
                check(buttonSuite->GetUserButtonIDAtIndex(pluginCommands, 0, &invalidButton) != kSPNoError, "Invalid button accepted");
                const unsigned batches = scenario == "partial" ? 1 : 4;
                for (unsigned i = 0; i < batches; ++i) check(surface->Update(ref) == kSPNoError, "Update failed");
                if (isRequest) runRequest(surface, ref, beforeConnect);
            }
            check(plugin->Disconnect(instance) == kSPNoError, "Disconnect failed");
            check(funcs.DeletePluginInstance(instance) == kSPNoError, "Delete failed");
            check(funcs.Shutdown() == kSPNoError, "Shutdown failed");
            clean(scenario == "match" ? 1 : 0);
            std::cout << "PASS " << scenario << '\n';
        }
        FreeLibrary(module);
        std::cout << "PASS host identity, SDK string ownership, suite cleanup, one fixed command per valid request\n";
        return 0;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
