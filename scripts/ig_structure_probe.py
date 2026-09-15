# -*- coding: utf-8 -*-
"""인스타 반응 층 구조 점검 — 수집 층이 반응 검증에 쓸 수 있는 모양인지 본다.

이 층은 엣지가 아니다(파이프라인 ⑥). 공식 계정 게시물에 달린 댓글로
반응을 검증하는 별도 층이며, 이미지 코딩은 하지 않는다.
본문은 나가지 않는다 — 건수와 구조만.
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
import re
import unicodedata
from glob import glob

RX_TAG = re.compile(r"#\w+", re.UNICODE)
RX_DECLARED = re.compile(
    r"#광고|#협찬|#제공|#유료광고|#ad\b|#sponsored|#paidpartnership|"
    r"paid partnership with|includes paid promotion|협찬받았습니다", re.I)


def script_of(text):
    s = set()
    for ch in text:
        if not ch.isalpha():
            continue
        n = unicodedata.name(ch, "")
        for pre, lab in (("HANGUL", "한글"), ("ARABIC", "아랍"), ("CYRILLIC", "키릴"),
                         ("CJK", "CJK"), ("HIRAGANA", "CJK"), ("KATAKANA", "CJK"),
                         ("THAI", "태국"), ("DEVANAGARI", "데바나가리"), ("LATIN", "라틴")):
            if n.startswith(pre):
                s.add(lab)
                break
    return "+".join(sorted(s)) if s else "문자없음"


def main(indir="sealed/instagram", outdir="work/instagram"):
    os.makedirs(outdir, exist_ok=True)
    rows, files = [], []
    for fp in sorted(glob(os.path.join(indir, "*.jsonl"))):
        b = os.path.basename(fp).replace("sealed_", "").replace(".jsonl", "")
        n = 0
        for line in open(fp, encoding="utf-8"):
            if line.strip():
                o = json.loads(line)
                o["_b"] = b
                rows.append(o)
                n += 1
        files.append({"batch": b, "rows": n})

    by_thread = collections.defaultdict(list)
    for r in rows:
        by_thread[r["thread_url"]].append(r)

    # 계정: URL 경로 첫 세그먼트. §6 의 공식 계정 판정이 여기서 끝난다.
    accounts = collections.Counter(t.split("/")[3] for t in by_thread)
    fmt = collections.Counter("reel" if "/reel/" in t else "p" for t in by_thread)

    # 파일 간 중복
    spanning = sum(1 for rs in by_thread.values() if len({r["_b"] for r in rs}) > 1)
    rid = collections.defaultdict(set)
    for r in rows:
        rid[r["record_id"]].add(r["_b"])

    # 중복 제거(스레드 내 텍스트 해시) 후 행 수
    # 같은 공식 게시물이 여러 모델 질의에 걸려 파일마다 캡션 사본이 생긴다.
    # 캡션이 스레드당 1개인지는 반드시 제거 뒤에 세야 한다.
    kept = 0
    kept_rows = []
    per_thread_kept = collections.Counter()
    cap_per_thread = collections.Counter()
    for t, rs in by_thread.items():
        seen = {hashlib.sha256((r.get("raw_text") or "").strip().encode()).hexdigest(): r
                for r in sorted(rs, key=lambda x: (x["_b"], x["record_id"]))}
        kept += len(seen)
        per_thread_kept[len(seen)] += 1
        cap_per_thread[sum(1 for r in seen.values() if not r.get("author_id_hash_full"))] += 1
        kept_rows.extend(seen.values())

    # 캡션 사본이 파일마다 생기므로 아래 집계는 전부 중복 제거 후 행으로 센다.
    comments = [r for r in kept_rows if r.get("author_id_hash_full")]
    caps = [r for r in kept_rows if not r.get("author_id_hash_full")]
    emoji_only = sum(1 for r in comments if not any(ch.isalnum() for ch in r["raw_text"]))

    tags = collections.Counter()
    for r in caps:
        for t in RX_TAG.findall(r["raw_text"]):
            tags[t.lower()] += 1

    manifest = {
        "layer": "instagram_reaction",
        "note": "엣지 아님. 공식 계정 게시물의 댓글로 반응을 검증하는 별도 층. 이미지 코딩 없음.",
        "input_files": files,
        "rows_in": len(rows),
        "threads": len(by_thread),
        "rows_after_thread_scoped_hash_dedup": kept,
        "accounts_in_url": dict(accounts),
        "post_format": dict(fmt),
        "unit_rule": {
            "rule": "author_id_hash_full 없음 = 공식 계정 캡션(post) · 있음 = 댓글",
            "captions_per_thread_after_dedup": {str(k): v for k, v in sorted(cap_per_thread.items())},
        },
        "dedup": {
            "threads_spanning_files": spanning,
            "record_id_colliding_across_files": sum(1 for v in rid.values() if len(v) > 1),
            "rows_removed": len(rows) - kept,
        },
        "comment_cap": {
            "rows_per_thread_after_dedup": {str(k): v for k, v in sorted(per_thread_kept.items())},
            "note": "파일당 스레드 최대 16행(캡션 1 + 댓글 15)로 잘려 있다. 수집 상한이므로 댓글 수를 인기 지표로 쓸 수 없다.",
        },
        "comment_character": {
            "comments": len(comments),
            "emoji_or_symbol_only": emoji_only,
            "emoji_share": round(emoji_only / len(comments), 3) if comments else 0,
            "scripts": dict(collections.Counter(script_of(r["raw_text"]) for r in comments).most_common(12)),
        },
        "caption_character": {
            "captions": len(caps),
            "scripts": dict(collections.Counter(script_of(r["raw_text"]) for r in caps).most_common(5)),
            "captions_without_hashtag": sum(1 for r in caps if "#" not in r["raw_text"]),
            "declared_sponsorship_markers": sum(1 for r in caps if RX_DECLARED.search(r["raw_text"])),
        },
        "hashtag_counts": dict(tags.most_common(40)),
    }
    with open(os.path.join(outdir, "ig_structure_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    print("행 %d · 스레드 %d · 중복 제거 후 %d · 계정 %s"
          % (len(rows), len(by_thread), kept, dict(accounts)))
    print("wrote %s/ig_structure_manifest.json" % outdir)


if __name__ == "__main__":
    main()
