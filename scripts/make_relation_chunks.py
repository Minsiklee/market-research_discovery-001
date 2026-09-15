# -*- coding: utf-8 -*-
"""② 소넷 전달용 청크 — 선별 스레드를 스레드 단위 20개씩 나눈다.

순위를 매기지 않는다. thread_key 순으로 자른다.
본문은 요약하지 않는다 — 통글을 그대로 싣는다.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import sys
from glob import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from screen import content_hash, thread_key_of, rec_num, load_records, decide_unit_rule  # noqa: E402

CHUNK = 20


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="indir", default="sealed/records")
    ap.add_argument("--screen", default="work/screen")
    ap.add_argument("--out", dest="outdir", default="work/relation_lite")
    ap.add_argument("--chunk", type=int, default=CHUNK)
    ap.add_argument("--comment-cap", type=int, default=0,
                    help="스레드당 댓글 상한(coding_guide §4). 0 이면 상한 없음 — 이 배치는 "
                         "청크당 약 25k 토큰이라 상한이 필요 없다.")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    selected = [l.strip() for l in open(os.path.join(args.screen, "selected_threads.txt"),
                                        encoding="utf-8") if l.strip()]
    meta = {r["thread_key"]: r for r in csv.DictReader(
        open(os.path.join(args.screen, "screen_rows.csv"), encoding="utf-8"))}

    rows, _files = load_records(args.indir)
    by_file = collections.defaultdict(list)
    for r in rows:
        by_file[r["_file"]].append(r)
    unit_rules = {f: decide_unit_rule(rs) for f, rs in by_file.items()}

    by_thread = collections.defaultdict(list)
    for r in rows:
        by_thread[r["_tkey"]].append(r)

    written = mismatch = 0
    manifest_chunks = []
    for i in range(0, len(selected), args.chunk):
        part = selected[i:i + args.chunk]
        n = i // args.chunk + 1
        path = os.path.join(args.outdir, "chunk_%02d.jsonl" % n)
        chars = 0
        with open(path, "w", encoding="utf-8") as fh:
            for tkey in part:
                # screen.py 와 같은 방식으로 스레드 안에서 content_hash 1건화
                seen = {}
                for r in sorted(by_thread[tkey], key=lambda x: (x["_file"], x["_num"])):
                    h = content_hash(r.get("raw_text"))
                    seen.setdefault(h, r)
                rs = sorted(seen.values(), key=lambda x: (x["_file"], x["_num"]))

                post = None
                for f in sorted({r["_file"] for r in rs}):
                    cand = [r for r in rs if r["_file"] == f]
                    if unit_rules[f]["rule"] == "url_presence":
                        u = [r for r in cand if r.get("url")]
                        if len(u) == 1:
                            post = u[0]
                            break
                    if post is None:
                        post = min(cand, key=lambda r: r["_num"])

                m = meta[tkey]
                if int(m["n_rows"]) != len(rs):          # screen.py 와 어긋나면 표시
                    mismatch += 1
                ordered = [post] + [r for r in rs if r is not post]
                if args.comment_cap:
                    ordered = ordered[:1 + args.comment_cap]
                out = {
                    "thread_key": tkey,
                    "batch": m["batch"],
                    "genesis_focus": m["genesis_focus"],
                    "top_partner": m["top_partner"],
                    "models": m["models"],
                    "brands": m["brands"],
                    "n_rows": len(rs),
                    "n_comments": len(rs) - 1,
                    "dominated": m["dominated"],
                    "high_density": len(rs) > 30,
                    "rows": [{"record_id": r["record_id"],
                              "unit": "post" if r is post else "comment",
                              "text": r.get("raw_text") or ""} for r in ordered],
                }
                chars += sum(len(x["text"]) for x in out["rows"])
                fh.write(json.dumps(out, ensure_ascii=False) + "\n")
                written += 1
        manifest_chunks.append({"chunk": n, "file": os.path.basename(path),
                                "threads": len(part), "chars": chars,
                                "approx_tokens": chars // 4})

    with open(os.path.join(args.outdir, "chunks_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump({"selected_threads": len(selected), "chunk_size": args.chunk,
                   "comment_cap": args.comment_cap or "없음",
                   "ordering": "thread_key 순. 순위가 아니다.",
                   "row_count_mismatch_vs_screen": mismatch,
                   "chunks": manifest_chunks}, fh, ensure_ascii=False, indent=2)
    print("스레드 %d → 청크 %d개  (screen.py 와 행수 불일치 %d)"
          % (written, len(manifest_chunks), mismatch))
    for c in manifest_chunks:
        print("  %s  %2d스레드  %7d자  ≈%6d토큰" % (c["file"], c["threads"], c["chars"], c["approx_tokens"]))


if __name__ == "__main__":
    raise SystemExit(main())
