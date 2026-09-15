# -*- coding: utf-8 -*-
"""후보 파일 가명화 — 워커 전달용 사본을 만든다.

사양
  - url 필드를 지운다. 원문 링크는 워커에게 흐르지 않는다.
  - handle 을 권역 안 등장 순서대로 SPK-{권역}-X-{001..} 로 바꾼다.
    등장 순서는 (파일명, 줄번호) 순이다 — 한 권역이 여러 파일로 쪼개져도 재현된다.
  - in_reply_to_url 은 같은 대화에 속하면 같은 CONV-{001..} 로 바꾼다.
    대화는 url ↔ in_reply_to_url 간선으로 묶는다(합집합 찾기). null 은 null 로 둔다.
  - 대응표(가명 ↔ 실제 handle, CONV ↔ 실제 url)는 봉인 대장에만 쓴다.
    사본과 manifest 에는 실제 값이 한 글자도 나오지 않는다.

  사본을 쓰기 전에 누출 검사를 건다. url·핸들 흔적이 한 건이라도 남으면
  아무 파일도 쓰지 않고 중단한다.

사용
  python3 scripts/anonymize_candidates.py --in sealed/candidates \
      --out work/anon --ledger sealed/ledger
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import json
import os
import re
import sys
from glob import glob

SCHEMA_VERSION = "anon_v1"
DROP_FIELDS = ("url",)

# 사본에 남아 있으면 안 되는 흔적. 가명(SPK-·CONV-)은 걸리지 않는다.
LEAK_PATTERNS = (
    ("url", re.compile(r"https?://|(?:^|[^\w])x\.com/|twitter\.com/", re.I)),
    ("handle", re.compile(r"(?:^|[^\w])@\w+")),
)


class Union:
    """대화 묶기용 합집합 찾기."""

    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def load(indir):
    """(파일명, 줄번호, 레코드) 를 파일명·줄번호 순으로 돌려준다."""
    out = []
    for path in sorted(glob(os.path.join(indir, "*.jsonl"))):
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                line = line.strip()
                if line:
                    out.append((name, i, json.loads(line)))
    return out


def build_speaker_map(rows):
    """권역 안 등장 순서대로 SPK 를 매긴다. handle 이 없으면 건너뛴다."""
    seq = collections.Counter()
    smap = {}
    first_seen = {}
    for name, ln, rec in rows:
        handle = rec.get("handle")
        if not handle:
            continue
        region = rec.get("region") or "XX"
        key = (region, handle)
        if key in smap:
            continue
        seq[region] += 1
        smap[key] = "SPK-%s-X-%03d" % (region, seq[region])
        first_seen[key] = (name, ln, rec.get("cand_id"))
    return smap, first_seen


def build_conv_map(rows):
    """url ↔ in_reply_to_url 간선으로 대화를 묶고 CONV 를 매긴다.

    번호는 권역과 무관한 전역 일련번호다 — 권역을 가로지르는 대화가 갈라지지
    않게 하고, 사본을 합쳐도 번호가 부딪히지 않는다.
    """
    uf = Union()
    for _name, _ln, rec in rows:
        parent = rec.get("in_reply_to_url")
        if not parent:
            continue
        uf.union(parent, rec.get("url") or "cand:%s" % rec.get("cand_id"))

    conv = {}
    members = collections.defaultdict(set)
    for _name, _ln, rec in rows:
        parent = rec.get("in_reply_to_url")
        if not parent:
            continue
        root = uf.find(parent)
        if root not in conv:
            conv[root] = "CONV-%03d" % (len(conv) + 1)
        members[conv[root]].add(parent)
        if rec.get("url"):
            members[conv[root]].add(rec["url"])
    return uf, conv, members


def scrub(rec, smap, uf, conv):
    out = {}
    for k, v in rec.items():
        if k in DROP_FIELDS:
            continue
        if k == "handle" and v:
            out[k] = smap[(rec.get("region") or "XX", v)]
        elif k == "in_reply_to_url" and v:
            out[k] = conv[uf.find(v)]
        else:
            out[k] = v
    return out


def leak_check(rec):
    """사본 한 줄에 남은 원문 흔적을 돌려준다."""
    hits = []
    for k, v in rec.items():
        if not isinstance(v, str):
            continue
        for label, pat in LEAK_PATTERNS:
            if pat.search(v):
                hits.append((k, label))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="indir", default="sealed/candidates")
    ap.add_argument("--out", dest="outdir", default="work/anon")
    ap.add_argument("--ledger", default="sealed/ledger")
    args = ap.parse_args()

    rows = load(args.indir)
    if not rows:
        sys.exit("후보 파일이 없다: %s" % args.indir)

    smap, first_seen = build_speaker_map(rows)
    uf, conv, members = build_conv_map(rows)

    # 사본을 메모리에서 다 만들고 누출 검사를 통과한 뒤에만 파일로 쓴다.
    staged = collections.OrderedDict()
    leaks = []
    for name, ln, rec in rows:
        clean = scrub(rec, smap, uf, conv)
        for field, label in leak_check(clean):
            leaks.append("%s:%d %s(%s)" % (name, ln, field, label))
        staged.setdefault(name, []).append(clean)
    if leaks:
        sys.exit("누출 검사 실패 — 사본을 쓰지 않았다:\n  " + "\n  ".join(leaks))

    os.makedirs(args.outdir, exist_ok=True)
    os.makedirs(args.ledger, exist_ok=True)

    per_file = []
    for name, recs in staged.items():
        outname = name.replace(".jsonl", ".anon.jsonl")
        with open(os.path.join(args.outdir, outname), "w", encoding="utf-8") as fh:
            for r in recs:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        per_file.append({
            "source_file": name,
            "anon_file": outname,
            "records": len(recs),
            "speakers": len({r["handle"] for r in recs if r.get("handle")}),
            "conv_refs": sum(1 for r in recs if r.get("in_reply_to_url")),
        })

    # ── 봉인 대장. 이 두 파일만 실제 값을 안다.
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    spk_path = os.path.join(args.ledger, "spk_map_%s.csv" % stamp)
    with open(spk_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["pseudonym", "region", "handle", "first_file", "first_line", "first_cand_id"])
        for (region, handle), pseudo in sorted(smap.items(), key=lambda kv: kv[1]):
            f, ln, cid = first_seen[(region, handle)]
            w.writerow([pseudo, region, handle, f, ln, cid])

    conv_path = os.path.join(args.ledger, "conv_map_%s.csv" % stamp)
    with open(conv_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["conv_id", "member_url"])
        for cid in sorted(set(conv.values()), key=lambda c: int(c.split("-")[1])):
            for url in sorted(members[cid]):
                w.writerow([cid, url])

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": stamp,
        "dropped_fields": list(DROP_FIELDS),
        "records": len(rows),
        "speakers_total": len(smap),
        "speakers_by_region": dict(sorted(collections.Counter(r for r, _h in smap).items())),
        "conversations": len(set(conv.values())),
        "files": per_file,
        "ledger_note": "대응표는 봉인 대장에만 있다 — %s/ (gitignore)" % args.ledger,
    }
    with open(os.path.join(args.outdir, "manifest_anon.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print("사본 %d 파일 · 레코드 %d · 화자 %d · 대화 %d"
          % (len(per_file), len(rows), len(smap), len(set(conv.values()))))
    for f in per_file:
        print("  %-42s %3d건 · 화자 %d" % (f["anon_file"], f["records"], f["speakers"]))
    print("봉인 대장: %s · %s" % (os.path.basename(spk_path), os.path.basename(conv_path)))


if __name__ == "__main__":
    main()
