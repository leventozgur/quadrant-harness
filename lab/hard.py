"""Hard tier: 7 agentic tasks in small repos with hidden checkers.

Each task: FIX[tid](dir) builds the fixture, P[tid] is a six-block spec prompt,
CHECK[tid](dir) -> (score 0..1, ok bool, detail). REF[tid](dir) applies a reference
solution (only used to validate the checkers).
"""
import ast, hashlib, importlib.util, json, random, shutil, subprocess, sys, textwrap, threading, time
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent
FIX, P, CHECK, REF = {}, {}, {}, {}
SPEC_TAIL = "Bitirme: işin sonunda belirtilen komutu koştur ve sonucunu raporla.\nFormat: (1) değişen dosyalar, (2) koştuğun komutlar ve sonuçları, (3) en fazla 3 cümle açıklama. Yanıtların Türkçe olsun."


def w(p: Path, s: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(s).lstrip("\n"))


def sha(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def run_cases(cases):
    ok, notes = 0, []
    for label, fn in cases:
        try:
            r = fn()
            if r is True:
                ok += 1
            else:
                notes.append(f"{label}: {r}")
        except Exception as e:
            notes.append(f"{label}: {type(e).__name__}: {e}")
    return ok, len(cases), notes


def snapshot(d: Path, files):
    (d / "_pristine.json").write_text(json.dumps({f: sha(d / f) for f in files}))


def unchanged(d: Path):
    snap = json.loads((d / "_pristine.json").read_text())
    return [f for f, h in snap.items() if sha(d / f) != h]


def unittest_ok(d: Path):
    r = subprocess.run([sys.executable, "-m", "unittest", "-q"], cwd=d, capture_output=True, text=True, timeout=120)
    return r.returncode == 0


def raises(exc, fn):
    try:
        fn()
    except exc:
        return True
    except Exception as e:
        return f"expected {exc.__name__}, got {type(e).__name__}"
    return f"expected {exc.__name__}, no error"


def eq(a, b):
    return True if a == b else f"expected {b!r}, got {a!r}"


# ============================================================ h01 pricing
def fix_h01(d):
    w(d / "shop/__init__.py", "")
    w(d / "shop/models.py", '''
        from dataclasses import dataclass
        from decimal import Decimal


        @dataclass
        class Item:
            sku: str
            unit_price: Decimal
            qty: int
        ''')
    w(d / "shop/discounts.py", '''
        from decimal import Decimal

        BULK_THRESHOLD = 10
        BULK_RATE = Decimal("0.10")


        def bulk_discount(item):
            """Adet BULK_THRESHOLD veya üzerindeyse satır brüt tutarının %10'u kadar indirim tutarını döndürür."""
            if item.qty > BULK_THRESHOLD:
                return item.unit_price * item.qty * BULK_RATE
            return Decimal("0")
        ''')
    w(d / "shop/pricing.py", '''
        from decimal import Decimal, ROUND_HALF_UP

        from .discounts import bulk_discount

        CENT = Decimal("0.01")


        def line_total(item):
            """Satır tutarı = brüt - toplu indirim, kuruşa yuvarlanmış (ROUND_HALF_UP)."""
            gross = item.unit_price * item.qty
            disc = bulk_discount(item)
            return (gross - disc - disc).quantize(CENT, rounding=ROUND_HALF_UP)


        def order_total(items, coupon=None):
            """Satırların toplamı; 'SAVE5' kuponu toplam 100 veya üzerindeyse 5 düşer."""
            total = sum((line_total(i) for i in items), Decimal("0"))
            if coupon == "SAVE5" and total > Decimal("100"):
                total -= Decimal("5")
            return total.quantize(CENT, rounding=ROUND_HALF_UP)
        ''')
    w(d / "tests/__init__.py", "")
    w(d / "tests/test_pricing.py", '''
        import unittest
        from decimal import Decimal

        from shop.models import Item
        from shop.pricing import line_total, order_total


        class TestPricing(unittest.TestCase):
            def test_no_discount(self):
                self.assertEqual(line_total(Item("a", Decimal("2.50"), 3)), Decimal("7.50"))

            def test_bulk_discount_at_threshold(self):
                self.assertEqual(line_total(Item("a", Decimal("10"), 10)), Decimal("90.00"))


        if __name__ == "__main__":
            unittest.main()
        ''')
    snapshot(d, ["tests/test_pricing.py", "shop/models.py"])


P["h01"] = """Görev: tests/test_pricing.py içindeki test_bulk_discount_at_threshold testi başarısız. Hatanın kök nedenini bul ve düzelt. Kodda docstring'lerde yazan davranışla çelişen başka hatalar varsa onları da düzelt.
Bağlam: Python paketi shop/ (models.py, discounts.py, pricing.py). Docstring'ler doğru iş kuralını anlatır.
Kapsam: yalnızca shop/discounts.py ve shop/pricing.py değiştirilebilir. tests/ ve shop/models.py DOKUNMA.
Kısıtlar: Python 3.12, harici kütüphane yok, fonksiyon imzaları korunacak, Decimal kullanımı korunacak.
""" + SPEC_TAIL.replace("belirtilen komutu", "`python3 -m unittest -q` komutunu")


def chk_h01(d):
    sys.path.insert(0, str(d))
    for m in [k for k in sys.modules if k == "shop" or k.startswith("shop.")]:
        del sys.modules[m]
    try:
        from decimal import Decimal as D
        import shop.models as M, shop.pricing as PR  # noqa
        I = M.Item
        cases = [
            ("thr10", lambda: eq(PR.line_total(I("a", D("10"), 10)), D("90.00"))),
            ("qty9", lambda: eq(PR.line_total(I("a", D("10"), 9)), D("90.00"))),
            ("qty12", lambda: eq(PR.line_total(I("a", D("2.50"), 12)), D("27.00"))),
            ("round_half_up", lambda: eq(PR.line_total(I("a", D("0.335"), 1)), D("0.34"))),
            ("round_bulk", lambda: eq(PR.line_total(I("a", D("1.115"), 10)), D("10.04"))),
            ("round_half_up_even_diff", lambda: eq(PR.line_total(I("a", D("0.345"), 1)), D("0.35"))),
            ("coupon_at_100", lambda: eq(PR.order_total([I("a", D("50"), 2)], "SAVE5"), D("95.00"))),
            ("coupon_below", lambda: eq(PR.order_total([I("a", D("99.99"), 1)], "SAVE5"), D("99.99"))),
            ("no_coupon", lambda: eq(PR.order_total([I("a", D("50"), 2)]), D("100.00"))),
            ("mixed", lambda: eq(PR.order_total([I("a", D("10"), 10), I("b", D("5"), 2)], "SAVE5"), D("95.00"))),
            ("empty", lambda: eq(PR.order_total([]), D("0.00"))),
        ]
        ok, n, notes = run_cases(cases)
    finally:
        sys.path.remove(str(d))
    ch = unchanged(d)
    return ok / n, ok == n and not ch, f"{ok}/{n} changed_protected={ch} " + "; ".join(notes)


def ref_h01(d):
    p = d / "shop/discounts.py"; p.write_text(p.read_text().replace("item.qty > BULK", "item.qty >= BULK"))
    p = d / "shop/pricing.py"
    p.write_text(p.read_text().replace("gross - disc - disc", "gross - disc").replace('total > Decimal("100")', 'total >= Decimal("100")'))


FIX["h01"], CHECK["h01"], REF["h01"] = fix_h01, chk_h01, ref_h01


# ============================================================ h02 csv formatter
def fix_h02(d):
    w(d / "report/__init__.py", "")
    w(d / "report/formatters.py", '''
        import json

        FORMATTERS = {}


        def register(name):
            def deco(fn):
                FORMATTERS[name] = fn
                return fn
            return deco


        @register("table")
        def as_table(rows, columns):
            widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in columns}
            lines = [" | ".join(c.ljust(widths[c]) for c in columns)]
            for r in rows:
                lines.append(" | ".join(str(r.get(c, "")).ljust(widths[c]) for c in columns))
            return "\\n".join(lines)


        @register("json")
        def as_json(rows, columns):
            return json.dumps([{c: r.get(c) for c in columns} for r in rows], ensure_ascii=False)
        ''')
    w(d / "report/cli.py", '''
        import argparse
        import json
        from pathlib import Path

        from .formatters import FORMATTERS

        COLUMNS = ["region", "product", "qty", "note"]


        def main(argv=None):
            ap = argparse.ArgumentParser()
            ap.add_argument("--format", choices=sorted(FORMATTERS), default="table")
            ap.add_argument("--data", default=str(Path(__file__).with_name("sales.json")))
            args = ap.parse_args(argv)
            rows = json.loads(Path(args.data).read_text(encoding="utf-8"))
            print(FORMATTERS[args.format](rows, COLUMNS))


        if __name__ == "__main__":
            main()
        ''')
    (d / "report/sales.json").write_text(json.dumps([
        {"region": "Marmara", "product": "Vida, M4", "qty": 120, "note": None},
        {"region": "Ege", "product": "Somun", "qty": 0, "note": 'müşteri "acil" dedi'},
        {"region": "İç Anadolu", "product": "Pul", "qty": 7, "note": "iki\nsatır"},
    ], ensure_ascii=False))
    snapshot(d, ["report/cli.py", "report/sales.json"])


P["h02"] = """Görev: report paketine "csv" çıktı biçimi ekle; `python3 -m report.cli --format csv` çalışmalı.
Bağlam: report/formatters.py içinde register(...) dekoratörüyle kayıtlı biçimlendiriciler var; cli.py seçenekleri FORMATTERS'tan okur. Biçimlendirici imzası: fn(rows: list[dict], columns: list[str]) -> str.
Kurallar: ilk satır başlık (columns sırasıyla). Ayraç virgül, satır sonu "\\n", sonda satır sonu yok. Değer None ise boş alan; diğerleri str(değer). Alan virgül, çift tırnak veya satır sonu içeriyorsa alanı çift tırnağa al ve içteki her çift tırnağı iki çift tırnak yap; diğer alanları tırnaklama.
Kapsam: yalnızca report/formatters.py değiştirilebilir. report/cli.py ve report/sales.json DOKUNMA.
Kısıtlar: Python 3.12, standart kütüphanedeki csv modülünü kullanma, mevcut biçimler aynen çalışmaya devam etmeli.
""" + SPEC_TAIL.replace("belirtilen komutu", "`python3 -m report.cli --format csv` komutunu")

H02_EXPECTED = ('region,product,qty,note\nMarmara,"Vida, M4",120,\nEge,Somun,0,"müşteri ""acil"" dedi"\n'
                'İç Anadolu,Pul,7,"iki\nsatır"')


def chk_h02(d):
    r = subprocess.run([sys.executable, "-m", "report.cli", "--format", "csv"], cwd=d, capture_output=True, text=True, timeout=60)
    out = r.stdout[:-1] if r.stdout.endswith("\n") else r.stdout
    sys.path.insert(0, str(d))
    for m in [k for k in sys.modules if k == "report" or k.startswith("report.")]:
        del sys.modules[m]
    try:
        import report.formatters as F
        f = F.FORMATTERS.get("csv")
        cases = [
            ("cli_exact", lambda: eq(out, H02_EXPECTED)),
            ("plain", lambda: eq(f([{"a": 1, "b": "x"}], ["a", "b"]), "a,b\n1,x")),
            ("missing_key_none", lambda: eq(f([{"a": None}], ["a", "b"]), "a,b\n,")),
            ("only_quote", lambda: eq(f([{"a": '"'}], ["a"]), 'a\n""""')),
            ("no_quote_space", lambda: eq(f([{"a": " x "}], ["a"]), "a\n x ")),
            ("header_quoted", lambda: eq(f([], ["a,b"]), '"a,b"')),
            ("table_still", lambda: eq(F.FORMATTERS["table"]([{"a": 1}], ["a"]), "a\n1")),
            ("json_still", lambda: eq(F.FORMATTERS["json"]([{"a": 1}], ["a"]), '[{"a": 1}]')),
        ]
        ok, n, notes = run_cases(cases) if f else (0, 8, ["no csv formatter"])
        src = (d / "report/formatters.py").read_text()
        uses_csv = any(isinstance(x, (ast.Import, ast.ImportFrom)) and "csv" in ast.dump(x) for x in ast.walk(ast.parse(src)))
    finally:
        sys.path.remove(str(d))
    ch = unchanged(d)
    return ok / n, ok == n and not ch and not uses_csv, f"{ok}/{n} changed_protected={ch} uses_csv_module={uses_csv} " + "; ".join(notes)


def ref_h02(d):
    p = d / "report/formatters.py"
    p.write_text(p.read_text() + '''

def _csv_field(v):
    s = "" if v is None else str(v)
    if any(ch in s for ch in ',"\\n'):
        s = '"' + s.replace('"', '""') + '"'
    return s


@register("csv")
def as_csv(rows, columns):
    lines = [",".join(_csv_field(c) for c in columns)]
    for r in rows:
        lines.append(",".join(_csv_field(r.get(c)) for c in columns))
    return "\\n".join(lines)
''')


FIX["h02"], CHECK["h02"], REF["h02"] = fix_h02, chk_h02, ref_h02


# ============================================================ h03 business days
def fix_h03(d):
    w(d / "README.md", "# workdays\n")


P["h03"] = """Görev: bu klasörde workdays.py dosyası oluştur ve içinde `business_days_between(start: date, end: date, holidays: set[date] | None = None) -> int` fonksiyonunu yaz.
Kurallar: [start, end) yarı-açık aralığındaki iş günlerini say (start dahil, end hariç). Cumartesi ve pazar iş günü değildir. holidays içindeki tarihler iş günü değildir; hafta sonuna denk gelen tatil ek bir etki yapmaz. start == end ise 0. end < start ise sonuç -business_days_between(end, start, holidays). holidays None ise boş küme say. start veya end date değilse (datetime dahil) TypeError fırlat.
Bağlam: datetime.date kullan; date.weekday() pazartesi=0 ... pazar=6.
Kapsam: yalnızca workdays.py oluştur; isteğe bağlı olarak tests/ altına test ekleyebilirsin. README.md DOKUNMA.
Kısıtlar: Python 3.12, harici kütüphane yok. 10 yıllık aralıklar için de 1 saniyenin altında çalışmalı.
""" + SPEC_TAIL.replace("belirtilen komutu", "kendi yazdığın testleri")


def chk_h03(d):
    p = d / "workdays.py"
    if not p.exists():
        return 0, False, "no workdays.py"
    from datetime import datetime
    m = load(p, f"workdays_{abs(hash(str(d)))}")
    f = m.business_days_between
    D = date
    hol = {D(2026, 11, 18), D(2026, 11, 21)}  # Wed, Sat

    def perf():
        t = time.time(); f(D(2016, 1, 1), D(2026, 1, 1), set()); return True if time.time() - t < 1 else "slow"

    def brute(a, b, h):
        if b < a:
            return -brute(b, a, h)
        n, x = 0, a
        while x < b:
            n += x.weekday() < 5 and x not in h; x += timedelta(1)
        return n

    def fuzz():
        rnd = random.Random(7)
        for _ in range(300):
            a = D(2025, 1, 1) + timedelta(rnd.randint(0, 800)); b = a + timedelta(rnd.randint(-40, 40))
            h = {a + timedelta(rnd.randint(-40, 40)) for _ in range(rnd.randint(0, 5))}
            if f(a, b, h) != brute(a, b, h):
                return f"mismatch {a} {b} {sorted(h)}"
        return True

    cases = [
        ("same_day", lambda: eq(f(D(2026, 11, 16), D(2026, 11, 16)), 0)),
        ("mon_to_mon", lambda: eq(f(D(2026, 11, 16), D(2026, 11, 23)), 5)),
        ("fri_to_mon", lambda: eq(f(D(2026, 11, 20), D(2026, 11, 23)), 1)),
        ("sat_to_sun", lambda: eq(f(D(2026, 11, 21), D(2026, 11, 22)), 0)),
        ("holiday_wed", lambda: eq(f(D(2026, 11, 16), D(2026, 11, 23), hol), 4)),
        ("negative", lambda: eq(f(D(2026, 11, 23), D(2026, 11, 16), hol), -4)),
        ("none_holidays", lambda: eq(f(D(2026, 11, 16), D(2026, 11, 17), None), 1)),
        ("datetime_type", lambda: raises(TypeError, lambda: f(datetime(2026, 11, 16), D(2026, 11, 17)))),
        ("str_type", lambda: raises(TypeError, lambda: f("2026-11-16", D(2026, 11, 17)))),
        ("perf_10y", perf),
        ("fuzz_300", fuzz),
    ]
    ok, n, notes = run_cases(cases)
    ch = unchanged(d)
    return ok / n, ok == n and not ch, f"{ok}/{n} changed_protected={ch} " + "; ".join(notes)


def fix_h03b(d):
    fix_h03(d); snapshot(d, ["README.md"])


def ref_h03(d):
    w(d / "workdays.py", '''
        from datetime import date, datetime, timedelta


        def business_days_between(start, end, holidays=None):
            for v in (start, end):
                if not isinstance(v, date) or isinstance(v, datetime):
                    raise TypeError("date bekleniyor")
            if end < start:
                return -business_days_between(end, start, holidays)
            holidays = holidays or set()
            days = (end - start).days
            weeks, rest = divmod(days, 7)
            n = weeks * 5
            for i in range(rest):
                if (start + timedelta(weeks * 7 + i)).weekday() < 5:
                    n += 1
            n -= sum(1 for h in holidays if start <= h < end and h.weekday() < 5)
            return n
        ''')


FIX["h03"], CHECK["h03"], REF["h03"] = fix_h03b, chk_h03, ref_h03


# ============================================================ h04 refactor
LEGACY = '''
import re


def normalize_phone(raw):
    if raw is None:
        raise TypeError("raw None olamaz")
    s = str(raw).strip()
    ext = None
    low = s.lower()
    if "dahili" in low:
        idx = low.index("dahili")
        tail = s[idx + 6:].strip()
        s = s[:idx].strip()
        if tail.isdigit() and 1 <= len(tail) <= 4:
            ext = tail
        else:
            return None
    cleaned = ""
    for ch in s:
        if ch in " -().":
            continue
        cleaned += ch
    if cleaned.startswith("+90"):
        cleaned = cleaned[3:]
    elif cleaned.startswith("0090"):
        cleaned = cleaned[4:]
    elif cleaned.startswith("90") and len(cleaned) == 12:
        cleaned = cleaned[2:]
    elif cleaned.startswith("0"):
        cleaned = cleaned[1:]
    if not cleaned.isdigit():
        return None
    if len(cleaned) != 10:
        return None
    first = cleaned[0]
    if first == "5":
        out = "+90 " + cleaned[0:3] + " " + cleaned[3:6] + " " + cleaned[6:8] + " " + cleaned[8:10]
    elif first in "234":
        if cleaned[1] == "0":
            return None
        out = "+90 (" + cleaned[0:3] + ") " + cleaned[3:6] + " " + cleaned[6:8] + " " + cleaned[8:10]
    else:
        return None
    if ext is not None:
        out = out + " #" + ext
    return out
'''


def fix_h04(d):
    w(d / "legacy.py", LEGACY)
    w(d / "tests/__init__.py", "")
    w(d / "tests/test_legacy.py", '''
        import unittest

        from legacy import normalize_phone


        class T(unittest.TestCase):
            def test_mobile(self):
                self.assertEqual(normalize_phone("0532 123 45 67"), "+90 532 123 45 67")

            def test_landline_ext(self):
                self.assertEqual(normalize_phone("(0212) 555-12-34 dahili 12"), "+90 (212) 555 12 34 #12")


        if __name__ == "__main__":
            unittest.main()
        ''')
    snapshot(d, ["tests/test_legacy.py"])


P["h04"] = """Görev: legacy.py içindeki normalize_phone fonksiyonunu okunabilir küçük fonksiyonlara böl (refactor). Davranış birebir aynı kalmalı: aynı girdi için aynı dönüş değeri (None dahil) ve aynı exception türü.
Bağlam: normalize_phone dış dünyanın kullandığı tek public fonksiyondur; adı ve imzası korunacak. Mevcut testler tests/test_legacy.py içinde.
Kapsam: yalnızca legacy.py değiştirilebilir. tests/ DOKUNMA.
Kısıtlar: Python 3.12, harici kütüphane yok. legacy.py içindeki hiçbir fonksiyon 25 satırı (def satırı dahil) geçmemeli. Yeni davranış ekleme, hata "düzeltme"; tuhaf görünen kurallar da korunacak.
""" + SPEC_TAIL.replace("belirtilen komutu", "`python3 -m unittest -q` komutunu")


def gen_inputs():
    rnd = random.Random(11)
    base = ["0532 123 45 67", "+90 532 1234567", "00905321234567", "905321234567", "5321234567", "(0212) 555-12-34",
            "0212.555.12.34 dahili 12", "0212 555 12 34 DAHİLİ 3", "0312 555 12 34 dahili", "0312 555 12 34 dahili 12345",
            "0200 555 12 34", "0612 555 12 34", "abc", "", "   ", "+90", "05321234567x", 5321234567, "0532-123-45-67 dahili 0007",
            "+905321234567dahili9", "9053212345", "0 5 3 2 1 2 3 4 5 6 7"]
    chars = "0123456789 +-().dahiliDAHILI"
    for _ in range(2500):
        k = rnd.random()
        if k < 0.5:
            pre = rnd.choice(["", "0", "+90", "0090", "90", "+9"])
            body = rnd.choice("2345 6") + "".join(rnd.choice("0123456789") for _ in range(rnd.choice([8, 9, 10])))
            sep = "".join(rnd.choice(" -.()") if rnd.random() < 0.2 else "" for _ in range(3))
            s = pre + sep + body
            if rnd.random() < 0.3:
                s += rnd.choice([" dahili ", "dahili", " Dahili "]) + "".join(rnd.choice("0123456789a") for _ in range(rnd.randint(0, 5)))
            base.append(s)
        else:
            base.append("".join(rnd.choice(chars) for _ in range(rnd.randint(0, 20))))
    return base


def chk_h04(d):
    ref_ns = {}
    exec(LEGACY, ref_ns)
    ref = ref_ns["normalize_phone"]
    p = d / "legacy.py"
    m = load(p, f"legacy_{abs(hash(str(d)))}")
    f = getattr(m, "normalize_phone", None)
    if f is None:
        return 0, False, "normalize_phone missing"
    inputs = gen_inputs() + [None]
    mism = []
    for x in inputs:
        def call(fn):
            try:
                return ("ok", fn(x))
            except Exception as e:
                return ("exc", type(e).__name__)
        a, b = call(ref), call(f)
        if a != b:
            mism.append((x, a, b))
    tree = ast.parse(p.read_text())
    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    longest = max((n.end_lineno - n.lineno + 1 for n in funcs), default=0)
    split = len(funcs) >= 3
    behave = 1 - len(mism) / len(inputs)
    ch = unchanged(d)
    ok = not mism and longest <= 25 and split and not ch
    return (behave if (longest <= 25 and split) else behave * 0.5), ok, (
        f"mismatches={len(mism)}/{len(inputs)} longest_fn={longest} n_funcs={len(funcs)} changed_protected={ch} "
        + (f"first={mism[0]!r}" if mism else ""))


def ref_h04(d):
    w(d / "legacy.py", '''
        def _split_ext(s):
            low = s.lower()
            if "dahili" not in low:
                return s, None, True
            idx = low.index("dahili")
            tail = s[idx + 6:].strip()
            if tail.isdigit() and 1 <= len(tail) <= 4:
                return s[:idx].strip(), tail, True
            return s, None, False


        def _clean(s):
            return "".join(ch for ch in s if ch not in " -().")


        def _strip_prefix(c):
            if c.startswith("+90"):
                return c[3:]
            if c.startswith("0090"):
                return c[4:]
            if c.startswith("90") and len(c) == 12:
                return c[2:]
            if c.startswith("0"):
                return c[1:]
            return c


        def _format(c):
            tail = c[3:6] + " " + c[6:8] + " " + c[8:10]
            if c[0] == "5":
                return "+90 " + c[0:3] + " " + tail
            if c[0] in "234" and c[1] != "0":
                return "+90 (" + c[0:3] + ") " + tail
            return None


        def normalize_phone(raw):
            if raw is None:
                raise TypeError("raw None olamaz")
            s, ext, valid = _split_ext(str(raw).strip())
            if not valid:
                return None
            c = _strip_prefix(_clean(s))
            if not c.isdigit() or len(c) != 10:
                return None
            out = _format(c)
            if out is not None and ext is not None:
                out += " #" + ext
            return out
        ''')


FIX["h04"], CHECK["h04"], REF["h04"] = fix_h04, chk_h04, ref_h04


# ============================================================ h05 debug LRU
def fix_h05(d):
    w(d / "cache.py", '''
        from collections import OrderedDict


        class LRUCache:
            """En son kullanılanı tutan önbellek. get ve put bir anahtarı 'en yeni' yapar.
            Kapasite aşılınca en eski kullanılan anahtar atılır. capacity 0 ise hiçbir şey saklanmaz;
            negatif capacity ValueError verir. get bulamazsa default döner."""

            def __init__(self, capacity):
                if capacity < 0:
                    raise ValueError("capacity negatif olamaz")
                self.capacity = capacity
                self._data = OrderedDict()

            def get(self, key, default=None):
                if key in self._data:
                    return self._data[key]
                return default

            def put(self, key, value):
                if self.capacity == 0:
                    return
                self._data[key] = value
                if len(self._data) > self.capacity:
                    self._data.popitem()

            def __len__(self):
                return len(self._data)
        ''')
    w(d / "tests/__init__.py", "")
    w(d / "tests/test_cache.py", '''
        import unittest

        from cache import LRUCache


        class T(unittest.TestCase):
            def test_basic(self):
                c = LRUCache(2)
                c.put("a", 1)
                self.assertEqual(c.get("a"), 1)

            def test_eviction_order(self):
                c = LRUCache(2)
                c.put("a", 1)
                c.put("b", 2)
                c.get("a")
                c.put("c", 3)
                self.assertEqual(c.get("b"), None)
                self.assertEqual(c.get("a"), 1)
                self.assertEqual(c.get("c"), 3)


        if __name__ == "__main__":
            unittest.main()
        ''')
    snapshot(d, ["tests/test_cache.py"])


P["h05"] = """Görev: aşağıdaki hata raporunu incele, kök nedeni bul ve düzelt.
Hata raporu:
```
FAIL: test_eviction_order (tests.test_cache.T.test_eviction_order)
Traceback (most recent call last):
  File "tests/test_cache.py", line 18, in test_eviction_order
    self.assertEqual(c.get("b"), None)
AssertionError: 2 != None
```
Bağlam: cache.py içindeki LRUCache; sınıf docstring'i doğru davranışı anlatır.
Kapsam: yalnızca cache.py değiştirilebilir. tests/ DOKUNMA.
Kısıtlar: Python 3.12, harici kütüphane yok, public API (get, put, __len__, capacity) korunacak. Docstring ile çelişen başka hata varsa onu da düzelt.
""" + SPEC_TAIL.replace("belirtilen komutu", "`python3 -m unittest -q` komutunu")


def chk_h05(d):
    m = load(d / "cache.py", f"cache_{abs(hash(str(d)))}")
    C = m.LRUCache

    def seq1():
        c = C(2); c.put("a", 1); c.put("b", 2); c.get("a"); c.put("c", 3)
        return eq((c.get("b"), c.get("a"), c.get("c")), (None, 1, 3))

    def seq_update_refreshes():
        c = C(2); c.put("a", 1); c.put("b", 2); c.put("a", 10); c.put("c", 3)
        return eq((c.get("b"), c.get("a"), len(c)), (None, 10, 2))

    def seq_miss_no_refresh():
        c = C(2); c.put("a", 1); c.put("b", 2); c.get("zzz"); c.put("c", 3)
        return eq((c.get("a"), c.get("b")), (None, 2))

    def cap0():
        c = C(0); c.put("a", 1); return eq((c.get("a"), len(c)), (None, 0))

    def cap1():
        c = C(1); c.put("a", 1); c.put("b", 2); return eq((c.get("a"), c.get("b")), (None, 2))

    def default():
        c = C(1); return eq(c.get("x", 42), 42)

    def falsy_value():
        c = C(2); c.put("a", 0); c.put("b", None); c.get("a"); c.put("c", 1)
        return eq((c.get("a", "D"), c.get("b", "D")), (0, "D"))

    def model_check():
        rnd = random.Random(3)
        for cap in [1, 2, 3, 5]:
            c = C(cap); ref = []  # list of (k, v), last = newest
            for _ in range(400):
                k = rnd.randint(0, 6)
                if rnd.random() < 0.5:
                    v = rnd.randint(0, 99); c.put(k, v)
                    ref = [p for p in ref if p[0] != k] + [(k, v)]
                    if len(ref) > cap:
                        ref.pop(0)
                else:
                    got = c.get(k)
                    hit = [p for p in ref if p[0] == k]
                    exp = hit[0][1] if hit else None
                    if hit:
                        ref = [p for p in ref if p[0] != k] + hit
                    if got != exp:
                        return f"cap={cap} key={k} got={got} exp={exp}"
        return True

    cases = [("seq1", seq1), ("update_refreshes", seq_update_refreshes), ("miss_no_refresh", seq_miss_no_refresh),
             ("cap0", cap0), ("cap1", cap1), ("default", default), ("falsy_value", falsy_value),
             ("neg_cap", lambda: raises(ValueError, lambda: C(-1))), ("model_check", model_check)]
    ok, n, notes = run_cases(cases)
    ch = unchanged(d)
    return ok / n, ok == n and not ch, f"{ok}/{n} changed_protected={ch} " + "; ".join(notes)


def ref_h05(d):
    p = d / "cache.py"
    s = p.read_text()
    s = s.replace("            return self._data[key]\n", "            self._data.move_to_end(key)\n            return self._data[key]\n")
    s = s.replace("        self._data[key] = value\n", "        self._data[key] = value\n        self._data.move_to_end(key)\n")
    s = s.replace("self._data.popitem()", "self._data.popitem(last=False)")
    p.write_text(s)


FIX["h05"], CHECK["h05"], REF["h05"] = fix_h05, chk_h05, ref_h05


# ============================================================ h06 token bucket
def fix_h06(d):
    w(d / "README.md", "# ratelimit\n")
    snapshot(d, ["README.md"])


P["h06"] = """Görev: bu klasörde ratelimit.py oluştur ve içinde `TokenBucket` sınıfını yaz.
Arayüz: TokenBucket(capacity: float, refill_per_sec: float, clock=time.monotonic); allow(n: float = 1.0) -> bool; tokens özelliği (property) o anki token sayısını (yenileme uygulanmış) döndürür.
Kurallar: kova dolu başlar (tokens == capacity). Her allow çağrısında önce clock() ile geçen süre kadar token eklenir: tokens = min(capacity, tokens + geçen_süre * refill_per_sec). tokens >= n ise n düşülür ve True döner; değilse hiçbir şey düşülmez ve False döner. n > capacity ise her zaman False. n <= 0 ise ValueError. capacity <= 0 veya refill_per_sec < 0 ise kurucu ValueError fırlatır. clock geriye giderse (önceki değerden küçük dönerse) geçen süre 0 sayılır.
Eşzamanlılık: allow ve tokens çoklu thread'den aynı anda çağrılabilir; hiçbir koşulda kapasiteden fazla token tüketilmemeli (thread-safe olmalı).
Kapsam: yalnızca ratelimit.py oluştur; isteğe bağlı tests/ altına test ekleyebilirsin. README.md DOKUNMA.
Kısıtlar: Python 3.12, yalnızca standart kütüphane.
""" + SPEC_TAIL.replace("belirtilen komutu", "kendi yazdığın testleri")


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def chk_h06(d):
    p = d / "ratelimit.py"
    if not p.exists():
        return 0, False, "no ratelimit.py"
    m = load(p, f"ratelimit_{abs(hash(str(d)))}")
    TB = m.TokenBucket

    def basic():
        c = FakeClock(); b = TB(3, 1, clock=c)
        r = [b.allow() for _ in range(4)]
        return eq(r, [True, True, True, False])

    def refill():
        c = FakeClock(); b = TB(2, 0.5, clock=c); b.allow(); b.allow(); c.t = 1.0
        a = b.allow(); c.t = 2.0; bb = b.allow()
        return eq((a, bb), (False, True))

    def cap_limit():
        c = FakeClock(); b = TB(2, 10, clock=c); c.t = 100
        return eq(round(b.tokens, 6), 2)

    def fractional():
        c = FakeClock(); b = TB(1, 1, clock=c); b.allow(); c.t = 0.5
        a = b.allow(0.5); bb = b.allow(0.01)
        return eq((a, bb), (True, False))

    def no_consume_on_fail():
        c = FakeClock(); b = TB(5, 0, clock=c); b.allow(4)
        a = b.allow(2); bb = b.allow(1)
        return eq((a, bb), (False, True))

    def over_capacity():
        c = FakeClock(); b = TB(5, 1, clock=c); return eq(b.allow(6), False)

    def clock_backwards():
        c = FakeClock(); c.t = 10; b = TB(2, 1, clock=c); b.allow(2); c.t = 5
        a = b.allow()
        return eq((a, b.tokens >= 0), (False, True))

    def errors():
        for fn in [lambda: TB(0, 1), lambda: TB(-1, 1), lambda: TB(1, -0.1), lambda: TB(1, 1).allow(0), lambda: TB(1, 1).allow(-1)]:
            r = raises(ValueError, fn)
            if r is not True:
                return r
        return True

    def threads():
        # Force frequent thread switches so an unlocked check-then-consume races visibly.
        old = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        try:
            for trial in range(10):
                b = TB(500, 0, clock=lambda: 0.0)
                results = []
                lock = threading.Lock()

                def worker():
                    local = [b.allow() for _ in range(100)]
                    with lock:
                        results.extend(local)
                ts = [threading.Thread(target=worker) for _ in range(32)]
                [t.start() for t in ts]; [t.join() for t in ts]
                if sum(results) != 500:
                    return f"trial {trial}: {sum(results)} allowed, expected 500"
        finally:
            sys.setswitchinterval(old)
        return True

    cases = [("basic", basic), ("refill", refill), ("cap_limit", cap_limit), ("fractional", fractional),
             ("no_consume_on_fail", no_consume_on_fail), ("over_capacity", over_capacity),
             ("clock_backwards", clock_backwards), ("errors", errors), ("threads_x10", threads)]
    ok, n, notes = run_cases(cases)
    ch = unchanged(d)
    return ok / n, ok == n and not ch, f"{ok}/{n} changed_protected={ch} " + "; ".join(notes)


def all_true(fn, k):
    for _ in range(k):
        r = fn()
        if r is not True:
            return r
    return True


def ref_h06(d):
    w(d / "ratelimit.py", '''
        import threading
        import time


        class TokenBucket:
            def __init__(self, capacity, refill_per_sec, clock=time.monotonic):
                if capacity <= 0 or refill_per_sec < 0:
                    raise ValueError("geçersiz parametre")
                self.capacity = float(capacity)
                self.rate = float(refill_per_sec)
                self._clock = clock
                self._tokens = float(capacity)
                self._last = clock()
                self._lock = threading.Lock()

            def _refill(self):
                now = self._clock()
                elapsed = max(0.0, now - self._last)
                self._last = max(self._last, now)
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)

            @property
            def tokens(self):
                with self._lock:
                    self._refill()
                    return self._tokens

            def allow(self, n=1.0):
                if n <= 0:
                    raise ValueError("n pozitif olmalı")
                with self._lock:
                    self._refill()
                    if n > self.capacity or self._tokens < n:
                        return False
                    self._tokens -= n
                    return True
        ''')


FIX["h06"], CHECK["h06"], REF["h06"] = fix_h06, chk_h06, ref_h06


# ============================================================ h07 csv line parser
def fix_h07(d):
    w(d / "README.md", "# csvline\n")
    snapshot(d, ["README.md"])


P["h07"] = """Görev: bu klasörde csvline.py oluştur ve içinde `split_csv_line(line: str) -> list[str]` fonksiyonunu yaz.
Kurallar (tek satır, RFC 4180 benzeri): alanlar virgülle ayrılır. Bir alan çift tırnakla başlıyorsa tırnaklı alandır: içindeki "" tek bir " olur, virgüller alanın parçasıdır, alan kapanış tırnağıyla biter ve kapanış tırnağından hemen sonra ya virgül ya da satır sonu gelmelidir, aksi halde ValueError. Kapanmayan tırnak ValueError. Tırnaksız bir alanın içinde çift tırnak geçerse ValueError. Boşluklar korunur (trim yok). Boş string [""] döndürür. Sondaki virgül sonda boş bir alan üretir. Satır sonu karakterleri girdide yoktur.
Kapsam: yalnızca csvline.py oluştur; isteğe bağlı tests/ altına test ekleyebilirsin. README.md DOKUNMA.
Kısıtlar: Python 3.12; csv modülünü ve regex (re) kullanma; tek geçişte çalışan bir durum makinesi yaz.
""" + SPEC_TAIL.replace("belirtilen komutu", "kendi yazdığın testleri")


def chk_h07(d):
    p = d / "csvline.py"
    if not p.exists():
        return 0, False, "no csvline.py"
    m = load(p, f"csvline_{abs(hash(str(d)))}")
    f = m.split_csv_line
    cases = [
        ("simple", lambda: eq(f("a,b,c"), ["a", "b", "c"])),
        ("empty", lambda: eq(f(""), [""])),
        ("trailing", lambda: eq(f("a,"), ["a", ""])),
        ("leading", lambda: eq(f(",a"), ["", "a"])),
        ("quoted_comma", lambda: eq(f('"a,b",c'), ["a,b", "c"])),
        ("escaped", lambda: eq(f('"say ""hi""",x'), ['say "hi"', "x"])),
        ("empty_quoted", lambda: eq(f('"",""'), ["", ""])),
        ("spaces", lambda: eq(f(" a , b "), [" a ", " b "])),
        ("only_quotes_pair", lambda: eq(f('""""'), ['"'])),
        ("unterminated", lambda: raises(ValueError, lambda: f('"abc'))),
        ("after_close", lambda: raises(ValueError, lambda: f('"a"b,c'))),
        ("quote_in_unquoted", lambda: raises(ValueError, lambda: f('a"b,c'))),
        ("space_before_quote", lambda: raises(ValueError, lambda: f(' "a",b'))),
        ("unicode", lambda: eq(f('ğ,"ş,ı"'), ["ğ", "ş,ı"])),
    ]
    ok, n, notes = run_cases(cases)
    src = p.read_text()
    bad_import = any(isinstance(x, (ast.Import, ast.ImportFrom)) and any(k in ast.dump(x) for k in ("'csv'", "'re'"))
                     for x in ast.walk(ast.parse(src)))
    ch = unchanged(d)
    return ok / n, ok == n and not ch and not bad_import, f"{ok}/{n} forbidden_import={bad_import} changed_protected={ch} " + "; ".join(notes)


def ref_h07(d):
    w(d / "csvline.py", '''
        def split_csv_line(line):
            fields, cur, i, n = [], [], 0, len(line)
            while True:
                cur = []
                if i < n and line[i] == '"':
                    i += 1
                    while True:
                        if i >= n:
                            raise ValueError("kapanmayan tırnak")
                        ch = line[i]
                        if ch == '"':
                            if i + 1 < n and line[i + 1] == '"':
                                cur.append('"'); i += 2; continue
                            i += 1
                            break
                        cur.append(ch); i += 1
                    if i < n and line[i] != ",":
                        raise ValueError("tırnak sonrası beklenmeyen karakter")
                else:
                    while i < n and line[i] != ",":
                        if line[i] == '"':
                            raise ValueError("tırnaksız alanda tırnak")
                        cur.append(line[i]); i += 1
                fields.append("".join(cur))
                if i >= n:
                    return fields
                i += 1
        ''')


FIX["h07"], CHECK["h07"], REF["h07"] = fix_h07, chk_h07, ref_h07

HARD = ["h01", "h02", "h03", "h04", "h05", "h06", "h07"]
