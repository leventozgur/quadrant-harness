# HX-52 ön kayıt — testçi ders dosyası (2026-11-26)

Ders kaynağı: hakem TEST_HATASI kayıtları (BrainAtlas, Mizan, CodartERP, quadrant-harness `.git/hx/*/test_issues.txt`; HX-46
korpusunun 16 işi HARİÇ, sızıntı olmasın diye). GLM-5.3-Flash#high (testçiden farklı aile) yalnız hakem gerekçelerinden aday ders
çıkardı (18 aday); en az 2 farklı işte görülen 12'si alındı (`templates/tester-lessons.md`, kaynaklı). Kol B şablonu
`lab/escapes/tester-hx52.md` = `templates/tester.md` + "Lessons" bölümü. Kol A = HX-44 A kolu (aynı gün, aynı model Qwen3.7 Plus#high,
aynı korpus ve tester lab; `quadrant-harness-results/hx44`).

Eşikler (önceden; KEEP için hepsi):
1. Korpusta temiz sürümde düşen (geçersiz) takım: B ≤ 6/16 (A = 9/16; kart: B ≤ A × 0.7).
2. Tester lab referansta geçen takım: B ≥ 12/14 (A = 13/14).
3. Geçerli takımlarda öldürülen mutant: B ≥ 46/56 (A = 49/56). Sapma: kart "B ≥ A" diyor; n = 14 takımdaki gürültü nedeniyle
   −%5 tolerans önceden konuldu.
Bilgi: korpus yakalama (A 1/16).
Aksi hâlde KILL. KEEP olursa dersler `templates/tester.md`'ye girer ve `tester-lessons.md` kaynak/budama kaydı olarak kalır.
