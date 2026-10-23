from __future__ import annotations

from datetime import datetime
import threading
import customtkinter as ctk

from deeplol_importer.deeplol_client import (
    DeepLoLClient,
    map_lcu_position_to_deeplol_lane,
    parse_deeplol_url,
)
from deeplol_importer.i18n import CODE_TO_DISPLAY, DISPLAY_TO_CODE, LANGUAGES, t
from deeplol_importer.lcu_client import LCUClient, resolve_summoner_spells
from deeplol_importer.models import NormalizedBuild, OTPPlayerSummary

SKILL_KEY_MAP = {1: "Q", 2: "W", 3: "E", 4: "R"}


class DeepLoLImporterApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.lang_code: str = "tr"
        self.deeplol = DeepLoLClient(lang_code=self.lang_code)
        self.lcu = LCUClient()

        self.title(t(self.lang_code, "window_title"))
        self.geometry("1020x750")
        self.minsize(900, 660)

        # State
        self._champions: list[tuple[int, str]] = []
        self._filtered_champions: list[tuple[int, str]] = []
        self._selected_champion_id: int = 103
        self._meta_builds_by_lane: dict[str, list[NormalizedBuild]] = {}
        self._otp_players: list[OTPPlayerSummary] = []
        self._current_builds: list[NormalizedBuild] = []
        self._selected_build: NormalizedBuild | None = None
        self._last_auto_imported_key: tuple[int, str] | None = None
        self._current_mode_key: str = "meta"  # "meta" or "otp"
        self._last_connected_summoner: str | None = None
        self._stop_polling = False

        self._build_ui()
        self._log(t(self.lang_code, "log_started"))

        threading.Thread(target=self._initial_load_worker, daemon=True).start()
        self.after(2000, self._poll_lcu_loop)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # 1. Top Status & Auto-Import Bar
        top_frame = ctk.CTkFrame(self, corner_radius=10)
        top_frame.grid(row=0, column=0, padx=14, pady=(12, 6), sticky="ew")
        top_frame.grid_columnconfigure(1, weight=1)

        self.lcu_status_label = ctk.CTkLabel(
            top_frame,
            text=t(self.lang_code, "lcu_waiting"),
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#f87171",
        )
        self.lcu_status_label.grid(row=0, column=0, padx=12, pady=10, sticky="w")

        self.champ_select_label = ctk.CTkLabel(
            top_frame,
            text=t(self.lang_code, "cs_inactive"),
            font=ctk.CTkFont(size=12),
            text_color="#9ca3af",
        )
        self.champ_select_label.grid(row=0, column=1, padx=10, pady=10, sticky="w")

        self.auto_import_var = ctk.BooleanVar(value=True)
        self.auto_import_switch = ctk.CTkSwitch(
            top_frame,
            text=t(self.lang_code, "auto_import"),
            variable=self.auto_import_var,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.auto_import_switch.grid(row=0, column=2, padx=10, pady=10, sticky="e")

        lang_names = [name for name, _ in LANGUAGES.values()]
        self.lang_var = ctk.StringVar(value=CODE_TO_DISPLAY[self.lang_code])
        self.lang_menu = ctk.CTkOptionMenu(
            top_frame,
            values=lang_names,
            variable=self.lang_var,
            width=145,
            command=self._on_language_changed,
        )
        self.lang_menu.grid(row=0, column=3, padx=(4, 12), pady=10, sticky="e")

        # Options Row inside top_frame
        opts_frame = ctk.CTkFrame(top_frame, fg_color="transparent")
        opts_frame.grid(row=1, column=0, columnspan=4, padx=12, pady=(0, 10), sticky="ew")

        self.import_runes_var = ctk.BooleanVar(value=True)
        self.chk_runes = ctk.CTkCheckBox(
            opts_frame,
            text=t(self.lang_code, "chk_runes"),
            variable=self.import_runes_var,
        )
        self.chk_runes.pack(side="left", padx=(0, 16))

        self.import_items_var = ctk.BooleanVar(value=True)
        self.chk_items = ctk.CTkCheckBox(
            opts_frame,
            text=t(self.lang_code, "chk_items"),
            variable=self.import_items_var,
        )
        self.chk_items.pack(side="left", padx=(0, 16))

        self.import_spells_var = ctk.BooleanVar(value=False)
        self.chk_spells = ctk.CTkCheckBox(
            opts_frame,
            text=t(self.lang_code, "chk_spells"),
            variable=self.import_spells_var,
        )
        self.chk_spells.pack(side="left", padx=(0, 16))

        self.lbl_flash_key = ctk.CTkLabel(opts_frame, text=t(self.lang_code, "flash_key"))
        self.lbl_flash_key.pack(side="left", padx=(8, 6))
        self.flash_key_var = ctk.StringVar(value="F")
        self.flash_key_menu = ctk.CTkOptionMenu(
            opts_frame,
            values=["F", "D"],
            variable=self.flash_key_var,
            width=70,
            command=lambda _: self._refresh_preview(),
        )
        self.flash_key_menu.pack(side="left")

        # 2. URL & Champion Selection Panel
        ctrl_frame = ctk.CTkFrame(self, corner_radius=10)
        ctrl_frame.grid(row=1, column=0, padx=14, pady=6, sticky="ew")
        ctrl_frame.grid_columnconfigure(1, weight=1)

        self.lbl_url = ctk.CTkLabel(
            ctrl_frame,
            text=t(self.lang_code, "lbl_url"),
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_url.grid(row=0, column=0, padx=12, pady=(10, 6), sticky="w")

        self.url_entry = ctk.CTkEntry(
            ctrl_frame,
            placeholder_text=t(self.lang_code, "ph_url"),
        )
        self.url_entry.grid(row=0, column=1, columnspan=3, padx=6, pady=(10, 6), sticky="ew")
        self.url_entry.bind("<Return>", lambda _: self._on_load_url_clicked())

        self.load_url_btn = ctk.CTkButton(
            ctrl_frame,
            text=t(self.lang_code, "btn_load_url"),
            width=125,
            command=self._on_load_url_clicked,
        )
        self.load_url_btn.grid(row=0, column=4, padx=12, pady=(10, 6))

        self.lbl_search_champ = ctk.CTkLabel(
            ctrl_frame,
            text=t(self.lang_code, "lbl_search_champ"),
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_search_champ.grid(row=1, column=0, padx=12, pady=(4, 10), sticky="w")

        champ_subframe = ctk.CTkFrame(ctrl_frame, fg_color="transparent")
        champ_subframe.grid(row=1, column=1, padx=6, pady=(4, 10), sticky="ew")

        self.champ_search_var = ctk.StringVar()
        self.champ_search_entry = ctk.CTkEntry(
            champ_subframe,
            textvariable=self.champ_search_var,
            placeholder_text=t(self.lang_code, "ph_search_champ"),
            width=140,
        )
        self.champ_search_entry.pack(side="left", padx=(0, 6))
        self.champ_search_entry.bind("<KeyRelease>", self._on_champion_filter_changed)

        self.champ_menu_var = ctk.StringVar(value="Ahri")
        self.champ_menu = ctk.CTkOptionMenu(
            champ_subframe,
            variable=self.champ_menu_var,
            values=["Ahri"],
            width=170,
            command=self._on_champion_selected,
        )
        self.champ_menu.pack(side="left")

        meta_label = t(self.lang_code, "mode_meta")
        otp_label = t(self.lang_code, "mode_otp")
        self.mode_var = ctk.StringVar(value=meta_label)
        self.mode_segment = ctk.CTkSegmentedButton(
            ctrl_frame,
            values=[meta_label, otp_label],
            variable=self.mode_var,
            command=self._on_mode_changed,
        )
        self.mode_segment.grid(row=1, column=2, padx=8, pady=(4, 10))

        self.lane_or_region_var = ctk.StringVar(value="Middle")
        self.lane_or_region_menu = ctk.CTkOptionMenu(
            ctrl_frame,
            variable=self.lane_or_region_var,
            values=["Top", "Jungle", "Middle", "Bottom", "Support", "Aram"],
            width=130,
            command=self._on_lane_or_region_changed,
        )
        self.lane_or_region_menu.grid(row=1, column=3, padx=6, pady=(4, 10))

        self.refresh_btn = ctk.CTkButton(
            ctrl_frame,
            text=t(self.lang_code, "btn_refresh"),
            width=125,
            fg_color="#374151",
            hover_color="#4b5563",
            command=self._reload_current_champion_data,
        )
        self.refresh_btn.grid(row=1, column=4, padx=12, pady=(4, 10))

        # 3. Build / OTP Selector Bar
        selector_frame = ctk.CTkFrame(self, corner_radius=10)
        selector_frame.grid(row=2, column=0, padx=14, pady=6, sticky="ew")
        selector_frame.grid_columnconfigure(1, weight=1)

        self.otp_player_label = ctk.CTkLabel(
            selector_frame,
            text=t(self.lang_code, "lbl_otp_player"),
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.otp_player_var = ctk.StringVar(value="")
        self.otp_player_menu = ctk.CTkOptionMenu(
            selector_frame,
            variable=self.otp_player_var,
            values=["..."],
            command=self._on_otp_player_selected,
        )

        self.lbl_build_var = ctk.CTkLabel(
            selector_frame,
            text=t(self.lang_code, "lbl_build_var"),
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_build_var.grid(row=1, column=0, padx=12, pady=10, sticky="w")

        self.build_var = ctk.StringVar(value="...")
        self.build_menu = ctk.CTkOptionMenu(
            selector_frame,
            variable=self.build_var,
            values=["..."],
            command=self._on_build_variation_selected,
        )
        self.build_menu.grid(row=1, column=1, padx=8, pady=10, sticky="ew")

        self.import_btn = ctk.CTkButton(
            selector_frame,
            text=t(self.lang_code, "btn_import"),
            font=ctk.CTkFont(size=13, weight="bold"),
            height=36,
            fg_color="#10b981",
            hover_color="#059669",
            command=self._on_manual_import_clicked,
        )
        self.import_btn.grid(row=1, column=2, padx=12, pady=10)

        # 4. Build Details Preview + Activity Log
        content_frame = ctk.CTkFrame(self, corner_radius=10)
        content_frame.grid(row=3, column=0, padx=14, pady=(6, 12), sticky="nsew")
        content_frame.grid_columnconfigure(0, weight=3)
        content_frame.grid_columnconfigure(1, weight=2)
        content_frame.grid_rowconfigure(1, weight=1)

        self.lbl_preview = ctk.CTkLabel(
            content_frame,
            text=t(self.lang_code, "lbl_preview"),
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.lbl_preview.grid(row=0, column=0, padx=12, pady=(10, 4), sticky="w")

        self.lbl_log = ctk.CTkLabel(
            content_frame,
            text=t(self.lang_code, "lbl_log"),
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.lbl_log.grid(row=0, column=1, padx=12, pady=(10, 4), sticky="w")

        self.preview_box = ctk.CTkTextbox(
            content_frame,
            font=ctk.CTkFont(family="Consolas", size=13),
            wrap="word",
        )
        self.preview_box.grid(row=1, column=0, padx=(12, 6), pady=(0, 12), sticky="nsew")

        self.log_box = ctk.CTkTextbox(
            content_frame,
            font=ctk.CTkFont(family="Consolas", size=12),
            wrap="word",
        )
        self.log_box.grid(row=1, column=1, padx=(6, 12), pady=(0, 12), sticky="nsew")

    def _on_language_changed(self, display_name: str) -> None:
        new_code = DISPLAY_TO_CODE.get(display_name, "en")
        if new_code == self.lang_code:
            return
        self.lang_code = new_code

        # Update static UI labels immediately
        self.title(t(self.lang_code, "window_title"))
        if self._last_connected_summoner:
            self.lcu_status_label.configure(
                text=t(self.lang_code, "lcu_connected", name=self._last_connected_summoner)
            )
        else:
            self.lcu_status_label.configure(text=t(self.lang_code, "lcu_waiting"))

        self.champ_select_label.configure(text=t(self.lang_code, "cs_inactive"))
        self.auto_import_switch.configure(text=t(self.lang_code, "auto_import"))
        self.chk_runes.configure(text=t(self.lang_code, "chk_runes"))
        self.chk_items.configure(text=t(self.lang_code, "chk_items"))
        self.chk_spells.configure(text=t(self.lang_code, "chk_spells"))
        self.lbl_flash_key.configure(text=t(self.lang_code, "flash_key"))
        self.lbl_url.configure(text=t(self.lang_code, "lbl_url"))
        self.url_entry.configure(placeholder_text=t(self.lang_code, "ph_url"))
        self.load_url_btn.configure(text=t(self.lang_code, "btn_load_url"))
        self.lbl_search_champ.configure(text=t(self.lang_code, "lbl_search_champ"))
        self.champ_search_entry.configure(placeholder_text=t(self.lang_code, "ph_search_champ"))

        meta_label = t(self.lang_code, "mode_meta")
        otp_label = t(self.lang_code, "mode_otp")
        self.mode_segment.configure(values=[meta_label, otp_label])
        self.mode_var.set(otp_label if self._current_mode_key == "otp" else meta_label)

        self.refresh_btn.configure(text=t(self.lang_code, "btn_refresh"))
        self.otp_player_label.configure(text=t(self.lang_code, "lbl_otp_player"))
        self.lbl_build_var.configure(text=t(self.lang_code, "lbl_build_var"))
        self.import_btn.configure(text=t(self.lang_code, "btn_import"))
        self.lbl_preview.configure(text=t(self.lang_code, "lbl_preview"))
        self.lbl_log.configure(text=t(self.lang_code, "lbl_log"))

        self._log(t(self.lang_code, "log_lang_changed", lang=display_name))

        def _switch_locale_worker() -> None:
            self.deeplol.set_language(new_code)
            self._reload_current_champion_data()

        threading.Thread(target=_switch_locale_worker, daemon=True).start()

    def _log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {message}\n"

        def _append() -> None:
            self.log_box.configure(state="normal")
            self.log_box.insert("end", line)
            self.log_box.see("end")
            self.log_box.configure(state="disabled")

        self.after(0, _append)

    def _initial_load_worker(self) -> None:
        try:
            ver = self.deeplol.get_recent_version()
            champs = self.deeplol.get_champion_list()
            self._champions = champs
            self._filtered_champions = list(champs)
            names = [name for _, name in champs]

            def _update_champ_menu() -> None:
                if names:
                    self.champ_menu.configure(values=names)
                    ahri_name = next((n for cid, n in champs if cid == 103), names[0])
                    self.champ_menu_var.set(ahri_name)

            self.after(0, _update_champ_menu)
            self._log(f"DeepLoL Patch: {ver} ({len(champs)} champions).")
            self._fetch_meta_builds_worker(self._selected_champion_id, preferred_lane="Middle")
        except Exception as exc:
            self._log(f"Init error: {exc}")

    def _on_champion_filter_changed(self, _event=None) -> None:
        query = self.champ_search_var.get().strip().lower()
        if not query:
            self._filtered_champions = list(self._champions)
        else:
            self._filtered_champions = [
                (cid, name) for cid, name in self._champions if query in name.lower()
            ]
        names = [name for _, name in self._filtered_champions] or ["-"]
        self.champ_menu.configure(values=names)
        if self._filtered_champions:
            first_cid, first_name = self._filtered_champions[0]
            if self.champ_menu_var.get() not in names:
                self.champ_menu_var.set(first_name)
                self._selected_champion_id = first_cid

    def _on_champion_selected(self, selected_name: str) -> None:
        for cid, name in self._champions:
            if name == selected_name:
                self._selected_champion_id = cid
                self._reload_current_champion_data()
                break

    def _on_mode_changed(self, selected_mode_label: str) -> None:
        otp_label = t(self.lang_code, "mode_otp")
        if selected_mode_label == otp_label:
            self._current_mode_key = "otp"
            self.lane_or_region_menu.configure(values=["KR", "EUW", "NA", "TR", "VN", "TW", "JP"])
            if self.lane_or_region_var.get() not in ("KR", "EUW", "NA", "TR", "VN", "TW", "JP"):
                self.lane_or_region_var.set("KR")
            self.otp_player_label.grid(row=0, column=0, padx=12, pady=(10, 0), sticky="w")
            self.otp_player_menu.grid(row=0, column=1, columnspan=2, padx=8, pady=(10, 0), sticky="ew")
        else:
            self._current_mode_key = "meta"
            self.otp_player_label.grid_forget()
            self.otp_player_menu.grid_forget()
            lanes = list(self._meta_builds_by_lane.keys()) or [
                "Top",
                "Jungle",
                "Middle",
                "Bottom",
                "Support",
                "Aram",
            ]
            self.lane_or_region_menu.configure(values=lanes)
            if self.lane_or_region_var.get() not in lanes:
                self.lane_or_region_var.set(lanes[0])
        self._reload_current_champion_data()

    def _on_lane_or_region_changed(self, value: str) -> None:
        if self._current_mode_key == "otp":
            threading.Thread(
                target=self._fetch_otp_list_worker,
                args=(self._selected_champion_id, value),
                daemon=True,
            ).start()
        else:
            lane_builds = self._meta_builds_by_lane.get(value, [])
            self._set_current_builds(lane_builds)

    def _reload_current_champion_data(self) -> None:
        if self._current_mode_key == "otp":
            region = self.lane_or_region_var.get() or "KR"
            threading.Thread(
                target=self._fetch_otp_list_worker,
                args=(self._selected_champion_id, region),
                daemon=True,
            ).start()
        else:
            preferred_lane = self.lane_or_region_var.get()
            threading.Thread(
                target=self._fetch_meta_builds_worker,
                args=(self._selected_champion_id, preferred_lane),
                daemon=True,
            ).start()

    def _on_load_url_clicked(self) -> None:
        url = self.url_entry.get().strip()
        if not url:
            return
        try:
            parsed = parse_deeplol_url(url)
            cid = self.deeplol.resolve_champion_id(parsed.champion_slug)
            champ_name = self.deeplol.get_champion_name(cid)
            self._selected_champion_id = cid
            self.champ_menu_var.set(champ_name)

            if parsed.mode == "otp":
                otp_label = t(self.lang_code, "mode_otp")
                self.mode_var.set(otp_label)
                self._on_mode_changed(otp_label)
            else:
                meta_label = t(self.lang_code, "mode_meta")
                self.mode_var.set(meta_label)
                self._current_mode_key = "meta"
                self.otp_player_label.grid_forget()
                self.otp_player_menu.grid_forget()
                threading.Thread(
                    target=self._fetch_meta_builds_worker,
                    args=(cid, parsed.lane),
                    daemon=True,
                ).start()
            self._log(f"URL: {champ_name} ({parsed.lane}, {parsed.mode})")
        except Exception as exc:
            self._log(f"URL Error: {exc}")

    def _fetch_meta_builds_worker(
        self,
        champion_id: int,
        preferred_lane: str | None = None,
        auto_import: bool = False,
    ) -> None:
        try:
            builds_by_lane = self.deeplol.get_meta_builds(champion_id)
            self._meta_builds_by_lane = builds_by_lane

            lanes = list(builds_by_lane.keys())
            if not lanes:
                return

            chosen_lane = preferred_lane if preferred_lane in builds_by_lane else lanes[0]
            lane_builds = builds_by_lane[chosen_lane]

            def _apply_ui() -> None:
                if self._current_mode_key == "meta":
                    self.lane_or_region_menu.configure(values=lanes)
                    self.lane_or_region_var.set(chosen_lane)
                    self._set_current_builds(lane_builds)
                    if auto_import and lane_builds:
                        self._execute_lcu_import(lane_builds[0])

            self.after(0, _apply_ui)
        except Exception as exc:
            self._log(f"Meta build error: {exc}")

    def _fetch_otp_list_worker(self, champion_id: int, region: str) -> None:
        try:
            otps = self.deeplol.get_otp_rankings(champion_id, platform_id=region)
            self._otp_players = otps
            if not otps:
                self.after(0, lambda: self.otp_player_menu.configure(values=["-"]))
                return

            labels = [o.display_label for o in otps]

            def _update_otp_ui() -> None:
                self.otp_player_menu.configure(values=labels)
                self.otp_player_var.set(labels[0])

            self.after(0, _update_otp_ui)
            self._fetch_otp_builds_worker(champion_id, otps[0])
        except Exception as exc:
            self._log(f"OTP list error: {exc}")

    def _on_otp_player_selected(self, label: str) -> None:
        for otp in self._otp_players:
            if otp.display_label == label:
                threading.Thread(
                    target=self._fetch_otp_builds_worker,
                    args=(self._selected_champion_id, otp),
                    daemon=True,
                ).start()
                break

    def _fetch_otp_builds_worker(self, champion_id: int, otp: OTPPlayerSummary) -> None:
        try:
            builds = self.deeplol.get_otp_player_builds(champion_id, otp)
            self.after(0, lambda: self._set_current_builds(builds))
        except Exception as exc:
            self._log(f"OTP build error: {exc}")

    def _set_current_builds(self, builds: list[NormalizedBuild]) -> None:
        self._current_builds = list(builds)
        if not builds:
            self.build_menu.configure(values=["-"])
            self.build_var.set("-")
            self._selected_build = None
            self._refresh_preview()
            return

        labels = [b.label for b in builds]
        self.build_menu.configure(values=labels)
        self.build_var.set(labels[0])
        self._selected_build = builds[0]
        self._refresh_preview()

    def _on_build_variation_selected(self, selected_label: str) -> None:
        for b in self._current_builds:
            if b.label == selected_label:
                self._selected_build = b
                self._refresh_preview()
                break

    def _refresh_preview(self) -> None:
        b = self._selected_build
        self.preview_box.configure(state="normal")
        self.preview_box.delete("1.0", "end")

        if b is None:
            self.preview_box.insert("end", t(self.lang_code, "preview_empty"))
            self.preview_box.configure(state="disabled")
            return

        lines: list[str] = []
        lines.append(t(self.lang_code, "preview_champ", champ=b.champion_name, lane=b.lane))
        lines.append(t(self.lang_code, "preview_var", label=b.label))
        lines.append("=" * 62)

        primary_tree = self.deeplol.format_style_name(b.runes.primary_style_id)
        sub_tree = self.deeplol.format_style_name(b.runes.sub_style_id)
        perks = b.runes.selected_perk_ids
        lines.append("\n" + t(self.lang_code, "preview_runes", champ=b.champion_name, lane=b.lane))
        lines.append(f"  {t(self.lang_code, 'preview_primary')} ({primary_tree}):")
        for idx, pid in enumerate(perks[:4]):
            tag = t(self.lang_code, "preview_keystone") if idx == 0 else f"Slot {idx}"
            lines.append(f"    • {tag}: {self.deeplol.format_perk_name(pid)} ({pid})")
        lines.append(f"  {t(self.lang_code, 'preview_sub')} ({sub_tree}):")
        for pid in perks[4:6]:
            lines.append(f"    • {self.deeplol.format_perk_name(pid)} ({pid})")
        lines.append(f"  {t(self.lang_code, 'preview_shards')}:")
        for pid in perks[6:9]:
            lines.append(f"    • {self.deeplol.format_perk_name(pid)} ({pid})")

        lines.append("\n" + t(self.lang_code, "preview_items", champ=b.champion_name, lane=b.lane))
        for block in b.item_blocks:
            item_names = [self.deeplol.format_item_name(iid) for iid in block.item_ids]
            lines.append(f"  ▪ {block.title}:")
            lines.append(f"    {' -> '.join(item_names)}")

        if len(b.spells) >= 2:
            s1, s2 = resolve_summoner_spells(b.spells, flash_key=self.flash_key_var.get())
            lines.append(
                f"\n{t(self.lang_code, 'preview_spells')} (Flash={self.flash_key_var.get()}): "
                f"D: {self.deeplol.format_spell_name(s1)} | F: {self.deeplol.format_spell_name(s2)}"
            )

        if b.skill_priority:
            prio_str = " > ".join(SKILL_KEY_MAP.get(s, str(s)) for s in b.skill_priority)
            lines.append(f"\n{t(self.lang_code, 'preview_skill_prio')}: {prio_str}")
        if b.skill_order:
            order_str = " - ".join(SKILL_KEY_MAP.get(s, str(s)) for s in b.skill_order[:15])
            lines.append(f"{t(self.lang_code, 'preview_skill_order')}: {order_str}")

        self.preview_box.insert("end", "\n".join(lines))
        self.preview_box.configure(state="disabled")

    def _on_manual_import_clicked(self) -> None:
        if self._selected_build is None:
            return
        self._execute_lcu_import(self._selected_build)

    def _execute_lcu_import(self, build: NormalizedBuild) -> None:
        def _worker() -> None:
            try:
                imported_parts: list[str] = []
                if self.import_runes_var.get():
                    self.lcu.import_rune_page(build)
                    imported_parts.append("Runes")
                if self.import_items_var.get():
                    self.lcu.import_item_set(build)
                    imported_parts.append("Item Set")
                if self.import_spells_var.get() and len(build.spells) >= 2:
                    try:
                        self.lcu.import_spells(build, flash_key=self.flash_key_var.get())
                        imported_parts.append(f"Spells (Flash={self.flash_key_var.get()})")
                    except Exception as spell_exc:
                        self._log(f"Spells warning: {spell_exc}")

                if imported_parts:
                    summary = ", ".join(imported_parts)
                    self._log(
                        t(
                            self.lang_code,
                            "log_imported",
                            champ=build.champion_name,
                            lane=build.lane,
                            parts=summary,
                        )
                    )
            except Exception as exc:
                self._log(f"❌ LCU Error: {exc}")

        threading.Thread(target=_worker, daemon=True).start()

    def _poll_lcu_loop(self) -> None:
        if self._stop_polling:
            return
        threading.Thread(target=self._check_lcu_status_worker, daemon=True).start()
        self.after(2500, self._poll_lcu_loop)

    def _check_lcu_status_worker(self) -> None:
        try:
            summoner = self.lcu.get_current_summoner()
            game_name = summoner.get("gameName") or summoner.get("displayName") or "Summoner"
            tag_line = summoner.get("tagLine")
            full_name = f"{game_name}#{tag_line}" if tag_line else game_name
            self._last_connected_summoner = full_name

            cs_state = self.lcu.get_champ_select_state()

            def _update_connected() -> None:
                self.lcu_status_label.configure(
                    text=t(self.lang_code, "lcu_connected", name=full_name),
                    text_color="#34d399",
                )
                if not cs_state.in_champ_select:
                    self.champ_select_label.configure(
                        text=t(self.lang_code, "cs_inactive"),
                        text_color="#9ca3af",
                    )
                elif cs_state.champion_id > 0:
                    cname = self.deeplol.get_champion_name(cs_state.champion_id)
                    lane = map_lcu_position_to_deeplol_lane(cs_state.assigned_position, cs_state.game_mode)
                    self.champ_select_label.configure(
                        text=t(self.lang_code, "cs_active", champ=cname, lane=lane),
                        text_color="#60a5fa",
                    )
                else:
                    self.champ_select_label.configure(
                        text=t(self.lang_code, "cs_waiting"),
                        text_color="#fbbf24",
                    )

            self.after(0, _update_connected)

            if cs_state.in_champ_select and cs_state.champion_id > 0:
                detected_lane = map_lcu_position_to_deeplol_lane(
                    cs_state.assigned_position,
                    cs_state.game_mode,
                )
                key = (cs_state.champion_id, detected_lane)
                if key != self._last_auto_imported_key:
                    self._last_auto_imported_key = key
                    self._selected_champion_id = cs_state.champion_id
                    cname = self.deeplol.get_champion_name(cs_state.champion_id)
                    self.after(0, lambda: self.champ_menu_var.set(cname))
                    should_auto = self.auto_import_var.get()
                    self._fetch_meta_builds_worker(
                        cs_state.champion_id,
                        preferred_lane=detected_lane,
                        auto_import=should_auto,
                    )
            elif not cs_state.in_champ_select:
                self._last_auto_imported_key = None

        except Exception:
            self._last_connected_summoner = None

            def _update_disconnected() -> None:
                self.lcu_status_label.configure(
                    text=t(self.lang_code, "lcu_waiting"),
                    text_color="#f87171",
                )
                self.champ_select_label.configure(
                    text=t(self.lang_code, "cs_inactive"),
                    text_color="#9ca3af",
                )

            self.after(0, _update_disconnected)
