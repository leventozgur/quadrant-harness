# GLM-5.3-Flash: Ajan Tabanlı Kod Geliştirme İçin Prompt ve Ayar Araştırması

## BULGULAR

**1. Sistem/Kullanıcı Prompt Yapısı**
- Kural listesi stili (madde madde, emir kipi) en iyi sonucu veriyor; düz metin değil — [gist.github.com/apnea/e9dd7a650bdc3300375fffc54592f48d](https://gist.github.com/apnea/e9dd7a650bdc3300375fffc54592f48d) — güven: topluluk (GLM-5 makalesi + resmi dokümanlardan türetim)
- Sistem promptu ~100-160 token tutulmalı; model öz-eğitiminde özlülüğe optimize edilmiş — [arxiv.org/html/2602.15763v1](https://arxiv.org/html/2602.15763v1) (Bölüm 3.1 SFT) — güven: resmi
- Rol tanımı kısa olmalı: "You are opencode, a coding agent." — [gist.github.com/apnea/e9dd7a650bdc3300375fffc54592f48d](https://gist.github.com/apnea/e9dd7a650bdc3300375fffc54592f48d) — güven: topluluk
- Numaralı öncelik sırası çelişen kurallarda belirleyici — [docs.z.ai/guides/llm/glm-5](https://docs.z.ai/guides/llm/glm-5) — güven: resmi (çıkarsama)
- Önceki tur `reasoning_content` blokları aynen döndürülmeli (cache + düşünce tutarlılığı) — [docs.z.ai/guides/capabilities/thinking-mode.md](https://docs.z.ai/guides/capabilities/thinking-mode.md) — güven: resmi
- Sistem promptu istekler arası sabit kalmalı (prefix tabanlı örtük cache) — [docs.z.ai/guides/capabilities/cache](https://docs.z.ai/guides/capabilities/cache) (apnea gist'te alıntılı) — güven: resmi

**2. Düşünme/Effort Seviyeleri**
- Üç seviye: `low`, `high`, `max`; varsayılan `max` — [huggingface.co/zai-org/GLM-5.3-Flash](https://huggingface.co/zai-org/GLM-5.3-Flash) — güven: resmi
- `high` = ~%31.4 kod skoru ~50K token; `max` = ~%34.5 ~75K token — [zentor.ai/blog/glm-5-3-reasoning-effort](https://zentor.ai/blog/glm-5-3-reasoning-effort) — güven: topluluk (Z.ai figürleri)
- Z.ai kod görevleri için `max` önerir — [docs.z.ai/guides/llm/glm-5.3](https://docs.z.ai/guides/llm/glm-5.3) — güven: resmi
- `thinking.type: "disabled"` artık desteklenmiyor (GLM-5.3'te zorunlu düşünme) — [zentor.ai/blog/glm-5-3-reasoning-effort](https://zentor.ai/blog/glm-5-3-reasoning-effort) — güven: resmi
- `temperature=1.0`, `top_p=0.95–1.0` kod/ajan değerlendirmelerinde kullanılıyor — [huggingface.co/zai-org/GLM-5.3-Flash](https://huggingface.co/zai-org/GLM-5.3-Flash) dipnot — güven: resmi
- "Adım adım düşün" gereksiz; düşünme zaten açık — [docs.z.ai/guides/capabilities/thinking-mode.md](https://docs.z.ai/guides/capabilities/thinking-mode.md) — güven: resmi
- Sohbet senaryolarında `clear_thinking=true` (varsayılan false) — [huggingface.co/zai-org/GLM-5.3-Flash](https://huggingface.co/zai-org/GLM-5.3-Flash) Note — güven: resmi

**3. Dil: Türkçe vs İngilizce**
- GLM-5 çok dilli ama fiilen EN kod/altyapı, ZH ürün dokümanı için kullanılıyor — [zilliz.com/ai-faq/what-languages-does-glm5-support](https://zilliz.com/ai-faq/what-languages-does-glm5-support) — güven: topluluk
- SWE-bench Multilingual = 73.3 (Türkçe özgül rakam yok) — [huggingface.co/zai-org/GLM-5](https://huggingface.co/zai-org/GLM-5) — güven: resmi
- Tokenizasyon dili başına maliyet/fark değişir; karışık dilde kayma riski — [zilliz.com/ai-faq/what-languages-does-glm5-support](https://zilliz.com/ai-faq/what-languages-does-glm5-support) — güven: topluluk
- Türkçe için doğrudan karşılaştırma kaynağı yok — çıkarım: kod/ajan için İngilizce daha güvenli

**4. Araç Çağırma Tuhaflıkları**
- Zaman zaman boş argümanlar (`pattern: Required` hatası) — [forum.cursor.com](https://forum.cursor.com/t/glm-5-3-agent-tool-calls-intermittently-arrive-with-empty-arguments-pattern-required-command-required/173756) — güven: topluluk
- Argümanlar bazen JSON yerine XML etiketi olarak üretiliyor — [github.com/zai-org/GLM-5/issues/84](https://github.com/zai-org/GLM-5/issues/84) — güven: topluluk
- ~2/25 turda JSON ayrıştırma hatası (soak test) — [github.com/noonghunna/club-3090/issues/1195](https://github.com/noonghunna/club-3090/issues/1195) — güven: topluluk
- Zorla `tool_choice` ile argüman kısalması/truncation — [github.com/vllm-project/vllm/issues/55541](https://github.com/vllm-project/vllm/issues/55541) — güven: topluluk
- Önlem: argümanları doğrula, timeout/büyüklük sınırı koy, tool çağrısı ile sonucu bitişik tut, `tool_choice` alanını "auto"da bırak — [glm5.app/api/docs/function-calling](https://glm5.app/api/docs/function-calling) — güven: resmi

**5. Gözlenen Hata Kalıplarına Karşı Önlemler**
- Testçi rolünün spec'le çelişen testler yazması: çıktı biçimini kısıtla ("Testler yalnızca spec'teki davranışı doğrulamalı; implementasyona karşı yazma"); spec metnini bağlamda tekrar ver — [docs.z.ai/guides/capabilities/function-calling.md](https://docs.z.ai/guides/capabilities/function-calling.md) Best Practices + çıkarım — güven: çıkarım
- 396 satırda satır numarası kaydırma: dosya içeriğini satır numaralı biçimde ver ve modelden "her değişiklik için kaynak satırı açıkça belirt" iste; uzun dosyaları parça parça okut — [arxiv.org/html/2602.15763v1](https://arxiv.org/html/2602.15763v1) (DSA'nın 128K'da küçük kaybı) — güven: çıkarım
- Recency bias: en önemli kuralı/sınırı promptun sonuna koy — [reddit.com/r/SillyTavernAI](https://www.reddit.com/r/SillyTavernAI/comments/1r8xx2q/glm_5_is_good_at_understanding_a_long_context_but/) — güven: topluluk

**6. Uzun Bağlam ve Uzun Görevler**
- 200K bağlam (GLM-5) / 1M (GLM-5.3); DSA ile uzun bağlam maliyeti ~1.5–2× düşüş — [arxiv.org/html/2602.15763v1](https://arxiv.org/html/2602.15763v1) — güven: resmi
- "Lost-in-the-middle" için interleaved packing uygulanmış — [arxiv.org/html/2602.15763v1](https://arxiv.org/html/2602.15763v1) (Bölüm 2.3) — güven: resmi
- Önemli talimatları bağlamın sonuna koy; prefix'i sabit tut — [docs.z.ai/guides/capabilities/cache](https://docs.z.ai/guides/capabilities/cache) + Reddit — güven: resmi + topluluk
- Interleaved thinking: araç çağrıları arasında düşünme bloklarını koru — [docs.z.ai/guides/capabilities/thinking-mode.md](https://docs.z.ai/guides/capabilities/thinking-mode.md) — güven: resmi
- Uzun görevlerde hata birikir (CC-Bench-V2 long-horizon: GLM-5 Opus 4.5'in gerisinde) — [arxiv.org/html/2602.15763v1](https://arxiv.org/html/2602.15763v1) (Bölüm 6.2.3) — güven: resmi

---

## ÖNERİLEN PROMPT KURALLARI

1. Sistem promptunu kısa tut (≤160 token); kural listesi + numaralı öncelik kullan.
2. Rol tanımı tek cümle: "You are a [role] agent."
3. Kod görevlerinde dili İngilizce yap; Türkçe prompt kod/altyapı görevlerinde riskli.
4. `temperature=1.0`, `top_p=0.95` kullan (resmi benchmark değerleri).
5. Araç şemalarını promptta tekrarlama (model zaten alıyor); sadece tercih sırası ver.
6. `tool_choice="auto"` bırak; gelen argümanları her zaman doğrula.
7. Her araç çağrısından sonra `reasoning_content` ve `tool_calls` bloklarını eksiksiz döndür.
8. Testçi rolünde: "Testler yalnızca spec'teki davranışı doğrulasın; implementasyona göre yazma" kuralını ekle.
9. Dosya değişikliklerinde: "Her düzeltme için kaynak dosyadan tam satır numarasını belirt" kuralını ekle.
10. Sistem promptunu sabit tut; değişken talimatları kullanıcı mesajının sonuna koy (cache + recency).
11. Uzun dosyaları parça parça okut; tek seferde 300+ satır yapıştırma.
12. "Adım adım düşün" yazma; düşünme zaten açık. Sadece görevi net anlat.

## ÖNERİLEN EFFORT

- **Hakem (judge)**: `low` — sınıflandırma kararları kısa akıl yürütme gerektirir; hızlı ve ucuz.
- **Yükseltme worker'ı**: `high` — kod üretimi için yeterli kalite (%31.4), ~50K token; maliyet/ Performans dengesi en iyi.
- **Holdout veri yazarı**: `max` — uzun, dikkat gerektiren, tek seferlik veri üretimi; hata pahalı, `max`'ın %3.1 puanlık artışı burada değerli.
