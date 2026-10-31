import importlib.util
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


PACKAGE = load("make_polaris_package_ios", ROOT / "scripts" / "make-polaris-package.py")
STAGE = load("build_polaris_ios_stage", ROOT / "scripts" / "build-ios-stage.py")
ESP = load("make_polaris_ios_esp", ROOT / "scripts" / "make-ios-esp.py")
INPUTS = load("check_polaris_ios_inputs", ROOT / "scripts" / "check-ios-stage-inputs.py")


class IOSStageScriptTests(unittest.TestCase):
    def test_real_shngroot_writer_places_apfs_windows_at_declared_offsets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = []
            for name in ('OS', 'SystemOS'):
                image = root / name
                data = bytearray(8192)
                struct.pack_into('<4sIQ', data, 32, b'NXSB', 4096, 2)
                data[100:100 + len(name)] = name.encode()
                image.write_bytes(data)
                sources.append(image)
            destination = root / 'darwin-root.img'
            subprocess.run([sys.executable, str(ROOT / 'scripts/make-userdata-linux.py'),
                            '--os', str(sources[0]), '--system-os', str(sources[1]),
                            '--partition', 'darwin', '--out', str(destination)],
                           check=True, capture_output=True)
            import hashlib
            with destination.open('rb') as stream:
                header = stream.read(4096)
                self.assertEqual(header[:8], b'SHNGROOT')
                self.assertEqual(struct.unpack_from('<IIQ', header, 8), (1, 2, 3 << 20))
                self.assertEqual(header[4064:], hashlib.sha256(header[:4064]).digest())
                for index, source in enumerate(sources):
                    name, offset, size, sector, flags, digest, reserved = struct.unpack_from(
                        '<32sQQII32s40s', header, 24 + index * 128)
                    self.assertEqual(name.rstrip(b'\0'), source.name.encode())
                    self.assertEqual((offset, size, sector, flags), ((index + 1) << 20, 8192, 512, 1))
                    stream.seek(offset)
                    window = stream.read(size)
                    self.assertEqual(window, source.read_bytes())
                    self.assertEqual(window[32:36], b'NXSB')
                    self.assertEqual(digest, hashlib.sha256(window).digest())

    def test_probe_patches_a_private_copy_and_leaves_the_artifact_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kernel = root / 'kernel.macho'
            kernel.write_bytes(b'prelinked-original')
            kernel.with_suffix('.json').write_text(json.dumps({
                'kernel_sha256': PACKAGE.sha256(kernel),
                'original_components_prelinked': True,
                'final_configured_link_passed': True,
            }))
            adt, trust = root / 'input.adt', root / 'trust.bundle'
            adt.write_bytes(b'adt')
            trust.write_bytes(b'trust')
            for relative in ('efi/Build/Out/AARCH64-DEBUG/UniXNU.efi',
                             'loader/build/DarwinBoot/DEBUG_GCC/AARCH64/DarwinBoot.efi'):
                path = root / relative
                path.parent.mkdir(parents=True)
                path.write_bytes(b'efi')
            out, tree = root / 'esp.img', root / 'tree'
            out.write_bytes(b'fat-placeholder')
            argv = ['make-ios-esp.py', '--kernel', str(kernel), '--adt', str(adt),
                    '--trust', str(trust), '--efi', str(root), '--out', str(out),
                    '--tree', str(tree), '--ipados-stage', '--probe', 'panic']
            with patch('sys.argv', argv), patch.object(ESP.subprocess, 'run') as run:
                run.return_value.stdout = 'FAT listing'
                ESP.main()
            # The prelinked artifact must survive byte-identical: its sidecar
            # report still describes it, and later consumers re-check the hash.
            self.assertEqual(kernel.read_bytes(), b'prelinked-original')
            self.assertEqual(json.loads(kernel.with_suffix('.json').read_text())['kernel_sha256'],
                             PACKAGE.sha256(kernel))
            # Both the probe and the FIPS re-seal must target that private copy,
            # never the artifact.
            patched = [call.args[0] for call in run.call_args_list
                       if call.args and call.args[0] and 'patch-xnu-entry-probe.py' in str(call.args[0][1])]
            self.assertTrue(patched, 'the probe tool was never invoked')
            probe_target = Path(patched[0][2])
            self.assertNotEqual(probe_target, kernel)
            self.assertEqual(probe_target.name, 'kernel.macho')
            sealed = [call.args[0] for call in run.call_args_list
                      if call.args and call.args[0] and 'seal-source-crypto-kernel.py' in str(call.args[0][1])]
            self.assertTrue(sealed, 'the FIPS seal was never re-run')
            self.assertEqual(Path(sealed[0][2]), probe_target)
            report = json.loads(out.with_suffix('.json').read_text())
            self.assertEqual(report['probe'], 'panic')
            self.assertEqual(report['input_kernel_sha256'], PACKAGE.sha256(kernel))

    def test_no_probe_flag_keeps_the_artifact_kernel(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kernel = root / 'kernel.macho'
            kernel.write_bytes(b'prelinked-original')
            kernel.with_suffix('.json').write_text(json.dumps({
                'kernel_sha256': PACKAGE.sha256(kernel),
                'original_components_prelinked': True,
                'final_configured_link_passed': True,
            }))
            adt, trust = root / 'input.adt', root / 'trust.bundle'
            adt.write_bytes(b'adt')
            trust.write_bytes(b'trust')
            for relative in ('efi/Build/Out/AARCH64-DEBUG/UniXNU.efi',
                             'loader/build/DarwinBoot/DEBUG_GCC/AARCH64/DarwinBoot.efi'):
                path = root / relative
                path.parent.mkdir(parents=True)
                path.write_bytes(b'efi')
            out, tree = root / 'esp.img', root / 'tree'
            out.write_bytes(b'fat-placeholder')
            argv = ['make-ios-esp.py', '--kernel', str(kernel), '--adt', str(adt),
                    '--trust', str(trust), '--efi', str(root), '--out', str(out),
                    '--tree', str(tree), '--ipados-stage', '--probe', 'panic', '--no-probe']
            with patch('sys.argv', argv), patch.object(ESP.subprocess, 'run') as run:
                run.return_value.stdout = 'FAT listing'
                ESP.main()
            self.assertFalse([c for c in run.call_args_list
                              if c.args and c.args[0] and 'patch-xnu-entry-probe.py' in str(c.args[0][1])])
            report = json.loads(out.with_suffix('.json').read_text())
            self.assertIsNone(report['probe'])

    def test_esp_installs_loader_named_trust_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kernel = root / 'kernel.macho'
            kernel.write_bytes(b'prelinked')
            kernel.with_suffix('.json').write_text(json.dumps({
                'kernel_sha256': PACKAGE.sha256(kernel),
                'original_components_prelinked': True,
                'final_configured_link_passed': True,
            }))
            adt, trust = root / 'input.adt', root / 'trust.bundle'
            adt.write_bytes(b'adt')
            trust.write_bytes(b'trust')
            for relative in ('efi/Build/Out/AARCH64-DEBUG/UniXNU.efi',
                             'loader/build/DarwinBoot/DEBUG_GCC/AARCH64/DarwinBoot.efi'):
                path = root / relative
                path.parent.mkdir(parents=True)
                path.write_bytes(b'efi')
            out, tree = root / 'esp.img', root / 'tree'
            out.write_bytes(b'fat-placeholder')
            argv = ['make-ios-esp.py', '--kernel', str(kernel), '--adt', str(adt),
                    '--trust', str(trust), '--efi', str(root), '--out', str(out),
                    '--tree', str(tree), '--ipados-stage']
            with patch('sys.argv', argv), patch.object(ESP.subprocess, 'run') as run:
                run.return_value.stdout = 'FAT listing'
                ESP.main()
            sidecar = 'EFI/UniXNU/Payloads/kernel.macho.trustcache'
            self.assertEqual((tree / sidecar).read_bytes(), b'trust')
            self.assertTrue(any(call.args[0][-1] == '::' + sidecar
                                for call in run.call_args_list))
            self.assertFalse((tree / 'EFI/UniXNU/Payloads/trust.bundle').exists())
            report = json.loads(kernel.with_suffix('.json').read_text())
            report['final_configured_link_passed'] = False
            kernel.with_suffix('.json').write_text(json.dumps(report))
            with patch('sys.argv', argv), patch.object(ESP.subprocess, 'run') as run:
                with self.assertRaisesRegex(SystemExit, 'final configured'):
                    ESP.main()
                run.assert_not_called()

    def test_stage_forwards_firmware_and_separate_storage_roles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = {}
            for name in ('kernel', 'adt', 'static-trust', 'system-trust', 'os', 'system-os'):
                path = root / name
                data = bytearray(8192)
                struct.pack_into('<4sIQ', data, 32, b'NXSB', 4096, 2)
                data[100:100 + len(name)] = name.encode()
                path.write_bytes(data)
                inputs[name] = path
            inputs['efi'] = root / 'efi'
            inputs['efi'].mkdir()
            inputs['firmware'] = root / 'firmware'
            inputs['firmware'].mkdir()
            (inputs['firmware'] / 'boot-polaris.img').write_bytes(b'firmware')
            output, package = root / 'stage', root / 'package'
            calls = []

            def assemble(script, args):
                calls.append((script, args))
                destination = Path(args[args.index('--out') + 1])
                if script == 'make-polaris-package.py':
                    PACKAGE.build_package(
                        Path(args[args.index('--esp') + 1]),
                        Path(args[args.index('--esp-image') + 1]), inputs['kernel'], destination,
                        firmware=Path(args[args.index('--firmware') + 1]),
                        userdata=Path(args[args.index('--userdata') + 1]),
                        darwin_root=Path(args[args.index('--darwin-root') + 1]))
                else:
                    destination.write_bytes(script.encode())
                if script == 'make-ios-esp.py':
                    payloads = Path(args[args.index('--tree') + 1]) / 'EFI/UniXNU/Payloads'
                    payloads.mkdir(parents=True)
                    for name, source in (('kernel.macho', inputs['kernel']),
                                         ('kernel.macho.adt', inputs['adt']),
                                         ('kernel.macho.trustcache', output / 'trust.bundle')):
                        (payloads / name).write_bytes(source.read_bytes())

            argv = ['build-ios-stage.py', '--out', str(output), '--package', str(package)]
            for name, path in inputs.items():
                argv.extend(['--' + name, str(path)])
            with patch('sys.argv', argv), patch.object(STAGE, 'run', side_effect=assemble):
                self.assertEqual(STAGE.main(), 0)
            manifest = json.loads((package / 'manifest.json').read_text())
            self.assertEqual(manifest['inputs']['userdata']['path'], 'esp.img')
            self.assertEqual(manifest['inputs']['darwin_root']['path'], 'darwin-root.img')
            self.assertEqual((package / 'firmware/boot-polaris.img').read_bytes(), b'firmware')
            self.assertFalse(manifest['flashable'])
            for base in (output, package):
                stage = json.loads((base / 'ios-stage-manifest.json').read_text())
                for fact in stage['inputs'].values():
                    if 'path' in fact:
                        self.assertEqual(STAGE.digest(base / fact['path']), fact['sha256'])
            inputs['firmware'].rename(root / 'moved-firmware')
            with patch('sys.argv', argv), patch.object(STAGE, 'run') as run:
                with self.assertRaises(SystemExit):
                    STAGE.main()
                run.assert_not_called()

    def test_raw_apfs_uses_object_header_and_checks_container_extent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "root.img"
            raw = bytearray(8192)
            struct.pack_into("<4sIQ", raw, 32, b"NXSB", 4096, 2)
            path.write_bytes(raw)
            self.assertEqual(STAGE.require_raw_apfs(path), {
                "block_size": 4096, "block_count": 2, "container_bytes": 8192,
            })
            path.write_bytes(raw[:4096])
            with self.assertRaisesRegex(SystemExit, "truncated"):
                STAGE.require_raw_apfs(path)

    def test_normalize_raw_apfs_keeps_a_valid_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "os.dmg"
            raw = bytearray(8192)
            struct.pack_into("<4sIQ", raw, 32, b"NXSB", 4096, 2)
            path.write_bytes(raw)
            normalized, geometry = STAGE.normalize_apfs_input(path, root / "work")
            self.assertEqual(normalized, path)
            self.assertEqual(geometry["container_bytes"], 8192)

    def test_normalized_apfs_inputs_must_be_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "same.img"
            image.write_bytes(b"same")
            with self.assertRaisesRegex(SystemExit, "different APFS images"):
                STAGE.require_distinct_apfs_images(image, image)
            other = root / "other.img"
            other.write_bytes(b"same")
            with self.assertRaisesRegex(SystemExit, "identical contents"):
                STAGE.require_distinct_apfs_images(image, other)

    def test_source_images_must_be_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            os_image = root / "os.dmg"
            system_image = root / "system.dmg"
            os_image.write_bytes(b"os")
            system_image.write_bytes(b"system")
            STAGE.require_distinct_images(os_image, system_image)
            with self.assertRaisesRegex(SystemExit, "different files"):
                STAGE.require_distinct_images(os_image, os_image)
            system_image.write_bytes(b"os")
            with self.assertRaisesRegex(SystemExit, "different content"):
                STAGE.require_distinct_images(os_image, system_image)

    def test_pinned_ios_inputs_are_hashed_and_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            os_image = root / "044-76040-038.dmg"
            system_image = root / "044-76034-038.dmg"
            os_image.write_bytes(b"os")
            system_image.write_bytes(b"system")
            import hashlib
            board = root / "board.toml"
            board.write_text(
                """[board]\nname = 'xiaomi,polaris'\n[ipsw]\nproduct = 'iPad7,1'\nversion = '17.7.11'\nbuild = '21H461'\n[ipsw.sha256]\n\"044-76040-038.dmg\" = '%s'\n\"044-76034-038.dmg\" = '%s'\n""" % (
                    hashlib.sha256(b"os").hexdigest(),
                    hashlib.sha256(b"system").hexdigest(),
                ),
                encoding="utf-8",
            )
            report = INPUTS.verify(root, board)
            self.assertTrue(report["verified"])
            self.assertEqual(report["members"]["044-76040-038.dmg"]["bytes"], 2)

    def test_misplaced_magic_and_invalid_geometry_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "root.img"
            path.write_bytes(b"NXSB" + bytes(8192))
            with self.assertRaisesRegex(SystemExit, "byte 32"):
                STAGE.require_raw_apfs(path)
            for block_size, count in ((0, 2), (6144, 2), (4096, 0), (131072, 1)):
                raw = bytearray(8192)
                struct.pack_into("<4sIQ", raw, 32, b"NXSB", block_size, count)
                path.write_bytes(raw)
                with self.assertRaisesRegex(SystemExit, "geometry"):
                    STAGE.require_raw_apfs(path)

    def test_ios_stage_entrypoints_are_host_only_and_guarded(self):
        source = (ROOT / "scripts" / "build-ios-stage.py").read_text(encoding="utf-8")
        self.assertIn("flashable", source)
        self.assertIn("no phone access", source)
        self.assertIn("make-trust-bundle.py", source)
        self.assertIn("make-ios-esp.py", source)
        self.assertIn("make-userdata-linux.py", source)
        self.assertIn("--driver-bundle", source)
        self.assertIn("driver bundle not found", source)
        self.assertIn("paths.append(args.driver_bundle)", source)

    def test_ipados_stage_requests_experimental_input_services(self):
        builder = (ROOT / "scripts" / "build-ios-stage.py").read_text(encoding="utf-8")
        esp = (ROOT / "scripts" / "make-ios-esp.py").read_text(encoding="utf-8")
        self.assertIn('"--ipados-stage"', builder)
        self.assertIn("polaris-touch-hid=1", esp)
        self.assertIn("polariskeys=1", esp)
        self.assertIn("polarisbattery=1", esp)
        self.assertIn("def render_toml(ipados_stage: bool)", esp)
        self.assertNotIn("polaris-touch-hid=1", ESP.render_toml(False))
        self.assertIn("polaris-touch-hid=1", ESP.render_toml(True))
        self.assertIn("polariskeys=1", ESP.render_toml(True))
        self.assertIn("polarisbattery=1", ESP.render_toml(True))
        self.assertIn("'boot_profile'", esp)
        self.assertIn("'experimental_input_services'", esp)

    def test_optional_driver_bundle_is_validated_and_forwarded(self):
        source = (ROOT / "scripts" / "build-ios-stage.py").read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--driver-bundle"', source)
        self.assertIn("driver bundle not found", source)
        self.assertIn('package_args.extend(["--driver-bundle", str(args.driver_bundle)])', source)

    def test_input_hash_report_is_validated_and_carried(self):
        source = (ROOT / "scripts" / "build-ios-stage.py").read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--input-hash-report"', source)
        self.assertIn("input hash report is not marked verified", source)
        self.assertIn('shutil.copy2(args.input_hash_report, out / "ios-input-hashes.json")', source)
        self.assertIn("rewrite_package_sums(package)", source)

    def test_os_and_system_os_must_be_distinct(self):
        source = (ROOT / "scripts" / "build-ios-stage.py").read_text(encoding="utf-8")
        self.assertIn("require_distinct_images(args.os, args.system_os)", source)
        self.assertIn("OS and SystemOS inputs must be different files", source)

    def test_udif_extractor_treats_liblzfse_as_lazy_dependency(self):
        import zlib
        with patch.dict(sys.modules, {"liblzfse": None, "lzfse": None}):
            extractor = load("udif_lazy_dependency", ROOT / "scripts" / "udif-extract.py")
        self.assertIsNone(extractor.liblzfse)
        plain = b"x" * 512
        self.assertEqual(extractor.decode(extractor.ZLIB, zlib.compress(plain), len(plain)), plain)
        with self.assertRaisesRegex(ValueError, r"LZFSE requires.*--lzfse-bin"):
            extractor.decode(extractor.LZFSE, b"encoded", len(plain))
        with patch.object(extractor, "external_lzfse", return_value=plain) as external:
            self.assertEqual(extractor.decode(extractor.LZFSE, b"encoded", len(plain), "decoder"), plain)
            external.assert_called_once_with(b"encoded", len(plain), "decoder")

    def test_package_carries_optional_darwin_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            esp = root / "esp"
            esp.mkdir()
            (esp / "BOOTAA64.EFI").write_bytes(b"efi")
            esp_image = root / "esp.img"
            esp_image.write_bytes(b"esp")
            kernel = root / "kernel.macho"
            kernel.write_bytes(b"kernel")
            kernel.with_suffix(".json").write_text(json.dumps({
                "kernel_sha256": PACKAGE.sha256(kernel),
                "final_configured_link_passed": True,
                "original_components_prelinked": True,
            }), encoding="utf-8")
            darwin = root / "darwin-root.img"
            darwin.write_bytes(b"root")
            output = root / "package"
            manifest = PACKAGE.build_package(esp, esp_image, kernel, output,
                                             darwin_root=darwin)
            self.assertFalse(manifest["flashable"])
            self.assertEqual(manifest["inputs"]["darwin_root"]["path"], "darwin-root.img")
            self.assertTrue((output / "darwin-root.img").is_file())
            self.assertIn("darwin", (output / "flash.ps1").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
