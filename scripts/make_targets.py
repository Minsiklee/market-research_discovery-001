#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""1차 배치 봉인층에서 재수집 대상 글 id 를 뽑는다.

work/targets_*.txt 는 저장소에 올리지 않으므로(공개 저장소), 새 PC 에서는
손에 있는 sealed 파일로 다시 만든다.

    python3 scripts/make_targets.py --sealed sealed_reddit-US-202601-202608-GV80.jsonl
"""
import argparse, json, os, re, sys

ap = argparse.ArgumentParser()
ap.add_argument("--sealed", required=True, help="1차 배치의 sealed_*.jsonl")
ap.add_argument("--out", default=None)
a = ap.parse_args()

model = "GV80" if "GV80" in os.path.basename(a.sealed) else \
        "G70" if "G70" in os.path.basename(a.sealed) else "UNKNOWN"
out = a.out or os.path.join("work", "targets_%s.txt" % model)
os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

ids = {}
for line in open(a.sealed, encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    d = json.loads(line)
    m = re.search(r"/comments/([a-z0-9]+)/", d.get("thread_url") or d.get("url") or "")
    if m:
        ids[m.group(1)] = 1

if not ids:
    print("thread_url 이 없어 글 id 를 뽑지 못했습니다 — 이 배치는 URL 이 소실된 쪽입니다.",
          file=sys.stderr)
    print("그 모델은 recollect.py g70 처럼 탐색부터 해야 합니다.", file=sys.stderr)
    sys.exit(1)

with open(out, "w", encoding="utf-8") as f:
    f.write("# %s 재수집 대상 — %s 에서 복원\n" % (model, os.path.basename(a.sealed)))
    f.write("# %d개\n" % len(ids))
    for i in sorted(ids):
        f.write(i + "\n")
print("%s — 글 %d개" % (out, len(ids)))
