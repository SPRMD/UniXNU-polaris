#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cassert>
#include <vector>
#include <openssl/evp.h>
#include "PolarisRootLayout.h"
struct Ops {
  FILE *file;
  uint64_t blocks;
  EVP_MD_CTX *sha = EVP_MD_CTX_new ();
  unsigned reads = 0;
  ~Ops () { EVP_MD_CTX_free (sha); }
  bool read (uint64_t lba, uint32_t count, void *out) {
    assert (count && count <= 32 && lba < blocks && count <= blocks - lba);
    ++reads;
    return !fseeko (file, lba * 4096, SEEK_SET) && fread (out, 4096, count, file) == count;
  }
  void beginDigest () { assert (EVP_DigestInit_ex (sha, EVP_sha256 (), nullptr)); }
  void updateDigest (const void *data, size_t size) { assert (EVP_DigestUpdate (sha, data, size)); }
  void endDigest (uint8_t *out) { unsigned n; assert (EVP_DigestFinal_ex (sha, out, &n) && n == 32); }
};
int main (int argc, char **argv) {
  assert (argc == 2);
  FILE *file = fopen (argv[1], "rb"); assert (file);
  fseeko (file, 0, SEEK_END); uint64_t bytes = ftello (file);
  Ops ops = {file, bytes / 4096};
  auto *work = new PolarisRootWorkspace;
  PolarisRootLayout layout;
  memset (&layout, 0xab, sizeof (layout));
  const char *error = polarisFindRoot (ops, bytes, *work, layout);
  delete work; fclose (file);
  if (error) {
    // Failure must not return any valid-looking partial window.
    assert (!layout.first && !layout.window[0].bytes && !layout.window[1].bytes);
    puts (error); return 1;
  }
  assert (!strcmp (layout.window[0].name, "SystemOS") && !strcmp (layout.window[1].name, "OS"));
  assert (layout.first == 64 && layout.last == 1800 && ops.reads > 10);
  puts ("PASS: darwin raw APFS windows and complete payload digests");
}
