Görevin bir araştırma: aşağıdaki modelden ajan tabanlı kod geliştirmede en iyi sonucu almak için prompt'ların ve ayarların nasıl olması gerektiğini bulmak.

Model: GLM-5.3-Flash (Zhipu/Z.ai GLM-5 serisi; opencode-go/glm-5.3-flash; effort varyantları: varsayılan, low, high, max)
Kullanım: OpenCode CLI üzerinden `opencode run -m <model> "<prompt>"` ile, tek atımlık ajan görevleri (dosya okuma/yazma, shell, test koşturma araçları var). Prompt'lar şu an Türkçe yazılıyor.
Roldeki görevi: hakem (düşen testin mi kodun mu hatalı olduğunu sınıflar), yükseltme worker'ı ve holdout veri yazarı
Bizim gözlediğimiz hata kalıpları: testçi rolünde spec'le çelişen testler (8 setin 4'ü), 396 satırlık yapıştırılmış dosyada satır numarasını kaydırma

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
