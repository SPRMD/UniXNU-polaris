// SPDX-License-Identifier: BSD-2-Clause-Patent
// Polaris display panel resource contract. No MMIO, DSI, GPIO, clocks,
// regulators, backlight, interrupts, firmware, DMA, or GPU operations occur.

#include <IOKit/IOService.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSIterator.h>
#include <pexpert/pexpert.h>
#include <stdint.h>
#include <string.h>

#include "PolarisDisplayPanelProtocol.h"

namespace {

static bool compatibleContains(IORegistryEntry *entry, const char *wanted)
{
  if (entry == nullptr || wanted == nullptr) return false;
  OSData *data = OSDynamicCast(OSData, entry->getProperty("compatible"));
  if (data == nullptr || data->getBytesNoCopy() == nullptr) return false;
  const char *bytes = static_cast<const char *>(data->getBytesNoCopy());
  const size_t length = data->getLength();
  const size_t wantedLength = strlen(wanted);
  for (size_t offset = 0; offset < length;) {
    size_t end = offset;
    while (end < length && bytes[end] != '\0') ++end;
    if (end - offset == wantedLength &&
        memcmp(bytes + offset, wanted, wantedLength) == 0) return true;
    offset = end < length ? end + 1 : length;
  }
  return false;
}

static bool boardIsPolaris()
{
  IORegistryEntry *root = IORegistryEntry::fromPath("/", gIODTPlane);
  if (root == nullptr) return false;
  const bool match = compatibleContains(root, "xiaomi,polaris") &&
                     compatibleContains(root, "qcom,sdm845");
  root->release();
  return match;
}

/* A dsi-display node is only a candidate.  Its label names one of the panel
 * builds that shipped on Polaris; the label alone never proves which panel is
 * actually attached to this unit. */
static bool isDsiDisplayCandidate(IORegistryEntry *entry)
{
  if (entry == nullptr) return false;
  const char *name = entry->getName();
  if (name != nullptr && strstr(name, "dsi-display") != nullptr) return true;
  return compatibleContains(entry, "qcom,dsi-display");
}

static uint8_t labelPanelKind(IORegistryEntry *entry)
{
  OSData *data = OSDynamicCast(OSData, entry->getProperty("label"));
  if (data == nullptr || data->getBytesNoCopy() == nullptr) {
    return PolarisDisplayPanelUnknown;
  }
  const char *bytes = static_cast<const char *>(data->getBytesNoCopy());
  const size_t length = data->getLength();
  size_t end = 0;
  while (end < length && bytes[end] != '\0') ++end;
  uint8_t kind = PolarisDisplayPanelUnknown;
  if (end == 0 || polaris_display_panel_name_kind(bytes, end, &kind) == 0) {
    return PolarisDisplayPanelUnknown;
  }
  return kind;
}

static void scanCandidates(IORegistryEntry *entry, unsigned depth,
                           unsigned *candidates, uint32_t *kinds)
{
  if (entry == nullptr || depth > 24 || *candidates >= 64) return;
  if (isDsiDisplayCandidate(entry)) {
    ++*candidates;
    const uint8_t kind = labelPanelKind(entry);
    if (kind != PolarisDisplayPanelUnknown && kind < 32) {
      *kinds |= 1U << kind;
    }
  }
  OSIterator *children = entry->getChildIterator(gIODTPlane);
  if (children == nullptr) return;
  while (IORegistryEntry *child =
             OSDynamicCast(IORegistryEntry, children->getNextObject())) {
    scanCandidates(child, depth + 1, candidates, kinds);
  }
  children->release();
}

} // namespace

class PolarisDisplayContract : public IOService {
  OSDeclareDefaultStructors(PolarisDisplayContract)
public:
  IOService *probe(IOService *provider, SInt32 *score) override
  {
    unsigned enabled = 0;
    if (provider == nullptr || !boardIsPolaris() ||
        !PE_parse_boot_argn("polaris-display-probe", &enabled, sizeof(enabled)) ||
        enabled != 1) return nullptr;
    if (score != nullptr) *score += 20;
    return IOService::probe(provider, score);
  }

  bool start(IOService *provider) override
  {
    if (!IOService::start(provider) || !boardIsPolaris()) return false;

    unsigned candidates = 0;
    uint32_t kinds = 0;
    scanCandidates(provider, 0, &candidates, &kinds);

    /* Exactly one candidate label is still only a label; more than one means
     * the DT does not say which panel this unit has.  Either way no panel
     * timing is parsed here, so the geometry below is a candidate set, never a
     * measured resolution. */
    unsigned distinctKinds = 0;
    uint8_t onlyKind = PolarisDisplayPanelUnknown;
    for (uint8_t kind = 1; kind < 32; ++kind) {
      if ((kinds & (1U << kind)) != 0) {
        ++distinctKinds;
        onlyKind = kind;
      }
    }

    PolarisDisplayPanelEvidence evidence = {};
    evidence.board_matches = 1;
    evidence.candidate_present = candidates != 0;
    evidence.active_panel_selected = 0;
    evidence.panel_kind =
        distinctKinds == 1 ? onlyKind : PolarisDisplayPanelUnknown;
    /* width/height/lanes stay 0: this contract does not parse panel timing
     * nodes, so it cannot confirm any geometry. */
    evidence.width = 0;
    evidence.height = 0;
    evidence.lanes = 0;
    evidence.command_mode = 0;
    const PolarisDisplayPanelPlan plan =
        polaris_display_panel_make_plan(evidence);

    setProperty("polaris-display-contract-version", 1U, 32);
    setProperty("polaris-display-panel-candidates",
                "dsi_jdi_fhd_nt35596s_video_display;"
                "dsi_jdi_fhd_r63452_cmd_display;"
                "dsi_ebbg_fhd_ft8716_video_display;"
                "dsi_ebbg_fhd_ft8719_video_display");
    setProperty("polaris-display-panel-candidate-nodes", candidates, 32);
    setProperty("polaris-display-panel-candidate-kind-mask", kinds, 32);
    /* Reference DTB timing nodes disagree on height (1080x1920 for the JDI
     * R63452 build, 1080x2160 for JDI NT35596S / EBBG FT8716, 1080x2246 for
     * EBBG FT8719), so a single resolution may not be published. */
    setProperty("polaris-display-resolution", "unresolved");
    setProperty("polaris-display-resolution-candidates",
                "1080x1920;1080x2160;1080x2246");
    setProperty("polaris-display-geometry-confirmed", false);
    setProperty("polaris-display-dsi-lanes-candidate", 4U, 32);
    setProperty("polaris-display-dsi-lanes-confirmed", false);
    setProperty("polaris-display-resource-contract-valid",
                plan.resource_contract_valid, 32);
    setProperty("polaris-display-plan-reason", plan.reason, 32);
    setProperty("polaris-display-panel-selected", false);
    setProperty("polaris-display-dsi-writes-allowed",
                plan.dsi_writes_allowed, 32);
    setProperty("polaris-display-backlight-allowed",
                plan.backlight_allowed, 32);
    setProperty("polaris-display-gpu-composition-allowed",
                plan.gpu_composition_allowed, 32);
    setProperty("polaris-display-mmio-performed", false);
    setProperty("polaris-display-darwin-driver-ready", false);
    setProperty("polaris-display-runtime-gate", "polaris-display-probe=1");
    setName("PolarisDisplayContract");
    registerService();
    IOLog("PolarisDisplayContract: candidates=%u kinds=%#x reason=%u; "
          "panel selected=0 DSI I/O=0\n",
          candidates, kinds, plan.reason);
    return true;
  }
};

OSDefineMetaClassAndStructors(PolarisDisplayContract, IOService)
