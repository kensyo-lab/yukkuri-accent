import sys, os; sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_samples import PAIRS
from accent_core import *
import difflib
t=load_numbers(None)
def dist(x,y):
    sm=difflib.SequenceMatcher(None,x,y,autojunk=False)
    return sum(max(i2-i1,j2-j1) for tg,i1,i2,j1,j2 in sm.get_opcodes() if tg!='equal')
tot0=tot1=0
for i,(b,a) in enumerate(PAIRS):
    d=Dictionary()
    for j,(bb,aa) in enumerate(PAIRS):
        if j!=i:
            for c in learn(bb,aa,t,d): d.upsert(c.src,c.dst,c.head_only)
    A=normalize(a); raw=prepare(b,t); out=convert(b,d,t).text
    d0,d1=dist(raw,A),dist(out,A); tot0+=d0; tot1+=d1
    print(f"例{i+1}: 修正箇所 {d0} → {d1}")
print(f"合計: {tot0} → {tot1}  ({(1-tot1/tot0)*100:.0f}% 減)")
