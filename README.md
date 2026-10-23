# DeepLoL.gg -> LoL İstemcisi (LCU) Build & Rün Aktarıcı

`deeplol.gg` üzerindeki güncel **Meta (Koridor / ARAM)** ve **OTP (One-Trick Pony)** şampiyon buildlerini, rün sayfalarını, eşya setlerini (Item Sets) ve sihirdar büyülerini **League of Legends istemcisine (LCU API)** otomatik veya manuel olarak aktaran masaüstü uygulaması.

## ✨ Özellikler

- **🎯 Şampiyon Seçiminde Otomatik Aktarım:** LoL istemcisinde Şampiyon Seçimi (`ChampSelect`) ekranını dinler; seçtiğiniz veya üzerinde durduğunuz şampiyonu ve koridoru/oyun modunu (Sihirdar Vadisi / ARAM) algılayıp en yüksek performanslı buildi otomatik aktarır.
- **🏆 Meta, ARAM ve OTP (One-Trick) Desteği:**
  - Standart koridor (`Top`, `Jungle`, `Middle`, `Bottom`, `Support`) ve `ARAM` meta varyasyonları.
  - `KR`, `EUW`, `NA`, `TR`, `VN`, `TW`, `JP` sunucularındaki en yüksek LP'li **OTP (One-Trick)** oyuncularının kişisel build ve rün dizilimleri.
- **🔗 DeepLoL URL Desteği:** Herhangi bir `deeplol.gg` şampiyon/build/mastery bağlantısını yapıştırarak doğrudan yükleme.
- **🛡️ Güvenli Rün & Eşya Seti Yönetimi:** Kendi özel rün sayfalarınıza veya eşya setlerinize dokunmaz; yalnızca `[DeepLoL]` önekli sayfayı/seti oluşturur ve günceller.
- **⚡ Akıllı Sıçra (Flash) Tuş Koruması:** Sihirdar büyülerini aktarırken Sıçra'yı (`D` veya `F`) tercih ettiğiniz slota yerleştirir.
- **🇹🇷 Türkçe Önizleme:** DataDragon üzerinden rün, eşya, büyü ve yetenek (skill) önceliğini Türkçe isimleriyle listeler.

---

## 📥 İndirme ve Kurulum (Python Gerektirmez)

1. [**Releases**](https://github.com/MustafaKoceerr/deeplol-lcu-importer/releases/latest) sayfasından **`DeepLoL-LCU-Importer.exe`** dosyasını indirin.
2. League of Legends istemciniz açıkken `DeepLoL-LCU-Importer.exe` dosyasını çalıştırın.

---

## 🛠️ Kaynak Koddan Çalıştırma ve Derleme

### Gereksinimler
- Python 3.11+
- Windows (LCU bağlantısı için)

```powershell
# Bağımlılıkları yükle
python -m pip install -r requirements.txt

# Uygulamayı başlat
python main.py

# Birim testlerini çalıştır
python -m pytest

# Tek dosya .exe derle (dist/DeepLoL-LCU-Importer.exe)
.\build_exe.ps1
```
