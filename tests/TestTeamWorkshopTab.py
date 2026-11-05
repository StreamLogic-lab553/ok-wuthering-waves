import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui import TeamWorkshopTab as workshop


class WorkshopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def response(self, payload):
        mocked = patch.object(workshop, "urlopen")
        opened = mocked.start()
        self.addCleanup(mocked.stop)
        opened.return_value.__enter__.return_value.read.return_value = payload
        return opened

    def test_official_catalog_inherits_team_and_orders_newest_first(self):
        opened = self.response(json.dumps({"teams": [{"team": "A, B, C", "members": ["A", "B", "C"],
            "codes": [{"name": "old", "timestamp": 1}, {"name": "new", "timestamp": 2}]}]}).encode())
        codes = workshop.fetch_catalog()
        self.assertEqual([c["name"] for c in codes], ["new", "old"])
        self.assertEqual(codes[0]["members"], ["A", "B", "C"])
        self.assertEqual(codes[0]["team"], "A, B, C")
        self.assertEqual(opened.call_args.args[0].full_url, workshop.CATALOG_URL)
        self.assertEqual(opened.call_args.kwargs["timeout"], 15)

    def test_catalog_preserves_explicit_member_data(self):
        self.response(json.dumps({"teams": [{"members": ["old"], "codes": [
            {"members": ["new"], "team": "custom", "timestamp": "invalid"}]}]}).encode())
        self.assertEqual(workshop.fetch_catalog()[0]["members"], ["new"])

    def test_catalog_rejects_invalid_structure(self):
        self.response(b'{"teams": null}')
        with self.assertRaises(ValueError):
            workshop.fetch_catalog()

    def test_catalog_rejects_invalid_json(self):
        self.response(b'not json')
        with self.assertRaises(ValueError):
            workshop.fetch_catalog()

    def test_catalog_size_bound(self):
        self.response(b'x' * (workshop.MAX_CATALOG_SIZE+1))
        with self.assertRaises(ValueError):
            workshop.fetch_catalog()

    def test_archive_uses_official_repo_and_escapes_chinese_filename(self):
        url = workshop.archive_url({"filename": "速刷4C_测试_1.0.zip", "rawUrl": "https://example.invalid/evil"})
        self.assertTrue(url.startswith(workshop.RAW_BASE + "codes/"))
        self.assertIn("%E9%80%9F", url)
        self.assertNotIn("example.invalid", url)

    def test_archive_rejects_paths_and_non_zip_files(self):
        for name in [None, "../a.zip", r"..\a.zip", "C:a.zip", "a.py", " a.zip", "a\x00.zip"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                workshop.archive_url({"filename": name})

    def test_archive_rejects_malformed_record(self):
        for code in (None, [], "team.zip"):
            with self.subTest(code=code), self.assertRaises(ValueError):
                workshop.archive_url(code)

    def test_catalog_skips_malformed_entries(self):
        self.response(json.dumps({"teams": [None, {"codes": None},
            {"team": "A", "codes": [None, {"name": "valid"}]}]}).encode())
        self.assertEqual([c["name"] for c in workshop.fetch_catalog()], ["valid"])

    def test_application_registers_the_workshop(self):
        from config import config
        self.assertIn(["src.gui.TeamWorkshopTab", "TeamWorkshopTab"], config["custom_tabs"])

    def test_open_keeps_unsaved_changes_guard_and_connects_import(self):
        from ok.util.config import Config
        from src.char.CustomCharLoader import clear_team_char_cache
        with tempfile.TemporaryDirectory() as folder, patch.object(Config, "config_folder", folder):
            clear_team_char_cache()
            tab = workshop.TeamWorkshopTab()
            try:
                self.assertEqual(tab.name, "角色工坊")
                self.assertTrue(tab.workshop_button.isEnabled())
                with (patch.object(tab, "_guard_unsaved_changes", return_value=False),
                      patch.object(workshop, "fetch_catalog") as fetch):
                    tab._open_workshop()
                    fetch.assert_not_called()
                with (patch.object(tab, "_guard_unsaved_changes", return_value=True),
                      patch.object(workshop, "fetch_catalog", return_value=[]) as fetch,
                      patch.object(workshop, "WorkshopDialog") as dialog,
                      patch.object(tab, "_import_workshop_code") as imported):
                    tab._open_workshop()
                    fetch.assert_called_once_with()
                    dialog.assert_called_once_with([], parent=tab.window())
                    dialog.return_value.exec.assert_called_once_with()
                    callback = dialog.return_value.import_requested.connect.call_args.args[0]
                    callback({"filename": "team.zip"})
                    imported.assert_called_once_with({"filename": "team.zip"}, dialog.return_value)
            finally:
                tab.deleteLater()
                self.app.processEvents()
                clear_team_char_cache()

    def test_catalog_error_is_reported_without_opening_dialog(self):
        with (patch.object(workshop, "fetch_catalog", side_effect=ValueError("invalid catalog")),
              patch.object(workshop, "show_info_bar") as error,
              patch.object(workshop, "WorkshopDialog") as dialog):
            tab = MagicMock()
            tab._guard_unsaved_changes.return_value = True
            workshop.TeamWorkshopTab._open_workshop(tab)
            dialog.assert_not_called()
            self.assertEqual(error.call_args.args[1], "invalid catalog")
            self.assertTrue(error.call_args.kwargs["error"])

    def test_invalid_archive_is_reported_without_downloading(self):
        with (patch.object(workshop, "show_info_bar") as error,
              patch.object(workshop.CharacterCodeTab, "_import_workshop_code") as imported):
            tab = MagicMock()
            workshop.TeamWorkshopTab._import_workshop_code(tab, {"filename": "../team.zip"}, tab)
            imported.assert_not_called()
            self.assertTrue(error.call_args.kwargs["error"])

    def test_import_keeps_upstream_confirmation_flow(self):
        from PySide6.QtWidgets import QApplication
        from ok.util.config import Config
        from src.char.CustomCharLoader import clear_team_char_cache
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder, patch.object(Config, "config_folder", folder):
            clear_team_char_cache()
            tab = workshop.TeamWorkshopTab()
            try:
                with patch.object(workshop.CharacterCodeTab, "_import_workshop_code") as imported:
                    code = {"filename": "team.zip", "downloadUrl": "https://obsolete.invalid/team.zip"}
                    tab._import_workshop_code(code, tab)
                    self.assertEqual(imported.call_args.args[0]["downloadUrl"], workshop.RAW_BASE + "codes/team.zip")
                    self.assertEqual(code["downloadUrl"], "https://obsolete.invalid/team.zip")
            finally:
                tab.deleteLater()
                app.processEvents()
                clear_team_char_cache()


def load_tests(loader, tests, pattern):
    # Reuse upstream's workshop behavior checks. Its full UI suite, including
    # font rasterization tests, still runs separately in the existing workflow.
    from tests.TestCharacterCodeTab import TestCharacterCodeTab
    related = {
        "test_team_lists_three_editable_character_codes",
        "test_team_dialogs_use_qt_kit_widgets",
        "test_team_info_shows_the_description_an_import_keeps",
    }
    names = set(loader.getTestCaseNames(TestCharacterCodeTab))
    if not related <= names:
        raise AssertionError("Upstream team-code regression tests changed; review compatibility.")
    for name in sorted(names):
        if "workshop" in name or name in related:
            tests.addTest(TestCharacterCodeTab(name))
    return tests


if __name__ == "__main__":
    unittest.main()
