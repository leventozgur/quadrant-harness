# HX-47 · Worker "minimal diff" kuralı — ön kayıt (2026-11-25, ölçümden önce yazıldı)

Kaynak: Ponytail prompt çerçevesinin "karar merdiveni" fikri (önce mevcut kod, sonra standart kütüphane, sonra mevcut
bağımlılık). Ponytail kurulmuyor (başlangıç hook'ları, ek bağımlılık). "Bu özellik gerekli mi?" basamağı worker'a
verilmez; kapsamı Opus spec'te belirler. Caveman bilerek alınmadı: maliyet girdide (Sonnet denetçi ≈67–69k/spawn), spec netliği
ucuz modeller için kritik.

## Hipotez
Worker şablonuna eklenen tek bir kural ve bir kontrol maddesi, doğruluğu düşürmeden worker'ın ürettiği kod miktarını azaltır.
Daha küçük diff, denetçi girdisini ve kapsam dışı değişiklik riskini düşürür.

## Kollar
- A = `templates/worker.md` (main @ 9af93e8).
- B = `templates/worker-hx47.md`: A + kural 4 ("smallest change…") + kontrol listesine bir madde. Fark yalnız bu.
- Model: `opencode-go/deepseek-v4.1-flash`, varsayılan effort. Lab: `lab/run_oc.py`, base 19 + hard 7, `hard_reps=1`.
- Her kol 2 tekrar (etiketler `hx47A1`, `hx47A2`, `hx47B1`, `hx47B2`), 4 iş eşzamanlı (lab v5 düzeni).

## Metrikler
- **Birincil:** üretilen kod satırı (`lab/loc.py`): kod görevlerinde (t01, t02, t08, t10, t12 hariç her koşu) worker'ın
  fixture'a eklediği/değiştirdiği boş olmayan satırlar + son cevaptaki kod bloklarının boş olmayan satırları. İki tekrarın toplamı.
  Betik doğrulaması: dokunulmamış fixture'lar 0; referans çözümler 2–35 satır.
- **Doğruluk:** `lab/score_all.py` (base puanı + hard ok), iki tekrarın toplamı.

## Eşikler (sonradan değiştirilmez)
- **KEEP**, üçü birden:
  1. B toplam üretilen satır ≤ A toplamının %80'i.
  2. B toplam doğruluk ≥ A toplam doğruluk (kalite önce; hiç kayıp yok).
  3. A'nın iki tekrarda da geçtiği hiçbir görevde B iki tekrarda da düşmez.
- Aksi hâlde **KILL**: dal silinir, sonuç bu dosyaya yazılır.
- Altyapı hatası (TIMEOUT, limit, NOT RUN) olan koşu yalnız kendisi yeniden koşulur; kötü sonuç yeniden koşulmaz.

## KEEP olursa
- `worker.md` ← B içeriği; `worker-hx47.md` silinir.
- `reviewer.md` 2. maddesine "spec'in istemediği yeni bağımlılık, soyutlama veya dosya" eklenir. Bu lab'da ölçülemez;
  benimsendikten sonra `hx report` denetçi reddi oranıyla izlenir (eşik > %40 → geri alınır).
- Yerel `main`'e birleştirme, push yok.

## Sonuç — KEEP (2026-11-25)

| Metrik | A (2 tekrar) | B (2 tekrar) | Eşik | Durum |
|---|---|---|---|---|
| Üretilen kod satırı (toplam) | 2082 | 1540 (×0,740) | ≤ ×0,80 | geçti |
| Doğruluk (base + hard) | 34/36 + 14/14 = 48 | 34/36 + 14/14 = 48 | B ≥ A | geçti |
| A'nın 2/2 geçip B'nin 2/2 düştüğü görev | — | yok | yok | geçti |

- Düşenler: A1 t02 ("ve" yasağı), A2 t11_low2 (SyntaxError), B1 t02, B2 t09. Lab v5'teki gürültü düzeyi (görev başına bir kayıp).
- Hard katmanında satır ×0,82 (824 → 676); h03, h04, h06, h07'nin hepsinde B daha kısa. Tüm hard görevleri iki kolda 7/7 geçti.
- **Dikkat (eşik kararını değiştirmez):**
  - Farkın büyük kısmı belirsiz t05'ten ("basit bir not uygulaması yaz") geliyor: B2 98 satır, diğer üç koşu ≈380–400. t05 hariç oran ×0,822, yani eşiğin hemen üstünde. Gerçek etki büyük ihtimalle %15–20.
  - B2 t09'u düşürdü: var olmayan fonksiyonu doğru reddetti, ama mevcut bağımlılıktaki `HTTPAdapter` + `Retry` yerine kendi sarmalayıcısını yazdı. Bu, kuralın amacının tersi; n=1, izlenmeli.
- Ölçüm sapması (kayıt için): `loc.py`'nin ilk sürümü cevaptaki satır içi ` ```python ` ifadesini blok başı sayıyordu (B1 t03 = 0 satır). Regex yalnız satır başındaki çitleri sayacak şekilde düzeltildi. Her iki kol aynı betikle yeniden ölçüldü; karar değişmedi (önce ×0,738, sonra ×0,740).
- Altyapı: h06 bir rate-limiter görevi. Çıktıdaki "rate limit" metni `run_oc.py`'nin limit sezgisini tetikledi ve gereksiz yeniden denemeler yapıldı (HX-23 ile aynı yanlış pozitif sınıfı). Her kolda son deneme kaydedildi.
- Maliyet: kol başına ≈$0,08 (`hx.est_cost`), toplam ≈$0,32. Veri: `lab/hx47*.log`, `lab/results_hx47*.json`, `lab/loc_hx47.json`.
- Uygulanan: `worker.md` ← B; `reviewer.md` 2. madde genişletildi. Denetçi değişikliği lab'da ölçülmedi. Sonraki 2 haftada `hx report` denetçi reddi oranı > %40 olursa geri alınır.
