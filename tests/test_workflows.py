import json
import unittest
from pathlib import Path


class WorkflowContractTests(unittest.TestCase):
    def test_exports_are_connected_and_contain_no_credentials(self):
        root = Path(__file__).resolve().parents[1]
        for filename in ("intake.json", "sla.json"):
            with self.subTest(workflow=filename):
                data = json.loads((root / "workflows" / filename).read_text(encoding="utf-8"))
                names = {n["name"] for n in data["nodes"]}
                self.assertEqual(len(names), len(data["nodes"]))
                self.assertFalse(data["active"])
                for name, outputs in data["connections"].items():
                    self.assertIn(name, names)
                    for output in outputs["main"]:
                        for edge in output:
                            self.assertIn(edge["node"], names)
                for node in data["nodes"]:
                    self.assertNotIn("credentials", node)
                    if node["type"] == "n8n-nodes-base.httpRequest":
                        self.assertEqual(node["parameters"]["genericAuthType"], "httpHeaderAuth")
                        self.assertTrue(node["retryOnFail"])
                        self.assertIn("/api/automation/", node["parameters"]["url"])


if __name__ == "__main__":
    unittest.main()
