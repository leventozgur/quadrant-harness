# hx geliştirme hipotezleri — 2026-11-17

Durum: **önerildi, hiçbiri geliştirilmedi.** Her hipotez kendi dalında (`exp/HX-NN`) denenir; eşik geliştirmeden önce sabitlenir.
KEEP → commit/merge, KILL → dal silinir (BrainAtlas PRJ-002 disiplini).

Kaynaklar:
- `research/harness-research-A-deepseek.md` (harness mimarileri) ve `research/harness-research-B-deepseek.md` (doğrulama/test/yönlendirme).
  Araştırmayı DeepSeek V4.1 Flash yaptı (opencode-go, varsayılan effort): 2 koşu, 70 web çağrısı, 503 s, ≈$0.08.
- Kendi metriklerimiz: `BrainAtlas/.git/hx/metrics.jsonl` ve `CodartERP_NetCore/.git/hx/metrics.jsonl` (2026-11-17'de okundu).
- Elle doğrulanan tek iddia: H5'teki DeepSeek model kartı tablosu. Diğer URL ve sayılar DeepSeek raporundan geliyor, **doğrulanmadı**.

## 1. Mevcut durum (ölçüm)

| Metrik | BrainAtlas | CodartERP | Toplam |
|---|---|---|---|
| Kapı koşusu / FAIL | 26 / 13 | 16 / 8 | 42 / 21 (**%50 FAIL**) |
| Hakem: KOD_HATASI / TEST_HATASI | 5 / 24 | 1 / 32 | 6 / 56 (**düşen gizli testlerin %90'ı yanlış test**) |
| Worker çağrısı / timeout / stall | 20 / 3 / 1 | 10 / 0 / 0 | 30 / 3 / 1 (%13) |
| Go maliyeti (tahmin) | $8.17 (testçi $2.72) | $0.54 | $8.71 |

Sonuç: en büyük kayıp **yanlış gizli testler**. Kod hatası nadir. Bu yüzden ilk sıradaki hipotezler testçi ve hakem tarafında.
Claude tarafında en büyük kalemler Opus spec yazımı ve Sonnet denetimi (~68k token/spawn).

## 2. Ortak ölçüm düzeni

- **Gerçek spec tekrar seti (R):** BA-38, BA-32b (ref = main 7e41e58, base = 503bcba) + CodartERP P1–P6 (ref = birleşmiş uygulama).
  Ref'te düşen her test TEST_HATASI sayılır (lab v6/v7'deki yöntem).
- **Sentetik set (S):** `lab/tester_lab.py`: 7 zor görev, 28 doğrulanmış mutant. Worker için `lab/hard.py` ve base set.
- **Gürültü:** lab v5'te tek görevlik fark gürültü düzeyindeydi. Bu yüzden her kol **3 tekrar** koşar ve karar tekrar ortalamasıyla verilir.
  Eşik geçmezse eşik gevşetilmez, parametre holdout'a göre ayarlanmaz.
- **Yeni holdout:** ayarlama gerekirse ayrı bir holdout'u (GLM yazar, worker/testçi görmez) kullan; R'ye karşı ayarlama yapma.

## 3. Hipotezler (öncelik sırasıyla)

### P1 — Yanlış gizli testler (sorunun %90'ı)

**HX-01 · Bağımsız referans uygulamalarla test karantinası (CodeT tarzı ikili uyum)**
- Hipotez: gizli testler kapıdan önce 2 bağımsız ucuz referans uygulamaya karşı koşturulur (GLM-5.3-Flash ve DeepSeek, yalnız spec'ten, worker'dan ayrı).
  İki referansta da düşen test "şüpheli" diye karantinaya alınır ve hakeme gider; worker döngüsüne girmez. Bu, worker'a ulaşan TEST_HATASI sayısını azaltır.
- Dayanak: CodeT test ile çözümler arası uyum, pass@1 +18.8 puan; SWT-Bench'te üretilen testler filtre olarak precision'ı 2 katına çıkarıyor; LLM assertion'larının >%62'si doğru çözümde düşüyor.
- Metrik (R): ref'te düşen ve karantinaya **alınmayan** test sayısı/iş, Qwen tabanına göre **≥%50 azalır**.
- Koruma: S'de mutant öldürme en fazla 1/28 düşer. Karantinaya alınan doğru testler (ref'te geçenler) ≤%10. Ek Go maliyeti ≤$0.10/iş.
- Not: referansın kendisi yanlış olabilir. İki farklı aile kullanmak ortak hata riskini azaltır ama sıfırlamaz.

**HX-02 · Spec'te "oracle tablosu"**
- Hipotez: Opus her sınır durumu için girdi → beklenen çıktı tablosu yazar (spec şablonuna zorunlu bölüm). Testçi beklenen değeri yalnız bu tablodan veya tabloda gösterilen hesaptan alır.
  Bu, TEST_HATASI sayısını azaltır.
- Dayanak: TDD (spec + test) MBPP +%12, HumanEval +%8.5; AlphaCodium'un test tabanlı akışı. Bizde TEST_HATASI'nın çoğu "beklenen değeri yanlış hesaplama".
- Metrik (R, aynı spec'lerin tablolu sürümü): TEST_HATASI/iş **≥%40 azalır**.
- Koruma: S'de mutant öldürme düşmez. Opus spec çıktı token'ı en çok +%25.
- Not: HX-01'den ucuz (kod değişikliği yok, şablon + Opus talimatı). İlk denenecek hipotez olarak önerilir.

**HX-03 · Hakem sınıflandırmak yerine oracle'ı yeniden hesaplasın**
- Hipotez: hakem önce spec'teki ilgili satırı alıntılar, beklenen değeri o satırdan kendisi hesaplar, sonra testteki değerle karşılaştırır.
  Alıntı yoksa sonuç BELIRSIZ olur. Bu, hakem doğruluğunu artırır.
- Dayanak: LLM'ler dışarıdan gelen oracle'ı yargılamada, üretmeye göre %18 daha az doğru; postcondition filtresi yanlış assertion'ların %63–65'ini yakalıyor.
- Metrik: geçmiş 62 hakem vakası etiketli set (etiket = Opus'un son kararı) üzerinde doğruluk **≥+10 puan**, KOD_HATASI→TEST_HATASI karışması ↓.
- Koruma: hakem süresi en çok 2×, maliyet ≤$0.05/vaka.
- Ön koşul: 62 vakanın etiketlerini metrics + karar notlarından çıkarmak (yarım gün iş).

**HX-04 · Sayısal sınırlar için makine-okunur `check.sh`**
- Hipotez: spec'teki ölçülebilir kısıtlar (satır sayısı, dosya listesi, yasak import) prose yerine spec'e eklenen bir `check.sh` olur.
  Worker bitirmeden önce bunu koşturur, kapı aynısını yeniden koşturur. Bu, sınır ihlallerini sıfıra indirir.
- Dayanak: Anthropic uzun koşu harness'i (passes bayraklı kabul listesi), Claude Code "değişmez kural hook'la, prose ile değil".
- Metrik (S'de sayısal sınır içeren görevler + README ≤15 satır vakası): ihlal **0/3 tekrar**.
- Koruma: worker süresi en çok +%10.

### P2 — Worker kalitesi ve süresi

**HX-05 · Worker için minimal scaffold (opencode'da yalnız bash + edit ajanı)**
- Hipotez: worker'ı varsayılan opencode build ajanı yerine yalnız `bash`, `read`, `edit` araçlı özel bir opencode ajanıyla (mini-SWE tarzı) çalıştırmak
  ilk turda kapı geçme oranını artırır ve adım sayısını azaltır.
- Dayanak (**doğrulandı**, HF model kartı, max effort, N=8): aynı model DeepSWE v1.1'de OpenCode %65.5, mini-SWE %74.2, DSH Minimal %72.6;
  Terminal-Bench 2.1'de 85.0 vs 90.3. SWE-agent ablasyonu: düzenleyici + lint koruması +3 puan.
- Metrik: worker hard set + R'de ilk tur kapı PASS **≥+15 puan** veya aynı başarıda adım/maliyet **≥%25 az**.
- Koruma: gizli dizine erişim 0, arka plan süreci 0, timeout artmaz.
- Risk: OpenCode Go uç noktasına opencode dışından erişim belirsiz. Bu yüzden önce opencode içinde araç kısıtlı ajan denenir; mini-swe-agent ancak API erişimi doğrulanırsa denenir.

**HX-06 · Worker effort `max` (yalnız zor işlerde)**
- Hipotez: spec "zor" işaretliyse (≥3 dosya veya ≥10 sınır durumu) worker `#max` ile çağrılır. Bu, ilk tur kapı geçme oranını artırır ve toplam iş maliyetini düşürür (daha az tekrar).
- Dayanak: DeepSeek resmi öneri: çok zor kod → max. Model kartındaki scaffold tablosu da max effort ile ölçüldü. Lab v5 yalnız low ve varsayılanı karşılaştırdı, max'ı denemedi.
- Metrik (hard set, 3 tekrar): ilk tur PASS **≥+1 görev/7** ve tekrar dahil iş başı maliyet artışı ≤%30.
- Koruma: stall/timeout artmaz.

**HX-07 · Hata sınıfına göre tekrar bütçesi**
- Hipotez: aynı ihlal edilmiş kural 2. turda yine düşerse 3. worker turu atlanıp doğrudan escalate'e geçilir. Syntax/import hatası ise kısa bir tur alır.
  Bu, duvar saati süresini düşürür ve çözüm oranını korur.
- Dayanak: self-repair kazancının çoğu ilk 2 turda; assertion hatası onarımı ~%45; feedback kalitesi darboğaz.
- Metrik: metrics.jsonl üzerinde geriye dönük simülasyon + sonraki 5 gerçek iş: iş başı süre **≥%20 az**, çözülen iş sayısı aynı.
- Not: bizde n küçük (1 escalate). Önce geriye dönük analiz yapılır; veri yetmezse ERTELE.

**HX-08 · Stall'da öldürmek yerine dürt + blok checkpoint**
- Hipotez: 900 s olaysız kalınca süreci öldürüp yeniden çağırmak yerine aynı oturuma "git status, son yeşil adımı yaz, tek sonraki komutu çalıştır" mesajı gönderilir.
  Worker her mantıksal blokta checkpoint commit atar. Bu, timeout/stall ile kaybolan işi azaltır.
- Dayanak: Live-SWE-agent'ta her adımda yansıtma, +3.2 puan; blok seviyesi checkpoint makalesi (doğrulanmadı).
- Metrik: uzun koşu sentetik görevi (≥60 adım) 3 tekrar: tamamlanma oranı ↑, kaybolan dakika ↓. Gerçek işlerde timeout/stall oranı %13 → ≤%5.
- Koruma: kapı mantığı değişmez, checkpoint commit'leri `hx commit` öncesi squash edilir.

### P3 — Claude token'ı (Opus/Sonnet kotası)

**HX-09 · Risk tabanlı denetçi yönlendirmesi**
- Hipotez: Sonnet yalnız riskli diff'te çalışır (kimlik doğrulama/güvenlik dosyası, >N satır, spec dışı dosya, ilk kapı FAIL'den sonra geçmiş).
  Diğerlerinde farklı aileden ucuz bir denetçi (Qwen3.7 Plus #high) çalışır. Bu, Claude denetim token'ını ≥%50 azaltır ve hata yakalamayı korur.
- Dayanak: RouteLLM ile kalitenin %95'i, pahalı çağrıların %26'sı; FrugalGPT/AutoMix kademeleri.
- Metrik: geçmiş diff'lerde Sonnet'in geçerli bulguları referans alınır. Ucuz denetçi bu bulguların **≥%90'ını** yakalar. Sonnet spawn sayısı ≥%50 azalır.
- Ön koşul: geçmiş Sonnet bulgularının (review=bulgu) diff + bulgu listesi olarak arşivlenmesi.

**HX-10 · Denetçi bağlamını daraltma**
- Hipotez: denetçiye spec + yalnız diff hunk'ları + kapı sonucu verilir ve "repo keşfi yapma; yalnız diff'teki satırlar ve doğrudan çağıranlar" sınırı konur.
  Çıktı en fazla 5 doğruluk bulgusu, stil yok. Bu, spawn başına token'ı 68k → ≤35k indirir ve bulguları korur.
- Dayanak: Anthropic context engineering (just-in-time retrieval, context rot), Claude Code "skip style" yoksa denetçi hep bir şey bulur.
- Metrik: aynı 5–8 geçmiş diff'te token/spawn **≤35k**, geçerli bulgu kaybı 0.
- Not: HX-09'dan bağımsız; ikisi birlikte denenmez (ayrı dallar, sonra birleşim).

**HX-11 · Ucuz locator geçişi (Opus spec'inden önce)**
- Hipotez: spec yazılmadan önce DeepSeek bir "bağlam haritası" çıkarır (ilgili dosya:satır aralıkları, semboller, mevcut testler, koşturma komutu; ≤2k token).
  Opus bu haritayla spec yazar, worker aynı haritayı alır. Bu, Opus'un repo okuma token'ını ve worker'ın keşif adımlarını azaltır.
- Dayanak: Agentless localize→repair→validate (Lite %32, $0.70); Aider repo map (1k token); AutoCodeRover.
- Metrik: 3 gerçek iş: Opus'un spec öncesi okuma tool çağrısı/token'ı **≥%40 az**, worker ilk 10 adımdaki keşif çağrısı ↓, kapı sonucu kötüleşmez.
- Risk: Opus token'ını ölçmek zor (Claude Code oturum dökümü gerekir). Ölçüm yöntemi önce netleştirilir.

## 4. Önerilen sıra

```
HX-02 (şablon, ucuz) ──┐
HX-04 (check.sh)  ─────┼─► sonra HX-01 (referans karantinası) ─► HX-03 (hakem)
                       │
HX-05 (minimal ajan) ──┴─► HX-06 (max effort, HX-05 sonucu üstüne)
HX-10 → HX-09 (Claude token)          HX-07, HX-08, HX-11: veri/ölçüm hazır olunca
```

Gerekçe: TEST_HATASI kayıpların %90'ı; HX-02 ve HX-04 kod gerektirmez ve hızlı ölçülür. HX-05 bağımsız ve en güçlü dış kanıta sahip.

## 5. Elenen fikirler (neden)

- Çoklu ajan / orientation ajanı: Augment ve Cognition net kazanç bulmadı; 80 başvuru analizinde çoklu ajan medyanı tek ajandan düşük.
- Worker'a kendi testlerini yazdırmak: 5.000 trajektuvar analizinde sonuca etkisi küçük, token maliyeti büyük. Bizde zaten gizli testçi var.
- LLMLingua tarzı sıkıştırma: Claude Code subagent girdisini kontrol etmiyoruz; HX-10 aynı amaca daha basit yoldan gidiyor.
- Prompt caching: Claude Code subagent'ları önbelleği zaten otomatik kullanıyor; ayrı hipotez gerektirmiyor.
- Best-of-N worker: Go maliyeti N katı; TEST_HATASI çözülmeden seçim sinyali (gizli testler) güvenilir değil. HX-01/02 sonrası yeniden değerlendirilir.
