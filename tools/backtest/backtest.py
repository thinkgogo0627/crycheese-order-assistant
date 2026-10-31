import numpy as np, pandas as pd, time, functools
from common import *
import models as M

P = load_panel()
# 공휴일 계수 캐시
_hf = {}
orig_hf = M.holiday_factor
def hf(P_, L):
    if L not in _hf: _hf[L] = orig_hf(P_, L)
    return _hf[L]
M.holiday_factor = hf
_di = {}
orig_di = M.store_dow_index
def sdi(P_, L, d, weeks=8):
    key=(L,(d-L)%7,weeks)
    if key not in _di: _di[key]=orig_di(P_,L,d,weeks)
    return _di[key]
M.store_dow_index = sdi

def run(fn, K=(1,2,3,4), t0="2026-06-01", t1="2026-09-30"):
    i0 = DATES.get_loc(pd.Timestamp(t0)); i1 = DATES.get_loc(pd.Timestamp(t1))
    out = {}
    for k in K:
        pred = np.zeros_like(P["Y"])
        for d in range(i0, i1+1):
            pred[:,:,d] = fn(P, d-k, k) * P["A"][:,:,d]
        out[k] = pred
    return out

def score(pred, t0, t1, K=(1,2,3,4)):
    i0 = DATES.get_loc(pd.Timestamp(t0)); i1 = DATES.get_loc(pd.Timestamp(t1))+1
    Y, A, B = P["Y"], P["A"], P["B"]
    res = {}
    yi = np.einsum("smd,mi->sid", Y[:,:,i0:i1], B)
    em=ei=bi=0; sm=si=0
    for k in K:
        p = pred[k][:,:,i0:i1]; y = Y[:,:,i0:i1]
        em += np.abs(p-y).sum(); sm += y.sum()
        pi = np.einsum("smd,mi->sid", p, B)
        # 식자재마다 단위가 달라 식자재별 WAPE의 평균(매크로)으로
        ei_k = np.abs(pi-yi).sum((0,2)) / yi.sum((0,2)); ei += ei_k
        bi += ((pi-yi).sum((0,2))/yi.sum((0,2)))
    nk=len(K)
    return dict(menu_WAPE=round(100*em/sm,2), ing_WAPE=round(100*np.nanmean(ei/nk),2), ing_bias=round(100*np.nanmean(bi/nk),2))

if __name__ == "__main__":
    cands = {
        "MA7": M.ma(7), "MA14": M.ma(14), "MA28": M.ma(28),
        "DOW4": M.dow(4), "DOW8": M.dow(8),
        "Blend(MA7,DOW4)": M.blend(M.ma(7), M.dow(4)),
        "Blend(MA14,DOW8)": M.blend(M.ma(14), M.dow(8)),
        "Level28×요일": M.level_dow(28, 8, False),
        "Level28×요일×공휴일": M.level_dow(28, 8, True),
        "Level14×요일×공휴일": M.level_dow(14, 8, True),
        "EWMA.1×요일×공휴일": M.ewma_dow(0.1), "EWMA.2×요일×공휴일": M.ewma_dow(0.2), "EWMA.05×요일×공휴일": M.ewma_dow(0.05),
    }
    rows=[]; preds={}
    for name, fn in cands.items():
        t=time.time(); pr = run(fn); preds[name]=pr
        rows.append(dict(model=name, **{f"val_{k}":v for k,v in score(pr,"2026-06-01","2026-07-31").items()},
                         **{f"test_{k}":v for k,v in score(pr,"2026-08-01","2026-09-30").items()}, sec=round(time.time()-t,1)))
        print(rows[-1], flush=True)
    pd.DataFrame(rows).to_csv("classical.csv", index=False)
    np.save("preds_classical.npy", {k:v for k,v in preds.items()}, allow_pickle=True)
