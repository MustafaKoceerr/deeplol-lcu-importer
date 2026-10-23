# DeepLoL.gg -> League of Legends Client (LCU) Build & Rune Importer

Automatically or manually import **Meta (Summoner's Rift / ARAM)** and **OTP (One-Trick Pony)** champion builds, rune pages, item sets, and summoner spells from [`deeplol.gg`](https://www.deeplol.gg/) directly into your **League of Legends Client (LCU API)**.

---

## 🌐 16 Supported Languages (UI + Riot DataDragon Localization)

Switching languages in the top bar dynamically translates both the desktop interface and all Riot DataDragon item, rune, and summoner spell names without restarting:

`Türkçe` · `English` · `Español` · `中文 (简体)` · `中文 (繁體)` · `हिन्दी` · `العربية` · `Português` · `Русский` · `日本語` · `한국어` · `Deutsch` · `Français` · `Italiano` · `Tiếng Việt` · `Bahasa Indonesia`

---

## ✨ Features / Özellikler

- **🎯 Auto-Import in Champion Select (Otomatik Aktarım):** Detects your hovered/locked champion, assigned lane, and game mode (Summoner's Rift / ARAM) via `/lol-champ-select/v1/session` and imports the top build automatically.
- **🏆 Meta, ARAM & OTP (One-Trick) Builds:**
  - Standard lane (`Top`, `Jungle`, `Middle`, `Bottom`, `Support`) and `ARAM` meta variations.
  - High-LP **OTP (One-Trick)** player builds across `KR`, `EUW`, `NA`, `TR`, `VN`, `TW`, and `JP` regions.
- **🔗 DeepLoL URL Parser:** Paste any `deeplol.gg` champion/build/mastery URL to load it directly.
- **🛡️ Safe Rune & Item Set Management:** Never deletes your personal custom rune pages or item sets — only manages and updates the `[DeepLoL]` prefixed page/set.
- **⚡ Smart Flash (D/F) Placement:** Places Flash (`4`) on your preferred key (`D` or `F`) when importing summoner spells.

---

## 📥 Download & Run (No Python Required / Kurulum Gerektirmez)

1. Download **`DeepLoL-LCU-Importer.exe`** from the [**Latest Release**](https://github.com/MustafaKoceerr/deeplol-lcu-importer/releases/latest) page.
2. Run `DeepLoL-LCU-Importer.exe` while your League of Legends client is open.

---

## 🛠️ Run from Source & Build

```powershell
# Install dependencies / Bağımlılıkları yükle
python -m pip install -r requirements.txt

# Run application / Uygulamayı başlat
python main.py

# Run unit tests / Birim testlerini çalıştır
python -m pytest

# Build standalone .exe / Tek dosya .exe derle
.\build_exe.ps1
```
