import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from accent_core import *
from samples_numbers import NUM_PAIRS
t = load_numbers(None)
for i,(src,ymm,ans) in enumerate(NUM_PAIRS,1):
    out = prepare(ymm,t)
    iss = validate(out)
    print(f"{i:2}. {src}\n   出力: {out}\n   実発: {ans}")
    for x in iss: print("   ",x.level,x.msg)
