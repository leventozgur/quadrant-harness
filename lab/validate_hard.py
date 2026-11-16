import shutil, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import hard as H
for t in H.HARD:
    for mode in ["pristine", "ref"]:
        d = Path(tempfile.mkdtemp(prefix=f"{t}_{mode}_"))
        H.FIX[t](d)
        if mode == "ref":
            H.REF[t](d)
        try:
            s, ok, det = H.CHECK[t](d)
        except Exception as e:
            s, ok, det = 0, False, f"CHECKER CRASH {e!r}"
        print(f"{t} {mode:8} score={s:.2f} ok={ok} {det[:160]}")
        shutil.rmtree(d)
