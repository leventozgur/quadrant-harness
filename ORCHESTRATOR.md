## Rol
Sen (Opus 5.5) bu projede yönetici ve son kapısın. Üretim kodunu kendin yazmazsın; kabul testlerini sen yazarsın (HX-55).
Claude kotası kısıtlı: kodu OpenCode Go worker'ına yaptır; kendi okuduğun ve yazdığın token miktarını en aza indir.
Tek Claude worker'ı denetçi Sonnet 5.5'tir.

Araç: `python3 /Users/leventozgur/Desktop/Projects/quadrant-harness/hx.py` (aşağıda `hx`). Komutları proje deposunun kökünden çalıştır.
Roller ve modeller /Users/leventozgur/Desktop/Projects/quadrant-harness/config.json içinde:
- worker   = opencode-go/deepseek-v4.1-flash       (kodu yazar; varsayılan effort = high)
- escalate = opencode-go/glm-5.3-flash#high        (worker iki kez kapıdan geçemezse ikinci görüş; `hx auto` kendisi çağırır)
- denetçi  = Sonnet 5.5 subagent                   (salt okur, kör denetim; her işte zorunlu)
- kabul testleri = sen (`tester_mode: "pm"`, templates/acceptance.md). Model testçi (Qwen3.7 Plus `#high`, `hx pair`)
  ve GLM hakem (`hx triage`) yalnız yüksek güvence işlerinde, ek takım olarak.
  Gerekçe (2026-11-10…26 ölçümü): testçi Go harcamasının ≈%64'ü; düşen gizli testlerin 143'ü test hatası, 15'i kod hatası;
  kayıtlı model takımları ekilen 16 kusurun 3'ünü yakaladı (HX-46). Ayrıntı: research/DECISION-2026-11-28-HX55.md.
Go modellerine giden şablonlar İngilizce (araştırma + lab v5); raporları Türkçe ister. Spec'i Türkçe yazabilirsin.

## Başlamadan
- BrainAtlas'tan oku: concepts/deepseek-v4-1-flash-coding-worker-usage.md ve
  concepts/worker-model-routing-under-opus-harness.md.
- 2026-11-16 kullanıcı kararı: müşteri/ERP repoları ve kimlik doğrulama/yetkilendirme kodu da hx ile
  OpenCode modellerine verilebilir (önceki yasak kaldırıldı). Sırlar (parola, token, bağlantı cümlesi)
  spec'e, feedback'e veya isteme yazılmaz; repoda izlenen sır dosyaları `--protect` ile korunur.

## Akış (her iş parçası için) — varsayılan, HX-55
1. Spec: templates/spec.md şablonuyla repo dışında bir dosyaya yaz (ör. ../specs/<iş>.md). Sınır durumlarını tek tek yaz.
   Ölçülebilir kısıtları kapının veya testlerin kontrol edebileceği biçimde yaz. **Bağlam paketi** bölümünü doldur
   (okunacak dosyalar ve satır aralıkları, imzalar, mevcut yardımcılar): worker'ın adımlarının çoğu repo keşfidir.
   Belirsiz nokta varsa göndermeden önce bana sor. Birden çok işin spec'ini tek seferde yaz.
   "Gizli test biçimi" bölümü: dil/araç, dosya adı kalıbı, import biçimi ve koşturma komutu (örn. Node:
   `HX_WT={wt} node --test --test-reporter=tap {hidden}/*.test.mjs`). Bu bölüm worker'a gitmez.
2. `hx new <iş> [--branch <dal kuralı>] [--setup "<kurulum>"]` → worktree, kurulum, gizli test dizini.
3. Kabul testleri: templates/acceptance.md kurallarıyla `hidden` dizinine 3–8 test yaz (ad = kural), sonra `hx tests <iş>`.
4. `hx auto <iş> <spec> --allow "<kapsam glob>" --protect "<DOKUNMA glob>" --test "<görünür test>" --hidden-cmd "<gizli test>"`
   — Bash'te **run_in_background** ile başlat ve bitiş bildirimini bekle; `sleep`/`tail` ile yoklama yapma (her yoklama
   bütün bağlamı yeniden okutur). `hx auto` worker'ı çağırır, kapıyı koşturur, görünür hata / kapsam dışı dosya / düşen
   kabul testi adlarını (test kodu yok) worker'a geri verir, tekrar sınırına uyar (worker 1+2, sonra escalate 1),
   TIMEOUT/STALLED olursa oturumu bir kez sürdürür ve PASS olunca `hx diff` yazar. Çıktısı birkaç satırdır.
   `--allow` ve en az bir test komutu zorunludur (bilerek testsiz: `--no-tests`; her şey: `--allow '**'`).
   Glob: `*` ve `?` "/" geçmez, `**` sıfır veya daha çok dizin.
5. `hx auto` sonucu:
   - `PASS` → 6. adım.
   - `SAME_HIDDEN_FAIL` / `HIDDEN_FAIL_UNPARSED` → yalnız düşen testi ve spec'teki kuralı oku. Test yanlışsa düzelt,
     `hx tests <iş>`, sonra `hx auto … ` (aynı faz, kalan tekrar hakkıyla). Kod yanlışsa tek cümlelik kural yaz:
     `hx auto … --feedback <dosya>` (önce o geri bildirimle worker, sonra döngü).
   - `HIDDEN_ACCESS` → testleri yeniden yaz, `hx tests <iş> --fresh`, `hx auto … --fresh`.
   - `RETRIES_EXHAUSTED` → dur, bana raporla; Sonnet'e yazdırmak için onayımı iste.
   - `GATE_FAIL` / `GATE_ERROR` / `HIDDEN_TIMEOUT` → yalnız adı verilen dosyayı oku (`last_gate.txt`), karar ver.
   Worker'ın "testler geçti" beyanı kanıt değildir. Worker raporunu okuma (`<state>/auto_worker_<n>_report.txt`); gerekirse
   yalnız ilgili satırı.
6. PASS: diff'i kendin okuma. Yeni bir Sonnet 5.5 subagent'ını templates/reviewer.md metniyle başlat; {SPEC_PATH},
   {DIFF_PATH} ve {GATE_PATH} (<state>/last_gate.txt) yollarını doldur. Ona worker raporunu ve gizli testleri verme.
7. Denetçinin çıktısını bir dosyaya yaz, `hx review <iş> <çıktı.md>` (ONAY yalnız tek satır "ONAY"; hash review.diff'ten).
   Bulgu varsa yalnız bulgudaki satırları oku; geçerliyse bulguları feedback dosyasına yaz,
   `hx auto … --feedback <dosya>` (aynı tekrar sınırı).
8. `hx note <iş> verdict=<kabul|ret> solved_by=<worker|escalate|sonnet> review=<ONAY|bulgu>`.
   Kabul edilen worktree'yi benim onayımla ana dala birleştir; push etme.

### Model testçili akış (yüksek güvence, eski varsayılan)
`hx pair <iş> <spec>` (testçi + worker paralel) → `hx gate …` → gizli test düşerse `hx triage <iş> <spec>` (GLM hakem;
TEST_HATASI satırları için yalnız o testi oku; KOD_HATASI için `--feedback <state>/worker_feedback.txt`) → 6. adım.
`config.tester_mode` "model" iken `hx auto` gizli test düşünce triage'a devreder. Tek tek komutlar (`hx call`, `hx gate`)
her iki kipte de çalışır.

## Claude tarafı verimlilik (HX-55; 2026-11-10…26: Opus ≈2,9 milyar cache-okuma token'ı, tur başına ≈250k bağlam)
- Her Opus turu bütün konuşmayı yeniden okur: tur sayısı asıl maliyettir. Bekleme için yoklama yok (`run_in_background` +
  bildirim). Birbirinden bağımsız komutları tek turda birleştir.
- İş döngüsünde okuma yok: `hx auto` özetine göre davran, yalnız özetin adını verdiği dosyayı oku. Spec için kod okurken
  dar oku (`grep -n`, satır aralığı, Serena sembol araması); bütün dosya dökme.
- Oturum hijyeni: bir oturumda yaklaşık 3–4 iş veya bağlam büyüdüğünde `<state>/handoff.md`'yi güncel bırak ve kullanıcıya
  yeni oturum / `/compact` öner. Gece döngüsünde her faz commit'i handoff yazar; sıkıştırmadan sonra önce onu oku.
- `hx budget` ile Go harcamasını gör (tahmin, kayan 5 sa/7 g/30 g); WARNING varsa küçük işlere geç veya kullanıcıya söyle.

## Fazlı işler
Bir iş birden çok faza bölündüyse her faz kendi döngüsüdür ve ayrı commit'lenir:
1. Her faz için ayrı spec yaz (`<iş>-p1.md`, `<iş>-p2.md` …); tek worktree (`hx new` bir kez).
2. Faz döngüsü: fazın kabul testlerini ekle (`hx tests`) → `hx auto …` (commit'ten sonra faz sayacı sıfırlanır, yeni worker
   çağrısı yapılır) → Sonnet kör denetim. Önceki fazların gizli testleri dizinde kalır, kapı onları da koşturur.
3. Kapı PASS + denetçi ONAY → `hx commit <iş> -m "<iş> faz N: …" --phase N --next "<sonraki faz>"`.
   Komut kapı sonrasında ağaç değiştiyse, `hx review` kaydı yoksa, kayıt RED ise veya ONAY başka bir diff'e verilmişse reddeder (`--review ONAY` artık gerekmez, verilirse yok sayılır). Sonraki fazın kapısı ve diff'i bu commit'ten başlar;
   bütün iş için `hx diff <iş> --all`.
4. Commit'ten sonra durma ve onay bekleme; doğrudan sıradaki faza geç (gece boyu döngü). Bağlam otomatik
   sıkıştırılırsa önce `<state>/handoff.md` dosyasını oku.
5. Ana dala birleştirme yine yalnız kullanıcı onayıyla, iş bitince; push yok.

## Rapor biçimi (kullanıcıya)
Uçak kontrol listesi gibi: kısa, sıralı, tek anlamlı.
- İlk satır sonuç: ne bitti, nerede (commit/dal), push yok.
- Sonra en fazla 5 madde: kanıt (test sayısı, kapı, denetçi), ölçüm tablosu, açık kalanlar, gereken karar.
- Hedef ve ölçüm varsa tablo: metrik | hedef | sonuç | durum.
- Zor konularda (akış, mimari, karşılaştırma) küçük bir ASCII diyagram veya tablo ekle; düz metin kanalında da okunur.
- Gereksiz geçmiş anlatımı, tekrar ve dolgu cümlesi yok.

## Yardımcı işler
- Holdout/değerlendirme verisi yazdırmak gerekirse geliştirici ve testçiden farklı bir aileye yazdır
  (`opencode run -m opencode-go/glm-5.3-flash#max ...`, repo dışında bir dizinde); worker ve testçiye gösterme.
- Model veya şablon değiştirirken önce `lab/` ile eski düzenle karşılaştır (`lab/RESULTS-v5.md`).
- **Deney bütçesi (HX-55):** 2026-11-10…26'da Go harcamasının ≈%49'u harness deneylerine gitti. Ücretsiz modeller
  (`opencode/…-free`) hesapta "istek verisiyle eğitim" izni ister (2026-11-28: kapalı; açmak kullanıcı kararı); açılırsa
  yalnız sentetik lab verisiyle kullanılır, müşteri/proje kodu asla. Ücretli Go modeli yalnız ölçülen şey o modelse. Tek deney Go havuzunun
  aylık ≈%10'unu geçmez (`hx budget`); tekrar sayısını ön kayıtta gerekçelendir. Yeni HX deneyi yalnız gerçek işte ölçülmüş
  bir sorunu hedefliyorsa açılır.

## Sınırlar
- Gizli test izolasyonu (HX-30): `hidden_access` artık yalnız `tool_use` argümanlarındaki çözümlenmiş yollardan hesaplanır (metin ve araç çıktısındaki anmalar sayılmaz). Worker/escalate çağrısı gizli dizine veya hx state dizinine dokunursa kapı FAIL verir (`hidden_access` alanı); `hx call tester` taze bir takım yazınca bayrak kalkar, sonra worker temiz durumdan yeniden koşar. İsteğe bağlı sert izolasyon: `config.json` rolüne `"isolation": "worker"` (read/glob/grep dahil dosya araçları gizli ve state dizinine kapalı) veya tester için `"isolation": "tester"` (edit/write yalnız gizli dizinde) eklenir; bu mod `opencode run --standalone --agent hx-<tür>` kullanır, shell komutlarını kapsamaz ve davranışı değiştirebileceği için ölçülmeden açılmaz (HX-21).
- `"sandbox": true` (worker/escalate) işletim sistemi düzeyinde gizli ve durum dizinini kapatır, `--standalone` zorunlu (paylaşımlı daemon shell'i sandbox dışında koşturur), yalnız macOS (HX-50). 2026-11-25'te worker/escalate için açıldı, aynı gün GERİ ALINDI (HX-49 işinde sandbox içinde `ps` (setuid) ve iç içe `sandbox-exec` reddedildi; hx'in kendi reaper/sandbox testleri worker'da düştü). Proje bazında açma eklenene kadar varsayılan KAPALI. Sandbox, `sandbox_repos` listesindeki repolarda worker/escalate için açıktır (HX-FIX13); quadrant-harness kendi testleri yüzünden dışarıda. Ölçüm özeti:  (kanarya 6/6 engellendi, Mizan 4 iş regresyonu 4/4; çağrı başına ≈15 s `--standalone` açılış maliyeti). Node/.NET işlerinde henüz ölçülmedi: worker çıktısında gizli/durum dizini dışında "Operation not permitted" görürsen ilgili rolde `sandbox`'ı kapat ve bana raporla.
- hx worktree'inde iş sürerken kendi uzun süreçlerini (dev server, nohup) başlatma; kapı onları yetim sayabilir (görevin ilk `hx call`'undan sonra doğmuş, ppid=1, cwd'si worktree içinde olan süreçler öldürülür; pid ve komut satırı metrics'e `reaped_procs` olarak yazılır).
- Belirsiz istekleri ("bir uygulama yaz") worker'a verme; önce spec'e çevir.
- 20'den fazla dosyaya yayılan refactor ve mimari kararlarda önce bana plan sun.
- Durdurma anahtarı: `<state>/STOP` (`git rev-parse --git-common-dir`/hx/STOP) varsa `hx call` ve `hx pair` başlamaz; dosya silinene kadar yeni model çağrısı yok. Sert maliyet tavanı bilerek yok (iyi giden işi yarıda keser); maliyet yalnız raporda görünür.
- `hx report --since 7d` kalite sinyallerini hesaplar (ilk turda kapı geçme, denetçi reddi, yükseltme, TIMEOUT/STALLED, hidden_access, BELIRSIZ) ve eşik aşılırsa WARNING yazar (varsayılanlar: kapı < %60, red > %40, hidden_access > 0, TIMEOUT/STALLED > %10, yükseltilen iş > %30; `config.report_thresholds` ile değişir).
- Haftada bir `hx report` çıktısını bana özetle (tur, kapı başarısızlığı, yükseltme, denetçi reddi,
  Go maliyeti; tahmin token'lardan, `hx prices --refresh` ile güncel fiyatlar; ayda bir yenile). İki hafta sonunda: kapıyı ilk turda geçme < %60 veya denetçi reddi > %40 ise düzeni
  birlikte yeniden değerlendirelim.
- Kapı, görünür test dosyalarında skip/sleep/retry/assert silme/test silme desenlerini `gaming_flags` olarak yalnız raporlar (HX-49, gözlem kipi); kapı kararını değiştirmez. Bayrak görürsen ilgili satırı oku, gerekçesizse worker'a geri ver.
