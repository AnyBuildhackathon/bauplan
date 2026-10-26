"""Mass and dimensional context for full-assembly USD exports."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pai_agent.state import BuildState
from pai_agent.tools.usd import export_product


class UsdExportTests(unittest.TestCase):
    def test_hero_export_keeps_dimensions_and_all_selected_masses(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            stl = directory / "frame.stl"
            stl.write_bytes(b"frame")
            state = BuildState("usd-test", directory, stl_path=str(stl), frame_mass_g=5.24,
                               cad_params={"arm_length_mm": 42.5, "thickness_mm": 2})
            masses = {"frame": (5.3, 1), "motor": (3.7, 4), "propeller": (0.93, 4),
                      "battery": (15, 1), "flight_controller": (4.13, 1),
                      "camera": (2, 1), "canopy": (2, 1), "hardware": (0.025, 12)}
            state.selected = {category: {"mass_g": mass, "bom_qty": quantity}
                              for category, (mass, quantity) in masses.items()}
            state.selected["motor"]["thrust_g"] = 50

            def blender(command, **kwargs):
                Path(command[-2]).write_bytes(b"USD fixture")
                return type("Completed", (), {"returncode": 0})()

            with patch("pai_agent.tools.usd.find_blender", return_value="blender"), \
                 patch("pai_agent.tools.usd._assembly", return_value={"glb": "hero.glb"}), \
                 patch("pai_agent.tools.usd.subprocess.run", side_effect=blender):
                spec = export_product(state, directory / "export")
            self.assertEqual(spec["arm_mm"], 42.5)
            self.assertEqual(spec["thickness_mm"], 2)
            self.assertAlmostEqual(spec["mass_kg"], 0.04719)
            self.assertEqual(len(spec["parts"]), 25)
            self.assertAlmostEqual(spec["max_thrust_n"], 1.96133)
            self.assertEqual(json.loads((directory / "export/assembly.json").read_text()), spec)
            self.assertIn("physics:mass = 0.047190000", (directory / "export/product.usda").read_text())
