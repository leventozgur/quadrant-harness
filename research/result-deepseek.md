# DeepSeek V4.1 Flash — Ajan Kod Görevlerinde Prompt ve Ayar Araştırması

## 1. Sistem/Kullanıcı Prompt Yapısı

- **Resmi öneri (6 katman, bu sırada):** Rol → Görev → Bağlam → Kısıtlar → Çıktı biçimi → Örnek. İlk token'lar daha ağır basar; rol ve görev bağlamdan önce gelmeli. Uzun bağlamdan sonra görevi tek satır tekrarlayın ("task sandwich"). — [deepseek.wang/en/tutorials/deepseek-prompt-engineering](https://deepseek.wang/en/tutorials/deepseek-prompt-engineering) — güven: topluluk (resmi dokümantasyonla tutarlı).
- **Ajan/kod için:** Sistem promptunda rol + görev + kısıtlar + "No preamble." + biçim; kullanıcı mesajı sadece veri/istek. Negatif örnek ("Wrong: … Right: …") olumlu talimattan daha etkili. — [deepseek.wang](https://deepseek.wang/en/tutorials/deepseek-prompt-engineering) — güven: topluluk.
- **Çıktı çapası (output anchor):** Prompt'u beklenen çıktının ilk karakterleriyle bitirmek V4-Flash'ta preamble kaymasını ciddi azaltır. — [deepseek.wang](https://deepseek.wang/en/tutorials/deepseek-prompt-engineering) — güven: topluluk.

## 2. Düşünme Modu ve Effort

- **Varsayılan:** thinking=enabled, effort=high (75). low=50, high=75, max=100. Orta değerler de kullanılabilir (enterpolasyon). — [api-docs.deepseek.com/guides/thinking_mode](https://api-docs.deepseek.com/guides/thinking_mode) — güven: resmi.
- **Hangi görev için hangi seviye:** Basit formatlama/sınıflandırma/çeviri → thinking=disabled. Çok adımlı ajan döngüsü → high. Çok zor kod/muhakeme → max (384K bağlam önerirler). — [api-docs.deepseek.com/guides/thinking_mode](https://api-docs.deepseek.com/guides/thinking_mode) + [huggingface model kartı](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/blob/main/encoding/README.md) — güven: resmi.
- **Düşünme açıkken:** `temperature`, `top_p`, `presence_penalty`, `frequency_penalty` **görmezden gelinir** (hata vermez ama etkisiz). Prompt'un kendisini ayarlayın. "Adım adım düşün" gereksiz — model zaten `<think>` bloğu üretiyor. — [api-docs.deepseek.com/guides/thinking_mode](https://api-docs.deepseek.com/guides/thinking_mode) — güven: resmi.
- **Thinking kapalıyken:** Kod için sıcaklık 0.0, genel 1.0, yaratıcı 1.3. — [deepseek.wang](https://deepseek.wang/en/tutorials/deepseek-prompt-engineering) — güven: topluluk (resmi tabloya referans).
- **Tool calling + thinking:** `reasoning_content` her turda API'ye geri verilmeli, aksi halde 400 hatası. — [api-docs.deepseek.com/guides/thinking_mode](https://api-docs.deepseek.com/guides/thinking_mode) — güven: resmi.

## 3. Dil (Türkçe vs İngilizce)

- DeepSeek'in ana bilgisi zh-en; Türkçe için resmi benchmark yok. V4-Flash'ın ara sıra Çince'ye kaydığı bilinen bir bug. — [github.com/deepseek-ai/DeepSeek-V3#1483](https://github.com/deepseek-ai/DeepSeek-V3/issues/1483), [huggingface abliterated kartı](https://huggingface.co/windowsxp811203/DeepSeek-V4.1-Flash-1017-Abliterated) — güven: topluluk.
- **arXiv:2607.14816** (460 görev, 3 model, 5 dil) İngilizce'nin sürekli en iyi kodu üretmediğini; etki model+programlama diline bağlı olduğunu gösteriyor. Türkçe denenmemiş ama kod tanımlayıcıları İngilizce olduğundan İngilizce prompt daha güvenli bir varsayılan. — [arxiv.org/abs/2607.14816](https://arxiv.org/abs/2607.14816) — güven: hakemli akademik.
- **Çıkarım:** Türkçe prompt kullanılacaksa, sistem promptunda "Reply in Turkish" gibi çıktı dili sabitlenmeli; teknik terimler ve kod örnekleri İngilizce kalmalı.

## 4. Araç Çağırma Tuhaflıkları

- **Uzun bağlamda tekrar döngüsü:** 92K–350K token derinliğinde model tool-call kararı noktasında "Let me run it." gibi kısa eylem duyurusunu sonsuz tekrarlıyor (Ollama, DashScope, vLLM'de doğrulandı). ≥20 önceki tekrar örneği → %87 başarısızlık. — [huggingface discussions/58](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731/discussions/58) — güven: topluluk (çoklu stack'te yeniden üretilmiş).
- **Önlemler:** `frequency_penalty >= 0.1` (döngüyü kırar ama başka bozulmalar getirebilir); gateway'de tekrar tespiti + resample; geçmişten döngü metnini sıyırıp yeniden göndermek. — [huggingface discussions/58](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731/discussions/58) — güven: topluluk (üretilmiş ölçüm).
- **Paralel tool call güvenilmez:** Tek `parallel_execute` çağrısına paketlemek workaround. — [github.com/deepseek-ai/awesome-deepseek-agent#483](https://github.com/deepseek-ai/awesome-deepseek-agent/issues/483) — güven: topluluk.
- **DSML format (V4.1):** `<｜DSML｜ calls>` (space'li), V4'te space yoktu. `string="true"`/`"false"` ayrımı kritik. — [huggingface encoding/README.md](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/blob/main/encoding/README.md) — güven: resmi.

## 5. Gözlenen Hatalarımıza Karşı Prompt Önlemleri

- **47 dk sessiz takılma:** Muhtemelen tool-call tekrar döngüsü. → Prompt sonuna "After reasoning, immediately invoke the required tool or produce the final answer. Do not repeat action announcements." ekleyin; `frequency_penalty=0.1`; harness tarafında circuit-breaker (>K char without tool_use → abort+retry). — [discussions/58](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731/discussions/58), [cline#13041](https://github.com/cline/cline/issues/13041) — güven: topluluk/çıkarım.
- **Zaman aşımına kadar çalışıp yarım rapor:** `max_tokens`'ı makul ayarlayın; prompta "If you cannot finish, stop cleanly and state what remains." — [deepseek.wang](https://deepseek.wang/en/tutorials/deepseek-prompt-engineering) — güven: çıkarım.
- **Sayısal sınır aşımı (README ≤15 satır):** Kısıt promptun en başına VE en sonuna konulmalı (sandviç); "Exceeding the limit is a hard failure." gibi sert ifade. — [deepseek.wang](https://deepseek.wang/en/tutorials/deepseek-prompt-engineering) — güven: topluluk.
- **Arka planda kalan npm test:** Prompta "Always terminate spawned processes before reporting; never leave background daemons." + sistem tarafında `pkill` garantisi. — çıkarım.

## 6. Uzun Bağlam / Uzun Görev

- 1M token bağlam resmi; 64K+ girişte bazı stack'lerde askı raporlanmış. — [vllm#41125](https://github.com/vllm-project/vllm/issues/41125) — güven: topluluk.
- KV cache 1/4 HBM ile sıkıştırılmış; istikrarlı sistem promptunu başa sabitleyip cache-hit'ten yararlanın. — [api-docs.deepseek.com/news/news260910](https://api-docs.deepseek.com/news/news260910) — güven: resmi.
- Araçlı konuşmalarda `drop_thinking` otomatik kapanır, her turun reasoning'i tutulur — bağlam hızlı şişer; gereksiz turları kısaltın. — [huggingface encoding/README.md](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/blob/main/encoding/README.md) — güven: resmi.
- 1017 sürümü "shorter outputs" iddiası; güncel sürüm kullanın. — [api-docs.deepseek.com/news/news261017](https://api-docs.deepseek.com/news/news261017) — güven: resmi.

---

## ÖNERİLEN PROMPT KURALLARI

1. Sistem promptu 6 katmanda yaz: Rol → Görev → Bağlam → Kısıtlar → Çıktı biçimi → 1–2 örnek.
2. Rolü tek cümle, görevi tek fiil-cümlesi tut; birden fazla ana görev listeleme.
3. Sayısal kısıtları (≤15 satır vb.) hem başa hem sona koy; "hard failure" diye işaretle.
4. Uzun bağlamdan sonra görevi tek satır tekrar et (task sandwich).
5. Prompt'u beklenen çıktının ilk karakterleriyle bitir (output anchor).
6. "Adım adım düşün" yazma — düşünme modunda gereksiz, kapalı modda zararlı.
7. Negatif örnek ver ("Wrong: … Right: …") — "do not" satırından daha etkili.
8. Kod ve teknik terimleri İngilizce tut; çıktı dili gerekirse açıkça belirt.
9. Process/spawn içeren görevlerde "Always terminate spawned processes before reporting." ekle.
10. Tool çağrılarında tekrar döngüsünü kırmak için prompt sonuna "Do not repeat action announcements; invoke the tool immediately." ekle.
11. `max_tokens`'ı gerçekçi tut; yetersiz bırakma.
12. Harness tarafında circuit-breaker: >N tekrar cümle veya >K char tool-call yoksa abort+retry.

## ÖNERİLEN EFFORT

**Worker (kod yazar) rolü için: `effort=high` (varsayılan, 75).** Gerekçe: Çok adımlı ajan döngüsünde `reasoning_content` geri beslenerek araç kararları iyileşir; `max` sadece çok karmaşık görevlerde fark yaratır ama token maliyetini ve "Let me…" döngüsü riskini büyütür. Basit tek-dosya yazma görevlerinde `low` (50) veya thinking=disabled düşünülebilir — ancak OpenCode'un tek atımlık ajan kullanımında `high` en iyi denge.
