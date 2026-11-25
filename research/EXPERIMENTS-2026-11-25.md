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

## Sonuç
(ölçümden sonra eklenecek)
