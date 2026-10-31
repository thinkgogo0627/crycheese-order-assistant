import numpy as np, math
from common import *
SAFETY={"냉동":0.25,"냉장":0.15,"상온":0.30}

class Baseline:
    """제공 데이터를 만든 합성 발주 정책 (명세서 7절)"""
    name="기존 정책"
    def attach(self, W): self.W=W
    def f(self, s, i, hist):
        h = hist[i]; n=h.shape[0]
        if n==0: return self.W.init[s,i]/3
        return h[max(0,n-7):].mean()
    def order(self, d, s, sid, items, lots, pipe, hist):
        W=self.W; nxt=W.next_order_day(sid,d); cover=nxt-d+1
        rows={}
        for i in items:
            f=self.f(s,i,hist); stock=sum(l[1] for l in lots[i])
            pend=sum(q for t,q in pipe[i].items() if t>d)
            pos=stock-f+pend; tgt=f*min(cover,W.shelf[i])*(1+SAFETY[W.storage[i]])
            q=math.ceil(round((tgt-pos)/W.pack[i],9)) if f>0 and tgt>pos else 0
            if q>0: q=max(q,int(W.moq_units[i]))
            rows[i]=dict(q=q, urgent=f>0 and tgt>pos and pos<2*f, ppd=f/W.pack[i])
        return self.moq(d, sid, rows)
    def moq(self, d, sid, rows):
        W=self.W; amt=sum(r["q"]*W.price[d,i] for i,r in rows.items()); m=W.sup[sid]["moq"]
        sel=[i for i,r in rows.items() if r["q"]>0]
        if sel and amt<m:
            if not any(rows[i]["urgent"] for i in sel): return {}
            order=sorted(sel,key=lambda i:-rows[i]["ppd"]); k=0
            while amt<m:
                i=order[k%len(order)]; rows[i]["q"]+=1; amt+=W.price[d,i]; k+=1
        return {i:r["q"] for i,r in rows.items()}
    def emergency(self, d, s, i, hist):
        f=self.f(s,i,hist); return max(1, math.ceil(f*1.5/self.W.pack[i]))

class Forecast:
    """수요예측(메뉴×BOM) 사전계산: fc[s,i,d,k] = 마지막 관측일 d-1 기준 d+k 소요량(k=0..13)"""
    def __init__(self, W, model, K=14):
        from backtest import P
        S,I=3,len(W.INGS); T=len(DATES)
        self.fc=np.zeros((S,I,T,K))
        for d in range(1,T):
            L=d-1
            for k in range(K):
                m = model(P, L, k+1)                       # [s,menu] 순수요
                tgt=min(d+k, T-1)
                av = P["A"][:,:,tgt] if d+k<T else P["A"][:,:,T-1]
                self.fc[:,:,d,k] = (m*av) @ W.B
        self.fc[:,:,0,:]=self.fc[:,:,1,:]
        # 실제 소요(무제약) — 사후 오차 계산용
        self.act=np.einsum("smd,mi->sid",P["Y"],W.B)

class Smart(Baseline):
    """개선 정책: 요일·공휴일 수요예측, 다음 입고 전날까지 정확한 기간, 예측오차 기반 안전재고, 로트별 사용기한 반영"""
    def __init__(self, F, z=1.0, shelf_cap=True, smart_pad=True, defer_frac=0.5, err_window=28, name=None):
        self.F=F; self.z=z; self.cap=shelf_cap; self.pad=smart_pad; self.df=defer_frac; self.ew=err_window
        self.name=name or f"개선(z={z}{', 기한상한' if shelf_cap else ''}{', 패딩개선' if smart_pad else ''}, 이월{defer_frac})"
    def rel_err(self, s, i, d):
        a=max(1,d-self.ew); p=self.F.fc[s,i,a:d,0]; y=self.F.act[s,i,a:d]
        if p.sum()<=0: return 0.5
        return float(np.sqrt(((p-y)**2).mean())/max(p.mean(),1e-9))
    def project(self, d, i, lots, pipe, f, H):
        """FEFO 투영: (예측 부족량, 기간 끝 사용가능 잔량, 기한경과 예상량)"""
        L=[[l[0],l[1],d] for l in lots[i]]+[[t+self.W.shelf[i]-1,q,t] for t,q in pipe[i].items() if t<d+H]
        L.sort(); short=0; exp=0
        for k in range(H):
            day=d+k; need=f[k]
            for l in L:
                if l[2]<=day and l[0]>=day and l[1]>0 and need>0:
                    t=min(l[1],need); l[1]-=t; need-=t
            short+=need
            for l in L:
                if l[0]==day and l[1]>0: exp+=l[1]; l[1]=0
        left=sum(l[1] for l in L if l[0]>=d+H)
        return short, left, exp
    def order(self, d, s, sid, items, lots, pipe, hist):
        W=self.W; fc=self.F.fc[s,:,d,:]
        a1=W.arrival(sid,d); nxt=W.next_order_day(sid,d); a2=W.arrival(sid,nxt)
        H=a2-d
        rows={}
        for i in items:
            f=fc[i,:max(H,1)]
            if f.sum()<=0: rows[i]=dict(q=0,urgent=False,ppd=0,risk=9,doc=99); continue
            short,left,_=self.project(d,i,lots,pipe,f,H)
            rel=self.rel_err(s,i,d); zz=self.z[W.storage[i]] if isinstance(self.z,dict) else self.z; ss=zz*rel*np.sqrt((f[(a1-d):]**2).sum())
            gap=short+max(0.0, ss-left)
            q=math.ceil(round(gap/W.pack[i],9)) if gap>1e-9 else 0
            if self.cap and q>0:
                life=min(W.shelf[i],14); post=fc[i,(a1-d):(a1-d)+life].sum()
                cap=math.floor(max(0,post-left)/W.pack[i]); qmin=math.ceil(round(short/W.pack[i],9))
                q=max(qmin,min(q,cap))
            if q>0: q=max(q,int(W.moq_units[i]))
            ppd=f.mean()/W.pack[i]
            stock=sum(l[1] for l in lots[i])+sum(q2 for t,q2 in pipe[i].items())
            rows[i]=dict(q=q, urgent=(short+max(0.0,self.df*ss-left))>1e-9, ppd=ppd,
                         risk=(W.pack[i]/max(f.mean(),1e-9))/W.shelf[i], doc=(stock+q*W.pack[i])/max(f.mean(),1e-9))
        if not self.pad: return self.moq(d,sid,rows)
        amt=sum(r["q"]*W.price[d,i] for i,r in rows.items()); m=W.sup[sid]["moq"]
        sel=[i for i,r in rows.items() if r["q"]>0]
        if sel and amt<m:
            if not any(rows[i]["urgent"] for i in sel): return {}
            # 기한 위험 낮은 품목 중 '보유 일수'가 가장 짧은 품목부터 1단위씩 (곧 발주할 품목을 앞당김)
            cand=[i for i in rows if rows[i]["ppd"]>0 and rows[i]["risk"]<0.35] or [i for i in rows if rows[i]["ppd"]>0]
            while amt<m:
                i=min(cand,key=lambda j:rows[j]["doc"])
                rows[i]["q"]+=1; rows[i]["doc"]+=W.pack[i]/max(fc[i,:max(H,1)].mean(),1e-9); amt+=W.price[d,i]
        return {i:r["q"] for i,r in rows.items()}
    def emergency(self, d, s, i, hist):
        f=self.F.fc[s,i,d,:2].mean(); return max(1, math.ceil(f*1.5/self.W.pack[i]))

class BaselineFC(Baseline):
    """기존 산식 그대로, 평균 소진량만 개선 예측으로 교체 (예측 효과 분리용)"""
    name="기존 산식 + 개선 예측"
    def __init__(self, F): self.F=F
    def order(self, d, s, sid, items, lots, pipe, hist):
        self._d=d; return super().order(d, s, sid, items, lots, pipe, hist)
    def f(self, s, i, hist):
        d=hist.shape[1]; W=self.W
        return self.F.fc[s,i,d,:3].mean()

from scipy.stats import norm
class Smart2(Smart):
    """품목별 서비스수준(뉴스벤더 임계비율) + 입고주기 합산오차 기반 안전재고"""
    def __init__(self, F, alpha=1.0, zmin=0.5, zmax=4.0, shelf_cap=True, defer_frac=0.5, err_window=42, hold={"냉장":0.003,"냉동":0.0005,"상온":0.0005}, name=None):
        super().__init__(F, 0, shelf_cap, True, defer_frac, err_window)
        self.alpha=alpha; self.zmin=zmin; self.zmax=zmax; self.hold=hold
        self.name=name or f"개선2(α={alpha})"
    def attach(self, W):
        super().attach(W)
        Y=self.F.act; B=W.B; I=len(W.INGS)
        # 식자재 1단위 부족 시 막히는 공헌이익 (해당 식자재를 쓰는 메뉴 공헌이익 / 그 메뉴들의 식자재 사용량)
        from backtest import P
        dem=P["Y"].sum((0,2))
        self.cu=np.zeros(I); self.co=np.zeros(I); self.zi=np.zeros(I)
        uc=W.price[:273].mean(0)/W.pack
        for i in range(I):
            ms=B[:,i]>0
            self.cu[i]=(dem[ms]*W.margin[ms]).sum()/max((dem[ms]*B[ms,i]).sum(),1e-9)
            # 초과 1단위 보유비용: 다음 입고까지(약 2일) 보관 손실 + 사용기한이 짧을수록 만료 위험
            self.co[i]=uc[i]*(self.hold[W.storage[i]]*2 + (2.0/W.shelf[i] if W.shelf[i]<=14 else 0))
            cr=self.cu[i]/(self.cu[i]+self.co[i])
            self.zi[i]=np.clip(self.alpha*norm.ppf(min(cr,0.99997)), self.zmin, self.zmax)
    def horizon_rmse(self, s, i, d, a_off, H):
        errs=[]
        for o in range(max(1,d-self.ew), d):
            if o+H>=self.F.act.shape[2]: break
            p=self.F.fc[s,i,o,a_off:H].sum(); y=self.F.act[s,i,o+a_off:o+H].sum(); errs.append(p-y)
        if len(errs)<5: return 0.5*self.F.fc[s,i,d,a_off:H].sum()
        return float(np.sqrt(np.mean(np.square(errs))))
    def order(self, d, s, sid, items, lots, pipe, hist):
        W=self.W; fc=self.F.fc[s,:,d,:]
        a1=W.arrival(sid,d); nxt=W.next_order_day(sid,d); a2=W.arrival(sid,nxt); H=a2-d
        rows={}
        for i in items:
            f=fc[i,:max(H,1)]
            if f.sum()<=0: rows[i]=dict(q=0,urgent=False,ppd=0,risk=9,doc=99); continue
            short,left,_=self.project(d,i,lots,pipe,f,H)
            ss=self.zi[i]*self.horizon_rmse(s,i,d,0,H)
            gap=short+max(0.0, ss-left)
            q=math.ceil(round(gap/W.pack[i],9)) if gap>1e-9 else 0
            if self.cap and q>0:
                life=min(W.shelf[i],14); post=fc[i,(a1-d):(a1-d)+life].sum()
                cap=math.floor(max(0,post-left)/W.pack[i]); qmin=math.ceil(round(short/W.pack[i],9))
                q=max(qmin,min(q,cap))
            if q>0: q=max(q,int(W.moq_units[i]))
            stock=sum(l[1] for l in lots[i])+sum(q2 for t,q2 in pipe[i].items())
            rows[i]=dict(q=q, urgent=(short+max(0.0,self.df*ss-left))>1e-9, ppd=f.mean()/W.pack[i],
                         risk=(W.pack[i]/max(f.mean(),1e-9))/W.shelf[i], doc=(stock+q*W.pack[i])/max(f.mean(),1e-9))
        amt=sum(r["q"]*W.price[d,i] for i,r in rows.items()); m=W.sup[sid]["moq"]
        sel=[i for i,r in rows.items() if r["q"]>0]
        if sel and amt<m:
            if not any(rows[i]["urgent"] for i in sel): return {}
            cand=[i for i in rows if rows[i]["ppd"]>0 and rows[i]["risk"]<0.35] or [i for i in rows if rows[i]["ppd"]>0]
            while amt<m:
                i=min(cand,key=lambda j:rows[j]["doc"])
                rows[i]["q"]+=1; rows[i]["doc"]+=W.pack[i]/max(fc[i,:max(H,1)].mean(),1e-9); amt+=W.price[d,i]
        return {i:r["q"] for i,r in rows.items()}
