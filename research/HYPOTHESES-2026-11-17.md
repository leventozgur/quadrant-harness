# hx geliştirme hipotezleri v2 — 2026-11-17

Durum: **önerildi, hiçbiri geliştirilmedi.** Her hipotez kendi dalında (`exp/HX-NN`) denenir; eşik geliştirmeden önce sabitlenir.
KEEP → commit/merge, KILL → dal silinir (BrainAtlas PRJ-002 disiplini).
Kural (kullanıcı, 2026-11-17): **kalite önce, tasarruf sonra; kaliteyi düşürebilecek hiçbir şey yok.** Bu yüzden her hipotez yalnız
ekleme yapar: test silmez, denetimi azaltmaz, bağlam daraltmaz.

Kaynaklar:
- `research/forensics-2026-11-17-sonnet.md`: 17 görevin gerçek hakem/denetçi/test verisinin kök neden analizi (Sonnet 5.5, salt okur).
- `research/harness-research-C-sonnet.md`: kalite odaklı web araştırması (Sonnet 5.5). Kaynakların yaklaşık yarısı açılarak okundu; [S] işaretliler yalnız arama özetinden.
- `research/harness-research-A/B-deepseek.md`: ilk tur araştırma. İlk liste: `HYPOTHESES-2026-11-17-v1.md`.

## 1. Gerçek hataların kök nedeni (56 TEST_HATASI, 34 denetçi bulgusu)

| Kök neden | Adet | Pay | Nerede |
|---|---|---|---|
| G · Kaynak metnine regex testi: spec'in sabitlemediği literal/değişken adı/yazım biçimi isteniyor | 32 | %57 | Codart P1–P6 (Haiku; ".NET koşmaz, yalnız metin" biçimi) |
| B · Bozuk test kodu (await yok, testler arası paylaşılan HOME, hatalı alt dizi kontrolü) | 14 | %25 | BA (Qwen) |
| C · Arayüz/import/fikstür biçimi varsayılmış (SDK import yolu, `isError` alanı) | 5 | %9 | BA-36, BA-32 |
| A · Spec'in tanımladığı beklenen değer yanlış hesaplanmış | 2 | %4 | BA-31J, BA-32b |
| D/E · Ortam durumu, tanımsız iç değerler | 3 | %5 | BA-43, BA-31J |

Diğer bulgular:
- PM triyajdan sonra **27 gizli testi atladı** (P2–P6). Bu bir düzeltme değil, kaybedilen kapsam.
- **34 denetçi bulgusunun hiçbirini gizli testler yakalamadı.** Bunların ~15'i spec boşluğu: sınır durumu, eşdeğerlik, varsayılan yolun bayt aynılığı.
  P4'te 7 platform API hatası var; regex bunları göremez.
- Kapıdan sonra kaçanlar: BA-28 +48 ms gecikme (yalnız PM ölçümüyle bulundu), P2 `/Health` ↔ gerçek `/api/Health`, BA-43 yanlış öncül, BA-21 listelenmemiş pinli test.
- Worker: BA-21 timeout'u 6 tam `npm test` koşusundan (1143 s'nin 1034 s'si shell'de). BA-43 sessizce takıldı.
  **Sayısal sınır ihlali veride hiç yok.**
- Testçiler P2/P4/P5/P6 raporlarında "regex yanlış düşebilir" diye uyardı; uyarıya göre davranılmadı.

**v1'deki seçimlere dürüst not:** oracle tablosu (HX-02) bu 56 hatanın yalnız ~2–3'ünü önlerdi (%5). Sayısal sınırlar için `check.sh` (HX-04) verideki hiçbir hataya denk gelmiyor.
Bağlam haritası (HX-11) ise ~6–8 hatayı ve 3 spec boşluğunu önlerdi; doğru bir fikir, aşağıda arayüz sözleşmesiyle birleştirildi (Q3).

## 2. Ortak ölçüm düzeni

- **Tekrar seti R:** kaydedilmiş gerçek işler. BA-31J, BA-32, BA-32b, BA-36, BA-38, BA-43 (ref = birleşmiş commit, base = `task.json` `task_base`)
  ve Codart P1–P6 (ref = 509f216, 627bf8a, 08ec1f6, 1965134, 31af173, c75ea3f). Ref'te düşen test = yanlış test.
- **Sentetik S:** `lab/tester_lab.py` (7 görev, 28 mutant), `lab/hard.py`.
- **Kaçan hata seti K:** 34 denetçi bulgusu + 4 kapı sonrası kaçış. Bunlar doğru diff'lere geri enjekte edilir; "yakalandı mı" diye ölçülür.
- Her kol 3 tekrar (lab v5: tek görevlik fark gürültü). Eşik gevşetilmez; ayarlama gerekirse ayrı holdout.
- **Kalite koruması (her hipotezde):** S'de mutant öldürme düşmez, R'de doğru testlerin atılması/karantinası = 0, denetçi girdisi daralmaz.

## 3. Hipotezler (önlediği gerçek hata sayısına göre)

### Gizli testlerin doğruluğu ve gücü

**Q1 · Çalıştırılabilir gizli testler (regex yerine) — HX-12**
- Hipotez: derleme gerektiren projelerde (Codart/.NET, PowerShell) testçi kaynak metnine regex yazmaz, davranış testi yazar.
  Seçenekler: worktree'ye referans veren gizli bir xUnit projesi, PowerShell AST/Pester, JS için `node vm`. Bu, G sınıfı yanlış testleri neredeyse sıfıra indirir ve atlanan davranış kapsamını geri getirir.
- Önlediği: G 32'nin tahminen 28–32'si; ayrıca 27 atlanan testin kapsamı ve P4/P5/P6'nın test edilmemiş davranışları.
- Ölçüm: P1–P6 gizli test takımlarını aynı spec'lerden yeni biçimle yeniden yazdır (Qwen ve Haiku, 3 tekrar) ve birleşmiş commit'lerde koştur.
  Hedef: ref'te düşen test **≤2 toplam** (şu an 32). Ayrıca P4 bulguları ve geri alınan P5/P6 mantığı enjekte edilince öldürme oranı ≥ eski takım.
- Kalite riski yok: testler metin biçimi yerine davranışı ölçer, yani daha güçlüdür. Kapı aynı kalır.
- Ön koşul: makinede `dotnet test` çalışıyor (raporda "muhtemel" denildi); ilk iş bu doğrulanır.

**Q2 · Gizli testlerin base üzerinde ön uçuşu — HX-13**
- Hipotez: worker sonucu kullanılmadan önce gizli takım değişmemiş base'de koşturulur. Assertion dışı hatayla çöken testler (import bulunamadı, TypeError, `JSON.parse(undefined)`) ve "değişmeyen davranış" etiketli olup base'de düşen testler
  worker döngüsüne girmeden testçiye geri döner. Test silinmez, düzeltilir.
- Önlediği: tahminen 8–11/56 (BA-36 ×4, BA-32b ×3, BA-32, BA-43).
- Ölçüm: kayıtlı gizli dizinleri `task_base` üzerinde yeniden koştur. Duyarlılık = işaretlenen ∩ hakemin TEST_HATASI dediği; **yanlış pozitif 0** şart.
- Kalite riski yok: test atılmaz, yalnız yeniden yazdırılır. Yeni davranış testlerinin base'de düşmesi beklenir ve işaretlenmez.

**Q3 · Spec'te arayüz sözleşmesi + otomatik bağlam haritası (HX-11'in güçlendirilmiş hali) — HX-14**
- Hipotez: spec yazılmadan önce deterministik bir betik (LLM değil) repodan rotaları, export'ları, import yollarını, ilgili mevcut testleri ve pinli davranışları çıkarır.
  Opus spec'e "Arayüz sözleşmesi" bölümü koyar: tam fonksiyon imzaları, import satırı, mevcut bir testten kelimesi kelimesine fikstür örneği, dosya yolları.
  Testçiye şu kural eklenir: "beklenen yolu SUT'a verdiğin aynı değişkenden türet". Bu, C ve B sınıfı hataları ve spec boşluklarını azaltır.
- Önlediği: tahminen 14–22/56 (BA-36, BA-32, BA-43 ×9, yardımcı biçim satırları) + 3 spec boşluğu (P2 `/api/Health`, BA-21 pinli test, BA-36 import).
- Ölçüm: BA-36, BA-32, BA-43b, P2–P6 spec'lerine bölümü ekle, yalnız testçiyi yeniden koştur (3 tekrar), kayıtlı uygulamalarda TEST_HATASI say.
  Harita için ayrıca: bu 5 işte sonradan düzeltme olan olguları geriye dönük bulma oranı **5/5**.
- Kalite riski yok: spec'e bilgi eklenir, hiçbir kontrol kalkmaz. Harita "doğrulanmamış ipucu" etiketiyle verilir.

**Q4 · Spec belirsizlik kapısı (iki farklı aile örnek üretir) — HX-15**
- Hipotez: Opus spec taslağını yazdıktan sonra GLM ve Qwen birbirini görmeden spec'i 5–8 somut girdi→çıktı örneğine çevirir.
  Çelişen her örnek bir belirsizlik adayıdır. Opus bunu worker ve testçi başlamadan spec'te çözer. Bu, denetçinin bulduğu spec boşluklarını ve yanlış testleri kaynağında azaltır.
- Dayanak: ClarifyGPT GPT-4 pass@1 68.0→75.8; Ask-or-Assume çözüm oranı 61.2→69.4 (araştırma C).
- Ölçüm: R spec'lerinde çelişkiler, sonradan ref'te düşen testleri ve denetçi spec-boşluğu bulgularını ne oranda öngörüyor? (≥%50 duyarlılık hedefi.)
  Sonra yamalı spec'lerle testçi 3 tekrar: yanlış test/iş ↓, denetçi spec-boşluğu bulgusu ↓.
- Kalite riski yok: yalnız spec'e açıklama eklenir. Maliyet ucuz model + biraz Opus.

**Q5 · Kural→test izlenebilirlik matrisi; kırılgan test kapı öncesi düzeltilir — HX-16**
- Hipotez: Opus spec kurallarını numaralar (R1..Rn). Testçi `trace.json` üretir (kural → test adları → türetme satırı). Hiçbir teste bağlanmamış kural deterministik olarak FAIL verir.
  Testçi kendi raporunda "kırılgan" dediği testleri kapıdan önce yeniden yazar. Bu, kaçan hataları ve "triyajdan sonra test atlama"yı azaltır.
- Önlediği: 27 atlanan test (kapsam kaybı) ve testçinin önceden uyardığı ama işlenmeyen kırılgan testler. Tahminen 8–14/32 G satırı önceden işaretlenirdi.
- Ölçüm: P1–P6 testçi raporlarındaki "kırılgan" beyanı ile 32 TEST_HATASI örtüşmesi (çevrimdışı). R spec'lerinde testi olmayan kural sayısı (taban) → sonra 0.
- Kalite riski yok: yalnız kapsam ve denetim eklenir.

### Kaçan hatalar (34 denetçi bulgusu, hiçbiri gizli testte yoktu)

**Q6 · Spec sınır durumu bataryası (denetçinin bulduğu sınıflardan) — HX-17**
- Hipotez: spec şablonuna, denetçinin tekrar tekrar bulduğu sınıflar için zorunlu bir kontrol listesi eklenir: büyük/küçük harf duyarsız dosya sistemi, CRLF/BOM, boş/sıfır değer, kısmi hata ve idempotans, symlink/uid'de kardeş yazarla eşlik, seçenek doğrulama sırası, varsayılan yolda bayt aynılığı, performans bütçesi.
  Opus her maddeyi "uygulanır / uygulanmaz" diye işaretler. Uygulananlar testçiye kural olarak gider.
- Önlediği: tahminen 34 bulgunun 12–15'i + BA-28 performans kaçışı.
- Ölçüm: 34 bulguyu bataryaya göre etiketle (geri çağırma oranı). Sonra BA-38'i bataryalı spec'le yeniden koştur, Sonnet bulgusu say (3 tekrar).
- Kalite riski yok: spec ve testler genişler.

**Q7 · Statik analiz + performans bütçesi kapısı — HX-18**
- Hipotez: kapıya dile göre analizciler eklenir (PSScriptAnalyzer veya pwsh smoke koşusu, dotnet analyzers, ESLint varsa).
  Spec performans bütçesi verirse (hook p95 gibi) hx bunu ölçer. Bu, regex ve testin göremediği hataları yakalar.
- Önlediği: P4 bulgu 1–6 (salt okunur özellik vb.), BA-28 +48 ms; tahminen 5–7/34 + 2 PM turu.
- Ölçüm: analizciyi P4'ün düzeltme öncesi commit'inde ve BA-28 düzeltme öncesi diff'inde koştur; 8+2 olaydan kaçını işaretliyor (≥5), yeni yanlış alarm sayısı.
- Kalite riski yok: ek kapı. Yalnız yeni uyarılar FAIL sayılır (mevcut uyarı tabanı hariç).

**Q8 · Kapı sonrası mutasyon taraması (yalnız diff) — HX-19**
- Hipotez: kapı PASS olduktan sonra Stryker/mutmut yalnız değişen satırlarda gizli + görünür takımla koşturulur. Hayatta kalan mutantlar eşdeğer-mutant filtresinden geçer.
  Kalanlar testçiye "bunu öldüren test yaz" diye, Sonnet'e de "bu diff'te test edilmeyen davranış" diye gider. Bu, zayıf takımları ve kaçan hataları azaltır.
- Dayanak: Meta ACH (mutant güdümlü testlerin %73'ü kabul edildi), MuTAP; UTBoost (SWE-bench'te geçen ama yanlış yamalar).
- Ölçüm: K setindeki enjekte hataların kapıda kaçan kısmı vs mutasyon turu sonrası kaçan kısmı (3 tekrar). R'de diff başına hayatta kalan mutant ve bunlardan gerçek hataya karşılık gelenler.
- Kalite riski yok: kapıdan sonra çalışır ve yalnız test/bilgi ekler. Yeni test yanlışsa hakeme gider.

**Q9 · Sonnet'e ek kanıt: spec'ten türetilmiş kontrol listesi + çalıştırma çıktısı — HX-20**
- Hipotez: denetimden önce ucuz bir model numaralı kurallardan repo temelli bir kontrol listesi çıkarır (kapsam, kural uyumu, sabit kodlama/test atlama, çalışma zamanı) ve hedefli komutlar koşturur.
  Sonnet şimdiki girdisinin **tamamına ek olarak** bu sonuçları görür. Bu, "benzer ama farklı" ve "fazladan davranış" hatalarının yakalanmasını artırır.
- Dayanak: PatchDiff (makul yamaların %29.6'sı farklı davranıyor; %46.8 benzer-ama-farklı, %27.3 fazladan davranış), Agentic Rubrics ROC-AUC 0.886.
- Ölçüm: K setinden PatchDiff türünde 10 hata doğru diff'lere enjekte edilir. Sonnet tek başına vs Sonnet + liste yakalama oranı, 3 tekrar (hedef ≥+2/10).
- Kalite riski yok: Sonnet'in girdisi kesin üst küme; Sonnet kalır, worker gerekçesine hâlâ kördür.

### Worker kalitesi

**Q10 · Minimal worker scaffold (v1 HX-05) — HX-21**
- Hipotez: worker'ı yalnız `bash`, `read`, `edit` araçlı bir opencode ajanıyla çalıştırmak ilk tur kapı geçmeyi artırır.
- Dayanak (**elle doğrulandı**, HF model kartı, max effort, N=8): DeepSWE v1.1'de OpenCode %65.5, mini-SWE %74.2; Terminal-Bench 2.1'de 85.0 vs 90.3.
- Ölçüm: hard + base set ve R, 3 tekrar: ilk tur PASS **≥+15 puan**. Koruma: gizli dizine erişim 0, timeout artmaz.
- Kalite riski: ölçümle kontrol edilir. Kol eskiyle aynı kapıdan geçer; kötüyse KILL.
- Not: aynı dalda worker'a "dar test koş" sarmalayıcısı (`hx test <dosya>`) de denenir. BA-21 timeout'unun kaynağı tam takım koşularıydı.

**Q11 · Zor işlerde max effort (v1 HX-06) — HX-22**
- Hipotez: spec'te "zor" işaretli işlerde worker `#max` ile çalışır; ilk tur PASS artar. DeepSeek'in resmi önerisi bu, model kartı da max ile ölçülmüş.
  Lab v5 max'ı hiç denemedi. Q10 sonucunun üstüne denenir.

## 4. Listeden çıkanlar (v1 → v2)

| v1 | Karar | Neden |
|---|---|---|
| HX-01 LLM referansıyla karantina | çıkarıldı → Q2 | İki ucuz referans aynı yanlış okumayı paylaşabilir, doğru testler karantinaya girer. Q2 aynı amacı model yazmadan, base koşusuyla sağlar. |
| HX-02 oracle tablosu | düşük öncelik | Gerçek veride hataların yalnız ~%5'ine değiyor. Q4 örnekleri benzer işi belirsizlik bulmak için yapıyor; ayrıca deneme gerekmez. |
| HX-03 hakem yeniden hesaplasın | beklemede | Verideki hakem kararları büyük ölçüde doğru; sorun hakemde değil test üretiminde. |
| HX-04 `check.sh` | düşük öncelik | Verideki sayısal sınır ihlali 0. Q7 statik kapısına alt madde olarak eklenebilir. |
| HX-07, HX-09, HX-10 | **çıkarıldı** | Tekrar azaltma, ucuz denetçi ve dar bağlam kaliteyi düşürebilir (kullanıcı kuralı). |
| HX-08 stall'da dürtme | beklemede | Tek gerçek vaka (BA-43); kaliteye etkisi nötr. |
| HX-11 bağlam haritası | **Q3'e birleşti** | Deterministik betik + arayüz sözleşmesiyle daha güçlü hali. |

## 5. Önerilen sıra

```
1. Q1 (çalıştırılabilir testler)  ─ 32/56 hata, Codart'ta en büyük kaldıraç
2. Q3 (sözleşme + harita)         ─ 14–22/56 + 3 spec boşluğu        ┐ ikisi bağımsız,
   Q2 (base ön uçuşu)             ─ 8–11/56, hx'e küçük ek            ┘ paralel dal
3. Q6 → Q4 → Q5                   ─ spec boşluklarını kaynağında kapatma
4. Q7, Q8, Q9                     ─ kaçan hatalar (34 bulgu)
5. Q10 → Q11                      ─ worker (bağımsız; istenirse erken)
```
Tahmini sayılar Sonnet analizinin tahminleridir (judge satırı bazında). Her dalın ilk işi tahmini R tekrarında ölçmektir.
