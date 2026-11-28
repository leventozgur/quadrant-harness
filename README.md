# quadrant-harness

Opus 5.5 yönetici (spec + kabul testleri) + OpenCode Go worker + Sonnet 5.5 kör denetçi düzeni. Model testçi/hakem
(Qwen/GLM) yüksek güvence işleri için isteğe bağlı (HX-55, `research/DECISION-2026-11-28-HX55.md`).

- `ORCHESTRATOR.md` — Opus'a verilecek talimat (yollar bu klasöre göre).
- `hx.py` — stdlib CLI: `new`, `tests`, `auto` (varsayılan faz döngüsü), `budget`, `pair`, `call [--resume]`, `gate`, `triage`, `diff [--all]`, `commit` (onaylı faz commit + `handoff.md`), `note`, `report`, `prices [--refresh]`. Durum: hedef reponun `.git/hx/`.
- `config.json` — roller/modeller/fiyatlar; `templates/` — spec, worker, tester, judge, reviewer.
- `lab/` — model seçimi laboratuvarı (worker ve tester rolü; RESULTS-v3/v4). Model veya şablon değişince regresyon kontrolü.
  Not: `lab/run_ds.py`, `extract_haiku.py` eski oturum yollarına bağlı tarihsel betiklerdir.

## Maliyet tahmini (2026-11-16 düzeltmesi)
OpenCode, Go çağrılarında `cost: 0` raporlar; tahmin `hx.est_cost` ile token'lardan hesaplanır. Fiyatlar `config.json` → `prices` (kaynak: models.dev `opencode-go`, `hx prices --refresh` ile yenilenir): giriş, çıkış, önbellek okuma/yazma ayrı; Qwen'in 256k üstü bağlam kademesi adım başına uygulanır. 2026-11-16 öncesi kayıtlar önbellek okumayı tam giriş fiyatından ve DeepSeek'i iki kat fiyattan sayıyordu (yaklaşık 10–25 kat fazla); `hx report` eski kayıtları token'lardan yeniden hesaplar. Gerçek değerler: BA-28 ≈ $0.19 (eski tahmin $2.03), BA-37 ≈ $0.23 (eski $3.45). Pahalı kalem testçi (Qwen) çağrısıydı; 2026-11-16'dan beri testçi Haiku 5.5 (~$0.01/iş). DeepSeek Go'da yoğun saatte (TR hafta içi 04–07, 09–13) 2× fiyatlıdır; tahmin taban fiyatı kullanır, yoğun saatte gerçek değer en çok 2 katıdır.
