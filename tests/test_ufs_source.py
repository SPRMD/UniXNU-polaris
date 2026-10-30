import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UFS = ROOT / 'drivers' / 'ShengUfs'


class UfsSourceTests(unittest.TestCase):
    def test_sd845_probe_sources_are_present(self):
        required = {
            'GccUfs.h', 'Info.plist', 'NativeUfs.cpp', 'RootCommands.h',
            'RootDiagnostics.h', 'RootLayout.h', 'RootPublication.h',
            'RootQueue.h', 'RootTransportLayout.h', 'RootWindowRead.h',
            'SmmuTakeover.h', 'TransferPoll.h',
        }
        self.assertEqual({path.name for path in UFS.iterdir() if path.is_file()} & required,
                         required)

    def test_probe_is_explicit_and_sdm845_scoped(self):
        source = (UFS / 'NativeUfs.cpp').read_text(encoding='utf-8')
        self.assertIn('qcom,sdm845-ufshc', source)
        self.assertIn('PE_parse_boot_argn ("native-ufs-probe"', source)
        self.assertIn('if (!probe || !OSDynamicCast', source)
        self.assertIn('0x01d84000ULL', (UFS / 'GccUfs.h').read_text(encoding='utf-8'))

    def test_default_board_does_not_request_probe(self):
        board = (ROOT / 'board.toml').read_text(encoding='utf-8')
        self.assertNotIn('native-ufs-probe=', board)
        self.assertNotIn('native-ufs-smmu=', board)

    def test_archive_name_matches_unixnu_component_manifest(self):
        build = (ROOT / 'scripts' / 'build-arm-driver.py').read_text(encoding='utf-8')
        self.assertIn("'ShengUfs': ('sheng-ufs', 'NativeUfs', 'ShengUfs')", build)
        self.assertIn("lib' + archive_name + '.a", build)


if __name__ == '__main__':
    unittest.main()
