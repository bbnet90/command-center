# Command Center

Python 3.11 veya üstü, Git ve pipx ile terminal panosunu kurup aç:

```sh
pipx install git+https://github.com/bbnet90/command-center.git
command-center
```

Bu sürümün kaynak kodunu indirdiysen proje klasöründe `pipx install .`
çalıştır. İlk açılışta kurulu panel yoksa katalog gelir. Bir panel seç,
Enter ile kaynağı ve komutu incele, y ile kurulumu onayla.
`command-center --plain` terminale tek bir özet yazar.

## Tuşlar

| Tuş | İşlem |
| --- | --- |
| Tab / Shift+Tab | Odağı ileri veya geri taşı |
| ↑ ↓ / PageUp PageDown | Paneli kaydır |
| r / R | Seçili paneli veya tüm panelleri yenile |
| [ / ] | Panel sırasını değiştir |
| Enter | Panelin programını aç veya soruyu gönder |
| l / t | Yerleşimi veya temayı değiştir |
| m | Kataloğu aç. Enter ile kurulum, x ile kaldırma planını gör |
| y / Esc | İşlemi onayla / pencereyi kapat |
| ? | Yardımı aç |
| q / Ctrl+C | Çık |

## Sorun giderme

- `command-center doctor` çevrimdışı çalışır. Kurulum ortamını, kullanılan dosyaları, yapılandırma hatalarını ve panel durumlarını gösterir.
- `command-center list` panelin görünür olup olmadığını, `command-center check <id>` hata ayrıntısını gösterir.
- Harici program açılmıyorsa aynı terminalde komutun PATH içinde olduğunu kontrol et.
- Katalog bağlantısını kapatmak için `~/.config/command-center/config.toml` dosyasına `catalog_refresh = false` yaz. XDG_CONFIG_HOME ayarlıysa onun altındaki command-center klasörü kullanılır.

[Yapılandırma ve modül yazma kılavuzu (İngilizce)](README.md)
