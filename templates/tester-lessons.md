# Tester lessons (HX-52)

Derived from judge TEST_HATASI records seen in at least 2 different tasks (BrainAtlas, Mizan, CodartERP, quadrant-harness;
HX-46 corpus tasks excluded). Each line keeps its source tasks. Max 15 lines; prune lines that stop recurring.

- Beklenen değerleri spec'in kurallarını (formül, hassasiyet, adım sırası, mevcut bileşenin gerçek davranışı) birebir uygulayarak hesapla; elle/sezgisel hesap ya da kendi varsayımlarınla üretme. (kaynak: BrainAtlas/BA-48, Mizan/YD-12b, Mizan/YD-13, Mizan/YD-16, Mizan/YD-18, Mizan/YD-28)
- Fixture'ın hedeflenen senaryoyu gerçekten tetiklediğini spec kurallarıyla doğrula; beklenen davranış için gereken önkoşulları (geçerli değerler, gerekli alanlar, uyuşan örnek veriler) sağlamadan oluşmasını bekleme. (kaynak: BrainAtlas/BA-53, Mizan/YD-12b, Mizan/YD-13, Mizan/YD-28, quadrant-harness/HX-45, quadrant-harness/HX-FIX1)
- Fixture'da dosya yazmadan önce üst dizinleri oluştur ve kurulum hatalarını ürün kodundan ayır. (kaynak: BrainAtlas/BA-48, quadrant-harness/HX-51)
- Test kurulumunu kodun gerçekten okuduğu/yazdığı yere ve yapıya bağla: mock kayıtlarını doğru dosyaya yaz, beklenen yolları testin kendi kurduğu ortamdan türet, değerleri spec'in gösterdiği kaynaktan al. (kaynak: BrainAtlas/BA-43, quadrant-harness/HX-51, quadrant-harness/HX-FIX1)
- SPEC'in tanımlamadığı veya garanti etmediği davranış ve biçimleri assertion'a konu etme (sıralama, tamamlanma zamanı, alan adları, serileştirme biçimi); yalnızca spec'te yazılı olanı doğrula. (kaynak: BrainAtlas/BA-31J, BrainAtlas/BA-43, BrainAtlas/BA-48, Mizan/YD-04, quadrant-harness/HX-44T, quadrant-harness/HX-45, quadrant-harness/HX-46)
- Eşleşme desenlerini ve beklentileri spec'in tanımlarıyla doğrula; tanımlara göre asla eşleşmeyecek ya da aykırı sonuç üretecek örüntüler kurma. (kaynak: BrainAtlas/BA-32, BrainAtlas/BA-47, quadrant-harness/HX-14, quadrant-harness/HX-46, quadrant-harness/HX-49)
- SPEC davranışı tanımlıyorsa birebir literal, değişken adı veya satır içi yazım zorlama; sabit kullanımını, yardımcı metot çağrısını ve eşdeğer sözdizimini (koşul yönü, operatör, girinti) kabul et. (kaynak: CodartERP_NetCore/P2-log, CodartERP_NetCore/P3-izlenebilirlik, CodartERP_NetCore/P4-hazirlik, CodartERP_NetCore/P5-stok-filtre, CodartERP_NetCore/P6-termin)
- Kaynak metinden kod parçası çıkarırken ilk eşleşmeyi kanıt sayma; sabit/yardımcı tanımları, birden çok geçen ifadeleri ve pencere sınırlarını hesaba kat. (kaynak: CodartERP_NetCore/P1-ui, CodartERP_NetCore/P3-izlenebilirlik, CodartERP_NetCore/P4-hazirlik, CodartERP_NetCore/P5-stok-filtre)
- Yol karşılaştırmalarında sembolik bağları çözümleyip kanonik yollarla eşleştir; alt sürecin getcwd davranışını varsayma. (kaynak: quadrant-harness/HX-44T, quadrant-harness/HX-45)
- Sahte betikler ve import yolları dahil tüm fixture bağımlılıklarını çalıştırmadan önce doğrula; kırık fixture ürün kodunu hiç test ettirmez. (kaynak: BrainAtlas/BA-36, quadrant-harness/HX-44T)
- Mock/enjeksiyonu ürün kodunun veya SDK'nın gerçekten kullandığı yapıya göre kur; iç alan adları ve isteğe bağlı alanların varlığı hakkında varsayım yapma. (kaynak: BrainAtlas/BA-32, BrainAtlas/BA-56)
- Uzunluk ve üç nokta iddialarını spec'in ölçüm tanımına göre kur; beklenen metni kendince yeniden kurarken ayraç/boş satır eklemelerini ölçüme dahil etme. (kaynak: BrainAtlas/BA-32, BrainAtlas/BA-47)
