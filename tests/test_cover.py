"""封面选路不能把 DoVi Profile 5 当普通 YUV 缩放。"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from capture_cover import cover_command


class CoverTests(unittest.TestCase):
    def command(self, **stream):
        return cover_command("ffmpeg", "输入.mkv", "封面.png", {"index": 0, **stream})

    def test_sdr_does_not_need_gpu(self):
        command = self.command(color_transfer="bt709")
        self.assertNotIn("-init_hw_device", command)
        self.assertIn("scale=1280:-2:flags=lanczos,format=rgb24", command)

    def test_profile5_initializes_vulkan_before_input_and_preserves_rpu(self):
        command = self.command(side_data_list=[{"side_data_type": "DOVI configuration record",
                                               "dv_profile": 5, "rpu_present_flag": 1}])
        self.assertLess(command.index("-init_hw_device"), command.index("-i"))
        self.assertNotIn("-hwaccel", command)
        filters = command[command.index("-vf") + 1]
        self.assertTrue(filters.startswith("libplacebo="))
        self.assertIn("apply_dolbyvision=true", filters)
        self.assertIn("color_trc=iec61966-2-1", filters)

    def test_missing_rpu_is_not_silently_accepted(self):
        with self.assertRaisesRegex(ValueError, "RPU"):
            self.command(side_data_list=[{"side_data_type": "DOVI configuration record"}])

    def test_hdr10_and_hlg_use_tone_mapping(self):
        for transfer in ("smpte2084", "arib-std-b67"):
            self.assertIn("-init_hw_device", self.command(color_transfer=transfer))
