from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import psutil
import requests
import urllib3

from deeplol_importer.models import NormalizedBuild

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

FLASH_SPELL_ID = 4


@dataclass(frozen=True)
class LCUConnectionInfo:
    port: int
    token: str
    protocol: str = "https"


@dataclass(frozen=True)
class ChampSelectState:
    in_champ_select: bool
    champion_id: int
    assigned_position: str
    game_mode: str
    is_locked: bool


def resolve_summoner_spells(spells: list[int], flash_key: str = "F") -> tuple[int, int]:
    """
    Ensure Flash (ID 4) is assigned to spell1Id (D) or spell2Id (F) according to user preference.
    """
    if len(spells) < 2:
        raise ValueError(f"En az 2 sihirdar büyüsü gerekli: {spells}")

    s1, s2 = int(spells[0]), int(spells[1])
    key = (flash_key or "F").strip().upper()

    if FLASH_SPELL_ID not in (s1, s2):
        return s1, s2

    other_spell = s2 if s1 == FLASH_SPELL_ID else s1
    if key == "D":
        return FLASH_SPELL_ID, other_spell
    return other_spell, FLASH_SPELL_ID


def discover_lcu_connection() -> LCUConnectionInfo | None:
    """
    Discover active LeagueClientUx.exe port and remoting-auth-token via psutil or lockfile.
    """
    try:
        for proc in psutil.process_iter(["name", "cmdline"]):
            name = (proc.info.get("name") or "").lower()
            if name not in ("leagueclientux.exe", "leagueclientux"):
                continue
            cmdline = proc.info.get("cmdline") or []
            port: int | None = None
            token: str | None = None
            for arg in cmdline:
                if arg.startswith("--app-port="):
                    port = int(arg.split("=", 1)[1])
                elif arg.startswith("--remoting-auth-token="):
                    token = arg.split("=", 1)[1]
            if port and token:
                return LCUConnectionInfo(port=port, token=token)
    except (psutil.Error, ValueError, OSError):
        pass

    candidate_paths = [
        Path("C:/Riot Games/League of Legends/lockfile"),
        Path("D:/Riot Games/League of Legends/lockfile"),
        Path("E:/Riot Games/League of Legends/lockfile"),
    ]
    for lf in candidate_paths:
        try:
            if lf.is_file():
                parts = lf.read_text(encoding="utf-8", errors="ignore").strip().split(":")
                if len(parts) >= 5:
                    return LCUConnectionInfo(
                        port=int(parts[2]),
                        token=parts[3],
                        protocol=parts[4] or "https",
                    )
        except OSError:
            continue

    return None


class LCUClient:
    def __init__(
        self,
        transport_override: Callable[[str, str, dict | None], tuple[int, Any]] | None = None,
    ) -> None:
        self._transport_override = transport_override
        self._session = requests.Session()
        self._session.verify = False
        self._conn_info: LCUConnectionInfo | None = None

    def is_connected(self) -> bool:
        try:
            summoner = self.get_current_summoner()
            return bool(summoner and summoner.get("summonerId"))
        except Exception:
            return False

    def _request(self, method: str, endpoint: str, json_data: dict | None = None) -> tuple[int, Any]:
        if self._transport_override is not None:
            return self._transport_override(method, endpoint, json_data)

        if self._conn_info is None:
            self._conn_info = discover_lcu_connection()
        if self._conn_info is None:
            raise ConnectionError("League of Legends istemcisi (LeagueClientUx.exe) açık değil.")

        url = f"{self._conn_info.protocol}://127.0.0.1:{self._conn_info.port}{endpoint}"
        try:
            resp = self._session.request(
                method=method.upper(),
                url=url,
                auth=("riot", self._conn_info.token),
                json=json_data,
                timeout=5,
                verify=False,
            )
        except requests.RequestException:
            # Refresh connection in case client restarted on a new port
            self._conn_info = discover_lcu_connection()
            if self._conn_info is None:
                raise ConnectionError("League of Legends istemcisiyle bağlantı kesildi.")
            url = f"{self._conn_info.protocol}://127.0.0.1:{self._conn_info.port}{endpoint}"
            resp = self._session.request(
                method=method.upper(),
                url=url,
                auth=("riot", self._conn_info.token),
                json=json_data,
                timeout=5,
                verify=False,
            )

        try:
            payload = resp.json() if resp.text else {}
        except ValueError:
            payload = {}
        return resp.status_code, payload

    def get_current_summoner(self) -> dict[str, Any]:
        status, data = self._request("GET", "/lol-summoner/v1/current-summoner")
        if status != 200 or not isinstance(data, dict):
            raise RuntimeError(f"Sihirdar bilgisi alınamadı (HTTP {status}).")
        return data

    def get_champ_select_state(self) -> ChampSelectState:
        status, session = self._request("GET", "/lol-champ-select/v1/session")
        if status != 200 or not isinstance(session, dict):
            return ChampSelectState(
                in_champ_select=False,
                champion_id=0,
                assigned_position="",
                game_mode="CLASSIC",
                is_locked=False,
            )

        local_cell_id = session.get("localPlayerCellId")
        my_team = session.get("myTeam") or []
        champion_id = 0
        pick_intent = 0
        assigned_position = ""

        for member in my_team:
            if member.get("cellId") == local_cell_id:
                champion_id = int(member.get("championId") or 0)
                pick_intent = int(member.get("championPickIntent") or 0)
                assigned_position = str(member.get("assignedPosition") or "")
                break

        effective_champ_id = champion_id if champion_id > 0 else pick_intent
        is_locked = champion_id > 0

        game_mode = "CLASSIC"
        gf_status, gf_data = self._request("GET", "/lol-gameflow/v1/session")
        if gf_status == 200 and isinstance(gf_data, dict):
            game_data = gf_data.get("gameData") or {}
            queue = game_data.get("queue") or {}
            game_mode = str(queue.get("gameMode") or "CLASSIC")

        return ChampSelectState(
            in_champ_select=True,
            champion_id=effective_champ_id,
            assigned_position=assigned_position,
            game_mode=game_mode,
            is_locked=is_locked,
        )

    def import_rune_page(self, build: NormalizedBuild, page_prefix: str = "[DeepLoL]") -> dict[str, Any]:
        status, pages = self._request("GET", "/lol-perks/v1/pages")
        if status != 200 or not isinstance(pages, list):
            raise RuntimeError(f"Rün sayfaları okunamadı (HTTP {status}).")

        # 1. Delete existing [DeepLoL] managed pages first so user's custom pages stay untouched
        deeplol_pages = [
            p
            for p in pages
            if p.get("isDeletable", True)
            and p.get("isEditable", True)
            and str(p.get("name") or "").startswith(page_prefix)
        ]

        for p in deeplol_pages:
            pid = p.get("id")
            if pid is not None:
                self._request("DELETE", f"/lol-perks/v1/pages/{pid}")

        page_name = f"{page_prefix} {build.champion_name} - {build.lane}"[:50]
        new_page_payload = {
            "name": page_name,
            "primaryStyleId": build.runes.primary_style_id,
            "subStyleId": build.runes.sub_style_id,
            "selectedPerkIds": list(build.runes.selected_perk_ids),
            "current": True,
        }

        post_status, created = self._request("POST", "/lol-perks/v1/pages", new_page_payload)
        if post_status in (200, 201):
            return created

        # Fallback if the user is at max rune page capacity and had no [DeepLoL] page yet:
        # replace the currently active editable page
        editable_pages = [p for p in pages if p.get("isEditable", False) and p.get("isDeletable", False)]
        if editable_pages:
            current_editable = next((p for p in editable_pages if p.get("current")), editable_pages[0])
            self._request("DELETE", f"/lol-perks/v1/pages/{current_editable['id']}")
            retry_status, retry_created = self._request("POST", "/lol-perks/v1/pages", new_page_payload)
            if retry_status in (200, 201):
                return retry_created

        raise RuntimeError(f"Rün sayfası oluşturulamadı (HTTP {post_status}): {created}")

    def import_item_set(
        self,
        build: NormalizedBuild,
        summoner_id: int | None = None,
        set_prefix: str = "[DeepLoL]",
    ) -> dict[str, Any]:
        if summoner_id is None:
            summoner_id = int(self.get_current_summoner()["summonerId"])

        endpoint = f"/lol-item-sets/v1/item-sets/{summoner_id}/sets"
        status, existing_payload = self._request("GET", endpoint)
        if status != 200 or not isinstance(existing_payload, dict):
            existing_payload = {"accountId": summoner_id, "itemSets": [], "timestamp": 0}

        existing_sets: list[dict] = list(existing_payload.get("itemSets") or [])

        # Keep all user custom sets and [DeepLoL] sets belonging to other champions;
        # replace only the [DeepLoL] set for this champion.
        filtered_sets: list[dict] = []
        for item_set in existing_sets:
            title = str(item_set.get("title") or "")
            assoc_champs = item_set.get("associatedChampions") or []
            is_same_champ_deeplol = title.startswith(set_prefix) and (
                build.champion_id in assoc_champs or not assoc_champs
            )
            if not is_same_champ_deeplol:
                filtered_sets.append(item_set)

        lcu_blocks: list[dict] = []
        for block in build.item_blocks:
            counts = Counter(block.item_ids)
            items_arr = [{"id": str(item_id), "count": count} for item_id, count in counts.items()]
            if items_arr:
                lcu_blocks.append({"type": block.title, "items": items_arr})

        new_item_set = {
            "uid": f"deeplol-{build.champion_id}-{build.lane.lower()}",
            "title": f"{set_prefix} {build.champion_name} - {build.lane}",
            "mode": "any",
            "map": "any",
            "type": "custom",
            "sortrank": 0,
            "startedFrom": "blank",
            "associatedChampions": [int(build.champion_id)],
            "associatedMaps": [11, 12],
            "blocks": lcu_blocks,
            "preferredItemSlots": [],
        }

        updated_payload = dict(existing_payload)
        updated_payload["itemSets"] = [new_item_set] + filtered_sets

        put_status, put_resp = self._request("PUT", endpoint, updated_payload)
        if put_status not in (200, 201, 204):
            raise RuntimeError(f"Eşya seti kaydedilemedi (HTTP {put_status}): {put_resp}")
        return new_item_set

    def import_spells(self, build: NormalizedBuild, flash_key: str = "F") -> tuple[int, int]:
        if len(build.spells) < 2:
            raise ValueError("Bu build içinde sihirdar büyüsü verisi bulunmuyor.")
        spell1_id, spell2_id = resolve_summoner_spells(build.spells, flash_key=flash_key)
        status, resp = self._request(
            "PATCH",
            "/lol-champ-select/v1/session/my-selection",
            {"spell1Id": spell1_id, "spell2Id": spell2_id},
        )
        if status not in (200, 204):
            raise RuntimeError(
                f"Sihirdar büyüleri uygulanamadı (Şampiyon Seçimi ekranında olmayabilirsiniz - HTTP {status})."
            )
        return spell1_id, spell2_id
