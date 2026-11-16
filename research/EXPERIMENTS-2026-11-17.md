# hx deneyleri — ön kayıt (2026-11-17, geliştirmeden önce yazıldı)

Kapsam: `HYPOTHESES-2026-11-17.md` (v2) içinden 4 hipotez, bu sırayla.
Her biri `exp/HX-NN` dalında geliştirilir. Kod `hx` ile yazılır: Opus spec yazar, DeepSeek worker yazar, Qwen gizli testleri yazar, GLM hakemlik yapar, Sonnet kör denetler.
Prompt şablonu metinleri Opus tarafından yazılır (kod değil).
- KEEP → dal `main`'e yerel olarak birleştirilir (push yok).
- KILL → worktree ve dal silinir, sonuç bu dosyaya ve `lab/RESULTS-HX.md`'ye yazılır.
- Eşikler sonradan değiştirilmez. Ölçüm başarısız olursa (altyapı) yeniden koşulur; sonuç kötüyse KILL.

## Sıra ve gerekçe
1. **HX-13 base ön uçuşu (Q2).** Küçük hx değişikliği, ölçümü deterministik ve ucuz. Testçi şablonuna dokunmaz.
2. **HX-21 minimal worker ajanı (Q10).** Worker tarafı, diğerlerinden bağımsız. Uzun Go ölçümü olduğu için erken başlar, diğerleriyle paralel koşar.
3. **HX-14 arayüz sözleşmesi + bağlam haritası (Q3).** Testçi şablonunu değiştirir.
4. **HX-12 çalıştırılabilir .NET gizli testleri (Q1).** Testçi şablonunu değiştirir; HX-14 kararından sonra güncel `main` üzerinde.
   P4 kapsam dışı: makinede `pwsh` yok.
Çakışma: HX-14 ve HX-12 aynı şablona dokunur, bu yüzden sıralı yapılırlar.

## Ortak tanımlar
- **Ref** = birleşmiş, denetlenmiş uygulama; ref'te düşen gizli test = yanlış test. **Base** = işin başladığı commit.
- BA tekrar işleri (Node, `node --test`):
  - BA-32: base 29acd76, ref d64fe0c
  - BA-32b: base 503bcba, ref 97b85a2
  - BA-36: base 503bcba, ref birleşmemişse `exp/BA-36` ucu
  - BA-43 faz 1: base 7e41e58, ref e137d75
  - BA-43 faz 2: base e137d75, ref 0dd3c2f
- Codart tekrar işleri (.NET): P2 ref 627bf8a, P5 ref 31af173, P6 ref c75ea3f; base = her birinin ilk ebeveyni.
- "Orijinal ilk tur takımı" = `tester-1.jsonl` içindeki son `write` içerikleriyle yeniden kurulan dosyalar. PM düzeltmeleri dahil değil.

## HX-13 · Base ön uçuşu: başarısızlık imzası karşılaştırması
- Değişiklik: `hx preflight <task> --hidden-cmd ...` gizli takımı geçici bir base worktree'sinde koşturur ve test başına başarısızlık imzasını kaydeder.
  İmza = hata türü + normalize mesaj; yollar, sayılar ve adresler atılır.
  Kapıda gizli test düşerse, imzası base'dekiyle aynı olan testler `hidden_failure.txt`'de `SUSPECT_TEST (fails identically without the change)` diye işaretlenir ve hakeme bu bilgiyle gider.
  **Hiçbir test atlanmaz veya silinmez.** Destek: unittest ve TAP (`node --test`).
- Duyarlılık: BA-32, BA-32b, BA-36, BA-43 (iki faz) orijinal ilk tur takımlarında, ref'te düşen testlerin SUSPECT işaretlenme oranı. Ref "mevcut kod" yerine kullanılır.
- Yanlış şüphe: tester lab'ın kayıtlı takımlarında (Qwen v3high, Haiku hk55), her mutantta düşen testlerin SUSPECT işaretlenme oranı. Mutant = gerçek kod hatası.
- **KEEP:** duyarlılık ≥ %50 **ve** yanlış şüphe ≤ %5. Ayrıca gizli testler geçtiğinde kapı çıktısı değişmez.

## HX-21 · Minimal worker ajanı
- Değişiklik: worker yalnız `bash`, `read`, `edit`, `write`, `grep`, `glob` araçlı özel bir opencode ajanıyla çalışır.
  `webfetch`, `task`/alt ajan ve todo araçları kapalı. Prompt şablonu aynı kalır. Ajan tanımı hx deposunda tutulur; kullanıcının global opencode ayarı değişmez.
- Ölçüm A/B (A = mevcut, B = minimal), DeepSeek V4.1 Flash varsayılan effort:
  1. Gerçek tekrar: BA-32b, BA-36, BA-43 faz 2 spec'leri base'den. Kapı = görünür takım + **son (düzeltilmiş) gizli takım**. Kol başına 3 tekrar. Birincil metrik: ilk tur kapı PASS sayısı (/9).
  2. Lab: `lab/hard.py` 7 görev × 2 tekrar.
- **KEEP:** gerçek tekrarda B PASS ≥ A PASS + 2, **veya** B PASS = A PASS ve lab skoru eşit iken B'nin ortalama adım ya da maliyeti ≥ %20 düşük.
  B herhangi bir kalite metriğinde (gerçek PASS, lab skoru) A'nın altındaysa KILL. Korumalar: gizli dizine erişim 0, timeout sayısı A'dan fazla değil.

## HX-14 · Arayüz sözleşmesi + deterministik bağlam haritası
- Değişiklik: `hx map` (LLM değil) bir spec yazılmadan önce ilgili dosyaların export/imza listesini, doğrudan bağımlılıkların gerçek import yollarını (package.json `exports`), anahtar kelimeyle eşleşen mevcut testleri ve bir fikstür örneğini çıkarır.
  Spec şablonuna "Arayüz sözleşmesi" bölümü eklenir. Testçi şablonuna iki kural eklenir: "sözleşmedeki import/imza/yol aynen kullanılır" ve "beklenen yollar SUT'a verilen aynı değişkenden türetilir".
- Ölçüm: BA-32, BA-36, BA-43 faz 2 spec'leri, Qwen3.7 Plus #high, kol başına 3 tekrar.
  A = orijinal spec + mevcut şablon; B = sözleşmeli spec (Opus, `hx map` çıktısından yazar) + yeni şablon.
  Metrik: koşu başına ref'te düşen test sayısı ve base'de düşen test sayısı (güç).
- Koruma: tester lab (7 görev, 28 mutant), B şablonu 1 tekrar; öldürme ≥ 24/28 (Qwen v3high tabanı 25) ve ref geçişi ≥ 6/7.
- **KEEP:** B'nin ref'te düşen test ortalaması ≤ A'nın %50'si **ve** B'nin base'de düşen test ortalaması ≥ A'nın %80'i **ve** koruma geçer.

## HX-12 · Çalıştırılabilir .NET gizli testleri (regex yerine)
- Değişiklik: .NET işleri için gizli test biçimi = gizli dizinde worktree'deki Web projesine referans veren bir xUnit projesi (şablon hx deposunda).
  Testçi şablonuna kural: "kaynak metnine regex/grep yalnız spec gereksinimi metnin kendisi olduğunda (görünür UI metni, CSS değeri); davranışı davranışla test et."
- Ölçüm: P2, P5, P6 spec'leri, Qwen3.7 Plus #high, kol başına 3 tekrar.
  A = orijinal biçim (regex); B = yeni biçim, spec gövdesi aynı, yalnız gizli test biçimi farklı.
  Metrik: koşu başına ref'te düşen test sayısı; base'de düşen test sayısı (güç); derlenmeyen takım = koşu başarısız (ref'te tüm testler düşmüş sayılır).
- **KEEP:** B'nin ref'te düşen test ortalaması ≤ A'nın %25'i **ve** B'nin base'de düşen test ortalaması ≥ A'nın %80'i **ve** 9 B koşusunun en az 8'i derlenir.

## Sonuçlar
(her deney bitince eklenir)
