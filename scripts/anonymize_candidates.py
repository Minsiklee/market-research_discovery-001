# -*- coding: utf-8 -*-
"""후보 파일 가명화 — 워커 전달용 사본을 만든다.

사양
  - url 필드를 지운다. 원문 링크는 워커에게 흐르지 않는다.
  - handle 을 권역 안 등장 순서대로 SPK-{권역}-X-{001..} 로 바꾼다.
    등장 순서는 (파일명, 줄번호) 순이다 — 한 권역이 여러 파일로 쪼개져도 재현된다.
  - in_reply_to_url 은 같은 대화에 속하면 같은 CONV-{001..} 로 바꾼다.
    대화는 url ↔ in_reply_to_url 간선으로 묶는다(합집합 찾기). null 은 null 로 둔다 —
    답글인지 아닌지는 이 필드로 그대로 읽힌다.
  - conv_id 를 새로 붙인다. 대화에 속한 모든 레코드가 받는다 — 원글도 받는다.
    원글은 in_reply_to_url 이 null 이라 그 필드만으로는 자기 대화를 가리키지 못한다.
  - 한 번 매긴 번호는 다시 매기지 않는다. 대장이 이미 있으면 대조해서, 기존 화자·대화의
    번호가 달라지면 중단한다(워커가 이미 받은 사본과 어긋나지 않게).
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

    원글이 후보셋 안에 있으면 그 원글도 같은 대화에 든다. 원글은 in_reply_to_url
    이 null 이므로 conv_id 로만 대화에 이어진다.
    """
    uf = Union()
    for _name, _ln, rec in rows:
        parent = rec.get("in_reply_to_url")
        if not parent:
            continue
        uf.union(parent, rec.get("url") or "cand:%s" % rec.get("cand_id"))

    conv = {}
    for _name, _ln, rec in rows:  # 등장 순서대로 번호를 매긴다
        parent = rec.get("in_reply_to_url")
        if not parent:
            continue
        root = uf.find(parent)
        if root not in conv:
            conv[root] = "CONV-%03d" % (len(conv) + 1)

    members = collections.defaultdict(set)
    for _name, _ln, rec in rows:
        for url in (rec.get("in_reply_to_url"), rec.get("url")):
            if url and uf.find(url) in conv:
                members[conv[uf.find(url)]].add(url)
    return uf, conv, members


def conv_of(rec, uf, conv):
    """레코드가 속한 대화. 원글(답글 아님)도 자기 url 로 찾는다."""
    for url in (rec.get("in_reply_to_url"), rec.get("url")):
        if url and uf.find(url) in conv:
            return conv[uf.find(url)]
    return None


def latest_ledger(ledger_dir, prefix):
    found = sorted(glob(os.path.join(ledger_dir, prefix + "_*.csv")))
    return found[-1] if found else None


def check_stable(ledger_dir, smap, uf, conv):
    """이미 발급한 번호가 바뀌었는지 대조한다. 바뀐 것만 돌려준다."""
    drift = []
    spk_prev = latest_ledger(ledger_dir, "spk_map")
    if spk_prev:
        for row in csv.DictReader(open(spk_prev, encoding="utf-8")):
            now = smap.get((row["region"], row["handle"]))
            if now is not None and now != row["pseudonym"]:
                drift.append("화자 %s → %s (%s)" % (row["pseudonym"], now, row["region"]))
    conv_prev = latest_ledger(ledger_dir, "conv_map")
    if conv_prev:
        for row in csv.DictReader(open(conv_prev, encoding="utf-8")):
            url = row["member_url"]
            now = conv.get(uf.find(url))
            if now is not None and now != row["conv_id"]:
                drift.append("대화 %s → %s" % (row["conv_id"], now))
    return sorted(set(drift))


def scrub(rec, smap, uf, conv):
    out = {}
    for k, v in rec.items():
        if k in DROP_FIELDS:
            continue
        if k == "handle" and v:
            out[k] = smap[(rec.get("region") or "XX", v)]
        elif k == "in_reply_to_url":
            out[k] = conv[uf.find(v)] if v else None
            out["conv_id"] = conv_of(rec, uf, conv)
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

    drift = check_stable(args.ledger, smap, uf, conv)
    if drift:
        sys.exit("이미 발급한 번호가 바뀐다 — 사본을 쓰지 않았다:\n  " + "\n  ".join(drift))

    # 한 계정이 두 권역에 나오면 권역마다 다른 번호를 받는다(권역 안 번호이므로).
    # 워커가 같은 화자를 둘로 세지 않게 가명끼리의 동일 관계만 알려준다.
    by_handle = collections.defaultdict(list)
    for (region, handle), pseudo in smap.items():
        by_handle[handle].append(pseudo)
    aliases = sorted(sorted(v) for v in by_handle.values() if len(v) > 1)

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
            "conv_members": sum(1 for r in recs if r.get("conv_id")),
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
        "speaker_aliases": aliases,
        "files": per_file,
        "ledger_note": "대응표는 봉인 대장에만 있다 — %s/ (gitignore)" % args.ledger,
    }
    with open(os.path.join(args.outdir, "manifest_anon.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print("사본 %d 파일 · 레코드 %d · 화자 %d · 대화 %d · 권역교차 화자 %d"
          % (len(per_file), len(rows), len(smap), len(set(conv.values())), len(aliases)))
    for f in per_file:
        print("  %-42s %3d건 · 화자 %d" % (f["anon_file"], f["records"], f["speakers"]))
    print("봉인 대장: %s · %s" % (os.path.basename(spk_path), os.path.basename(conv_path)))


if __name__ == "__main__":
    main()
