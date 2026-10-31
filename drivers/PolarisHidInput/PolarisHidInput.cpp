// SPDX-License-Identifier: BSD-2-Clause-Patent
// Explicit offline keyboard/consumer input source. Uses the unchanged original
// HID parser and event dispatch; no user-client entitlement is substituted.
#include "OriginalHidDeviceABI.h"
#include <IOKit/IOBufferMemoryDescriptor.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/IOTimerEventSource.h>
#include <libkern/c++/OSString.h>
#include <libkern/c++/OSIterator.h>
#include <pexpert/pexpert.h>
extern "C" void polaris_hid_input_observed(unsigned,int);
extern "C" void polaris_hid_live_checkpoint(IOService *);
extern "C" bool polaris_hid_input_requested(void);
extern "C" void polaris_touch_runtime_set_sink(void (*)(void *), void *) __attribute__((weak_import));
// Optional hardware buttons fed by the board button driver: a mask of report 2 bits, sent on every change.
extern "C" void polaris_buttons_set_sink(void (*)(void *, uint32_t), void *) __attribute__((weak_import));
// Optional touch digitizer fed by the board touch probe (drivers/PolarisSynapticsTouch/PolarisTouchRuntime.c): finger set published with a seqlock.
extern "C" {
extern volatile uint32_t polaris_touch_seq, polaris_touch_count, polaris_touch_hid_reports;
extern volatile int polaris_touch_x[10], polaris_touch_y[10], polaris_touch_ids[10];
}
// Keyboard Application collection ensures the original generic keyboard
// personality can match. Report 2 carries the Consumer buttons, bit 0 Menu (Home),
// bit 1 Power, bit 2 Volume Increment, bit 3 Volume Decrement. Report 1 is an
// ordinary boot keyboard report.
static const unsigned char descriptor[]={
    0x05,0x01,0x09,0x06,0xa1,0x01,0x85,0x01,
    0x05,0x07,0x19,0xe0,0x29,0xe7,0x15,0x00,0x25,0x01,
    0x75,0x01,0x95,0x08,0x81,0x02,
    0x75,0x08,0x95,0x01,0x81,0x03,
    0x19,0x00,0x29,0x65,0x15,0x00,0x25,0x65,
    0x75,0x08,0x95,0x06,0x81,0x00,
    0x85,0x02,0x05,0x0c,0x09,0x40,0x09,0x30,0x09,0xe9,0x09,0xea,0x15,0x00,0x25,0x01,
    0x75,0x01,0x95,0x04,0x81,0x02,
    0x75,0x04,0x95,0x01,0x81,0x03,0xc0
};
// Report 3: ten-finger Touch Screen collection (Tip Switch, Touch Valid, Contact Identifier, X, Y per finger, then Contact Count).
// Touch Valid (0x47) is the finger confidence: IOHIDEventDriver turns a finger transducer whose value is 0 into a hand (palm), which
// multi-finger and system edge gestures ignore, so every finger, down or lifting, sends 1.
// Coordinates are normalised to 0..32767 on both axes by the producer.
#define FINGER_DESC \
    0x09,0x22,0xa1,0x02, 0x09,0x42,0x15,0x00,0x25,0x01,0x75,0x01,0x95,0x01,0x81,0x02, 0x09,0x47,0x81,0x02, 0x75,0x06,0x95,0x01,0x81,0x03, \
    0x09,0x51,0x75,0x08,0x95,0x01,0x15,0x00,0x26,0xff,0x00,0x81,0x02, \
    0x05,0x01,0x09,0x30,0x15,0x00,0x26,0xff,0x7f,0x75,0x10,0x95,0x01,0x81,0x02, 0x09,0x31,0x81,0x02, 0x05,0x0d, 0xc0,
static const unsigned char touchDescriptor[]={
    0x05,0x0d,0x09,0x04,0xa1,0x01,0x85,0x03,
    FINGER_DESC FINGER_DESC FINGER_DESC FINGER_DESC FINGER_DESC
    FINGER_DESC FINGER_DESC FINGER_DESC FINGER_DESC FINGER_DESC
    0x09,0x54,0x75,0x08,0x95,0x01,0x15,0x00,0x26,0xff,0x00,0x81,0x02,0xc0
};
#define TOUCH_FINGERS 10
// Edge contacts (int-163). A contact that starts within ~3 mm of a panel edge carries kIOHIDDigitizerEventFromEdgeTip (0x800) in its
// finger events' event mask for its whole life, as Apple's multitouch stack reports it (MultitouchHID). UIKit derives UITouch's edge
// type from that bit alone (_UIEventHIDTouchEdgeTypeForHIDEvent: 0x800/0x1000/0x2000/0x40000 -> 1..4), and every screen-edge
// recognizer of SpringBoard fails at once on edge type 0: int-162 logged edge=0 for touches starting 2 pt above the bottom edge and
// SBHomeGesturePanGestureRecognizer / SBFluidSwitcherScreenEdgePanGestureRecognizer going 0->5, so no home or switcher gesture.
// The original IOHIDEventDriver (IOHIDFamily-2031.120.4) never sets the bit. Its dispatchEvent (IOHIDEventService slot 198, the slot
// 37 of IOHIDFamily's indirect calls use) is wrapped for this device's driver only, in a copy of its vtable; the wrapper adds the bit
// to the finger children of each digitizer collection and calls the original. IOHIDEvent virtuals of that version: getType 18,
// getIntegerValue 23, setIntegerValue 24, getFixedValue 25 (setIntegerValue/getIntegerValue at +0xc0/+0xb8 in the driver's own
// calls); _children at +24 (IOHIDEvent.h; appendChild stores into it and free releases it). _parent is never set (appendChild only
// stores the child, int-163 skipped every finger by comparing it), so each child is an IOHIDEvent by its class instead.
namespace edge {
enum {kSlots=256,kDispatch=198,kGetType=18,kGetInteger=23,kSetInteger=24,kGetFixed=25,kContacts=256};
enum : uint32_t {kDigitizer=11,kX=0xB0000,kY=0xB0001,kIndex=0xB0005,kMask=0xB0007,kTouch=0xB0009,kMaskTouch=2,kFromEdgeTip=0x800};
// 48 panel pixels of the Polaris 1080 x 2160 panel, in the driver's normalised IOFixed coordinates.
static const int32_t kEdgeX=48*65536/1080,kEdgeY=48*65536/2160;
static uintptr_t originalDispatch;
static bool fromEdge[kContacts];
extern "C" {volatile uint32_t polaris_touch_edge_stats[4];}   // [0] installed, [1] contacts begun, [2] of them at an edge, [3] skipped events
// [0] reports with two or more fingers down, [1] the most fingers down in one report, [2] tip-up entries sent for vanished fingers
extern "C" {volatile uint32_t polaris_touch_hid_multi[3];}
template <typename R,typename... A> static R call(void *object,unsigned slot,A... args) {
    return reinterpret_cast<R (*)(void *,A...)>((*reinterpret_cast<uintptr_t **>(object))[slot])(object,args...);
}
// One finger event; true when it now carries the bit.
static bool mark(void *child) {
    if(call<uint32_t,IOOptionBits>(child,kGetType,0)!=kDigitizer)return false;   // the scan-time vendor child
    const uint32_t index=(uint32_t)call<int32_t,uint32_t,IOOptionBits>(child,kGetInteger,kIndex,0);
    if(index>=kContacts) {polaris_touch_edge_stats[3]=polaris_touch_edge_stats[3]+1;return false;}
    const uint32_t mask=(uint32_t)call<int32_t,uint32_t,IOOptionBits>(child,kGetInteger,kMask,0);
    const bool touch=call<int32_t,uint32_t,IOOptionBits>(child,kGetInteger,kTouch,0)!=0;
    if((mask&kMaskTouch) && touch) {   // the contact begins: its position now decides
        const int32_t x=call<int32_t,uint32_t,IOOptionBits>(child,kGetFixed,kX,0),y=call<int32_t,uint32_t,IOOptionBits>(child,kGetFixed,kY,0);
        fromEdge[index]=x<kEdgeX || x>65536-kEdgeX || y<kEdgeY || y>65536-kEdgeY;
        polaris_touch_edge_stats[1]=polaris_touch_edge_stats[1]+1;
        if(fromEdge[index])polaris_touch_edge_stats[2]=polaris_touch_edge_stats[2]+1;
    }
    const bool edged=fromEdge[index];
    if(edged)call<void,uint32_t,int32_t,IOOptionBits>(child,kSetInteger,kMask,(int32_t)(mask|kFromEdgeTip),0);
    if(!touch && (mask&kMaskTouch))fromEdge[index]=false;   // the lift keeps the bit; the next contact with this index starts fresh
    return edged;
}
static void dispatch(IOService *self,OSObject *event,IOOptionBits options) {
    if(event && call<uint32_t,IOOptionBits>(event,kGetType,0)==kDigitizer) {
        OSArray *children=*reinterpret_cast<OSArray **>(reinterpret_cast<uint8_t *>(event)+24);
        if(children && OSDynamicCast(OSArray,children) && children->getCount()) {
            // A collection (the driver's touch-screen dispatch): its mask is the union of its fingers', so it takes the bit as well.
            bool any=false;
            for(unsigned i=0;i<children->getCount();++i) {
                OSObject *child=children->getObject(i);
                if(child && child->metaCast("IOHIDEvent"))any|=mark(child);
                else polaris_touch_edge_stats[3]=polaris_touch_edge_stats[3]+1;
            }
            if(any) {
                const uint32_t mask=(uint32_t)call<int32_t,uint32_t,IOOptionBits>(event,kGetInteger,kMask,0);
                call<void,uint32_t,int32_t,IOOptionBits>(event,kSetInteger,kMask,(int32_t)(mask|kFromEdgeTip),0);
            }
        } else if(!children) mark(event);   // one transducer dispatched on its own
    }
    reinterpret_cast<void (*)(IOService *,OSObject *,IOOptionBits)>(originalDispatch)(self,event,options);
}
// This device's own event driver gets the wrapped copy; any other driver keeps the original table.
static void install(IORegistryEntry *driver) {
    if(originalDispatch || !driver)return;
    uintptr_t *table=*reinterpret_cast<uintptr_t **>(driver);
    uintptr_t *copy=static_cast<uintptr_t *>(IOMalloc(kSlots*sizeof(uintptr_t)));
    if(!copy)return;
    memcpy(copy,table,kSlots*sizeof(uintptr_t));
    originalDispatch=copy[kDispatch];copy[kDispatch]=(uintptr_t)&dispatch;
    __asm__ volatile("dmb ish":::"memory");
    *reinterpret_cast<uintptr_t **>(driver)=copy;
    polaris_touch_edge_stats[0]=1;
}
}  // namespace edge
class PolarisHidInput : public IOHIDDevice {
    OSDeclareDefaultStructors(PolarisHidInput)
    IOWorkLoop *inputLoop=nullptr;
    IOTimerEventSource *timer=nullptr;
    bool down=false;
    uint8_t buttons=0;   // report 2 bits held by the hardware buttons
    bool touchEnabled=false;
    // The digitizer is a separate service from the keyboard: backboardd matches digitizers by primary usage page/usage
    // (Digitizer/Touch Screen) and the Built-In flag, which a combined keyboard-first descriptor would not provide.
    bool touchOnly=false;
    bool eventDriverFound=false;
    uint32_t lastSeq=0;
    bool touchPending=false;
    unsigned touchTicks=0;
    // Fingers sent as down in the previous report; a vanished identifier gets one explicit tip-up report.
    int prevIds[TOUCH_FINGERS]={-1,-1,-1,-1,-1,-1,-1,-1,-1,-1};
    int prevX[TOUCH_FINGERS]={},prevY[TOUCH_FINGERS]={};
    static unsigned transformCoordinate(int value,int maximum) {
        if(value<0)value=0;if(value>=maximum)value=maximum-1;
        return (unsigned)((long long)value*32767/(maximum-1));
    }
    // The producer only marks work pending. Timer state belongs to the work
    // loop; setTimeoutMS is not serialized for concurrent callers. Never wait
    // on the loop gate here: stop() can hold it while draining this sink.
    static void touchNotify(void *context) {
        PolarisHidInput *self=static_cast<PolarisHidInput *>(context);
        if(self)__atomic_store_n(&self->touchPending,true,__ATOMIC_RELEASE);
    }
    void touchSend() {
        PolarisHidInput *self=this;
        if(!self->hasEventDriverCached())return;
        uint32_t before=__atomic_load_n(&polaris_touch_seq,__ATOMIC_ACQUIRE);
        if((before&1) || before==self->lastSeq)return;
        __asm__ volatile("dmb ish":::"memory");
        unsigned count=__atomic_load_n(&polaris_touch_count,__ATOMIC_RELAXED);if(count>TOUCH_FINGERS)count=TOUCH_FINGERS;
        int ids[TOUCH_FINGERS],xs[TOUCH_FINGERS],ys[TOUCH_FINGERS];
        for(unsigned i=0;i<count;++i){ids[i]=__atomic_load_n(&polaris_touch_ids[i],__ATOMIC_RELAXED);xs[i]=__atomic_load_n(&polaris_touch_x[i],__ATOMIC_RELAXED);ys[i]=__atomic_load_n(&polaris_touch_y[i],__ATOMIC_RELAXED);}
        __asm__ volatile("dmb ish":::"memory");
        if(__atomic_load_n(&polaris_touch_seq,__ATOMIC_ACQUIRE)!=before)return;      // torn read: retry on the next tick
        // Map the Polaris 1080 x 2160 coordinates to the HID 0..32767 range.
        unsigned char report[1+TOUCH_FINGERS*6+1]={3};
        unsigned slot=0;
        int nextIds[TOUCH_FINGERS],nextX[TOUCH_FINGERS],nextY[TOUCH_FINGERS];
        for(unsigned i=0;i<count && slot<TOUCH_FINGERS;++i,++slot) {
            unsigned x=transformCoordinate(xs[i],1080),y=transformCoordinate(ys[i],2160);
            unsigned char *f=report+1+slot*6;
            f[0]=3;f[1]=(unsigned char)(ids[i]&0xff);f[2]=(unsigned char)x;f[3]=(unsigned char)(x>>8);f[4]=(unsigned char)y;f[5]=(unsigned char)(y>>8);   // tip, valid
            nextIds[slot]=ids[i];nextX[slot]=(int)x;nextY[slot]=(int)y;
        }
        const unsigned downCount=slot;
        // Identifiers that were down and are gone: tip up at the last known position. They are matched by identifier, not by slot:
        // the producer packs its fingers, so when one lifts the others move down a slot and a slot match would lift a finger still
        // down and leave the lifted one stuck.
        for(unsigned j=0;j<TOUCH_FINGERS;++j) {
            const int id=self->prevIds[j];
            if(id<0)continue;
            bool kept=false;
            for(unsigned i=0;i<downCount && !kept;++i)kept=(ids[i]&0xff)==(id&0xff);
            if(kept || slot>=TOUCH_FINGERS)continue;
            unsigned char *f=report+1+slot*6;
            f[0]=2;f[1]=(unsigned char)(id&0xff);   // tip up, valid
            f[2]=(unsigned char)self->prevX[j];f[3]=(unsigned char)(self->prevX[j]>>8);
            f[4]=(unsigned char)self->prevY[j];f[5]=(unsigned char)(self->prevY[j]>>8);
            ++slot;
        }
        if(!slot){self->lastSeq=before;return;}
        report[1+TOUCH_FINGERS*6]=(unsigned char)slot;
        IOBufferMemoryDescriptor *buffer=IOBufferMemoryDescriptor::withBytes(report,sizeof(report),kIODirectionNone);
        IOReturn result=buffer?self->handleReport(buffer,0,0):kIOReturnNoMemory;
        OSSafeReleaseNULL(buffer);
        polaris_hid_input_observed(6,result);
        if(result!=kIOReturnSuccess)return; // Keep previous contacts/sequence for retry.
        self->lastSeq=before;
        if(downCount>=2)edge::polaris_touch_hid_multi[0]=edge::polaris_touch_hid_multi[0]+1;
        if(downCount>edge::polaris_touch_hid_multi[1])edge::polaris_touch_hid_multi[1]=downCount;
        edge::polaris_touch_hid_multi[2]=edge::polaris_touch_hid_multi[2]+slot-downCount;
        for(unsigned j=0;j<TOUCH_FINGERS;++j) {
            self->prevIds[j]=j<downCount?nextIds[j]:-1;
            if(j<downCount){self->prevX[j]=nextX[j];self->prevY[j]=nextY[j];}
        }
        polaris_touch_hid_reports=polaris_touch_hid_reports+1;
    }
    // The button driver's thread calls buttonsNotify on every change of the pressed set.
    static void buttonsNotify(void *context,uint32_t mask) {
        PolarisHidInput *self=static_cast<PolarisHidInput *>(context);
        if(self && self->inputLoop)self->inputLoop->runAction(&PolarisHidInput::buttonsAction,self,reinterpret_cast<void *>(uintptr_t(mask)));
    }
    static IOReturn buttonsAction(OSObject *owner,void *mask,void *,void *,void *) {
        PolarisHidInput *self=OSDynamicCast(PolarisHidInput,owner);if(!self)return kIOReturnSuccess;
        self->buttons=static_cast<uint8_t>(uintptr_t(mask)&0xe);
        if(!self->hasEventDriverCached())return kIOReturnSuccess;
        unsigned char report[]={2,static_cast<unsigned char>((self->down?1:0)|self->buttons)};
        IOBufferMemoryDescriptor *buffer=IOBufferMemoryDescriptor::withBytes(report,sizeof(report),kIODirectionNone);
        IOReturn result=buffer?self->handleReport(buffer,0,0):kIOReturnNoMemory;
        OSSafeReleaseNULL(buffer);
        polaris_hid_input_observed(4,result);
        return kIOReturnSuccess;
    }
    bool hasEventDriverCached() {
        if(!eventDriverFound) {
            IORegistryEntry *driver=eventDriver(this,4);
            eventDriverFound=driver!=nullptr;
            // This vtable patch is a separate, unqualified private ABI.
            unsigned edgeHook=0;
            if(driver && (touchEnabled || touchOnly) &&
               PE_parse_boot_argn("polaris-touch-edge-hook",&edgeHook,sizeof(edgeHook)) && edgeHook==1)
                edge::install(driver);
        }
        return eventDriverFound;
    }
    static bool hasEventDriver(IORegistryEntry *parent,unsigned depth) {return eventDriver(parent,depth)!=nullptr;}
    // The IOHIDEventDriver below this device, if one has attached.
    static IORegistryEntry *eventDriver(IORegistryEntry *parent,unsigned depth) {
        if(!depth)return nullptr;
        OSIterator *it=parent->getChildIterator(gIOServicePlane);if(!it)return nullptr;
        IORegistryEntry *found=nullptr;
        while(OSObject *child=it->getNextObject()) {
            IORegistryEntry *entry=OSDynamicCast(IORegistryEntry,child);
            if(!entry)continue;
            found=entry->metaCast("IOHIDEventDriver")?entry:eventDriver(entry,depth-1);
            if(found)break;
        }
        it->release();return found;
    }
    static void tick(OSObject *owner,IOTimerEventSource *source) {
        PolarisHidInput *self=OSDynamicCast(PolarisHidInput,owner);if(!self)return;
        if(!(self->touchOnly || self->touchEnabled) || self->touchTicks++%50==0)
            polaris_hid_live_checkpoint(self);
        // Periodic recovery also covers late IOHIDEventDriver matching, torn
        // snapshots and failed allocations/reports without a new hardware frame.
        if(self->touchOnly || self->touchEnabled) {
            // Check even without a notification: a failed report or late
            // event-driver match must retry the same stationary frame.
            if(__atomic_exchange_n(&self->touchPending,false,__ATOMIC_ACQ_REL) ||
               __atomic_load_n(&polaris_touch_seq,__ATOMIC_ACQUIRE)!=self->lastSeq)
                self->touchSend();
        }
        if(self->touchOnly || self->touchEnabled){source->setTimeoutMS(20);return;}
        if(!self->down && !hasEventDriver(self,4)) {
            polaris_hid_input_observed(3,0);
            source->setTimeoutMS(1000);
            return;
        }
        polaris_hid_input_observed(3,1);
        if(!self->down && !polaris_hid_input_requested()) {source->setTimeoutMS(1000);return;}
        unsigned char report[]={2,static_cast<unsigned char>((self->down?0:1)|self->buttons)};
        IOBufferMemoryDescriptor *buffer=IOBufferMemoryDescriptor::withBytes(report,sizeof(report),kIODirectionNone);
        IOReturn result=buffer?self->handleReport(buffer,0,0):kIOReturnNoMemory;
        OSSafeReleaseNULL(buffer);
        polaris_hid_input_observed(self->down?5:4,result);
        // Always attempt release, even if down returned an error: input must
        // never be left pressed by an ambiguous report completion.
        if(!self->down) {self->down=true;source->setTimeoutMS(100);}
        else {self->down=false;source->setTimeoutMS(1000);}
    }
public:
    void setTouchOnly() {touchOnly=true;}
    IOWorkLoop *getWorkLoop() const override {return inputLoop;}
    OSString *newTransportString() const override {return OSString::withCString(touchOnly?"I2C":"Virtual");}
    OSString *newProductString() const override {return OSString::withCString(touchOnly?"Offline touch digitizer":"Offline HID input probe");}
    IOReturn newReportDescriptor(IOMemoryDescriptor **out) const override {
        if(!out)return kIOReturnBadArgument;
        unsigned char combined[sizeof(descriptor)+sizeof(touchDescriptor)];
        size_t size;
        if(touchOnly){size=sizeof(touchDescriptor);memcpy(combined,touchDescriptor,size);}
        else{
            size=sizeof(descriptor);memcpy(combined,descriptor,size);
            // Default: one device, keyboard collection first, digitizer second (the arrangement whose event driver
            // and user client attach on hardware); the separate digitizer device is enabled with polaris-touch-hid=2.
            if(touchEnabled){memcpy(combined+size,touchDescriptor,sizeof(touchDescriptor));size+=sizeof(touchDescriptor);}
        }
        *out=IOBufferMemoryDescriptor::withBytes(combined,size,kIODirectionNone);
        return *out?kIOReturnSuccess:kIOReturnNoMemory;
    }
    bool start(IOService *provider) override {
        inputLoop=IOWorkLoop::workLoop();if(!inputLoop)return false;
        // Request the normal generic HID event personality for this owned
        // keyboard. This is a matching property, not a client entitlement.
        if(!setProperty("HIDDefaultBehavior",true))return false;
        unsigned touch=0;
        touchEnabled=PE_parse_boot_argn("polaris-touch-hid",&touch,sizeof(touch)) && touch==1;
        // DigitizerCollectionDispatch: IOHIDEventDriver (setDigitizerProperties) reads it up the service plane and then sends each
        // report's fingers as one digitizer collection with a child per finger. Without it a touch screen gets one event per finger,
        // and backboardd takes each as the whole touch set, so no two fingers are ever down together for UIKit (no pinch, no
        // multi-finger or system gestures).
        if(touchOnly||touchEnabled){setProperty("Built-In",true);setProperty("DisplayIntegrated",true);setProperty("DigitizerCollectionDispatch",true);}
        if(!IOHIDDevice::start(provider))return false;
        timer=IOTimerEventSource::timerEventSource(this,tick);
        if(!timer || inputLoop->addEventSource(timer)!=kIOReturnSuccess) {
            OSSafeReleaseNULL(timer);IOHIDDevice::stop(provider);return false;
        }
        if(touchOnly||touchEnabled) {
            if(&polaris_touch_runtime_set_sink)polaris_touch_runtime_set_sink(&PolarisHidInput::touchNotify,this);
        }
        if(!touchOnly && &polaris_buttons_set_sink)polaris_buttons_set_sink(&PolarisHidInput::buttonsNotify,this);
        setProperty("OfflineInputProbe",true);
        polaris_hid_input_observed(2,0);
        timer->setTimeoutMS((touchOnly||touchEnabled)?20:1000);return true;
    }
    void stop(IOService *provider) override {
        if((touchOnly||touchEnabled) && &polaris_touch_runtime_set_sink)polaris_touch_runtime_set_sink(nullptr,nullptr);
        if(!touchOnly && &polaris_buttons_set_sink)polaris_buttons_set_sink(nullptr,nullptr);
        if(timer){timer->cancelTimeout();inputLoop->removeEventSource(timer);OSSafeReleaseNULL(timer);}
        IOHIDDevice::stop(provider);
    }
    void free() override {OSSafeReleaseNULL(inputLoop);IOHIDDevice::free();}
};
OSDefineMetaClassAndStructors(PolarisHidInput,IOHIDDevice)
extern "C" IOService *polaris_hid_input_allocate(void) {return new PolarisHidInput;}
extern "C" IOService *polaris_hid_touch_allocate(void) {PolarisHidInput *device=new PolarisHidInput;if(device)device->setTouchOnly();return device;}
