from __future__ import annotations

from datetime import datetime
import threading
import customtkinter as ctk

from deeplol_importer.deeplol_client import (
    DeepLoLClient,
    map_lcu_position_to_deeplol_lane,
    parse_deeplol_url,
)
from deeplol_importer.lcu_client import LCUClient, resolve_summoner_spells
from deeplol_importer.models import NormalizedBuild, OTPPlayerSummary

SKILL_KEY_MAP = {1: "Q", 2: "W", 3: "E", 4: "R"}


class DeepLoLImporterApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("DeepLoL.gg -> LoL İstemcisi (LCU) Build & Rün Aktarıcı")
        self.geometry("980x740")
        self.minsize(880, 660)

        self.deeplol = DeepLoLClient()
        self.lcu = LCUClient()

        # State
        self._champions: list[tuple[int, str]] = []
        self._filtered_champions: list[tuple[int, str]] = []
        self._selected_champion_id: int = 103  # Default: Ahri
        self._meta_builds_by_lane: dict[str, list[NormalizedBuild]] = {}
        self._otp_players: list[OTPPlayerSummary] = []
        self._current_builds: list[NormalizedBuild] = []
        self._selected_build: NormalizedBuild | None = None
        self._last_auto_imported_key: tuple[int, str] | None = None
        self._stop_Polling = False

        self._build_ui()
        self._log("Uygulama başlatıldı. DeepLoL şampiyon verileri yükleniyor...")

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
            text="🔴 LCU: LoL İstemcisi Bekleniyor...",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#f87171",
        )
        self.lcu_status_label.grid(row=0, column=0, padx=12, pady=10, sticky="w")

        self.champ_select_label = ctk.CTkLabel(
            top_frame,
            text="Şampiyon Seçimi: Aktif Değil",
            font=ctk.CTkFont(size=12),
            text_color="#9ca3af",
        )
        self.champ_select_label.grid(row=0, column=1, padx=10, pady=10, sticky="w")

        self.auto_import_var = ctk.BooleanVar(value=True)
        self.auto_import_switch = ctk.CTkSwitch(
            top_frame,
            text="Şampiyon Seçiminde Otomatik Aktar",
            variable=self.auto_import_var,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.auto_import_switch.grid(row=0, column=2, padx=12, pady=10, sticky="e")

        # Options Row inside top_frame
        opts_frame = ctk.CTkFrame(top_frame, fg_color="transparent")
        opts_frame.grid(row=1, column=0, columnspan=3, padx=12, pady=(0, 10), sticky="ew")

        self.import_runes_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            opts_frame,
            text="Rün Sayfası Aktar",
            variable=self.import_runes_var,
        ).pack(side="left", padx=(0, 16))

        self.import_items_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            opts_frame,
            text="Eşya Seti (Item Set) Aktar",
            variable=self.import_items_var,
        ).pack(side="left", padx=(0, 16))

        self.import_spells_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            opts_frame,
            text="Sihirdar Büyülerini (D/F) Aktar",
            variable=self.import_spells_var,
        ).pack(side="left", padx=(0, 16))

        ctk.CTkLabel(opts_frame, text="Sıçra (Flash) Tuşu:").pack(side="left", padx=(8, 6))
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

        # Row 0: URL Input
        ctk.CTkLabel(
            ctrl_frame,
            text="DeepLoL URL:",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=0, column=0, padx=12, pady=(10, 6), sticky="w")

        self.url_entry = ctk.CTkEntry(
            ctrl_frame,
            placeholder_text="Örn: https://www.deeplol.gg/champions/ahri/build/mid veya /champions/ahri/mastery/all",
        )
        self.url_entry.grid(row=0, column=1, columnspan=3, padx=6, pady=(10, 6), sticky="ew")
        self.url_entry.bind("<Return>", lambda _: self._on_load_url_clicked())

        self.load_url_btn = ctk.CTkButton(
            ctrl_frame,
            text="URL'den Çek",
            width=120,
            command=self._on_load_url_clicked,
        )
        self.load_url_btn.grid(row=0, column=4, padx=12, pady=(10, 6))

        # Row 1: Manual Champion Filter + Dropdown + Mode + Lane/Region
        ctk.CTkLabel(
            ctrl_frame,
            text="Şampiyon Ara:",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=1, column=0, padx=12, pady=(4, 10), sticky="w")

        champ_subframe = ctk.CTkFrame(ctrl_frame, fg_color="transparent")
        champ_subframe.grid(row=1, column=1, padx=6, pady=(4, 10), sticky="ew")

        self.champ_search_var = ctk.StringVar()
        self.champ_search_entry = ctk.CTkEntry(
            champ_subframe,
            textvariable=self.champ_search_var,
            placeholder_text="Filtrele (örn. Ahri)...",
            width=140,
        )
        self.champ_search_entry.pack(side="left", padx=(0, 6))
        self.champ_search_entry.bind("<KeyRelease>", self._on_champion_Filter_changed)

        self.champ_menu_var = ctk.StringVar(value="Ahri")
        self.champ_menu = ctk.CTkOptionMenu(
            champ_subframe,
            variable=self.champ_menu_var,
            values=["Ahri"],
            width=170,
            command=self._on_champion_selected,
        )
        self.champ_menu.pack(side="left")

        self.mode_var = ctk.StringVar(value="Meta & ARAM")
        self.mode_segment = ctk.CTkSegmentedButton(
            ctrl_frame,
            values=["Meta & ARAM", "OTP (One-Trick)"],
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
            text="Verileri Yenile",
            width=120,
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
            text="OTP Oyuncu:",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.otp_player_var = ctk.StringVar(value="")
        self.otp_player_menu = ctk.CTkOptionMenu(
            selector_frame,
            variable=self.otp_player_var,
            values=["OTP Yükleniyor..."],
            command=self._on_otp_player_selected,
        )

        ctk.CTkLabel(
            selector_frame,
            text="Build Varyasyonu:",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=1, column=0, padx=12, pady=10, sticky="w")

        self.build_var = ctk.StringVar(value="Yükleniyor...")
        self.build_menu = ctk.CTkOptionMenu(
            selector_frame,
            variable=self.build_var,
            values=["Yükleniyor..."],
            command=self._on_build_variation_selected,
        )
        self.build_menu.grid(row=1, column=1, padx=8, pady=10, sticky="ew")

        self.import_btn = ctk.CTkButton(
            selector_frame,
            text="⚡ İstemciye Aktar (LCU Import)",
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

        ctk.CTkLabel(
            content_frame,
            text="Seçili Build & Rün Önizlemesi",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, padx=12, pady=(10, 4), sticky="w")

        ctk.CTkLabel(
            content_frame,
            text="İşlem Günlüğü (Log)",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=1, padx=12, pady=(10, 4), sticky="w")

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
            self._log(f"DeepLoL güncel yama: {ver} ({len(champs)} şampiyon yüklendi).")
            self._fetch_meta_builds_worker(self._selected_champion_id, preferred_lane="Middle")
        except Exception as exc:
            self._log(f"Başlangıç yükleme hatası: {exc}")

    def _on_champion_Filter_changed(self, _event=None) -> None:
        query = self.champ_search_var.get().strip().lower()
        if not query:
            self._filtered_champions = list(self._champions)
        else:
            self._filtered_champions = [
                (cid, name) for cid, name in self._champions if query in name.lower()
            ]
        names = [name for _, name in self._filtered_champions] or ["Sonuç Yok"]
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

    def _on_mode_changed(self, mode: str) -> None:
        if mode == "OTP (One-Trick)":
            self.lane_or_region_menu.configure(values=["KR", "EUW", "NA", "TR", "VN", "TW", "JP"])
            if self.lane_or_region_var.get() not in ("KR", "EUW", "NA", "TR", "VN", "TW", "JP"):
                self.lane_or_region_var.set("KR")
            self.otp_player_label.grid(row=0, column=0, padx=12, pady=(10, 0), sticky="w")
            self.otp_player_menu.grid(row=0, column=1, columnspan=2, padx=8, pady=(10, 0), sticky="ew")
        else:
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
        if self.mode_var.get() == "OTP (One-Trick)":
            threading.Thread(
                target=self._fetch_otp_list_worker,
                args=(self._selected_champion_id, value),
                daemon=True,
            ).start()
        else:
            lane_builds = self._meta_builds_by_lane.get(value, [])
            self._set_current_builds(lane_builds)

    def _reload_current_champion_data(self) -> None:
        if self.mode_var.get() == "OTP (One-Trick)":
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
            self._log("Lütfen bir deeplol.gg URL'si girin.")
            return
        try:
            parsed = parse_deeplol_url(url)
            cid = self.deeplol.resolve_champion_id(parsed.champion_slug)
            champ_name = self.deeplol.get_champion_name(cid)
            self._selected_champion_id = cid
            self.champ_menu_var.set(champ_name)

            if parsed.mode == "otp":
                self.mode_var.set("OTP (One-Trick)")
                self._on_mode_changed("OTP (One-Trick)")
            else:
                self.mode_var.set("Meta & ARAM")
                self.otp_player_label.grid_forget()
                self.otp_player_menu.grid_forget()
                threading.Thread(
                    target=self._fetch_meta_builds_worker,
                    args=(cid, parsed.lane),
                    daemon=True,
                ).start()
            self._log(f"URL çözümlendi: {champ_name} ({parsed.lane}, mod={parsed.mode})")
        except Exception as exc:
            self._log(f"URL hatası: {exc}")

    def _fetch_meta_builds_worker(
        self,
        champion_id: int,
        preferred_lane: str | None = None,
        auto_import: bool = False,
    ) -> None:
        try:
            champ_name = self.deeplol.get_champion_name(champion_id)
            self._log(f"{champ_name} için DeepLoL meta buildleri çekiliyor...")
            builds_by_lane = self.deeplol.get_meta_builds(champion_id)
            self._meta_builds_by_lane = builds_by_lane

            lanes = list(builds_by_lane.keys())
            if not lanes:
                self._log(f"{champ_name} için build bulunamadı.")
                return

            chosen_lane = preferred_lane if preferred_lane in builds_by_lane else lanes[0]
            lane_builds = builds_by_lane[chosen_lane]

            def _apply_ui() -> None:
                if self.mode_var.get() == "Meta & ARAM":
                    self.lane_or_region_menu.configure(values=lanes)
                    self.lane_or_region_var.set(chosen_lane)
                    self._set_current_builds(lane_builds)
                    if auto_import and lane_builds:
                        self._execute_lcu_import(lane_builds[0])

            self.after(0, _apply_ui)
        except Exception as exc:
            self._log(f"Meta build çekme hatası: {exc}")

    def _fetch_otp_list_worker(self, champion_id: int, region: str) -> None:
        try:
            champ_name = self.deeplol.get_champion_name(champion_id)
            self._log(f"{champ_name} ({region}) için OTP sıralaması çekiliyor...")
            otps = self.deeplol.get_otp_rankings(champion_id, platform_id=region)
            self._otp_players = otps
            if not otps:
                self._log(f"{champ_name} ({region}) için OTP verisi bulunamadı.")
                self.after(0, lambda: self.otp_player_menu.configure(values=["OTP Bulunamadı"]))
                return

            labels = [o.display_label for o in otps]

            def _update_otp_ui() -> None:
                self.otp_player_menu.configure(values=labels)
                self.otp_player_var.set(labels[0])

            self.after(0, _update_otp_ui)
            self._fetch_otp_builds_worker(champion_id, otps[0])
        except Exception as exc:
            self._log(f"OTP listesi hatası: {exc}")

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
            self._log(f"OTP {otp.riot_id_name} build detayları çekiliyor...")
            builds = self.deeplol.get_otp_player_builds(champion_id, otp)
            self.after(0, lambda: self._set_current_builds(builds))
        except Exception as exc:
            self._log(f"OTP build detayı hatası: {exc}")

    def _set_current_builds(self, builds: list[NormalizedBuild]) -> None:
        self._current_builds = list(builds)
        if not builds:
            self.build_menu.configure(values=["Build Bulunamadı"])
            self.build_var.set("Build Bulunamadı")
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
            self.preview_box.insert("end", "Gösterilecek build seçilmedi.")
            self.preview_box.configure(state="disabled")
            return

        lines: list[str] = []
        lines.append(f"Şampiyon : {b.champion_name} ({b.lane})")
        lines.append(f"Varyasyon: {b.label}")
        lines.append("=" * 62)

        # Runes section
        primary_tree = self.deeplol.format_style_name(b.runes.primary_style_id)
        sub_tree = self.deeplol.format_style_name(b.runes.sub_style_id)
        perks = b.runes.selected_perk_ids
        lines.append(f"\n[RÜN SAYFASI] -> [DeepLoL] {b.champion_name} - {b.lane}")
        lines.append(f"  Ana Ağaç ({primary_tree}):")
        for idx, pid in enumerate(perks[:4]):
            tag = "Anahtar Rün" if idx == 0 else f"Slot {idx}"
            lines.append(f"    • {tag}: {self.deeplol.format_perk_name(pid)} ({pid})")
        lines.append(f"  Yan Ağaç ({sub_tree}):")
        for pid in perks[4:6]:
            lines.append(f"    • {self.deeplol.format_perk_name(pid)} ({pid})")
        lines.append("  Nitelik Rünleri (Stat Shards - Saldırı / Esnek / Savunma):")
        for pid in perks[6:9]:
            lines.append(f"    • {self.deeplol.format_perk_name(pid)} ({pid})")

        # Items section
        lines.append(f"\n[EŞYA SETİ] -> [DeepLoL] {b.champion_name} - {b.lane}")
        for block in b.item_blocks:
            item_names = [self.deeplol.format_item_name(iid) for iid in block.item_ids]
            lines.append(f"  ▪ {block.title}:")
            lines.append(f"    {' -> '.join(item_names)}")

        # Spells section
        if len(b.spells) >= 2:
            s1, s2 = resolve_summoner_spells(b.spells, flash_key=self.flash_key_var.get())
            lines.append(
                f"\n[SİHİRDAR BÜYÜLERİ] (Sıçra={self.flash_key_var.get()}): "
                f"D: {self.deeplol.format_spell_name(s1)} | F: {self.deeplol.format_spell_name(s2)}"
            )

        # Skills section
        if b.skill_priority:
            prio_str = " > ".join(SKILL_KEY_MAP.get(s, str(s)) for s in b.skill_priority)
            lines.append(f"\n[YETENEK ÖNCELİĞİ]: {prio_str}")
        if b.skill_order:
            order_str = " - ".join(SKILL_KEY_MAP.get(s, str(s)) for s in b.skill_order[:15])
            lines.append(f"[İLK 15 SEVİYE]: {order_str}")

        self.preview_box.insert("end", "\n".join(lines))
        self.preview_box.configure(state="disabled")

    def _on_manual_import_clicked(self) -> None:
        if self._selected_build is None:
            self._log("Aktarılacak bir build seçili değil.")
            return
        self._execute_lcu_import(self._selected_build)

    def _execute_lcu_import(self, build: NormalizedBuild) -> None:
        def _worker() -> None:
            try:
                imported_parts: list[str] = []
                if self.import_runes_var.get():
                    self.lcu.import_rune_page(build)
                    imported_parts.append("Rün Sayfası")
                if self.import_items_var.get():
                    self.lcu.import_item_set(build)
                    imported_parts.append("Eşya Seti")
                if self.import_spells_var.get() and len(build.spells) >= 2:
                    try:
                        self.lcu.import_spells(build, flash_key=self.flash_key_var.get())
                        imported_parts.append(f"Büyüler (Sıçra={self.flash_key_var.get()})")
                    except Exception as spell_exc:
                        self._log(f"Büyü aktarım uyarısı: {spell_exc}")

                if imported_parts:
                    summary = ", ".join(imported_parts)
                    self._log(f"✅ LCU Aktarımı Başarılı ({build.champion_name} - {build.lane}): {summary}")
                else:
                    self._log("⚠️ Aktarılacak hiçbir bileşen seçili değil (Rün / Eşya / Büyü).")
            except Exception as exc:
                self._log(f"❌ LCU Aktarım Hatası: {exc}")

        threading.Thread(target=_worker, daemon=True).start()

    def _poll_lcu_loop(self) -> None:
        if self._stop_Polling:
            return
        threading.Thread(target=self._check_lcu_status_worker, daemon=True).start()
        self.after(2500, self._poll_lcu_loop)

    def _check_lcu_status_worker(self) -> None:
        try:
            summoner = self.lcu.get_current_summoner()
            game_name = summoner.get("gameName") or summoner.get("displayName") or "Sihirdar"
            tag_line = summoner.get("tagLine")
            full_name = f"{game_name}#{tag_line}" if tag_line else game_name

            cs_state = self.lcu.get_champ_select_state()

            def _update_connected() -> None:
                self.lcu_status_label.configure(
                    text=f"🟢 LCU Bağlı: {full_name}",
                    text_color="#34d399",
                )
                if not cs_state.in_champ_select:
                    self.champ_select_label.configure(
                        text="Şampiyon Seçimi: Aktif Değil",
                        text_color="#9ca3af",
                    )
                elif cs_state.champion_id > 0:
                    cname = self.deeplol.get_champion_name(cs_state.champion_id)
                    lane = map_lcu_position_to_deeplol_lane(cs_state.assigned_position, cs_state.game_mode)
                    self.champ_select_label.configure(
                        text=f"Şampiyon Seçimi: {cname} ({lane})",
                        text_color="#60a5fa",
                    )
                else:
                    self.champ_select_label.configure(
                        text="Şampiyon Seçimi: Şampiyon Bekleniyor...",
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
                    self._log(
                        f"🎯 Şampiyon Seçimi algılandı: {cname} ({detected_lane}) "
                        f"{'[Otomatik Aktarılıyor]' if should_auto else '[Önizleme Yükleniyor]'}"
                    )
                    self._fetch_meta_builds_worker(
                        cs_state.champion_id,
                        preferred_lane=detected_lane,
                        auto_import=should_auto,
                    )
            elif not cs_state.in_champ_select:
                self._last_auto_imported_key = None

        except Exception:
            def _update_disconnected() -> None:
                self.lcu_status_label.configure(
                    text="🔴 LCU: LoL İstemcisi Bekleniyor...",
                    text_color="#f87171",
                )
                self.champ_select_label.configure(
                    text="Şampiyon Seçimi: Aktif Değil",
                    text_color="#9ca3af",
                )

            self.after(0, _update_disconnected)
