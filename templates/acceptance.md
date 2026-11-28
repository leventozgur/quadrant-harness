# Kabul testleri (PM yazar — tester_mode "pm", HX-55)

Opus spec'i yazdıktan hemen sonra, kod yazılmadan önce gizli kabul testlerini `hx paths <iş>` çıktısındaki `hidden`
dizinine yazar, sonra `hx tests <iş>` ile kaydeder. Worker bu dosyaları görmez; testler düşerse worker'a yalnız
**düşen testlerin adları** gider. Bu yüzden test adı kuralın kendisidir.

## Kurallar
1. **Az ve keskin:** 3–8 test. Her test spec'te yazılı bir kuralı veya sınır durumunu kontrol eder; spec'in söylemediği
   davranışı test etme (sıralama, biçim, alan adı, zaman garanti edilmediyse).
2. **Ad = kural:** test adı Türkçe, kuralı tek cümlede söyler ("boş girdi boş liste döner", "eşitlikte sol taraf kazanır").
   unittest'te ad kısa olabilir ama ilk docstring satırı kuralı söylemeli. Adda beklenen değer veya iç ayrıntı olmasın.
3. **Beklenen değeri spec'ten hesapla:** girdiye kuralları adım adım uygula, hesabı test yanına kısa yorum olarak yaz.
   Sınırdan uzak girdi seç; eşiğin kendisini ayrı bir testte, yalnız spec eşikte ne olacağını söylüyorsa test et.
4. **Davranışı test et, yazımı değil:** literal, değişken adı, yardımcı metot ya da sözdizimi zorlama. Kaynak metni okuyan
   statik testleri yalnız çalıştırılamayan dosyalar (PowerShell, config) için kullan; orada da eşdeğer yazımı kabul et.
5. **Her koşuda bir şey doğrula:** `if` içinde assert yok; ondalıkları toleransla karşılaştır; fixture'ı kendi kur,
   üst dizinleri oluştur, ürün kodunun gerçekten okuduğu yere yaz.
6. **Import ve koşturma** spec'in "Gizli test biçimi" bölümündeki komutla aynı olsun (`{hidden}`, `{wt}` yer tutucuları).
   Kaydetmeden önce testlerin sözdizimini kontrol et (ör. `python3 -m py_compile`, `node --check`); taban kodda
   koşturmak isteğe bağlı: özellik henüz yoksa düşmeleri beklenir.
7. Eski dersler: `templates/tester-lessons.md` (model testçilerin gerçek hataları) — aynılarını yapma.

## Ne zaman model testçi (yüksek güvence)
`hx pair` / `hx call tester` hâlâ var. Kimlik doğrulama, para/hesaplama çekirdeği, veri silme/migration gibi işlerde
PM testlerine ek olarak bağımsız bir model takımı istenebilir; o zaman düşen gizli testler `hx triage` ile sınıflanır.
