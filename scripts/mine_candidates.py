# -*- coding: utf-8 -*-
"""사전 v2 후보 역도출 — 말뭉치에서 차명꼴 토큰을 캐내 스레드 빈도로 센다.

사전 §0-3: 경쟁 세트는 상식이 아니라 담론에서 역도출한다(P5).
그래서 아는 차명을 얹지 않고, 코퍼스에서 차명꼴을 뽑아 빈도를 붙인 뒤 사람이 고른다.

출력은 토큰 빈도표다. 본문은 나가지 않는다.
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys
from glob import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dictionary_v1 import MODELS, BRANDS  # noqa: E402
from screen import normalize, thread_key_of  # noqa: E402

RX_V1 = [re.compile(p, re.I) for _, _, _, p in MODELS] + [re.compile(p, re.I) for _, p in BRANDS]

# 차명꼴 후보 — 원문 대소문자를 살려서 잡는다. 모델 코드는 대문자로 쓰인다.
CAND = [
    ("code_alnum",  r"\b[A-Z]{1,3}[-\s]?\d{1,3}[A-Za-z]?\b"),   # X5 · Q7 · LS500 · M340i · i7
    ("acronym",     r"\b[A-Z]{2,4}\b"),                          # EQS · GLS · RDX · TLX
    ("nameplate",   r"\b[A-Z][a-z]{3,}[-\s](?:Class|Series|Cruiser|Rover|Wagon|Country)\b"),
    ("propernoun",  r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]{3,}\b"),    # 문장 첫머리가 아닌 고유명사
]
RX_CAND = [(n, re.compile(p, re.M)) for n, p in CAND]

# 자동차 담론의 일반어 — 차명이 아니다. 빈도 상위에서 걷어낸다.
STOP = set("""The This That They There Then Than These Those When What Which While Where With Would Will
Your You Yeah Yes Just Have Having Here Hard Some Same Said Says Sure Still Should Shit Since Seems
Only Once Also About After Again Agree Anyone Anything Another Been Being Best Better Both But Buy
Cars Care Come Could Dont Does Doing Even Every Everyone First From Feel Front Fuck Good Great Guys
Honestly Just Know Like Little Look Looking Lots Make Many Maybe Mine Most Much Need Never Next Nice
Nope Notice Only Other People Personally Pretty Probably Really Right Same Take Thanks Thing Think
Time Tried Truly Very Want Well Went Were Whatever Yeah Year Years Edit Reply Deleted Removed
Genesis Hyundai Genesis Owner Owners Dealer Dealers Service Warranty Miles Interior Exterior Engine
Drive Driving Drove Price Lease Lucky Love Enjoy Congrats Beautiful Awesome Amazing Perfect Sounds
Sport Sports Base Trim Package Premium Standard Advanced Prestige Launch Edition Model Models
America American Korea Korean Japan German Germany Europe Canada Texas California Florida Carolina
York Jersey City County Costco Reddit Google YouTube Carvana CarMax Autotrader Kelley Consumer
SUV EVS EPA MPG MSRP APR OEM USA CPO AWD RWD FWD ICE DIY IMO IIRC TBH FYI LOL LMAO WTF OTD ETA
ADAS ACC HUD LED OLED USB GPS NAV BSD AEB TPMS CVT DCT ABS ESC TCS VIN PDF URL FAQ PSA EDIT NHTSA
KBB JDM EPA DOT IRS HOV EV PHEV HEV BEV EREV KM MPH RPM HP TQ NM FT LB KG OK OKAY""".split())


def main():
    rows = []
    for fp in sorted(glob("sealed/records/*.jsonl")):
        for line in open(fp, encoding="utf-8"):
            if line.strip():
                rows.append(json.loads(line))
    by_thread = collections.defaultdict(list)
    for r in rows:
        by_thread[thread_key_of(r.get("thread_url"))].append(r.get("raw_text") or "")

    thread_hits = collections.Counter()
    kind_of = {}
    for tkey, texts in by_thread.items():
        blob = "\n".join(texts)
        found = set()
        for kind, rx in RX_CAND:
            for m in rx.findall(blob):
                tok = re.sub(r"\s+", " ", m).strip()
                if tok in STOP or tok.upper() in STOP:
                    continue
                key = tok.upper().replace(" ", "").replace("-", "")
                found.add((key, tok, kind))
        seen_keys = set()
        for key, tok, kind in found:
            if key in seen_keys:
                continue
            seen_keys.add(key)
            thread_hits[key] += 1
            kind_of.setdefault(key, (tok, kind))

    # v1 사전이 이미 잡는 토큰은 뺀다
    out = []
    for key, n in thread_hits.most_common():
        tok, kind = kind_of[key]
        norm = normalize(tok)
        if any(rx.search(norm) for rx in RX_V1):
            continue
        out.append((n, key, tok, kind))

    os.makedirs("work/screen", exist_ok=True)
    with open("work/screen/candidate_tokens.tsv", "w", encoding="utf-8") as fh:
        fh.write("thread_hits\tkey\texample\tkind\n")
        for n, key, tok, kind in out:
            fh.write(f"{n}\t{key}\t{tok}\t{kind}\n")

    print(f"threads={len(by_thread)}  후보 토큰={len(out)}  (v1 기매칭 제외)")
    print(f"{'스레드':>5}  {'토큰':<14} {'꼴'}")
    for n, key, tok, kind in out[:90]:
        if n >= 3:
            print(f"{n:>5}  {tok:<14} {kind}")


if __name__ == "__main__":
    raise SystemExit(main())
