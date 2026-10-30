# Local Polaris firmware inputs

The official MIUI V12.5.1.0.QDGCNXM fastboot package supplied in the parent
workspace is a source of board firmware evidence. Keep it outside Git and pass
an extracted directory to the bundle tool explicitly:

```powershell
$py = 'C:\Users\James\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py scripts/make-polaris-driver-bundle.py `
  --out out/local-driver-bundle-with-a630 `
  --vendor-root ..\..\polaris_ios16_driver_research\.local\miui-a630 `
  --copy-vendor
```

The current local A630 set is:

| file | bytes | SHA-256 |
| --- | ---: | --- |
| `a630_gmu.bin` | 32768 | `b07f90299ff2ae33948fcfd6ed67f53fbd287b5bf85ff2d43db11d4d32c1621f` |
| `a630_sqe.fw` | 31980 | `34edacb6fdedfbfc07ed5cd1d29b0b57a3543ef5be6ab34a43bd64686826fa1e` |
| `a630_zap.mdt` | 6684 | `1882b214d24c13eae4ffc39ba5456d5e61c80b089fb77e8b15f7bdd04bc9c831` |
| `a630_zap.b00` | 148 | `b2975f6a4c28a98197c1d694f6e275e71b23ec7e31e32ff5d1f83fdb80a94282` |
| `a630_zap.b01` | 6536 | `c94da0d6edf4820885b814ecda2f91c89b9d766126c3574c05d580c418815b5f` |
| `a630_zap.b02` | 1968 | `519b5538809f54ee566246b0520746a8ea82ca9384ea6bddb0b0e0d3c2de520c` |

These are firmware inputs only. They do not implement Adreno power, GMU/HFI,
PAS, SMMU, command processing, rendering, or an iOS userland path. The bundle
tool therefore keeps `flashable=false`, `hardware_tested=false`, and
`darwin_driver=false` even when `--copy-vendor` is used.
