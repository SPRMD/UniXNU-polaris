#include <assert.h>
#include <stdint.h>
#include "../drivers/PolarisSynapticsTouch/SynapticsRmi4Protocol.h"

int main(void)
{
  const uint8_t pdt[] = {
    0x10, 0x20, 0x30, 0x40, 0x03, 0x01,
    0x50, 0x60, 0x70, 0x80, 0x02, 0x12,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
  };
  PolarisRmi4Pdt parsed = {};
  assert(polaris_rmi4_parse_pdt(pdt, sizeof(pdt), &parsed));
  assert(parsed.has_f01 && parsed.has_f12 && parsed.terminated);
  assert(parsed.f12.data_base == 0x80);

  const uint8_t frame[] = {1, 0x34, 0x02, 0x78, 0x04, 0, 0, 0};
  PolarisRmi4Contact contact = {};
  assert(polaris_rmi4_parse_contact(frame, sizeof(frame), 1080, 2160, &contact));
  assert(contact.present && contact.x == 0x0234 && contact.y == 0x0478);

  const uint8_t release[] = {0, 0xff, 0xff, 0xff, 0xff, 0, 0, 0};
  assert(polaris_rmi4_parse_contact(release, sizeof(release), 1080, 2160, &contact));
  assert(!contact.present);
  return 0;
}


