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
