# HX-49 · Kapıda test hilesi taraması (gözlem kipi) — ön kayıt (2026-11-25, taramadan önce)

Kaynak: Claude Code ekibinin doğrulama yazısı (flaky test atlama/sleep/retry yasağı) ve shipping yazısı (observe → enforce).

## Ölçüm
- Veri: BrainAtlas, Mizan, CodartERP_NetCore ve quadrant-harness'taki tek fazlı, kabul edilmiş hx işlerinin commit'leri
  (`commit^..commit`), `hx scan-gaming` ile taranır. Bu diff'ler denetçi ONAY'ı almış, yani hile olmadığı varsayılan "temiz" küme.
- Her bayrak PM tarafından diff bağlamıyla okunup "gerçek hile" / "yanlış bayrak" diye etiketlenir (gerekçe yazılır).

## Karar kuralı (tür başına)
- Bir tür, temiz kümede yanlış bayrak sayısı / taranan diff sayısı ≤ 0.05 ise ve en az bir gerçek kullanım örneği tanımlanabiliyorsa
  zorlamaya ADAY olur (zorlamaya geçiş ayrı karar; bu deney yalnız gözlem kipini merge eder).
- Yanlış bayrak oranı > 0.05 olan tür gözlemde kalır; desen daraltması ayrı kart.
- Gözlem kipi kapı kararını değiştirmediği için merge ölçütü: kapı sonuçları değişmez (testler) + denetçi ONAY.

## Sonuç (2026-11-25) — tarama `exp/HX-49` worker#2 sürümüyle (tarayıcı kuralları sonraki turlarda değişmedi, yalnız ayrıştırma sağlamlaştı)
117 kabul edilmiş tek fazlı diff (BrainAtlas, Mizan, CodartERP, quadrant-harness), 202 bayrak. Etiketleme desen düzeyinde yapıldı
(her tür için en sık satırlar ve tetikleyen işler okundu; 202 satırın her biri tek tek okunmadı). Kabul edilmiş işlerde gerçek hile bulunmadı.

| Tür | Bayrak | Bayraklı diff | Yanlış bayrak / taranan diff | Gerçek kullanım (temiz) | Karar |
|---|---|---|---|---|---|
| skip | 57 | 9 | 0.077 | ortama bağlı atlama (ssh-keygen, API anahtarı, symlink izni) | gözlemde kalır; daraltma kartı |
| sleep | 30 | 8 | 0.068 | zamanlama/backoff testleri | gözlemde kalır |
| retry | 78 | 10 | 0.085 | retry özelliğinin kendi testleri | gözlemde kalır |
| assert_removed | 32 | 3 | 0.026 | planlı ölü test temizliği (R3-DEADTESTS), refactor (R4-PERF, BA-75) | zorlamaya ADAY (spec izniyle istisna) |
| test_deleted | 5 | 2 | 0.017 | R3-DEADTESTS, R4-DOCS | zorlamaya ADAY (spec izniyle istisna) |

Not: silinen test dosyası hem test_deleted hem assert_removed üretiyor (R3-DEADTESTS iki türde de sayıldı); oranlar diff başına
olduğu için karar değişmiyor. Zorlamaya geçiş ayrı karar (kullanıcı); geçilirse spec'te `Test değişikliği serbest:` istisnası gerekir.
Skip/sleep/retry için olası daraltma: yalnız taban commit'te var olan bir testi değiştiren eklemeler veya koşulsuz skip.
