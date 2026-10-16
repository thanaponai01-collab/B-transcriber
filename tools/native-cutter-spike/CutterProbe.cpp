// Experimental Control Surface plugin: lists the host's commands and runs one fixed command,
// Add Edit to All Tracks, once per request file written by the CutDeck helper
// (docs/research/cutdeck-native-cutter-2026-10-16.md, "Plan: one Add Edit"). SDK declarations
// come from Premiere Pro 26.0 C++ SDK/Examples/Headers; SDK files are not redistributed.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>
#include <filesystem>
#include <atomic>
#include <fstream>
#include <memory>
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
SPBasicSuite* basic = nullptr;
SPSuitesSuite* suites = nullptr;
SPSuiteListRef suiteList = nullptr;
ADOBESDK_StringSuite1* strings = nullptr;
std::atomic<unsigned> logCounter{0};
// The only command this plugin ever executes; a request cannot name another.
const char* const kSplitContext = "global";
const char* const kSplitCommand = "cmd.sequence.razorateditline.all";
const int64_t kRequestMaxAgeMs = 10000;

std::filesystem::path spikeDirectory() {
    wchar_t temp[MAX_PATH + 1]{};
    DWORD length = GetTempPathW(MAX_PATH + 1, temp);
    if (!length || length > MAX_PATH) return {};
    return std::filesystem::path(temp) / L"CutDeckCutterSpike";
}
int64_t unixMs() {
    FILETIME now{};
    GetSystemTimeAsFileTime(&now);
    const uint64_t t = (uint64_t(now.dwHighDateTime) << 32) | now.dwLowDateTime;
    return int64_t(t / 10000) - 11644473600000LL;
}
void trace(const char* stage, SPErr error = kSPNoError) noexcept {
    try {
        const auto directory = spikeDirectory();
        if (directory.empty()) return;
        std::filesystem::create_directories(directory);
        const auto file = directory / (L"lifecycle-" + std::to_wstring(GetCurrentProcessId()) + L".jsonl");
        std::ofstream log(file, std::ios::binary | std::ios::app);
        log << "{\"stage\":\"" << stage << "\",\"error\":" << error << "}\n";
    } catch (...) { }
}

template<class T> SPErr acquire(const char* name, int version, T** out) {
    const void* acquired = nullptr;
    SPErr error = basic->AcquireSuite(name, version, &acquired);
    *out = const_cast<T*>(static_cast<const T*>(acquired));
    return error;
}

SPErr makeString(const char* text, ADOBESDK_String* out) {
    return strings->AllocateFromUTF8(reinterpret_cast<const ADOBESDK_UTF8Char*>(text), out);
}

struct HostString {
    ADOBESDK_String value{};
    ~HostString() { strings->DisposeString(&value); }
    std::string utf8() const {
        uint32_t size = 256;
        std::vector<ADOBESDK_UTF8Char> buffer(size);
        SPErr error = strings->CopyToUTF8String(&value, buffer.data(), &size);
        if (error == kADOBESDK_Error_StringBufferTooSmall) {
            buffer.resize(size);
            error = strings->CopyToUTF8String(&value, buffer.data(), &size);
        }
        if (error != kSPNoError) throw error;
        return reinterpret_cast<const char*>(buffer.data());
    }
};

std::string quote(const std::string& value) {
    const char* hex = "0123456789abcdef";
    std::string out = "\"";
    for (unsigned char c : value) {
        if (c == '"' || c == '\\') { out += '\\'; out += c; }
        else if (c < 0x20) { out += "\\u00"; out += hex[c >> 4]; out += hex[c & 15]; }
        else out += c;
    }
    return out + '"';
}

class Connection {
    ADOBESDK_ControlSurfaceHostSuite1* host = nullptr;
    ADOBESDK_ControlSurfaceHostCommandSuite1* commands = nullptr;
    ADOBESDK_ControlSurfaceHostCommandRef commandRef = nullptr;
    ADOBESDK_ControlSurfaceHostTransportSuite1* transport = nullptr;
    ADOBESDK_ControlSurfaceHostTransportRef transportRef = nullptr;
    std::ofstream output;
    uint32_t total = 0, examined = 0, failures = 0;
    bool finished = false, updated = false;
    int64_t connectedMs = 0;
    uint64_t lastPollTick = 0;
public:
    ~Connection() {
        if (output.is_open() && !finished) finish(false);
        if (transport) basic->ReleaseSuite(kADOBESDK_ControlSurfaceHostTransportSuite, 1);
        if (commands) basic->ReleaseSuite(kADOBESDK_ControlSurfaceHostCommandSuite, 1);
        if (host) basic->ReleaseSuite(kADOBESDK_ControlSurfaceHostSuite, 1);
    }
    SPErr connect(ADOBESDK_ControlSurfaceHostRef ref) {
        SPErr error = acquire(kADOBESDK_ControlSurfaceHostSuite, 1, &host);
        trace("acquire_host_suite", error);
        if (error != kSPNoError) return error;
        error = acquire(kADOBESDK_ControlSurfaceHostCommandSuite, 1, &commands);
        trace("acquire_command_suite", error);
        if (error != kSPNoError) return error;
        error = host->GetCommandRef(ref, &commandRef);
        trace("get_command_ref", error);
        if (error != kSPNoError) return error;
        error = commands->GetCommandCount(commandRef, &total);
        trace("get_command_count", error);
        if (error != kSPNoError) return error;
        // Optional: without the transport the playhead can't be checked, so every request is refused.
        SPErr transportError = acquire(kADOBESDK_ControlSurfaceHostTransportSuite, 1, &transport);
        if (transportError == kSPNoError) transportError = host->GetTransportRef(ref, &transportRef);
        trace("get_transport_ref", transportError);
        if (transportError != kSPNoError) {
            if (transport) basic->ReleaseSuite(kADOBESDK_ControlSurfaceHostTransportSuite, 1);
            transport = nullptr;
            transportRef = nullptr;
        }
        connectedMs = unixMs();
        auto directory = spikeDirectory();
        if (directory.empty()) return kSPBadParameterError;
        std::filesystem::create_directories(directory);
        auto file = directory / (L"commands-" + std::to_wstring(GetCurrentProcessId())
            + L"-" + std::to_wstring(GetTickCount64()) + L"-" + std::to_wstring(++logCounter) + L".json");
        output.open(file, std::ios::binary | std::ios::out);
        if (!output) { trace("catalog_open_failed", kSPBadParameterError); return kSPBadParameterError; }
        trace("catalog_opened");
        output << "{\"schema\":1,\"mode\":\"read-only\",\"pid\":" << GetCurrentProcessId()
            << ",\"reportedCommands\":" << total << ",\"commands\":[";
        return output ? kSPNoError : kSPBadParameterError;
    }
    void finish(bool completed) noexcept {
        try {
            output << "],\"examinedCommands\":" << examined << ",\"errors\":" << failures
                << ",\"complete\":" << (completed && failures == 0 ? "true" : "false") << "}\n";
            output.close();
        } catch (...) { }
        finished = true;
        trace(completed ? "catalog_finished" : "catalog_interrupted");
    }
    SPErr update() {
        if (!updated) { updated = true; trace("first_update"); }
        if (finished) return pollRequest();
        // Bounded work on the host callback; no worker thread calls host APIs.
        for (unsigned batch = 0; batch < 64 && examined < total; ++batch) {
            HostString contextID, contextName, commandID, commandName;
            SPErr error = commands->GetCommand(commandRef, examined,
                &contextID.value, &contextName.value, &commandID.value, &commandName.value);
            if (examined) output << ',';
            output << "{\"index\":" << examined << ",\"error\":" << error;
            if (error == kSPNoError) {
                try {
                    const auto context = contextID.utf8(), contextLabel = contextName.utf8();
                    const auto command = commandID.utf8(), label = commandName.utf8();
                    output << ",\"contextID\":" << quote(context) << ",\"contextName\":" << quote(contextLabel)
                        << ",\"commandID\":" << quote(command) << ",\"commandName\":" << quote(label);
                } catch (...) { ++failures; output << ",\"stringDecodeFailed\":true"; }
            } else ++failures;
            output << '}';
            ++examined;
            if (!output) { finish(false); return kSPBadParameterError; }
        }
        if (examined == total) finish(true);
        return kSPNoError;
    }

private:
    struct Outcome { std::string status = "refused", reason, timeBefore, timeAfter; uint32_t mode = 0; SPErr error = kSPNoError; };

    SPErr timeDisplay(std::string* out, uint32_t* mode) {
        HostString value;
        SPErr error = transport->GetTimeDisplayString(transportRef, mode, 64, &value.value);
        if (error == kSPNoError) *out = value.utf8();
        return error;
    }
    static bool validNonce(const std::string& nonce) {
        if (nonce.size() != 32) return false;
        for (char c : nonce) if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
        return true;
    }
    static bool validTimecode(const std::string& value) {
        if (value.empty() || value.size() > 32) return false;
        for (char c : value) if (!((c >= '0' && c <= '9') || c == ':' || c == ';' || c == '.')) return false;
        return true;
    }

    // One request per poll, polled every 100 ms from Update. The file is deleted before anything
    // runs, so a request executes once at most, even if its result can't be written.
    SPErr pollRequest() {
        const uint64_t tick = GetTickCount64();
        if (tick - lastPollTick < 100) return kSPNoError;
        lastPollTick = tick;
        const auto directory = spikeDirectory();
        std::error_code ignored;
        if (directory.empty() || !std::filesystem::is_directory(directory, ignored)) return kSPNoError;
        std::filesystem::path file;
        for (const auto& entry : std::filesystem::directory_iterator(directory, ignored)) {
            const auto name = entry.path().filename().wstring();
            if (name.rfind(L"request-", 0) == 0 && entry.path().extension() == L".txt") { file = entry.path(); break; }
        }
        if (file.empty()) return kSPNoError;
        const auto stem = file.stem().wstring();
        std::string fileNonce;
        for (size_t i = 8; i < stem.size(); ++i) fileNonce += stem[i] < 128 ? char(stem[i]) : '?';
        std::string nonce, expected, created, extra;
        {
            std::ifstream in(file, std::ios::binary);
            std::getline(in, nonce); std::getline(in, expected); std::getline(in, created); std::getline(in, extra);
        }
        if (!DeleteFileW(file.c_str())) {
            // Never execute a request that could be picked up a second time.
            trace("request_not_consumed", kSPBadParameterError);
            return kSPNoError;
        }
        trace("request_consumed");
        int64_t createdMs = 0;
        try { size_t used = 0; createdMs = std::stoll(created, &used); if (used != created.size()) createdMs = 0; }
        catch (...) { createdMs = 0; }
        const int64_t now = unixMs();
        Outcome outcome;
        if (!validNonce(nonce) || nonce != fileNonce || !validTimecode(expected) || !createdMs || !extra.empty()) outcome.reason = "malformed";
        else if (createdMs < connectedMs) outcome.reason = "before_connect";
        else if (now - createdMs > kRequestMaxAgeMs || createdMs - now > 2000) outcome.reason = "stale";
        else if (!transport) outcome.reason = "no_transport";
        else {
            ADOBESDK_Boolean playing = kAdobesdk_False;
            if ((outcome.error = transport->GetPlayState(transportRef, &playing)) != kSPNoError) outcome.reason = "play_state_failed";
            else if (playing) outcome.reason = "playing";
            else if ((outcome.error = timeDisplay(&outcome.timeBefore, &outcome.mode)) != kSPNoError) outcome.reason = "time_display_failed";
            else if (outcome.mode != kADOBESDK_ControlSurfaceTimeDisplayMode_SMPTE) outcome.reason = "display_mode";
            else if (outcome.timeBefore != expected) outcome.reason = "timecode_mismatch";
            else {
                HostString context, command;
                outcome.error = makeString(kSplitContext, &context.value);
                if (outcome.error == kSPNoError) outcome.error = makeString(kSplitCommand, &command.value);
                if (outcome.error != kSPNoError) outcome.reason = "string_failed";
                else {
                    trace("execute");
                    outcome.error = commands->ExecuteCommand(commandRef, &context.value, &command.value);
                    outcome.status = "executed";
                    uint32_t mode = 0;
                    timeDisplay(&outcome.timeAfter, &mode);
                }
            }
        }
        trace(outcome.status == "executed" ? "executed" : "refused", outcome.error);
        writeResult(directory, validNonce(fileNonce) ? fileNonce : std::string("invalid"), expected, now - createdMs, outcome);
        return kSPNoError;
    }

    static void writeResult(const std::filesystem::path& directory, const std::string& nonce, const std::string& expected,
                            int64_t pickupMs, const Outcome& o) noexcept {
        try {
            const std::wstring wide(nonce.begin(), nonce.end());
            const auto partial = directory / (L"partial-" + wide + L".json");
            {
                std::ofstream out(partial, std::ios::binary | std::ios::trunc);
                out << "{\"schema\":1,\"nonce\":" << quote(nonce) << ",\"pid\":" << GetCurrentProcessId()
                    << ",\"status\":" << quote(o.status) << ",\"reason\":" << quote(o.reason)
                    << ",\"error\":" << o.error << ",\"context\":" << quote(kSplitContext)
                    << ",\"command\":" << quote(kSplitCommand) << ",\"expected\":" << quote(expected)
                    << ",\"timeBefore\":" << quote(o.timeBefore) << ",\"timeAfter\":" << quote(o.timeAfter)
                    << ",\"displayMode\":" << o.mode << ",\"pickupMs\":" << pickupMs << "}\n";
            }
            MoveFileExW(partial.c_str(), (directory / (L"result-" + wide + L".json")).c_str(), MOVEFILE_REPLACE_EXISTING);
        } catch (...) { }
    }
};

struct Instance { std::unique_ptr<Connection> connection; };

SPErr connect(ADOBESDK_ControlSurfacePluginRef ref, ADOBESDK_ControlSurfaceHostRef host,
              ADOBESDK_ControlSurfaceRef* out) {
    if (!ref || !host || !out) return kSPBadParameterError;
    *out = nullptr;
    trace("connect");
    try {
        auto* instance = reinterpret_cast<Instance*>(ref);
        if (instance->connection) return kSPBadParameterError;
        auto connection = std::make_unique<Connection>();
        SPErr error = connection->connect(host);
        trace("connect_result", error);
        if (error != kSPNoError) return error;
        instance->connection = std::move(connection);
        *out = reinterpret_cast<ADOBESDK_ControlSurfaceRef>(instance);
        return kSPNoError;
    } catch (...) { return kSPBadParameterError; }
}
SPErr disconnect(ADOBESDK_ControlSurfacePluginRef ref) {
    if (!ref) return kSPBadParameterError;
    trace("disconnect");
    reinterpret_cast<Instance*>(ref)->connection.reset();
    return kSPNoError;
}
SPErr pluginID(ADOBESDK_ControlSurfacePluginRef, ADOBESDK_String* out) { return makeString("CutDeck.NativeCutter.ReadOnlySpike", out); }
SPErr displayName(ADOBESDK_ControlSurfacePluginRef, ADOBESDK_String* out) { return makeString("CutDeck Cutter Probe (Add Edit test)", out); }
SPErr getSettings(ADOBESDK_ControlSurfacePluginRef, ADOBESDK_String* out) { return makeString("", out); }
SPErr setSettings(ADOBESDK_ControlSurfacePluginRef, const ADOBESDK_String*) { return kSPNoError; }
SPErr hasDialog(ADOBESDK_ControlSurfacePluginRef, ADOBESDK_Boolean* out) { *out = kAdobesdk_False; return kSPNoError; }
SPErr dialog(ADOBESDK_ControlSurfacePluginRef, void*, ADOBESDK_Boolean* changed) { *changed = kAdobesdk_False; return kSPUnimplementedError; }
SPErr focus(ADOBESDK_ControlSurfacePluginRef) { return kSPNoError; }
SPErr configID(ADOBESDK_ControlSurfaceRef, ADOBESDK_String* out) { return makeString("CutDeck.NativeCutter.ReadOnlySpike", out); }
SPErr flags(ADOBESDK_ControlSurfaceRef, uint32_t* out) { *out = kADOBESDK_ControlSurfaceFlag_CanDisplayUnicode; return kSPNoError; }
template<class T> SPErr noInterface(ADOBESDK_ControlSurfaceRef, T* out) { *out = nullptr; return kSPNoError; }
SPErr update(ADOBESDK_ControlSurfaceRef ref) {
    if (!ref) return kSPBadParameterError;
    auto* instance = reinterpret_cast<Instance*>(ref);
    try { return instance->connection ? instance->connection->update() : kSPBadParameterError; }
    catch (...) { instance->connection.reset(); return kSPBadParameterError; }
}
SPErr commandInterface(ADOBESDK_ControlSurfaceRef ref, ADOBESDK_ControlSurfaceCommandRef* out) {
    if (!ref || !out) return kSPBadParameterError;
    trace("plugin_command_interface");
    *out = reinterpret_cast<ADOBESDK_ControlSurfaceCommandRef>(ref);
    return kSPNoError;
}
SPErr buttonCount(ADOBESDK_ControlSurfaceCommandRef, uint32_t* out) {
    if (!out) return kSPBadParameterError;
    *out = 0;
    return kSPNoError;
}
SPErr buttonID(ADOBESDK_ControlSurfaceCommandRef, uint32_t, ADOBESDK_String*) { return kSPBadParameterError; }
SPErr buttonName(ADOBESDK_ControlSurfaceCommandRef, const ADOBESDK_String*, ADOBESDK_String*) { return kSPBadParameterError; }
SPErr setButton(ADOBESDK_ControlSurfaceCommandRef, const ADOBESDK_String*, const ADOBESDK_String*, const ADOBESDK_String*) { return kSPBadParameterError; }
SPErr getButton(ADOBESDK_ControlSurfaceCommandRef, const ADOBESDK_String*, ADOBESDK_String*, ADOBESDK_String*) { return kSPBadParameterError; }
ADOBESDK_ControlSurfaceCommandSuite1 commandSuite = { buttonCount, buttonID, buttonName, setButton, getButton };
// The host's transport reference, like its command reference, needs the plugin-side suite
// (the SDK sample registers both). This plugin has no transport LEDs, so it ignores the calls.
SPErr transportInterface(ADOBESDK_ControlSurfaceRef ref, ADOBESDK_ControlSurfaceTransportRef* out) {
    if (!ref || !out) return kSPBadParameterError;
    trace("plugin_transport_interface");
    *out = reinterpret_cast<ADOBESDK_ControlSurfaceTransportRef>(ref);
    return kSPNoError;
}
SPErr ignoreState(ADOBESDK_ControlSurfaceTransportRef, ADOBESDK_Boolean) { return kSPNoError; }
SPErr ignoreTime(ADOBESDK_ControlSurfaceTransportRef, uint32_t, const ADOBESDK_String*) { return kSPNoError; }
ADOBESDK_ControlSurfaceTransportSuite1 transportSuite = {
    ignoreState, ignoreState, ignoreState, ignoreState, ignoreState, ignoreState, ignoreState, ignoreTime
};
ADOBESDK_ControlSurfaceSuite2 surfaceSuite = {
    configID, flags, transportInterface,
    noInterface<ADOBESDK_ControlSurfaceMixerRef>, noInterface<ADOBESDK_ControlSurfaceMarkerRef>,
    commandInterface, update, noInterface<ADOBESDK_ControlSurfaceLumetriRef>
};
ADOBESDK_ControlSurfacePluginSuite1 pluginSuite = {
    connect, disconnect, pluginID, displayName, getSettings, setSettings, hasDialog, dialog, focus, focus
};
SPErr shutdown() {
    if (suiteList) { suites->FreeSuiteList(suiteList); suiteList = nullptr; }
    if (suites) { basic->ReleaseSuite(kSPSuitesSuite, kSPSuitesSuiteVersion); suites = nullptr; }
    if (strings) { basic->ReleaseSuite(kADOBESDK_StringSuite, 1); strings = nullptr; }
    return kSPNoError;
}
SPErr startup() {
    trace("startup");
    SPErr error = acquire(kADOBESDK_StringSuite, 1, &strings);
    if (error == kSPNoError) error = acquire(kSPSuitesSuite, kSPSuitesSuiteVersion, &suites);
    if (error == kSPNoError) error = suites->AllocateSuiteList(kSPRuntimeStringPool, kSPRuntimePluginList, &suiteList);
    if (error == kSPNoError) {
        SPSuiteRef added = nullptr;
        error = suites->AddSuite(suiteList, nullptr, kADOBESDK_ControlSurfacePluginSuite, 1, 1, &pluginSuite, &added);
        if (error == kSPNoError) error = suites->AddSuite(suiteList, nullptr, kADOBESDK_ControlSurfaceCommandSuite, 1, 1, &commandSuite, &added);
        if (error == kSPNoError) error = suites->AddSuite(suiteList, nullptr, kADOBESDK_ControlSurfaceTransportSuite, 1, 1, &transportSuite, &added);
        if (error == kSPNoError) error = suites->AddSuite(suiteList, nullptr, kADOBESDK_ControlSurfaceSuite, 2, 2, &surfaceSuite, &added);
        if (error == kSPNoError) error = suites->AddSuite(suiteList, nullptr, kADOBESDK_ControlSurfaceSuite, 1, 1, &surfaceSuite, &added);
    }
    trace("startup_result", error);
    if (error != kSPNoError) shutdown();
    return error;
}
SPErr createInstance(ADOBESDK_ControlSurfacePluginRef* out) {
    if (!out) return kSPBadParameterError;
    try { *out = reinterpret_cast<ADOBESDK_ControlSurfacePluginRef>(new Instance); return kSPNoError; }
    catch (...) { *out = nullptr; return kSPOutOfMemoryError; }
}
SPErr deleteInstance(ADOBESDK_ControlSurfacePluginRef ref) { delete reinterpret_cast<Instance*>(ref); return kSPNoError; }
SPErr getSuiteList(SPSuiteListRef* out) { *out = suiteList; return kSPNoError; }
ADOBESDK_ControlSurfacePluginFuncs functions = { startup, shutdown, createInstance, deleteInstance, getSuiteList };
}

extern "C" ADOBE_CONTROLSURFACE_API SPErr EntryPoint(SPBasicSuite* inBasic, uint32_t, uint32_t,
    ADOBESDK_ControlSurfaceHostID host, ADOBESDK_ControlSurfacePluginFuncs* out) {
    if (!inBasic || !out || host != kADOBESDK_ControlSurfaceHost_PremierePro) return kSPBadParameterError;
    trace("entrypoint");
    basic = inBasic;
    *out = functions;
    return kSPNoError;
}
