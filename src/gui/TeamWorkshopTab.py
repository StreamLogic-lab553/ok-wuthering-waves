"""Keep the team workshop available in this fork.

This adapter keeps the existing editor, archive inspection and confirmation flow, and reads
the same public workshop data directly from its authoritative GitHub repository.
"""
import json
from urllib.parse import quote
from urllib.request import Request, urlopen

from src.gui.CharacterCodeTab import (
    CharacterCodeTab, WorkshopDialog, WORKSHOP_USER_AGENT, show_info_bar,
)

RAW_BASE = "https://raw.githubusercontent.com/ok-oldking/ok-ww-char-code/refs/heads/main/"
CATALOG_URL = RAW_BASE + "teams.json"
MAX_CATALOG_SIZE = 5_000_000


def _timestamp(code):
    try:
        return int(code.get("timestamp") or 0)
    except (TypeError, ValueError):
        return 0


def fetch_catalog():
    """Read the official static catalog without using the unavailable custom host."""
    request = Request(CATALOG_URL, headers={"User-Agent": WORKSHOP_USER_AGENT})
    with urlopen(request, timeout=15) as response:
        content = response.read(MAX_CATALOG_SIZE + 1)
    if len(content) > MAX_CATALOG_SIZE:
        raise ValueError("工坊目录超过大小限制。")
    payload = json.loads(content.decode("utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("teams"), list):
        raise ValueError("工坊目录格式不正确。")
    records = []
    for team in payload["teams"]:
        if not isinstance(team, dict) or not isinstance(team.get("codes"), list):
            continue
        for code in team["codes"]:
            if not isinstance(code, dict):
                continue
            record = dict(code)
            record["team"] = record.get("team") or team.get("team", "")
            record["members"] = record.get("members") or team.get("members", [])
            records.append(record)
    return sorted(records, key=_timestamp, reverse=True)


def archive_url(code):
    """Build a GitHub URL for one filename; never trust a catalog-supplied host."""
    if not isinstance(code, dict):
        raise ValueError("工坊压缩包记录格式不正确。")
    name = code.get("filename")
    if (not isinstance(name, str) or not name.lower().endswith(".zip")
            or name in {".", ".."} or any(char in name for char in ("/", "\\", "\x00", ":"))
            or name != name.strip()):
        raise ValueError("工坊压缩包文件名不正确。")
    return RAW_BASE + "codes/" + quote(name, safe="")


class TeamWorkshopTab(CharacterCodeTab):
    @property
    def name(self):
        return "角色工坊"

    def _open_workshop(self):
        if not self._guard_unsaved_changes():
            return
        try:
            codes = fetch_catalog()
        except Exception as error:
            show_info_bar(self.window(), str(error), title=self.tr("Workshop Error"), error=True)
            return
        dialog = WorkshopDialog(codes, parent=self.window())
        dialog.import_requested.connect(lambda code: self._import_workshop_code(code, dialog))
        dialog.exec()

    def _import_workshop_code(self, code, parent):
        try:
            url = archive_url(code)
        except (AttributeError, ValueError) as error:
            show_info_bar(parent, str(error), title=self.tr("Workshop Error"), error=True)
            return
        # Retain upstream's size limit, archive inspection and explicit import
        # confirmation, but replace the obsolete custom-domain download URL.
        super()._import_workshop_code({**code, "downloadUrl": url}, parent)
