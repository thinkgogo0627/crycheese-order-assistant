"""수요 예측 후보. 모든 함수는 (Y, A, L, k) -> 예측 [store, menu]: 마지막 관측일 L(인덱스), 목표일 L+k"""
import numpy as np
from common import *

def _avail_mean(Y, A, idx):
    idx = [i for i in idx if i >= 0]
    if not idx: return np.zeros(Y.shape[:2])
    y = Y[:,:,idx]; a = A[:,:,idx]
    n = a.sum(2); return np.where(n>0, (y*a).sum(2)/np.maximum(n,1), 0.0)

def ma(n):
    def f(P, L, k): return _avail_mean(P["Y"], P["A"], range(L-n+1, L+1))
    return f

def dow(w):
    def f(P, L, k):
        d = L + k
        return _avail_mean(P["Y"], P["A"], [d-7*j for j in range(1, w+8) if d-7*j <= L][:w])
    return f

def blend(f1, f2, a=0.5):
    def f(P, L, k): return a*f1(P,L,k) + (1-a)*f2(P,L,k)
    return f

def store_dow_index(P, L, d, weeks=8):
    """매장 전체 수요 기준 요일 지수 (최근 N주, 같은 요일 평균 / 전체 평균), 공휴일 제외"""
    Y = P["Y"].sum(1); hol = P["hol"]
    idx = [i for i in range(max(0, L-7*weeks+1), L+1) if not hol[i]]
    same = [i for i in idx if (i - d) % 7 == 0]
    if len(same) < 2: return np.ones(3)
    return Y[:, same].mean(1) / Y[:, idx].mean(1)

def holiday_factor(P, L):
    """과거 공휴일의 매장 수요 / 같은 요일 직전 4주 평균 (L 이전 공휴일만)"""
    Y = P["Y"].sum(1); hol = P["hol"]; rs = []
    for i in range(28, L+1):
        if hol[i]:
            base = [i-7*j for j in range(1,5) if not hol[i-7*j]]
            if base: rs.append(Y[:, i] / Y[:, base].mean(1))
    return np.mean(rs, 0) if rs else np.ones(3)

def level_dow(n=28, weeks=8, use_hol=True):
    """메뉴 레벨(최근 n일 요일보정 평균) × 매장 요일지수 × 공휴일 계수"""
    def f(P, L, k):
        d = L + k; Y, A = P["Y"], P["A"]
        idx = list(range(max(0, L-n+1), L+1))
        # 과거 각 날짜를 요일지수로 나눠 탈계절화
        des = np.zeros(Y.shape[:2]); cnt = np.zeros(Y.shape[:2])
        for i in idx:
            di = store_dow_index(P, L, i, weeks)
            h = holiday_factor(P, L) if (use_hol and P["hol"][i]) else np.ones(3)
            des += Y[:,:,i] / (di*h)[:,None] * A[:,:,i]; cnt += A[:,:,i]
        lvl = np.where(cnt>0, des/np.maximum(cnt,1), 0)
        fac = store_dow_index(P, L, d, weeks)
        if use_hol and d < len(P["hol"]) and P["hol"][d]: fac = fac * holiday_factor(P, L)
        return lvl * fac[:,None]
    return f

def ewma_dow(alpha=0.15, weeks=8, use_hol=True):
    def f(P, L, k):
        d = L + k; Y, A = P["Y"], P["A"]
        lvl = None
        for i in range(max(0, L-60), L+1):
            di = store_dow_index(P, L, i, weeks)
            h = holiday_factor(P, L) if (use_hol and P["hol"][i]) else np.ones(3)
            x = Y[:,:,i] / (di*h)[:,None]
            if lvl is None: lvl = x.copy()
            lvl = np.where(A[:,:,i], alpha*x + (1-alpha)*lvl, lvl)
        fac = store_dow_index(P, L, d, weeks)
        if use_hol and d < len(P["hol"]) and P["hol"][d]: fac = fac * holiday_factor(P, L)
        return lvl * fac[:,None]
    return f

def total_share(alpha=0.1, share_days=28, weeks=8):
    """매장 전체 수요(EWMA×요일×공휴일) × 메뉴 구성비(최근 share_days일)"""
    base = ewma_dow(alpha, weeks, True)
    def f(P, L, k):
        Y, A = P["Y"], P["A"]
        tot = base(P, L, k).sum(1)               # 매장 합계 예측
        idx = range(max(0, L-share_days+1), L+1)
        y = Y[:,:,list(idx)].sum(2); a = A[:,:,list(idx)].sum(2)
        rate = np.where(a>0, y/np.maximum(a,1), 0)   # 취급일 기준 일평균
        rate = rate * A[:,:,min(L+k, A.shape[2]-1)]  # 목표일 취급 메뉴만
        share = rate / np.maximum(rate.sum(1, keepdims=True), 1e-9)
        return tot[:,None] * share
    return f
