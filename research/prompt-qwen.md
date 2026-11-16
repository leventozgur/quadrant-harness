Görevin bir araştırma: aşağıdaki modelden ajan tabanlı kod geliştirmede en iyi sonucu almak için prompt'ların ve ayarların nasıl olması gerektiğini bulmak.

Model: Qwen3.7 Plus (Alibaba Qwen3 serisi; opencode-go/qwen3.7-plus; effort varyantları: varsayılan, high, max)
Kullanım: OpenCode CLI üzerinden `opencode run -m <model> "<prompt>"` ile, tek atımlık ajan görevleri (dosya okuma/yazma, shell, test koşturma araçları var). Prompt'lar şu an Türkçe yazılıyor.
Roldeki görevi: gizli kabul testi yazan testçi
Bizim gözlediğimiz hata kalıpları: spec'le çelişen beklenen değer yazma (sınır değerinde ters sonuç bekleme), koşullu assert yazma, bir kez araç çağrısını düz metin olarak yazıp durma

Araştır (önce modelin resmi kaynakları: model kartı, resmi API/dokümantasyon, resmi GitHub/HuggingFace sayfası, resmi blog; sonra güvenilir topluluk kaynakları). Web araçlarını (webfetch / websearch) gerçekten kullan; erişemediğin kaynakları uydurma.
Cevaplanacak sorular:
1. Resmi önerilen sistem/kullanıcı prompt yapısı; ajan/kod görevleri için özel öneriler (talimat sırası, XML/Markdown bölümleri, örnek verme, rol tanımı).
2. Düşünme/akıl yürütme modu ve effort seviyeleri: hangi görev için hangi seviye önerilir, düşünme açıkken prompt'ta nelerden kaçınılmalı (ör. "adım adım düşün" gereksiz mi), sıcaklık/top_p önerileri.
3. Dil: Türkçe prompt mu İngilizce prompt mu daha iyi sonuç verir; kaynak var mı?
4. Araç çağırma (tool calling) ile ilgili bilinen tuhaflıklar ve önlemler.
5. Yukarıdaki gözlenen hata kalıplarımıza karşı prompt düzeyinde somut önlemler.
6. Uzun bağlam ve uzun görevlerde dikkat edilecekler.

Çıktı (Türkçe, en fazla 70 satır, başka şey yazma):
- Her bulgu için: bulgu — kaynak URL (gerçekten açtığın) — güven (resmi / topluluk / çıkarım).
- Sonda "ÖNERİLEN PROMPT KURALLARI" başlığı altında bu model ve bu rol için en fazla 12 madde, uygulanabilir ve kısa.
- Sonda "ÖNERİLEN EFFORT" başlığı altında role göre tek satır öneri ve gerekçe.
