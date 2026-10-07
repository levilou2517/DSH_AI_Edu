import importlib
import html
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path


SERVICES = Path(__file__).parents[1] / "services"
sys.path.insert(0, str(SERVICES))
import shiban_store


class MaterialStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["SHIBAN_ROOT"] = str(Path(self.temp.name) / "root")
        self.store = importlib.reload(shiban_store)
        self.store.init()

    def tearDown(self):
        self.temp.cleanup()
        os.environ.pop("SHIBAN_ROOT", None)
        importlib.reload(shiban_store)

    def add_atom(self, asset_id="atom", interface=None, body=None):
        source = Path(self.temp.name) / f"{asset_id}.html"
        source.write_text(body or "<!doctype html><html><body><script>document.body.textContent = window.__MATERIAL_DATA.value</script><p>atom</p></body></html>", encoding="utf-8")
        return self.store.add_asset(asset_id, "html", asset_id, str(source), knowledge_point="DNA", params={"interface": interface or {}})

    def test_add_deduplicates_and_returns_absolute_path(self):
        first = self.add_atom("one")
        second = self.add_atom("two")
        self.assertFalse(first["existed"])
        self.assertTrue(second["existed"])
        self.assertEqual(second["asset_id"], "one")
        self.assertTrue(Path(second["absolute_file_path"]).is_file())
        self.assertTrue(self.store.get_asset("one")["file_path"].startswith("data/assets/"))

    def test_compose_isolates_atoms_without_rewriting_source(self):
        self.add_atom("atom", {"value": {"type": "string", "required": True}}, '<!doctype html><html><body><div>atom</div><script>document.body.dataset.value=window.__MATERIAL_DATA.value</script></body></html>')
        atom_path = Path(self.store.get_asset("atom")["absolute_file_path"])
        original = atom_path.read_text(encoding="utf-8")
        result = self.store.compose_asset({"page_id": "page", "title": "<unsafe>", "layout": {"mode": "grid", "gap": 12}, "sections": [
            {"asset": "atom", "label": "<label>", "data": {"value": "</script><x>"}},
            {"asset": "atom", "data": {"value": "second"}},
        ]})
        output = Path(result["absolute_file_path"]).read_text(encoding="utf-8")
        self.assertEqual(output.count('sandbox="allow-scripts"'), 2)
        self.assertNotIn("allow-same-origin", output)
        self.assertIn("&lt;unsafe&gt;", output)
        self.assertIn("&lt;label&gt;", output)
        srcdocs = [html.unescape(value) for value in re.findall(r'srcdoc="([^"]*)"', output, re.S)]
        self.assertEqual(len(srcdocs), 2)
        for document in srcdocs:
            self.assertIn("window.__MATERIAL_DATA=", document)
            self.assertNotIn("</script><x>", document)
            self.assertLess(document.index("window.__MATERIAL_DATA="), document.index("document.body.dataset.value"))
        self.assertIn('"value":"second"', srcdocs[1])
        self.assertEqual(atom_path.read_text(encoding="utf-8"), original)
        self.assertEqual(self.store.get_asset("atom")["reuse_count"], 2)

    def test_recomposing_identical_spec_is_idempotent(self):
        self.add_atom("atom")
        spec = {"page_id": "page", "title": "page", "sections": [{"asset": "atom"}]}
        first = self.store.compose_asset(spec)
        second = self.store.compose_asset(spec)
        self.assertFalse(first["existed"])
        self.assertTrue(second["existed"])
        self.assertEqual(second["asset_id"], "page")
        self.assertEqual(self.store.get_asset("atom")["reuse_count"], 1)
        with self.assertRaisesRegex(ValueError, "已存在"):
            self.store.compose_asset({**spec, "title": "different"})

    def test_standard_schema_and_legacy_interface_validation(self):
        self.add_atom("atom", {"type": "object", "properties": {"base": {"type": "string", "enum": ["A", "T"]}}, "required": ["base"]})
        with self.assertRaisesRegex(ValueError, "缺少必填字段"):
            self.store.compose_asset({"page_id": "bad", "title": "bad", "sections": [{"asset": "atom", "data": {}}]})
        result = self.store.compose_asset({"page_id": "ok", "title": "ok", "sections": [{"asset": "atom", "data": {"base": "A"}}]})
        self.assertTrue(result["ok"])

    def test_failed_compose_does_not_increment_or_leave_output(self):
        self.add_atom("atom", {"value": {"required": True}})
        with self.assertRaises(ValueError):
            self.store.compose_asset({"page_id": "bad", "title": "bad", "sections": [{"asset": "atom", "data": {}}]})
        self.assertEqual(self.store.get_asset("atom")["reuse_count"], 0)
        self.assertFalse((Path(self.store.DATA_DIR) / "assets" / "bad").exists())

    def test_page_can_be_composed_again_as_opaque_html(self):
        self.add_atom("atom")
        self.store.compose_asset({"page_id": "page", "title": "page", "sections": [{"asset": "atom"}]})
        second = self.store.compose_asset({"page_id": "outer", "title": "outer", "sections": [{"asset": "page"}]})
        output = Path(second["absolute_file_path"]).read_text(encoding="utf-8")
        self.assertIn('sandbox="allow-scripts"', output)
        self.assertEqual(self.store.get_asset("page")["reuse_count"], 1)
        self.assertEqual(self.store.get_asset("atom")["reuse_count"], 1)


if __name__ == "__main__":
    unittest.main()
