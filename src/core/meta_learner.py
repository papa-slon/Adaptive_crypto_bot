
"""Meta-Learner weight allocator (simplified)."""
import redis, os, json, math, time
r=redis.Redis(host=os.getenv("REDIS_HOST","127.0.0.1"),decode_responses=True)
AGENTS=["trend","mr","vwap","stat","mm"]
def run():
    while True:
        sharpe={a:float(r.hget(f'stats:sharpe',a) or 0) for a in AGENTS}
        p=float(r.get('state:regime') or 0.5)
        w={}
        for a,s in sharpe.items():
            k=0.7 if a=="trend" else (-0.5 if a=="mr" else 0)
            w[a]=max(0,s)*math.exp(k*p)
        s=sum(w.values()) or 1
        for a in w: w[a]/=s
        r.set('alloc',json.dumps(w))
        time.sleep(900)
