# HX-51 · Hakem tutarlılığı — ön kayıt (2026-11-25, ölçümden önce yazıldı)

Ölçüm, hipotez değil. Kaynak: hillclimbing (değerlendiriciyi aynı çıktıda çift koştur) ve safety evals (insan/yapı etiketine
karşı kappa, "fail loudly") yazıları; bkz. planning PRJ-003 HX-51.

## Düzen
- Vakalar: `lab/judge_lab.py build`, tester lab 7 görev × 2 tekrar, iki testçi: Qwen3.7 Plus#high (`hx51qw`), Kimi K2.7 Code (`hx51km`,
  daha sık yanlış test yazar → TEST vakaları). Etiket yapıdan: referansta düşen test = TEST; referansta geçip mutantta düşen = KOD.
- Hakem: `opencode-go/glm-5.3-flash#low` (config judge), `templates/judge.md` @ main 9af93e8, vaka başına 3 rep, kör kopyalar.
- Veri: `~/Desktop/Projects/quadrant-harness-results/hx51/`.

## Karar kuralları (sabit)
1. `flip_rate` > 0.10 → hakem kararsız; BELIRSIZ yolunu/çift koşu oylamasını ele alan yeni kart açılır.
2. `kod_judged_test` > 0.05 → tehlikeli (gerçek kod hatası worker'a gitmez); judge şablonu/effort için yeni kart.
3. `test_judged_kod` > 0.20 → yanlış testler worker'a kural ihlali diye gidiyor; yeni kart.
4. Hiçbiri aşılmazsa: hakem "bilerek alınmayanlar"daki kabulle uyumlu (büyük ölçüde doğru), değişiklik yok.
- Infra rep'ler ayrı sayılır; geçerli rep oranı < %90 ise sonuç "belirsiz" ve ölçüm tekrarlanır.
- Sınırlama: sentetik Python görevleri; gerçek işlerdeki Node/.NET dağılımını temsil etmeyebilir.

## Ek (2026-11-25, hakem koşmadan önce)
- Yapı yalnız 2 TEST vakası verdi (98 KOD); iki testçi de bu kez neredeyse hep doğru test yazdı. TEST tarafı için ek kaynak:
  `hx51bad` = `hx51qw` takımlarının kopyası; DeepSeek V4.1 Flash her takımda tek bir assertion'ı spec'e aykırı hâle getirdi
  ("dikkatsiz testçi" simülasyonu). Bu takımlardan yalnız TEST vakaları alınır (mutant/KOD vakaları atılır).
- Maliyet/süre için KOD vakaları örneklenir: her görev için `hx51qw` ve `hx51km`'den case_id sırasına göre ilk 3'er KOD vakası
  (en çok 42). Diğer KOD vaka dizinleri `out/unused/` altına taşınır, silinmez.
- Karar kuralları değişmedi. Sınırlama: enjekte TEST vakaları gerçek testçi hatalarından daha "temiz" olabilir.

## Sonuç (2026-11-25)
56 vaka (42 KOD, 14 TEST: 2 yapısal + 12 enjekte), 3 rep, GLM-5.3-Flash#low, infra 0.

| Metrik | Eşik | Sonuç |
|---|---|---|
| flip_rate | ≤ 0.10 | 0.036 (2/56 vaka) |
| kod_judged_test | ≤ 0.05 | 0.016 (2/126 rep) |
| test_judged_kod | ≤ 0.20 | 0.000 |
| rep doğruluğu KOD / TEST | — | 0.984 / 1.000 |
| çoğunluk doğruluğu, kappa | — | 1.000, 1.000 |
| BELIRSIZ oranı | — | 0.000 |

Karar: kural 4 — hiçbir eşik aşılmadı; hakem şablonu/modeli değişmez. Çoğunluk oyu tek rep hatalarını düzeltiyor ama tek rep
zaten %98+ doğru; çift koşu oylaması maliyetine değmez (bilerek alınmayan "3'lü hakem oylaması" kararı bu veriyle destekleniyor).
Sınırlama: sentetik Python görevleri ve temiz enjekte TEST vakaları; gerçek işlerdeki G sınıfı (.NET regex) testleri temsil edilmedi.
Veri: `~/Desktop/Projects/quadrant-harness-results/hx51/out/score.json`.
