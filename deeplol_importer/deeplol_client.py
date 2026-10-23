from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse
import requests

from deeplol_importer.i18n import get_ddragon_locale, t
from deeplol_importer.models import (
    ItemBlockData,
    NormalizedBuild,
    OTPPlayerSummary,
    ParsedDeepLoLUrl,
    RunePageData,
)

DEEPLOL_API_BASE = "https://b2c-api-cdn.deeplol.gg"

LANE_ALIASES: dict[str, str] = {
    "top": "Top",
    "jungle": "Jungle",
    "jgl": "Jungle",
    "jg": "Jungle",
    "mid": "Middle",
    "middle": "Middle",
    "bot": "Bottom",
    "bottom": "Bottom",
    "adc": "Bottom",
    "sup": "Support",
    "supp": "Support",
    "support": "Support",
    "utility": "Support",
    "aram": "Aram",
    "all": "All",
}

SPELL_FALLBACK_EN: dict[int, str] = {
    1: "Cleanse",
    3: "Exhaust",
    4: "Flash",
    6: "Ghost",
    7: "Heal",
    11: "Smite",
    12: "Teleport",
    13: "Clarity",
    14: "Ignite",
    21: "Barrier",
    32: "Mark / Dash",
}

STYLE_FALLBACK_EN: dict[int, str] = {
    8000: "Precision",
    8100: "Domination",
    8200: "Sorcery",
    8300: "Inspiration",
    8400: "Resolve",
}

STAT_SHARD_BY_LANG: dict[str, dict[int, str]] = {
    "tr": {
        5008: "Değişken Kuvvet (+9)",
        5005: "Saldırı Hızı (%10)",
        5007: "Yetenek Hızı (+8)",
        5010: "Hareket Hızı (%2)",
        5011: "Taban Can (+65)",
        5013: "Sıvışma ve Yavaşlatma Direnci (%10)",
        5001: "Büyüyen Can (+10-180)",
    },
    "en": {
        5008: "Adaptive Force (+9)",
        5005: "Attack Speed (+10%)",
        5007: "Ability Haste (+8)",
        5010: "Move Speed (+2%)",
        5011: "Health (+65)",
        5013: "Tenacity & Slow Resist (+10%)",
        5001: "Health Scaling (+10-180)",
    },
}


def normalize_slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def normalize_rune_perks(
    main_build: list[int],
    sub_build: list[int],
    stat_build: list[int],
) -> RunePageData:
    """
    Convert DeepLoL rune arrays into LCU RunePageData.
    Note: DeepLoL returns stat_build in reverse order [defense, flex, offense].
    LCU expects [offense, flex, defense] at the end of selectedPerkIds.
    """
    if len(main_build) < 5 or len(sub_build) < 3 or len(stat_build) < 3:
        raise ValueError(
            f"Eksik rün verisi: main={main_build}, sub={sub_build}, stat={stat_build}"
        )

    primary_style_id = int(main_build[0])
    sub_style_id = int(sub_build[0])
    primary_perks = [int(x) for x in main_build[1:5]]
    sub_perks = [int(x) for x in sub_build[1:3]]
    stat_perks = [int(stat_build[2]), int(stat_build[1]), int(stat_build[0])]

    return RunePageData(
        primary_style_id=primary_style_id,
        sub_style_id=sub_style_id,
        selected_perk_ids=primary_perks + sub_perks + stat_perks,
    )


def map_lcu_position_to_deeplol_lane(assigned_position: str, game_mode: str = "CLASSIC") -> str:
    mode_upper = (game_mode or "").upper()
    if mode_upper in ("ARAM", "KIWI", "CHERRY"):
        return "Aram"
    pos_clean = (assigned_position or "").strip().lower()
    return LANE_ALIASES.get(pos_clean, "Middle")


def parse_deeplol_url(url: str) -> ParsedDeepLoLUrl:
    cleaned = (url or "").strip()
    if not cleaned:
        raise ValueError("Empty URL.")
    if not cleaned.startswith(("http://", "https://")):
        cleaned = "https://" + cleaned

    parsed = urlparse(cleaned)
    host = parsed.netloc.lower()
    if "deeplol.gg" not in host:
        raise ValueError(f"Invalid deeplol.gg URL: {url}")

    path_parts = [p for p in parsed.path.split("/") if p]
    query = parse_qs(parsed.query)

    if len(path_parts) >= 2 and path_parts[0].lower() == "champions" and path_parts[1].lower() == "detail":
        champ_list = query.get("championName") or query.get("champion")
        if not champ_list:
            raise ValueError("championName parameter missing in URL.")
        champ_slug = normalize_slug(champ_list[0])
        lane_raw = (query.get("lane", ["Middle"])[0]).lower()
        lane = LANE_ALIASES.get(lane_raw, "Middle")
        return ParsedDeepLoLUrl(champion_slug=champ_slug, lane=lane, mode="meta")

    if len(path_parts) >= 2 and path_parts[0].lower() == "champions":
        champ_slug = normalize_slug(path_parts[1])
        mode = "meta"
        lane = "Middle"
        if len(path_parts) >= 3:
            sub_section = path_parts[2].lower()
            if sub_section in ("mastery", "otp"):
                mode = "otp"
                lane = "All"
            elif sub_section in LANE_ALIASES:
                lane = LANE_ALIASES[sub_section]
        if len(path_parts) >= 4:
            lane_raw = path_parts[3].lower()
            lane = LANE_ALIASES.get(lane_raw, lane)
        return ParsedDeepLoLUrl(champion_slug=champ_slug, lane=lane, mode=mode)

    raise ValueError(f"Unsupported deeplol.gg URL format: {url}")


class DeepLoLClient:
    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: int = 10,
        lang_code: str = "tr",
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
            }
        )
        self.timeout = timeout
        self.lang_code = lang_code
        self._recent_version: str | None = None
        self._dd_version: str | None = None
        self._champions_by_id: dict[int, dict] = {}
        self._champion_id_by_slug: dict[str, int] = {}

        # Per-locale DataDragon caches
        self._loaded_locales: set[str] = set()
        self._item_names_by_locale: dict[str, dict[int, str]] = {}
        self._perk_names_by_locale: dict[str, dict[int, str]] = {}
        self._style_names_by_locale: dict[str, dict[int, str]] = {}
        self._spell_names_by_locale: dict[str, dict[int, str]] = {}

    def set_language(self, lang_code: str) -> None:
        self.lang_code = lang_code
        locale = get_ddragon_locale(lang_code)
        if locale not in self._loaded_locales:
            self._load_ddragon_locale(locale)

    def get_recent_version(self) -> str:
        if self._recent_version:
            return self._recent_version
        resp = self.session.get(
            f"{DEEPLOL_API_BASE}/champion/version",
            params={"cnt": 3},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        self._recent_version = data.get("recent_version") or (data.get("game_version_list") or ["16.21"])[0]
        return self._recent_version

    def ensure_static_data(self) -> None:
        if not self._champions_by_id:
            resp = self.session.get(
                f"{DEEPLOL_API_BASE}/common/champion-info",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            champions = resp.json().get("champions", [])
            for ch in champions:
                cid = int(ch["champion_id"])
                name_en = ch.get("champion_name_en", f"Champion {cid}")
                image_key = ch.get("image_name", "").replace(".png", "")
                self._champions_by_id[cid] = {
                    "id": cid,
                    "name": name_en,
                    "key": image_key or name_en,
                }
                self._champion_id_by_slug[normalize_slug(name_en)] = cid
                if image_key:
                    self._champion_id_by_slug[normalize_slug(image_key)] = cid

        locale = get_ddragon_locale(self.lang_code)
        if locale not in self._loaded_locales:
            self._load_ddragon_locale(locale)

    def _load_ddragon_locale(self, locale: str) -> None:
        try:
            if not self._dd_version:
                ver_resp = self.session.get(
                    "https://ddragon.leagueoflegends.com/api/versions.json",
                    timeout=5,
                )
                ver_resp.raise_for_status()
                self._dd_version = ver_resp.json()[0]

            dd_ver = self._dd_version
            item_map: dict[int, str] = {}
            perk_map: dict[int, str] = dict(
                STAT_SHARD_BY_LANG.get("tr" if locale == "tr_TR" else "en", STAT_SHARD_BY_LANG["en"])
            )
            style_map: dict[int, str] = dict(STYLE_FALLBACK_EN)
            spell_map: dict[int, str] = dict(SPELL_FALLBACK_EN)

            items_resp = self.session.get(
                f"https://ddragon.leagueoflegends.com/cdn/{dd_ver}/data/{locale}/item.json",
                timeout=5,
            )
            if items_resp.ok:
                for item_id_str, item_info in items_resp.json().get("data", {}).items():
                    if item_id_str.isdigit():
                        item_map[int(item_id_str)] = item_info.get("name", item_id_str)

            runes_resp = self.session.get(
                f"https://ddragon.leagueoflegends.com/cdn/{dd_ver}/data/{locale}/runesReforged.json",
                timeout=5,
            )
            if runes_resp.ok:
                for tree in runes_resp.json():
                    tree_id = int(tree.get("id") or 0)
                    if tree_id:
                        style_map[tree_id] = tree.get("name", str(tree_id))
                    for slot in tree.get("slots", []):
                        for rune in slot.get("runes", []):
                            perk_map[int(rune["id"])] = rune.get("name", str(rune["id"]))

            spells_resp = self.session.get(
                f"https://ddragon.leagueoflegends.com/cdn/{dd_ver}/data/{locale}/summoner.json",
                timeout=5,
            )
            if spells_resp.ok:
                for spell_info in spells_resp.json().get("data", {}).values():
                    key_str = str(spell_info.get("key") or "")
                    if key_str.isdigit():
                        spell_map[int(key_str)] = spell_info.get("name", key_str)

            self._item_names_by_locale[locale] = item_map
            self._perk_names_by_locale[locale] = perk_map
            self._style_names_by_locale[locale] = style_map
            self._spell_names_by_locale[locale] = spell_map
            self._loaded_locales.add(locale)
        except Exception:
            pass

    def get_champion_list(self) -> list[tuple[int, str]]:
        self.ensure_static_data()
        return sorted(
            [(cid, info["name"]) for cid, info in self._champions_by_id.items()],
            key=lambda x: x[1].lower(),
        )

    def resolve_champion_id(self, name_or_slug: str) -> int:
        self.ensure_static_data()
        slug = normalize_slug(name_or_slug)
        if slug in self._champion_id_by_slug:
            return self._champion_id_by_slug[slug]
        for key_slug, cid in self._champion_id_by_slug.items():
            if slug in key_slug or key_slug in slug:
                return cid
        raise ValueError(f"Champion not found: {name_or_slug}")

    def get_champion_name(self, champion_id: int) -> str:
        self.ensure_static_data()
        return self._champions_by_id.get(champion_id, {}).get("name", f"Champion #{champion_id}")

    def format_item_name(self, item_id: int) -> str:
        self.ensure_static_data()
        locale = get_ddragon_locale(self.lang_code)
        name = self._item_names_by_locale.get(locale, {}).get(int(item_id))
        return f"{name}" if name else f"Item #{item_id}"

    def format_perk_name(self, perk_id: int) -> str:
        self.ensure_static_data()
        locale = get_ddragon_locale(self.lang_code)
        name = self._perk_names_by_locale.get(locale, {}).get(int(perk_id))
        return f"{name}" if name else f"Perk #{perk_id}"

    def format_style_name(self, style_id: int) -> str:
        self.ensure_static_data()
        locale = get_ddragon_locale(self.lang_code)
        return self._style_names_by_locale.get(locale, STYLE_FALLBACK_EN).get(
            int(style_id), f"Style #{style_id}"
        )

    def format_spell_name(self, spell_id: int) -> str:
        self.ensure_static_data()
        locale = get_ddragon_locale(self.lang_code)
        return self._spell_names_by_locale.get(locale, SPELL_FALLBACK_EN).get(
            int(spell_id), f"Spell #{spell_id}"
        )

    def get_meta_builds(
        self,
        champion_id: int,
        tier: str = "Emerald+",
        platform_id: str = "KR",
    ) -> dict[str, list[NormalizedBuild]]:
        self.ensure_static_data()
        version = self.get_recent_version()
        champ_name = self.get_champion_name(champion_id)

        resp = self.session.get(
            f"{DEEPLOL_API_BASE}/champion/build",
            params={
                "platform_id": platform_id,
                "champion_id": champion_id,
                "game_version": version,
                "tier": tier,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        build_by_lane = resp.json().get("build_by_lane", {})
        games_word = t(self.lang_code, "games")

        result: dict[str, list[NormalizedBuild]] = {}
        for lane_name, lane_payload in build_by_lane.items():
            if not isinstance(lane_payload, dict):
                continue
            raw_list = lane_payload.get("build_lst") or []
            lane_builds: list[NormalizedBuild] = []
            for idx, entry in enumerate(raw_list, start=1):
                try:
                    rune_obj = entry.get("rune") or {}
                    runes = normalize_rune_perks(
                        rune_obj.get("main_build") or [],
                        rune_obj.get("sub_build") or [],
                        rune_obj.get("stat_build") or [],
                    )
                except ValueError:
                    continue

                start_items = [int(x) for x in (entry.get("start_item", {}).get("build") or []) if x]
                boots_id = entry.get("boots", {}).get("item")
                core_items = [int(x) for x in (entry.get("item", {}).get("build") or []) if x]
                detail_items = [int(x) for x in (entry.get("item", {}).get("detail") or []) if x]

                blocks: list[ItemBlockData] = []
                starter_and_boots = list(start_items)
                if boots_id and int(boots_id) not in starter_and_boots:
                    starter_and_boots.append(int(boots_id))
                if starter_and_boots:
                    blocks.append(
                        ItemBlockData(title=t(self.lang_code, "starter_boots"), item_ids=starter_and_boots)
                    )
                if core_items:
                    blocks.append(
                        ItemBlockData(title=t(self.lang_code, "core_items"), item_ids=core_items)
                    )
                if detail_items:
                    blocks.append(
                        ItemBlockData(title=t(self.lang_code, "build_order"), item_ids=detail_items)
                    )

                spells = [int(x) for x in (entry.get("spell", {}).get("build") or []) if x]
                skill_prio = [int(x) for x in (entry.get("skill", {}).get("build") or []) if x]
                skill_order = [int(x) for x in (entry.get("skill", {}).get("detail") or []) if x]

                win_rate = float(entry.get("win_rate") or 0.0)
                pick_rate = float(entry.get("pick_rate") or 0.0)
                games = int(entry.get("games") or 0)
                keystone_name = self.format_perk_name(runes.selected_perk_ids[0])
                main_item_id = entry.get("main_item") or (core_items[0] if core_items else 0)
                main_item_name = self.format_item_name(int(main_item_id)) if main_item_id else "Build"

                label = (
                    f"Meta #{idx}: {keystone_name} + {main_item_name} "
                    f"(%{win_rate * 100:.1f} WR | %{pick_rate * 100:.1f} PR | {games} {games_word})"
                )

                lane_builds.append(
                    NormalizedBuild(
                        label=label,
                        champion_id=champion_id,
                        champion_name=champ_name,
                        lane=lane_name,
                        games=games,
                        win_rate=win_rate,
                        pick_rate=pick_rate,
                        runes=runes,
                        item_blocks=blocks,
                        spells=spells,
                        skill_priority=skill_prio,
                        skill_order=skill_order,
                    )
                )
            if lane_builds:
                result[lane_name] = lane_builds

        return result

    def get_otp_rankings(
        self,
        champion_id: int,
        platform_id: str = "KR",
        lane: str = "All",
        cnt: int = 15,
    ) -> list[OTPPlayerSummary]:
        resp = self.session.get(
            f"{DEEPLOL_API_BASE}/champion/mastery_rank",
            params={
                "platform_id": platform_id,
                "lane": lane,
                "champion_id": champion_id,
                "cnt": cnt,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data_list = resp.json().get("data_list") or []
        otps: list[OTPPlayerSummary] = []
        for row in data_list:
            puu_id = row.get("puu_id")
            if not puu_id:
                continue
            otps.append(
                OTPPlayerSummary(
                    rank=int(row.get("rank") or 0),
                    platform_id=str(row.get("platform_id") or platform_id),
                    tier=str(row.get("tier") or ""),
                    lp=int(row.get("lp") or 0),
                    champion_id=int(row.get("champion_id") or champion_id),
                    riot_id_name=str(row.get("riot_id_name") or row.get("name") or "OTP"),
                    riot_id_tag_line=str(row.get("riot_id_tag_line") or ""),
                    lane=str(row.get("lane") or "Middle"),
                    games=int(row.get("games") or 0),
                    win_rate=float(row.get("win_rate") or 0.0),
                    kda=float(row.get("kda") or 0.0),
                    puu_id=str(puu_id),
                )
            )
        return otps

    def get_otp_player_builds(
        self,
        champion_id: int,
        otp: OTPPlayerSummary,
    ) -> list[NormalizedBuild]:
        self.ensure_static_data()
        champ_name = self.get_champion_name(champion_id)
        resp = self.session.get(
            f"{DEEPLOL_API_BASE}/champion/master_build",
            params={
                "puu_id": otp.puu_id,
                "platform_id": otp.platform_id,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        champ_entries = resp.json().get("data") or []

        target_entry = None
        for ce in champ_entries:
            if int(ce.get("champion_id") or 0) == int(champion_id):
                target_entry = ce
                break
        if not target_entry and champ_entries:
            target_entry = champ_entries[0]
        if not target_entry:
            return []

        games_word = t(self.lang_code, "games")
        builds: list[NormalizedBuild] = []
        data_list = target_entry.get("data_list") or []
        for group in data_list:
            if group.get("version") != "All":
                continue
            lane_name = group.get("lane") or otp.lane or "Middle"
            for detail in group.get("build_detail") or []:
                rune_main_id = int(detail.get("rune_main") or 0)
                core_item_id = int(detail.get("core_item") or 0)
                if rune_main_id == 0 and core_item_id == 0:
                    continue

                rune_obj = detail.get("rune") or {}
                try:
                    runes = normalize_rune_perks(
                        rune_obj.get("rune_main") or [],
                        rune_obj.get("rune_sub") or [],
                        rune_obj.get("rune_stat") or [],
                    )
                except ValueError:
                    continue

                blocks: list[ItemBlockData] = []
                start_list = detail.get("start_item") or []
                starter_ids: list[int] = []
                if start_list and isinstance(start_list[0], dict):
                    starter_ids = [int(x) for x in (start_list[0].get("start_item") or []) if x]

                boots_list = detail.get("boots") or []
                if boots_list and isinstance(boots_list[0], dict):
                    b_id = boots_list[0].get("boots")
                    if b_id and int(b_id) not in starter_ids:
                        starter_ids.append(int(b_id))

                if starter_ids:
                    blocks.append(
                        ItemBlockData(title=t(self.lang_code, "starter_boots"), item_ids=starter_ids)
                    )

                core_ids: list[int] = []
                for key in ("item_build_3", "item_build_4", "item_build_2", "item_build_5"):
                    arr = detail.get(key) or []
                    if arr and isinstance(arr[0], dict):
                        for item_id in arr[0].get("items") or []:
                            if item_id and int(item_id) not in core_ids:
                                core_ids.append(int(item_id))
                if not core_ids and core_item_id:
                    core_ids.append(core_item_id)
                if core_ids:
                    blocks.append(
                        ItemBlockData(title=t(self.lang_code, "otp_core_items"), item_ids=core_ids)
                    )

                spells: list[int] = []
                spell_list = detail.get("spell") or []
                if spell_list and isinstance(spell_list[0], dict):
                    spells = [int(x) for x in (spell_list[0].get("spell") or []) if x]

                skill_prio: list[int] = []
                seq_list = detail.get("skill_master_seq") or []
                if seq_list and isinstance(seq_list[0], dict):
                    skill_prio = [int(x) for x in (seq_list[0].get("skill") or []) if x]

                skill_order: list[int] = []
                sb_list = detail.get("skill_build") or []
                if sb_list and isinstance(sb_list[0], dict):
                    skill_order = [int(x) for x in (sb_list[0].get("skill") or []) if x]

                games = int(detail.get("games") or otp.games)
                win_rate = float(detail.get("win_rate") or otp.win_rate)
                keystone_name = self.format_perk_name(runes.selected_perk_ids[0])
                core_name = self.format_item_name(core_ids[0]) if core_ids else "Build"

                label = (
                    f"OTP {otp.riot_id_name} ({lane_name}): {keystone_name} + {core_name} "
                    f"(%{win_rate * 100:.1f} WR | {games} {games_word})"
                )
                builds.append(
                    NormalizedBuild(
                        label=label,
                        champion_id=champion_id,
                        champion_name=champ_name,
                        lane=lane_name if lane_name != "All" else otp.lane,
                        games=games,
                        win_rate=win_rate,
                        pick_rate=float(rune_obj.get("pick_rate") or 1.0),
                        runes=runes,
                        item_blocks=blocks,
                        spells=spells,
                        skill_priority=skill_prio,
                        skill_order=skill_order,
                    )
                )

        unique_builds: list[NormalizedBuild] = []
        seen_keys: set[tuple] = set()
        for b in builds:
            key = (tuple(b.runes.selected_perk_ids), tuple(b.item_blocks[0].item_ids if b.item_blocks else []))
            if key not in seen_keys:
                seen_keys.add(key)
                unique_builds.append(b)
        return unique_builds
