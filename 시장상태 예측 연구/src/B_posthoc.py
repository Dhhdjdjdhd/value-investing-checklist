"""파트 B 사후 점검 (결과를 본 뒤 추가, 판정에는 쓰지 않음).

'-20% 도달' 사건은 이미 -20% 이하인 날에는 거의 자동으로 1 이다. 그런 날을 뺀 뒤에도 표가 기준 확률을 이기는지 본다.
실행: py -I src/B_posthoc.py -> results/B_posthoc.csv
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import B_macro as B  # noqa: E402

C = B.compute()
st, cuts = B.daily_states(C["g"], C["p"].p1)
o = B.outcomes(st)
X = pd.concat([st, o], axis=1)
X["_pos"] = np.arange(len(X))
we = pd.to_datetime(X.window_end)
X["sample"] = np.where(X.full & (we <= pd.Timestamp("1999-12-31")), "학습", np.where(X.full & (X.index >= "2000-01-03"), "검증", None))
Xf = X[X.full & X.vol.notna() & X.ma.notna()].copy()
rows = []
for sname in ["dd", "vol", "ma", "T3", "T4"]:
    for ev in ["hit20", "add10"]:
        pred, base, obs, level = B.predict_from_table(Xf, sname, ev)
        keep = (Xf.loc[obs.index, "dd"] != "4: -20이하").values
        tr = Xf[(Xf["sample"] == "학습") & (Xf.dd != "4: -20이하")]
        if sname == "T4":
            tr = tr[tr.index >= "1967-01-01"].dropna(subset=["r1"])
        base2 = tr[ev].mean()                       # -20% 이하 날을 뺀 학습 기준 확률
        e1, e0 = ((pred - obs) ** 2).values[keep], ((base2 - obs) ** 2).values[keep]
        rows.append({"spec": sname, "event": ev, "조건": "검증 구간 중 낙폭 -20% 이하인 날 제외", "n_days": int(keep.sum()),
                     "obs_freq": obs[keep].mean(), "base_train": base2, "Brier": e1.mean(), "Brier_base": e0.mean(),
                     "skill": 1 - e1.mean() / e0.mean(), "boot_P(Brier<base)": B.boot_brier(e1, e0), "AUC": B.auc(pred[keep], obs[keep])})
r = pd.DataFrame(rows)
r.to_csv(B.RES / "B_posthoc.csv", index=False, encoding="utf-8-sig")
pd.set_option("display.width", 250, "display.float_format", lambda x: f"{x:.4f}")
print(r.to_string(index=False))
