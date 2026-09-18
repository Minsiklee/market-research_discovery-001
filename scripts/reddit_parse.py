#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""raw 원응답 → 작업층·봉인층·manifest (가이드 v2.2 schema 1.6).

reddit_fetch.py 가 남긴 raw/{글id}.json 만 읽는다. 네트워크를 타지 않으므로
규칙이 바뀌면 몇 번이든 다시 돌릴 수 있다 — 그게 raw 를 남기는 이유다.

1차 배치가 어긴 것을 여기서 구조적으로 막는다.
  §4-1  record_id 에 배치를 넣어 전역 유일. 원 id 는 record_id_orig
  §4-2  parent_id 는 레딧 원응답의 parent_id 를 그대로 옮긴다(추정 금지)
  §4-3  region 은 GLOBAL 고정
  §4-4  author_key 는 계정명 그대로(작업층), 닉네임 원문은 봉인층
  §4-5  마스킹 후 작업층, 마스킹 전 raw_text 는 봉인층
  §5-1  모델·브랜드는 dictionary_v2 로만 — 자체 정규식 금지
  §5-6  전동화는 사전의 eG80·eGV70·EREV 항목으로 가른다(근접 매칭)

사용
    python3 scripts/reddit_parse.py --raw sealed/raw/GV80 --model GV80 \
        --window 202601_202608 --since 2026-01-01 --until 2026-08-31 \
        --out work --sealed sealed/records
"""
import argparse, json, os, re, sys, collections, datetime, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _console; _console.setup()
from cleanse_reddit_v1 import (normalize, mask, sha, BOT, COMMERCIAL, SPONSOR_DECL,
                               BMW7, NONCAR, GENESIS, SCHEMA_VERSION)
import dictionary_v2 as D

RULE_VERSION = "reddit-parse-v1 (2026-09-17)"
RX_MODEL = [(x.code, x.marque, x.canonical, re.compile(x.pattern, 0 if x.cs else re.I), x.cs)
            for x in D.MODELS]
RX_BRAND = [(x.brand, re.compile(x.pattern, re.I)) for x in D.BRANDS]
RX_WS = re.compile(r"\s+")

# 사전에서 전동화 변형인 항목. canonical 은 일반형이라 라벨을 따로 만든다.
EV_CODES = {"eG80": "Electrified G80", "eGV70": "Electrified GV70",
            "GV70 EREV": "Electrified GV70"}


def norm_cs(t):
    t = (t or "").replace("’", "'").replace("‘", "'")
    for a, b in (("‐", "-"), ("‑", "-"), ("–", "-"), ("—", "-")):
        t = t.replace(a, b)
    return RX_WS.sub(" ", t)


def match_models(text):
    """반환: (라벨 목록, 코드 카운터). cs 패턴은 대소문자를 살린 텍스트에 건다."""
    cs, lo = norm_cs(text), norm_cs(text).lower()
    counts, labels = collections.Counter(), []
    for code, mq, canon, rx, is_cs in RX_MODEL:
        n = len(rx.findall(cs if is_cs else lo))
        if n:
            counts[code] += n
            labels.append(EV_CODES.get(code, canon))
    return sorted(set(labels)), counts


def match_brands(text):
    lo = norm_cs(text).lower()
    return sorted({b for b, rx in RX_BRAND if rx.search(lo)})


# ------------------------------------------------------------------ raw 펼치기
def flatten(payload):
    """원응답에서 (본문, 댓글 목록)을 꺼낸다. 댓글은 parent_id 를 원문 그대로 보존."""
    listing = payload["listing"]
    post = ((listing[0].get("data") or {}).get("children") or [{}])[0].get("data") or {}
    out = []

    def walk(node, depth):
        if not isinstance(node, dict):
            return
        if node.get("kind") != "t1":
            return
        d = node.get("data") or {}
        out.append({"id": d.get("id"), "parent_id": d.get("parent_id"),
                    "author": d.get("author"), "body": d.get("body"),
                    "created_utc": d.get("created_utc"), "edited": d.get("edited"),
                    "score": d.get("score"), "depth": depth,
                    "permalink": d.get("permalink")})
        rep = d.get("replies")
        if isinstance(rep, dict):
            for ch in (rep.get("data") or {}).get("children") or []:
                walk(ch, depth + 1)

    for ch in ((listing[1].get("data") or {}).get("children") or []):
        walk(ch, 0)
    for th in payload.get("morechildren") or []:
        walk(th, -1)                      # 접혀 있던 댓글. 깊이는 parent_id 로 다시 세운다
    return post, out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--window", required=True)
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sealed", required=True)
    a = ap.parse_args()

    since = datetime.datetime.strptime(a.since, "%Y-%m-%d").replace(
        tzinfo=datetime.timezone.utc).timestamp()
    until = datetime.datetime.strptime(a.until, "%Y-%m-%d").replace(
        tzinfo=datetime.timezone.utc).timestamp() + 86399
    batch_id = "reddit-GLOBAL-%s-%s" % (a.window, a.model)
    prefix = "RD-GLOBAL-%s" % a.model

    files = sorted(f for f in os.listdir(a.raw) if f.endswith(".json") and not f.startswith("_"))
    threads = []
    for fn in files:
        payload = json.load(open(os.path.join(a.raw, fn), encoding="utf-8"))
        post, comments = flatten(payload)
        if not post.get("id"):
            continue
        threads.append((post, comments, payload))
    threads.sort(key=lambda x: x[0].get("created_utc") or 0)

    rep = collections.Counter()
    records, sealed, masking = [], [], collections.Counter()
    seq = 0
    for post, comments, payload in threads:
        tid = post["id"]
        # 구간 판정은 본문 게시일로 — 스레드가 구간에 걸치면 통째로 넣는다(§1)
        if not (since <= (post.get("created_utc") or 0) <= until):
            rep["drop_out_of_window"] += 1
            continue
        title = post.get("title") or ""
        body = post.get("selftext") or ""
        post_text = normalize((title + "\n\n" + body).strip())
        if len(post_text) < 20:
            rep["drop_length_short_post"] += 1
            continue
        full = " ".join([post_text] + [normalize(c.get("body") or "") for c in comments])
        sub = post.get("subreddit") or ""
        # 관련성 관문 — 대상 모델이 스레드 어디에도 없으면 버린다.
        # 검색이 댓글 언급까지 물어오므로(§2) 제목만 보고 판정하지 않는다.
        full_labels, _ = match_models(full)
        if a.model not in full_labels:
            rep["drop_no_target_model"] += 1
            continue
        if not (GENESIS.search(full) or sub.lower().startswith("genesis")):
            if NONCAR.search(full):
                rep["drop_collision_noncar"] += 1
                continue
            if BMW7.search(full) and a.model in ("G70", "G80", "G90"):
                rep["drop_collision_chassis"] += 1
                continue

        rows = [{"kind": "post", "id": tid, "parent": None, "author": post.get("author"),
                 "text": post_text, "created": post.get("created_utc"),
                 "score": post.get("score"), "permalink": post.get("permalink"),
                 "raw": (title + "\n\n" + body).strip()}]
        for c in comments:
            t = normalize(c.get("body") or "")
            if len(t) < 5:
                rep["excl_length_short_comment"] += 1
                continue
            if t in ("[deleted]", "[removed]"):
                rep["excl_deleted"] += 1
                continue
            rows.append({"kind": "comment", "id": c["id"], "parent": c.get("parent_id"),
                         "author": c.get("author"), "text": t, "created": c.get("created_utc"),
                         "score": c.get("score"), "permalink": c.get("permalink"),
                         "raw": c.get("body") or ""})
        rows[1:] = sorted(rows[1:], key=lambda r: r["created"] or 0)

        idmap, authors, seen = {}, {}, {}
        kept = []
        for r in rows:
            txt, ap_ = mask(r["text"])
            masking.update(ap_)
            limit = 5000 if r["kind"] == "post" else 2000
            trunc = len(txt) > limit
            if trunc:
                txt = txt[:limit]
                rep["truncated"] += 1
            ch = sha(txt)
            if ch in seen:                                  # §4-6 스레드 안에서만 중복 판정
                rep["excl_dup_in_thread"] += 1
                continue
            seen[ch] = True
            seq += 1
            rid = "%s-%06d" % (prefix, seq)
            idmap[r["id"]] = rid
            au = r["author"]
            ak = None if au in (None, "", "[deleted]") else "reddit:" + au
            authors[r["id"]] = ak
            kept.append((r, rid, txt, ch, trunc, ak))

        post_author = kept[0][5] if kept else None
        thread_models, _ = match_models(" ".join(k[2] for k in kept))
        for r, rid, txt, ch, trunc, ak in kept:
            parent_id = position = reply_to = None
            resolved = None
            if r["kind"] == "comment":
                praw = (r["parent"] or "")
                pid = praw.split("_", 1)[1] if "_" in praw else ""
                if praw.startswith("t3_"):
                    parent_id, position, resolved = idmap.get(tid), "top", True
                elif pid in idmap:
                    parent_id, position, resolved = idmap[pid], "reply", True
                    reply_to = authors.get(pid)
                else:
                    parent_id, position, resolved = idmap.get(tid), "reply", False
                    rep["parent_unresolved"] += 1       # 부모가 삭제·미수집인 경우만
                rep["pos_" + position] += 1
            mm, _ = match_models(txt)
            when = datetime.datetime.fromtimestamp(r["created"] or 0, datetime.timezone.utc)
            isbot = bool(BOT.search(txt))
            records.append({
                "record_id": rid, "record_id_orig": r["id"], "thread_key": "rd:" + tid,
                "unit": r["kind"], "position": position, "parent_id": parent_id,
                "platform": "reddit", "section": "r/" + sub,
                "region": "GLOBAL", "region_basis": "platform_global",
                "region_confidence": None, "region_note": None,
                "lang": "en", "lang_conf": None,
                "text": txt, "text_len": len(txt), "truncated": trunc,
                "posted_at": when.isoformat(), "posted_at_precision": "exact",
                "author_key": ak,
                "author_is_op": (None if ak is None or post_author is None
                                 else (ak == post_author and r["kind"] != "post")),
                "reply_to_key": reply_to, "parent_resolved": resolved,
                "same_speaker_suspect": None,
                "engagement": {"likes": r["score"], "replies": post.get("num_comments")
                               if r["kind"] == "post" else None, "views": None},
                "media_count": None, "media_types": [],
                "model_mentions": mm, "thread_model_mentions": thread_models,
                "brand_mentions": match_brands(txt),
                "brand_only": (not mm) and ("Genesis" in match_brands(txt)),
                "context_suspect": None,
                "sponsored_flag": "declared" if SPONSOR_DECL.search(txt) else "none",
                "official_source_flag": isbot, "official_source_provisional": True,
                "bot_flag": isbot, "minor_flag": False,
                "commercial_series": bool(COMMERCIAL.search(txt)),
                "attrs_prefill": None, "trim_variant_prefill": "none",
                "query_codes": [], "window": a.window, "batch_id": batch_id,
                "content_hash": ch, "near_dup_of": None,
                "comment_coverage": "%d/%d" % (len(kept) - 1, post.get("num_comments") or 0)
                                    if r["kind"] == "post" else None,
                "access_method": "api" if payload.get("auth") == "oauth" else "public_page",
                "collected_at": payload.get("fetched_at"),
                "schema_version": SCHEMA_VERSION,
            })
            sealed.append({
                "record_id": rid, "record_id_orig": r["id"], "thread_key": "rd:" + tid,
                "url": "https://www.reddit.com" + (r["permalink"] or ""),
                "thread_url": "https://www.reddit.com" + (post.get("permalink") or ""),
                "media_ids": [], "raw_text": r["raw"], "author_display": r["author"],
            })

    os.makedirs(a.out, exist_ok=True)
    os.makedirs(a.sealed, exist_ok=True)
    rp = os.path.join(a.out, "records_%s.jsonl" % batch_id)
    sp = os.path.join(a.sealed, "sealed_%s.jsonl" % batch_id)
    for path, data in ((rp, records), (sp, sealed)):
        with open(path, "w", encoding="utf-8") as f:
            for x in data:
                f.write(json.dumps(x, ensure_ascii=False) + "\n")

    posts = [r for r in records if r["unit"] == "post"]
    cov = []
    for r in posts:
        m = re.fullmatch(r"(\d+)/(\d+)", str(r.get("comment_coverage") or ""))
        if m and int(m.group(2)):
            cov.append(int(m.group(1)) / int(m.group(2)))
    dates = sorted(r["posted_at"][:10] for r in records)
    man = {
        "schema_version": SCHEMA_VERSION, "batch_id": batch_id,
        "platform": "reddit", "region": "GLOBAL", "model_label": a.model,
        "window": a.window, "window_type": "posted_date",
        "posted_at_range": {"min": dates[0] if dates else None,
                            "max": dates[-1] if dates else None},
        "attempted_searches": "reddit_fetch.py discover --log 산출물을 여기에 옮긴다",
        "target": 100, "collected_posts": len(posts),
        "collected_comments": len(records) - len(posts), "collected_records": len(records),
        "target_shortfall_reason": None,
        "excluded": {k: v for k, v in rep.items() if k.startswith(("drop_", "excl_"))},
        "relevance_check": {"threads": len(threads), "threads_with_target_model": len(posts),
                            "method": "dictionary_v2 모델·브랜드 매칭 + 충돌 패턴 스캔"},
        "collision_check": {"model": a.model,
                            "brand": "BMW" if a.model in ("G70", "G80", "G90") else None,
                            "sampled": len(threads),
                            "contaminated": rep.get("drop_collision_chassis", 0)
                                            + rep.get("drop_collision_noncar", 0),
                            "severity": "moderate" if a.model in ("G70", "G90", "G80") else "none"},
        "ev_split": {"applied": True, "rule": "dictionary_v2 eG80·eGV70·GV70 EREV (§5-6)",
                     "passed": None, "rejected": None},
        "unit_rule": "post = 스레드 본문, comment = 원응답 t1 노드",
        "parent_id_rule": "레딧 원응답의 parent_id 를 그대로 옮긴다. t3_ → 본문, t1_ → 상위 댓글",
        "parent_unresolved": rep.get("parent_unresolved", 0),
        "comment_coverage_mean": round(sum(cov) / len(cov), 3) if cov else None,
        "comment_coverage_threads_under_80pct": sum(1 for x in cov if x < 0.8),
        "keyword_dict_version": "dictionary_v2 (1차 배치 역도출)",
        "author_key_rule_version": "reddit-username-plain-v1",
        "author_key_cross_batch_linkable": True,
        "author_key_coverage": "%d/%d" % (sum(1 for r in records if r["author_key"]), len(records)),
        "masking_applied": sorted(k for k, v in masking.items() if v),
        "masking_counts": dict(masking),
        "known_nulls": ["engagement.views", "media_count(안 셌다 — 없는 것이 아니다)",
                        "lang_conf(영어 가정 고정값)", "attrs_prefill(코딩 단계에서 채운다)",
                        "minor_flag·official_source_flag(발주자 계정 목록 미수령)"],
        "access_method_counts": dict(collections.Counter(r["access_method"] for r in records)),
        "access_note": "레딧 공개 API. 원응답을 sealed/raw 에 보관한다 — 재파싱 가능",
        "parse_rule_version": RULE_VERSION,
        "cleansed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "checksums": {"records": hashlib.sha256(open(rp, "rb").read()).hexdigest(),
                      "sealed": hashlib.sha256(open(sp, "rb").read()).hexdigest()},
    }
    mp = os.path.join(a.out, "manifest_%s.json" % batch_id)
    json.dump(man, open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps({"threads": len(threads), "records": len(records),
                      "posts": len(posts), "rep": dict(rep),
                      "coverage_mean": man["comment_coverage_mean"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
