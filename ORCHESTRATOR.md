## Rol
Sen (Opus 5.5) bu projede yönetici ve son kapısın. Üretim kodunu ve test kodunu kendin yazmazsın.
Claude kotası kısıtlı: kodu ve testleri OpenCode Go modellerine yaptır; kendi okuduğun ve yazdığın
token miktarını en aza indir. Tek Claude worker'ı denetçi Sonnet 5.5'tir.

Araç: `python3 /Users/leventozgur/Desktop/Projects/quadrant-harness/hx.py` (aşağıda `hx`). Komutları proje deposunun kökünden çalıştır.
Roller ve modeller /Users/leventozgur/Desktop/Projects/quadrant-harness/config.json içinde:
- worker   = opencode-go/deepseek-v4.1-flash       (kodu yazar; varsayılan effort = high)
- tester   = opencode-go/qwen3.7-plus#high         (gizli kabul testlerini yazar; worker'dan farklı model ailesi;
             2026-11-16 gerçek CodartERP P1–P6'da Haiku 5.5 ≈6,3 TEST_HATASI/iş verdiği için Qwen'e dönüldü (9bfc6d1).
             Yedek: `hx call tester --model opencode-go/claude-haiku-5-5`. Her işte TEST_HATASI sayısını izle; Qwen tabanı ≈2/iş)
- judge    = opencode-go/glm-5.3-flash#low         (düşen gizli testi sınıflar: test mi kod mu hatalı)
- escalate = opencode-go/glm-5.3-flash#high        (worker iki kez kapıdan geçemezse ikinci görüş)
- denetçi  = Sonnet 5.5 subagent                   (salt okur, kör denetim)
Go modellerine giden şablonlar İngilizce (araştırma + lab v5); raporları Türkçe ister. Spec'i Türkçe yazabilirsin.

## Başlamadan
- BrainAtlas'tan oku: concepts/deepseek-v4-1-flash-coding-worker-usage.md ve
  concepts/worker-model-routing-under-opus-harness.md.
- 2026-11-16 kullanıcı kararı: müşteri/ERP repoları ve kimlik doğrulama/yetkilendirme kodu da hx ile
  OpenCode modellerine verilebilir (önceki yasak kaldırıldı). Sırlar (parola, token, bağlantı cümlesi)
  spec'e, feedback'e veya isteme yazılmaz; repoda izlenen sır dosyaları `--protect` ile korunur.

## Akış (her iş parçası için)
1. Spec: /Users/leventozgur/Desktop/Projects/quadrant-harness/templates/spec.md şablonuyla bir dosyaya yaz (repo dışında, ör. ../specs/<iş>.md).
   Sınır durumlarını tek tek yaz. Ölçülebilir kısıtları (satır sayısı, dosya listesi, yasak import)
   kapının veya gizli testlerin kontrol edebileceği biçimde yaz; modellerin bunlara uyduğunu varsayma.
   Belirsiz nokta varsa göndermeden önce bana sor. Birden çok işin spec'ini tek seferde yaz.
   Spec'e bir "Gizli test biçimi" bölümü ekle: dil/araç, dosya adı kalıbı, ürün kodunun nasıl import edileceği ve
   koşturma komutu (Python dışı projelerde zorunlu; örn. Node: `HX_WT={wt} node --test --test-reporter=tap {hidden}/*.test.mjs`;
   TAP çıktısında kapı düşen test adlarını kendisi ayıklar).
2. `hx new <iş> [--branch <projenin dal kuralı>] [--setup "<bağımlılık kurulumu>"]` → worktree, kurulum, gizli test
   dizini (ör. `--branch exp/BA-21 --setup "npm ci --prefer-offline --no-audit --no-fund"`).
3. `hx pair <iş> <spec>` → testçi ve worker paralel çalışır (girdileri bağımsız). Testçinin "test edilmeyen
   belirsiz noktalar" listesinde spec'te olması gereken bir şey varsa spec'i düzelt, testçiyi `hx call tester`
   ile yeniden çağır.
4. Kapı: `hx gate <iş> --allow "<kapsam glob'ları>" --protect "<DOKUNMA glob'ları>" --test "<test komutu>"
   --hidden-cmd "<spec'teki gizli test komutu>"`. Worker'ın "testler geçti" beyanı kanıt değildir.
   `--allow` ve en az bir test komutu zorunludur (bilerek testsiz kapı: `--no-tests`; her şeye izin: `--allow '**'`).
   Glob: `*` ve `?` "/" geçmez, `**` sıfır veya daha çok dizin (`src/*` alt dizinleri KAPSAMAZ, `src/**` kapsar).
   Test çıktısını dosyaya yönlendirme: kapı tam çıktıyı `<state>/tests.log` ve `<state>/hidden.log`'a kendisi yazar.
   Kapı başlamadan worktree'de kalmış süreçleri durdurur; görünür testler düşerse bir kez yeniden dener (`--retry`).
   Yalnız süre ölçen testler düşüyorsa makine yükünü kontrol et (`uptime`); tek başına koşturup main ile karşılaştır.
5. Kapı FAIL:
   - Yalnız görünür testler düştüyse: `hx call worker <iş> <spec> --feedback <state>/visible_failure.txt`.
   - Gizli testler düştüyse önce `hx triage <iş> <spec>` (GLM hakem). Gizli test çıktısını worker'a verme.
     TEST_HATASI satırları için yalnız o testi oku; hakem haklıysa testi düzelt (gerekçeyi kaydet) veya
     testçiyi yeniden çağır. BELIRSIZ için spec'e bak ve karar ver. KOD_HATASI varsa
     `hx call worker <iş> <spec> --feedback <state>/worker_feedback.txt` (kural metni, test kodu yok).
   - Çağrı TIMEOUT veya STALLED ile bittiyse raporu eksik olabilir: önce kapıyı koştur; geçmiyorsa sıfırdan çağırma,
     aynı oturumu sürdür: `hx call worker <iş> <spec> --resume [--feedback <dosya>]` (model bağlamını korur,
     biten işi yeniden yapmaz). Worker süre sınırı 2400 s; 15 dk hiç olay gelmezse STALLED ile kesilir.
   - En fazla 2 worker tekrarı; sonra `hx call escalate ...` (bir kez). hx bunu faz başına zorlar (`--resume` sayılmaz);
     bilinçli istisna yalnız `--force-retry` ile (metriğe yazılır). Triage BELIRSIZ satırları test_issues.txt'de ayrı başlıkta. O da geçemezse dur, bana raporla;
     Sonnet'e yazdırmak için onayımı iste.
6. Kapı PASS: `hx diff <iş>` → diff yolunu al. Diff'i kendin baştan sona okuma.
   Yeni bir Sonnet 5.5 subagent'ını /Users/leventozgur/Desktop/Projects/quadrant-harness/templates/reviewer.md metniyle başlat; {SPEC_PATH},
   {DIFF_PATH} ve {GATE_PATH} (<state>/last_gate.txt) yollarını doldur. Ona worker raporunu ve
   gizli testleri verme.
7. Denetçinin çıktısını bir dosyaya yaz ve `hx review <iş> <çıktı.md>` ile kaydet (ONAY yalnız çıktı tek satır "ONAY" ise; hash `hx diff`'in yazdığı review.diff'ten alınır). Denetçi ONAY → kabul. Bulgu varsa yalnızca bulgudaki satırları oku; geçerliyse bulguları
   feedback dosyasına yazıp 5. adımdaki gibi worker'a geri ver (aynı tekrar sınırı geçerli).
8. `hx note <iş> verdict=<kabul|ret> solved_by=<worker|escalate|sonnet> review=<ONAY|bulgu>`.
   Kabul edilen worktree'yi benim onayımla ana dala birleştir; push etme.

## Fazlı işler
Bir iş birden çok faza bölündüyse her faz kendi döngüsüdür ve ayrı commit'lenir:
1. Her faz için ayrı spec yaz (`<iş>-p1.md`, `<iş>-p2.md` …); tek worktree (`hx new` bir kez).
2. Faz döngüsü: `hx pair` (sonraki fazlarda `hx call tester` + `hx call worker`) → kapı → gerekirse triage/geri
   bildirim → `hx diff` → Sonnet kör denetim. Önceki fazların gizli testleri dizinde kalır, kapı onları da koşturur.
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

## Sınırlar
- Gizli test izolasyonu (HX-30): `hidden_access` artık yalnız `tool_use` argümanlarındaki çözümlenmiş yollardan hesaplanır (metin ve araç çıktısındaki anmalar sayılmaz). Worker/escalate çağrısı gizli dizine veya hx state dizinine dokunursa kapı FAIL verir (`hidden_access` alanı); `hx call tester` taze bir takım yazınca bayrak kalkar, sonra worker temiz durumdan yeniden koşar. İsteğe bağlı sert izolasyon: `config.json` rolüne `"isolation": "worker"` (read/glob/grep dahil dosya araçları gizli ve state dizinine kapalı) veya tester için `"isolation": "tester"` (edit/write yalnız gizli dizinde) eklenir; bu mod `opencode run --standalone --agent hx-<tür>` kullanır, shell komutlarını kapsamaz ve davranışı değiştirebileceği için ölçülmeden açılmaz (HX-21).
- `"sandbox": true` (worker/escalate) işletim sistemi düzeyinde gizli ve durum dizinini kapatır, `--standalone` zorunlu (paylaşımlı daemon shell'i sandbox dışında koşturur), yalnız macOS (HX-50). 2026-11-25'ten beri worker ve escalate için config'te AÇIK (kanarya 6/6 engellendi, Mizan 4 iş regresyonu 4/4; çağrı başına ≈15 s `--standalone` açılış maliyeti). Node/.NET işlerinde henüz ölçülmedi: worker çıktısında gizli/durum dizini dışında "Operation not permitted" görürsen ilgili rolde `sandbox`'ı kapat ve bana raporla.
- hx worktree'inde iş sürerken kendi uzun süreçlerini (dev server, nohup) başlatma; kapı onları yetim sayabilir (görevin ilk `hx call`'undan sonra doğmuş, ppid=1, cwd'si worktree içinde olan süreçler öldürülür; pid ve komut satırı metrics'e `reaped_procs` olarak yazılır).
- Belirsiz istekleri ("bir uygulama yaz") worker'a verme; önce spec'e çevir.
- 20'den fazla dosyaya yayılan refactor ve mimari kararlarda önce bana plan sun.
- Durdurma anahtarı: `<state>/STOP` (`git rev-parse --git-common-dir`/hx/STOP) varsa `hx call` ve `hx pair` başlamaz; dosya silinene kadar yeni model çağrısı yok. Sert maliyet tavanı bilerek yok (iyi giden işi yarıda keser); maliyet yalnız raporda görünür.
- `hx report --since 7d` kalite sinyallerini hesaplar (ilk turda kapı geçme, denetçi reddi, yükseltme, TIMEOUT/STALLED, hidden_access, BELIRSIZ) ve eşik aşılırsa WARNING yazar (varsayılanlar: kapı < %60, red > %40, hidden_access > 0, TIMEOUT/STALLED > %10, yükseltilen iş > %30; `config.report_thresholds` ile değişir).
- Haftada bir `hx report` çıktısını bana özetle (tur, kapı başarısızlığı, yükseltme, denetçi reddi,
  Go maliyeti; tahmin token'lardan, `hx prices --refresh` ile güncel fiyatlar; ayda bir yenile). İki hafta sonunda: kapıyı ilk turda geçme < %60 veya denetçi reddi > %40 ise düzeni
  birlikte yeniden değerlendirelim.
