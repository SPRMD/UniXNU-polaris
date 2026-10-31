"""Execute production touch/HID methods with host stubs; no device access.

Run on Linux/WSL: python3 -m unittest discover -s tests -p test_polaris_touch_hid_runtime.py -v
"""
import ast
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def method(source, signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


class BuildCommandTests(unittest.TestCase):
    def test_compile_record_dependency_flags_are_removed_as_pairs(self):
        tree = ast.parse((ROOT / "scripts/build-polaris-hid-input.py").read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "compile_source")
        class Runner:
            PIPE = 1
            STDOUT = 2
            @staticmethod
            def run(command, **kwargs):
                return type("Result", (), {"returncode": 0, "stdout": ""})()
        for flags in (["-MF", "old.d", "-MJ", "old.json", "-MT", "old.o", "-MQ", "old.o"],
                      ["-MFold.d", "-MJold.json", "-MTold.o", "-MQold.o"]):
            scope = dict(Path=Path, subprocess=Runner, OUT=Path("out"), BUILD_ROOT=Path("tree"),
                         record={"arguments": ["clang++", "-c", "old.cpp", "-o", "old.o", "-MMD", "-MP"] + flags + ["-DKEEP=1"],
                                 "file": "old.cpp", "directory": "."})
            exec(compile(ast.Module(body=[function], type_ignores=[]), "recipe", "exec"), scope)
            command, status, _ = scope["compile_source"](Path("new.cpp"), Path("new.o"))
            self.assertEqual(command[:6], ["clang++", "-c", "new.cpp", "-o", "new.o", "-DKEEP=1"])
            self.assertFalse(any(x.startswith(("-MF", "-MJ", "-MT", "-MQ", "-MMD")) for x in command))
            self.assertEqual(status, 0)


@unittest.skipUnless(shutil.which("clang++"), "clang++ host compiler required")
class RuntimeTests(unittest.TestCase):
    def compile_run(self, code, flags=()):
        with tempfile.TemporaryDirectory(prefix="polaris-touch-") as tmp:
            source = Path(tmp) / "test.cpp"
            binary = Path(tmp) / "test"
            source.write_text(code)
            subprocess.run(["clang++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                            "-Wno-unused-variable", "-Wno-missing-field-initializers", "-pthread", *flags,
                            str(source), "-o", str(binary)], check=True, capture_output=True, text=True)
            subprocess.run([str(binary)], check=True, timeout=15)

    def test_producer_publication_registration_and_drain(self):
        source = (ROOT / "drivers/PolarisSynapticsTouch/PolarisTouchRuntime.c").read_text()
        # Only substitute ARM barriers for host fences; execute the actual producer and sink code.
        source = re.sub(r'__asm__ volatile\("[^"\n]+" ::: "memory"\);',
                        '__atomic_thread_fence(__ATOMIC_SEQ_CST);', source)
        self.compile_run(r'''#include <cassert>
#include <atomic>
#include <chrono>
#include <thread>
#include <cstdio>
''' + source + r'''
vm_offset_t ml_io_map(vm_offset_t, unsigned long) { assert(false); return 0; }
int PE_parse_boot_argn(const char *, void *, unsigned int) { return 0; }
void IOSleep(unsigned ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); }
void IODelay(unsigned) {}
int kernel_thread_start(void (*)(void *, int), void *, void **) { return -1; }
void thread_deallocate(void *) {}
static unsigned calls;
static void observe(void *p) {
    assert(p == &calls);
    assert((polaris_touch_seq & 1) == 0);
    ++calls;
}
static std::atomic<bool> entered{false}, leave{false}, detached{false};
static void blocking(void *) {
    entered = true;
    while (!leave) std::this_thread::yield();
}
int main() {
    contact_down[2] = true; contact_x[2] = 1079; contact_y[2] = 2159;
    publish_contacts();
    assert(polaris_touch_count == 1 && polaris_touch_seq == 2);
    assert(polaris_touch_ids[0] == 2 && polaris_touch_x[0] == 1079);
    assert(polaris_touch_hid_reports == 0); // Producer is not a HID delivery.
    polaris_touch_runtime_set_sink(observe, &calls);
    assert(calls == 1); // Registration replays the held frame.
    release_contacts();
    assert(calls == 2 && polaris_touch_count == 0 && polaris_touch_seq == 4);
    polaris_touch_runtime_set_sink(nullptr, nullptr);
    publish_contacts(); assert(calls == 2);
    // Registration calls the callback under the same lifetime guard as publish.
    std::thread publisher([] { polaris_touch_runtime_set_sink(blocking, nullptr); });
    while (!entered) std::this_thread::yield();
    std::thread stopper([] { polaris_touch_runtime_set_sink(nullptr, nullptr); detached = true; });
    IOSleep(10); assert(!detached);
    leave = true; publisher.join(); stopper.join();
    assert(detached); publish_contacts();
    uint8_t invalid[8] = {2}; int x=0,y=0; bool present=false;
    assert(!decode_frame(invalid,&x,&y,&present));
}
''')

    def test_runtime_stops_on_consecutive_malformed_frames(self):
        source = (ROOT / "drivers/PolarisSynapticsTouch/PolarisTouchRuntime.c").read_text()
        source = re.sub(r'__asm__ volatile\("[^"\n]+" ::: "memory"\);',
                        '__atomic_thread_fence(__ATOMIC_SEQ_CST);', source)
        original = method(source, "static bool\nrmi_read(")
        source = source.replace(original, "static bool rmi_read(uint16_t reg, uint8_t *buffer, unsigned length) { return mock_read(reg,buffer,length); }")
        self.compile_run(r'''#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdio>
static bool mock_read(uint16_t,uint8_t *,unsigned);
''' + source + r'''
static uint32_t pads[0x23000/4],reset_pad[0x1000/4];
static unsigned frames;
vm_offset_t ml_io_map(vm_offset_t p, unsigned long) {
    return (vm_offset_t)(p==TLMM_NORTH_PA ? pads : reset_pad);
}
int PE_parse_boot_argn(const char *,void *,unsigned int) { return 0; }
void IOSleep(unsigned) {}
void IODelay(unsigned) {}
int kernel_thread_start(void (*)(void *,int),void *,void **) { return -1; }
void thread_deallocate(void *) {}
static bool mock_read(uint16_t reg,uint8_t *b,unsigned n) {
    if(reg==0xe3) { const uint8_t f[]={0x2c,0x23,0x0c,0x06,0,1}; assert(n==6);memcpy(b,f,6);return true; }
    if(reg==0xdd) { const uint8_t f[]={0x49,0,0x12,0x08,0,0x12}; assert(n==6);memcpy(b,f,6);return true; }
    if(reg==0x4d)return false; // Retain the bounded one-slot fallback.
    assert(reg==8 && n==8 && frames<24);
    memset(b,0,n);
    // Eight separated failures must not stop polling; eight consecutive do.
    b[0]=(frames<16 && frames%2) ? 1 : 2;
    ++frames;return true;
}
int main() {
    pads[(SDA_CFG+GPIO_IO)/4]=1;pads[(SCL_CFG+GPIO_IO)/4]=1;
    pads[SDA_CFG/4]=0x155;pads[SCL_CFG/4]=0x166;
    touch_thread(nullptr,0);
    assert(frames==24 && polaris_touch_runtime_state[5]==16);
    assert(polaris_touch_count==0 && !(polaris_touch_seq&1));
    assert(pads[SDA_CFG/4]==0x155 && pads[SCL_CFG/4]==0x166);
}
''')

    def test_hid_retries_and_release_report(self):
        source = (ROOT / "drivers/PolarisHidInput/PolarisHidInput.cpp").read_text()
        send = method(source, "    void touchSend()")
        send = send.replace('__asm__ volatile("dmb ish":::"memory");', '__atomic_thread_fence(__ATOMIC_SEQ_CST);')
        transform = method(source, "    static unsigned transformCoordinate")
        self.compile_run(r'''#include <cassert>
#include <cstdint>
#include <cstring>
#include <vector>
#define TOUCH_FINGERS 10
using IOReturn = int;
constexpr int kIOReturnSuccess=0,kIOReturnNoMemory=-1,kIODirectionNone=0;
volatile uint32_t polaris_touch_seq,polaris_touch_count,polaris_touch_hid_reports;
volatile int polaris_touch_ids[10],polaris_touch_x[10],polaris_touch_y[10];
namespace edge { unsigned polaris_touch_hid_multi[3]; }
void polaris_hid_input_observed(unsigned,int) {}
static bool failAlloc=false;
struct IOBufferMemoryDescriptor {
    std::vector<unsigned char> bytes;
    static IOBufferMemoryDescriptor *withBytes(const void *p,size_t n,int) {
        if(failAlloc)return nullptr;
        auto *b=new IOBufferMemoryDescriptor;
        b->bytes.assign((const unsigned char *)p,(const unsigned char *)p+n);return b;
    }
};
#define OSSafeReleaseNULL(p) do { delete p; p=nullptr; } while(0)
struct PolarisHidInput {
    bool ready=false;
    int result=0;
    uint32_t lastSeq=0;
    int prevIds[10]={-1,-1,-1,-1,-1,-1,-1,-1,-1,-1},prevX[10]={},prevY[10]={};
    std::vector<unsigned char> report;
    bool hasEventDriverCached() { return ready; }
    int handleReport(IOBufferMemoryDescriptor *b,unsigned,unsigned) { report=b->bytes;return result; }
''' + transform + send + r'''
};
int main() {
    PolarisHidInput hid;
    polaris_touch_seq=2;polaris_touch_count=1;polaris_touch_ids[0]=2;
    polaris_touch_x[0]=1079;polaris_touch_y[0]=2159;
    hid.touchSend();assert(hid.lastSeq==0);
    hid.ready=true;failAlloc=true;
    hid.touchSend();assert(hid.lastSeq==0 && hid.prevIds[0]==-1);
    failAlloc=false;hid.result=-2;
    hid.touchSend();assert(hid.lastSeq==0 && hid.prevIds[0]==-1);
    hid.result=0;hid.touchSend();
    assert(hid.lastSeq==2 && hid.prevIds[0]==2 && polaris_touch_hid_reports==1);
    assert(hid.report.size()==62 && hid.report[0]==3 && hid.report[1]==3);
    assert(hid.report[3]==255 && hid.report[4]==127 && hid.report[5]==255 && hid.report[6]==127);
    hid.touchSend();assert(polaris_touch_hid_reports==1);
    polaris_touch_seq=3;polaris_touch_count=0;
    hid.touchSend();assert(hid.lastSeq==2);
    polaris_touch_seq=4;hid.result=-2;
    hid.touchSend();assert(hid.prevIds[0]==2 && hid.lastSeq==2);
    hid.result=0;hid.touchSend();
    assert(hid.prevIds[0]==-1 && hid.lastSeq==4);
    assert(hid.report[1]==2 && hid.report[2]==2 && hid.report[61]==1);
    assert(polaris_touch_hid_reports==2);
}
''')


if __name__ == "__main__":
    unittest.main()
