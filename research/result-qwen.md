Şimdi topladığım tüm bilgileri sentezleyip sonucu hazırlıyorum.

---

## BULGULAR

**1. Sistem/kullanıcı prompt yapısı (ajan-kod görevleri)**
- Qwen3, Hermes-style tool calling template'ini öneriyor; Qwen-Agent framework'ü bu template'i dahili olarak uyguluyor — https://qwen.readthedocs.io/en/latest/framework/function_call.html — **resmi**
- Qwen3'ün kendi sistem promptları XML tag'leri (`<model_identity>`, `<capabilities>`) kullanıyor; sızdırılmış prompt arşivi bu yapıyı doğruluyor — https://huggingface.co/Smoffyy/Qwen-Open-System-Prompts — **topluluk**
- Resmî blog: "Qwen-Agent kullanarak tool-calling template ve parser'larından yararlanın" — https://qwenlm.github.io/blog/qwen3 — **resmi**
- Rol tanımı prompt'un başında, tek cümle; talimatlar Markdown başlıklarla bölümlenmeli; örnek (few-shot) tool-call formatı için verilmeli — https://qwen.readthedocs.io/en/latest/framework/function_call.html — **resmi**

**2. Düşünme modu, effort, sampling**
- Düşünme modu için: `Temperature=0.6, TopP=0.95, TopK=20, MinP=0`; non-thinking: `T=0.7, TopP=0.8, TopK=20, MinP=0` — https://huggingface.co/Qwen/Qwen3-8B — **resmi**
- Greedy decoding **kesinlikle yasak**; sonsuz tekrar ve performans düşüşüne yol açıyor — https://huggingface.co/Qwen/Qwen3-8B — **resmi**
- `presence_penalty` 0–2 arası; tekrar azaltır ama yüksek değer dil karışımına yol açabilir — https://qwen.readthedocs.io/en/latest/getting_started/quickstart.html — **resmi**
- Düşünme modu zaten adım adım akıl yürütme yapıyor; "adım adım düşün" talimatı gereksiz, hatta çelişki yaratabilir — https://qwenlm.github.io/blog/qwen3 — **resmi + çıkarım**
- Topluluk: effort "medium" ajan-kod görevlerinde en iyi tokenden/doğruluk oranını veriyor; "xhigh" tek araç çağrısında 40K token'a çıkabiliyor — https://news.ycombinator.com/item?id=49355510, https://www.ssdnodes.com/learn/reasoning-effort-settings-local-llm — **topluluk**
- `preserve_thinking=True` ajan döngülerinde tekrarlayan düşünmeyi azaltır, prefix cache'i etkin kılar — https://forums.developer.nvidia.com/t/qwen3-5-tool-calling-finally-fixed-possibly/366451 — **topluluk**

**3. Dil: Türkçe vs İngilizce prompt**
- Qwen3 119 dili destekliyor, Türkçe (Turkic ailesi) resmî listede — https://qwenlm.github.io/blog/qwen3 — **resmi**
- TÜDÜM çalışması gösteriyor ki: Qwen modeli Türkçe prompt'a Türkçe cevap verse bile düşünme bloğunu İngilizce üretiyor; SFT ile Türkçe düşünme eğitilebiliyor ama doğruluk düşüyor — https://arxiv.org/html/2607.01927v1 — **akademik**
- Doğrudan "Türkçe prompt vs İngilizce prompt" benchmark'ı yok; çıkarım: kod/ajan görevlerinde İngilizce prompt biraz daha iyi, çünkü modelin reasoning trace'i İngilizce ağırlıklı — https://arxiv.org/html/2607.01927v1 + Flutter fine-tune çalışması — **çıkarım**

**4. Araç çağırma tuhaflıkları**
- Reasoning modellerinde ReAct (stopword-tabanlı) template **önerilmez**; model düşünce sırasında stopword üretebilir — https://qwen.readthedocs.io/en/latest/framework/function_call.html — **resmi**
- Bilinen sorun: model metin cevabından sonra tool call'da `` tag'ini atlayabiliyor — https://github.com/QwenLM/Qwen3-Coder/issues/475 — **topluluk**
- Bilinen sorun: model araç adını yanlış üretebiliyor (örn. "grep" → "ggrep") — https://github.com/QwenLM/Qwen3-Coder/issues/475 — **topluluk**
- Uzun ajan oturumlarında tool tanımaları context'i şişirir; tool search pattern önerilir — https://www.youtube.com/watch?v=R7OCrqyGMeY — **topluluk**

**5. Uzun bağlam**
- Native 32K; YaRN ile 128K'ya genişletilebilir — https://huggingface.co/Qwen/Qwen3-8B ��� **resmi**
- Düşünce token'ları context'te birikir; multi-turn'da thinking içeriğini geçmişten çıkarmak resmî best-practice — https://huggingface.co/Qwen/Qwen3-8B — **resmi**
- Max output: çoğu sorgu için 32.768, karmaşık problemler için 38.912 token öneriliyor — https://huggingface.co/Qwen/Qwen3-8B — **resmi**

---

## ÖNERİLEN PROMPT KURALLARI

1. **Rol tanımı tek cümle, prompt'un en başında.** ("Sen gizli kabul testi yazan bir testçisin.")
2. **Türkçe prompt kullan ama kritik terimleri İngilizce bırak** (assert, expect, boundary, edge case); model düşünce bloğunu İngilizce üretse de çıktı Türkçe olur.
3. **"Adım adım düşün" yazma;** düşünme modu zaten açık, bu talimat gereksiz token harcıyor.
4. **Spec'deki beklenen değerleri modelin uydurmasını engelle:** "Beklenen değerleri yalnızca spec'teki formül/tablo/denjenden türet; kendi yorumunla değer atama."
5. **Koşullu assert yasağı açıkça yaz:** "assert/if-else içeren koşul yazma; her test satırı koşulsuz çalışmalı."
6. **Araç çağrısını metin olarak yazma yasağı:** "Araç çağrılarını yalnızca tool-call mekanizmasıyla yap; asla düz metin içinde tool sözdizimi yazma."
7. **Her araç çağrısından önce spec'i oku:** Prompt'a "Önce ilgili spec dosyasını oku, sonra test yaz" sırasını koy.
8. **Few-shot örnek ekle:** 1 doğru tool-call + 1 doğru test örneği, modelin formatı takip etmesini sağlar.
9. **XML veya Markdown bölümleri kullan:** `<rol>`, `<görev>`, `<kurallar>`, `<örnek>` şeklinde bölümle; Qwen3 kendi sistem promptlarında XML kullanıyor.
10. **Çıktı formatını sabitle:** "Test dosyasını `<test>` bloğu içinde, başka açıklama olmadan yaz."
11. **Negatif talimat yerine pozitif talimat ver:** "Yapma" yerine "şöyle yap" demek Qwen3'te daha etkili.
12. **Uzun görevlerde görevi parçala:** Tek prompt'ta >3 dosya veya >50 satır kod üretme; her adımda bir dosya/ fonksiyon iste.

---

## ÖNERİLEN EFFORT

**"high" (veya OpenCode'daki karşılığı)** — Gerekçe: Gizli kabul testi yazma görevi sınır-değer analizi, spec-doğrulama ve koşullu mantık içeriyor; "varsayılan" bu görevlerde yetersiz kalıyor (gözlenen hata kalıpları bunu doğruluyor), "max" ise düşünce bloğunu aşırı uzatarak tek araç çağrısında 40K+ token harcıyor ve ajan döngüsünü yavaşlatıyor. Topluluk benchmark'ları "medium/high" seviyesinin ajan-kod görevlerinde en iyi doğruluk/hız oranını verdiğini gösteriyor.
