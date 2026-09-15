# -*- coding: utf-8 -*-
"""① screen.py — 스레드 단위 선별. LLM 호출 없음. 정규식·사전만.

사양
  - 스레드 단위로 묶어(thread_url) 점수·중복·화자지배를 계산한다.
  - 순위를 매기지 않는다. 점수는 임계값(>=3) 판정에만 쓴다.
  - 본문은 파일에서 파일로만 흐른다. stdout 에 본문을 내보내지 않는다.

이 배치(sealed reddit US)에 적용한 조정 — 전부 manifest 에 기록된다
  1) record_id 는 파일 로컬이다(파일 간 2,230건 충돌). 전역 키는 "파일::record_id".
  2) content_hash 는 필드가 없어 직접 계산하고, 중복 판정 범위를 스레드 안으로 한정한다.
     전역 해시 중복은 "Thanks" 같은 짧은 댓글을 다른 스레드끼리 합친다.
  3) unit 필드가 없다. 파일마다 규칙을 자동 판정한다(url_presence / min_record_id).
  4) author 해시가 없는 파일의 dominated 는 unknown.
  5) "모델+브랜드" 조항은 매칭된 모델의 마크와 다른 브랜드일 때만 인정한다.
     Genesis 는 거의 모든 행에 나오므로 글자 그대로 잡으면 임계값이 무의미해진다.

사용
  python3 scripts/screen.py --in sealed/records --out work/screen
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
import os
import re
import sys
import unicodedata
from glob import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
def load_dictionary(version):
    """사전 판을 불러와 (모델, 브랜드, 프로브, 판이름) 으로 돌려준다.
    v1 은 평튜플, v2 는 네임드튜플(cs·obs 필드 추가)이라 여기서 모양을 맞춘다."""
    if version == "v1":
        import dictionary_v1 as d
        models = [(c, mq, cn, p, False) for c, mq, cn, p in d.MODELS]
        brands = [(b, p) for b, p in d.BRANDS]
        probe = list(d.V2_PROBE)
        name = "keyword_dictionary_v1 (2026-09-04) §1 · §2-2 US"
    else:
        import dictionary_v2 as d
        models = [(x.code, x.marque, x.canonical, x.pattern, x.cs) for x in d.MODELS]
        brands = [(x.brand, x.pattern) for x in d.BRANDS]
        probe = list(d.PROBE)
        name = "keyword_dictionary_v2 (1차 배치 역도출) §1 · §2-2 US + 신규 %d" % sum(1 for x in d.MODELS if x.obs)
    return models, brands, probe, name

SCHEMA_VERSION = "screen_v1"
SELECT_THRESHOLD = 3
SIZE_BUCKETS = [(1, 1, "1"), (2, 3, "2-3"), (4, 10, "4-10"), (11, 30, "11-30"), (31, 10 ** 9, "31+")]

# ---------------------------------------------------------------- 정규식 층

# 사양의 플래그 정규식. 어두에 \b 만 걸고 그 외에는 사양 그대로 둔다.
FLAG_PATTERNS = {
    "cmp":  r"\b(?:vs|versus|or the|instead of|over the|compared|better than|rather than)",
    "fp":   r"\b(?:i bought|i own|my (?:g|gv)\s?\d0|test drove|traded|came from|i'm looking)",
    "q":    r"\b(?:should i|which|worth it)",
    "deal": r"\b(?:lease|msrp|deal|negotiat|apr|financ)",
    "qual": r"\b(?:recall|lemon|buyback|warranty|dealer.*(?:problem|issue|nightmare)|noise|defect)",
}
# 플래그별 대안 갈래 — manifest 진단용(어느 갈래가 플래그를 켰는지 센다)
FLAG_ALTERNATIVES = {
    "cmp":  ["vs", "versus", "or the", "instead of", "over the", "compared", "better than", "rather than"],
    "fp":   ["i bought", "i own", r"my (?:g|gv)\s?\d0", "test drove", "traded", "came from", "i'm looking"],
    "q":    ["should i", "which", "worth it"],
    "deal": ["lease", "msrp", "deal", "negotiat", "apr", "financ"],
    "qual": ["recall", "lemon", "buyback", "warranty", r"dealer.*(?:problem|issue|nightmare)", "noise", "defect"],
}

RX_FLAG = {k: re.compile(v, re.I) for k, v in FLAG_PATTERNS.items()}
RX_FLAG_ALT = {k: [(a, re.compile(r"\b(?:%s)" % a, re.I)) for a in v] for k, v in FLAG_ALTERNATIVES.items()}
# 검토 §2 A-2: 상업·시리즈 게시물. 중고차 수출 소싱 가이드 같은 연재물은
# 소비자 담론이 아니고 차명이 수십 개 나와 관계 추출기를 헷갈리게 한다.
COMMERCIAL_ALTERNATIVES = [
    ("(n/n)",     r"\(\d+\s*/\s*\d+\)"),
    ("deep dive", r"\bdeep dive\b"),
    ("auction",   r"\bauction\b"),
    ("export",    r"\bexport\b"),
]
RX_COMMERCIAL = re.compile("|".join(p for _, p in COMMERCIAL_ALTERNATIVES), re.I)
RX_COMMERCIAL_ALT = [(n, re.compile(p, re.I)) for n, p in COMMERCIAL_ALTERNATIVES]

RX_WS = re.compile(r"\s+")
RX_REDDIT_ID = re.compile(r"/comments/([a-z0-9]+)", re.I)


def normalize_cs(text: str) -> str:
    """공백·하이픈 정규화. 대소문자는 살린다 —
    렉서스 ES·IS 가 영어 단어 es/is 와 갈리는 유일한 단서다."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = t.replace("’", "'").replace("‘", "'")          # 곡선 어포스트로피
    t = t.replace("‐", "-").replace("‑", "-")          # 곡선 하이픈
    t = t.replace("–", "-").replace("—", "-")
    return RX_WS.sub(" ", t)


def normalize(text: str) -> str:
    """공백·하이픈·소문자 정규화. 매칭 전용 — 출력에는 쓰지 않는다."""
    return normalize_cs(text).lower()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).strip().encode("utf-8")).hexdigest()


def batch_of(filename: str) -> str:
    b = os.path.basename(filename)
    b = re.sub(r"^sealed_", "", b)
    b = re.sub(r"\.jsonl$", "", b)
    return b


def thread_key_of(url: str) -> str:
    """reddit 글 id 로 스레드 키를 만든다. 없으면 정규화한 URL."""
    u = (url or "").strip()
    m = RX_REDDIT_ID.search(u)
    if m:
        return "rd:" + m.group(1).lower()
    u = u.split("#", 1)[0].split("?", 1)[0].rstrip("/").lower()
    return "url:" + hashlib.sha256(u.encode("utf-8")).hexdigest()[:16]


def rec_num(record_id: str) -> int:
    m = re.search(r"(\d+)\s*$", record_id or "")
    return int(m.group(1)) if m else -1


# ---------------------------------------------------------------- 적재 · unit

def load_records(indir: str):
    rows, files = [], []
    for fp in sorted(glob(os.path.join(indir, "*.jsonl"))):
        n_lines = n_bad = 0
        for line in open(fp, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            n_lines += 1
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                n_bad += 1
                continue
            o["_file"] = os.path.basename(fp)
            o["_batch"] = batch_of(fp)
            o["_gid"] = "%s::%s" % (o["_file"], o.get("record_id", ""))
            o["_num"] = rec_num(o.get("record_id", ""))
            o["_tkey"] = thread_key_of(o.get("thread_url"))
            rows.append(o)
        files.append({
            "file": os.path.basename(fp),
            "batch": batch_of(fp),
            "bytes": os.path.getsize(fp),
            "lines": n_lines,
            "unparsable_lines": n_bad,
        })
    return rows, files


def decide_unit_rule(rows_of_file):
    """파일별 unit 추정 규칙을 자동 판정한다.

    url_presence   : url 이 채워진 행이 스레드당 정확히 1개 → 그 행이 post
    min_record_id  : url 이 단서가 못 될 때, 스레드 내 최소 record_id 를 post 로 [가설]
    """
    by_thread = collections.defaultdict(list)
    for r in rows_of_file:
        by_thread[r["_tkey"]].append(r)
    n_url = sum(1 for r in rows_of_file if r.get("url"))
    one_url_threads = sum(1 for rs in by_thread.values() if sum(1 for r in rs if r.get("url")) == 1)
    usable = one_url_threads == len(by_thread) and n_url < len(rows_of_file)

    # 두 규칙이 함께 성립하는 스레드에서 일치율을 재 둔다(대체 규칙의 근거)
    agree = checked = 0
    for rs in by_thread.values():
        u = [r for r in rs if r.get("url")]
        if len(u) == 1:
            checked += 1
            if u[0]["_num"] == min(r["_num"] for r in rs):
                agree += 1
    return {
        "rule": "url_presence" if usable else "min_record_id",
        "hypothesis": not usable,
        "threads": len(by_thread),
        "rows": len(rows_of_file),
        "rows_with_url": n_url,
        "threads_with_exactly_one_url_row": one_url_threads,
        "min_record_id_agreement": "%d/%d" % (agree, checked) if checked else "n/a",
    }


# ---------------------------------------------------------------- 매칭

def match_models(text_n: str, text_cs: str):
    """모델 출현을 센다. cs 패턴은 대소문자를 살린 텍스트에 건다."""
    counts, marque, canon = collections.Counter(), {}, {}
    for code, mq, cn, rx, cs in RX_MODEL:
        n = len(rx.findall(text_cs if cs else text_n))
        if n:
            counts[code] += n
            marque[code] = mq
            canon[code] = cn
    return counts, marque, canon


def match_brands(text_n: str):
    c = collections.Counter()
    for b, rx in RX_BRAND:
        n = len(rx.findall(text_n))
        if n:
            c[b] += n
    return c


# ---------------------------------------------------------------- 본체

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="indir", default="sealed/records")
    ap.add_argument("--out", dest="outdir", default="work/screen")
    ap.add_argument("--threshold", type=int, default=SELECT_THRESHOLD)
    ap.add_argument("--scope", choices=("post", "thread"), default="post",
                    help="정규식·사전을 걸 범위. 본문(post)이 기본 — coding_guide 의 '본문' 용법을 따른다.")
    ap.add_argument("--dict", choices=("v1", "v2"), default="v2", help="키워드 사전 판")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    global RX_MODEL, RX_BRAND, RX_PROBE, DICT_VERSION
    models, brands, probe, DICT_VERSION = load_dictionary(args.dict)
    RX_MODEL = [(c, mq, cn, re.compile(p, 0 if cs else re.I), cs) for c, mq, cn, p, cs in models]
    RX_BRAND = [(b, re.compile(p, re.I)) for b, p in brands]
    RX_PROBE = [(n, re.compile(p, re.I)) for n, p in probe]

    rows, files = load_records(args.indir)
    if not rows:
        print("입력 없음: %s" % args.indir, file=sys.stderr)
        return 1

    # --- unit 규칙을 파일별로 판정 ---
    by_file = collections.defaultdict(list)
    for r in rows:
        by_file[r["_file"]].append(r)
    unit_rules = {f: decide_unit_rule(rs) for f, rs in by_file.items()}

    # --- 스레드로 묶기(파일 간 같은 thread_url 은 한 스레드) ---
    by_thread = collections.defaultdict(list)
    for r in rows:
        by_thread[r["_tkey"]].append(r)

    # --- 중복 제거: 스레드 안에서 content_hash 로 1건화 ---
    dedup = {"cross_file_rows": 0, "within_file_rows": 0,
             "threads_spanning_files": 0, "rows_kept": 0, "rows_in": len(rows)}
    global_hash_groups = collections.defaultdict(list)
    for r in rows:
        global_hash_groups[content_hash(r.get("raw_text"))].append(r)
    dedup["alt_global_hash_rows_removed"] = len(rows) - len(global_hash_groups)
    dedup["alt_global_hash_cross_thread_groups"] = sum(
        1 for v in global_hash_groups.values()
        if len(v) > 1 and len({x["_tkey"] for x in v}) > 1)

    kept_by_thread = {}
    # 배치는 중복 제거 전에 잡는다. 제거 뒤에 세면 교차 파일 중복(dup_of)이 사라진다.
    thread_batches = {t: sorted({r["_batch"] for r in rs}) for t, rs in by_thread.items()}
    for tkey, rs in by_thread.items():
        if len({r["_file"] for r in rs}) > 1:
            dedup["threads_spanning_files"] += 1
        seen = {}
        for r in sorted(rs, key=lambda x: (x["_file"], x["_num"])):
            h = content_hash(r.get("raw_text"))
            if h in seen:
                if seen[h]["_file"] != r["_file"]:
                    dedup["cross_file_rows"] += 1
                else:
                    dedup["within_file_rows"] += 1
                continue
            seen[h] = r
        kept_by_thread[tkey] = list(seen.values())
        dedup["rows_kept"] += len(seen)

    # --- 스레드별 계산 ---
    out_rows = []
    score_hist = collections.Counter()
    flag_thread_counts = collections.Counter()
    flag_alt_counts = collections.Counter()
    v2_counts = collections.Counter()
    dominated_counts = collections.Counter()
    model_thread_counts = collections.Counter()
    brand_thread_counts = collections.Counter()
    naive_flip = 0
    scope_flip = 0
    commercial_alt_counts = collections.Counter()
    genesis_focus_counts = collections.Counter()
    top_partner_counts = collections.Counter()
    n_commercial = 0
    score_hist_alt = collections.Counter()
    size_stats = collections.defaultdict(lambda: {"threads": 0, "selected": 0, "score_sum": 0})

    for tkey in sorted(kept_by_thread):
        rs = kept_by_thread[tkey]
        batches = thread_batches[tkey]
        primary, dup_of = batches[0], ";".join(batches[1:])

        # post / comment
        post = None
        for f in sorted({r["_file"] for r in rs}):
            rule = unit_rules[f]["rule"]
            cand = [r for r in rs if r["_file"] == f]
            if rule == "url_presence":
                u = [r for r in cand if r.get("url")]
                if len(u) == 1:
                    post = u[0]
                    break
            if post is None:
                post = min(cand, key=lambda r: r["_num"])
        for r in rs:
            r["_unit"] = "post" if r is post else "comment"
        n_comments = sum(1 for r in rs if r["_unit"] == "comment")

        # 본문 = 게시물 본문(댓글의 반대말). coding_guide §3-1·§3-9 의 용법.
        post_cs = normalize_cs(post.get("raw_text") or "")
        thread_cs = normalize_cs(" \n ".join(r.get("raw_text") or "" for r in rs))
        post_n, thread_n = post_cs.lower(), thread_cs.lower()
        title_n = normalize(((post.get("raw_text") or "").strip().splitlines() or [""])[0])

        def evaluate(text_n, text_cs):
            fl = {k: bool(rx.search(text_n)) for k, rx in RX_FLAG.items()}
            fl["q"] = fl["q"] or title_n.endswith("?")
            mc, mq_map, cn_map = match_models(text_n, text_cs)
            bc = match_brands(text_n)
            cmods = {cn_map[c] for c in mc}
            mmarq = {mq_map[c] for c in mc}
            xbrands = [b for b in bc if b not in mmarq]
            p_strict = len(cmods) >= 2 or (len(mc) >= 1 and len(xbrands) >= 1)
            p_naive = len(cmods) >= 2 or (len(mc) >= 1 and len(bc) >= 1)
            d_only = fl["deal"] and not (fl["cmp"] or fl["fp"] or fl["q"] or fl["qual"])
            b = fl["cmp"] * 2 + fl["fp"] + fl["q"] + fl["qual"] - (1 if d_only else 0)
            return {"flags": fl, "mcounts": mc, "bcounts": bc, "marque": mq_map,
                    "score": b + (2 if p_strict else 0), "score_naive": b + (2 if p_naive else 0)}

        ev_post, ev_thread = evaluate(post_n, post_cs), evaluate(thread_n, thread_cs)
        ev = ev_post if args.scope == "post" else ev_thread
        ev_alt = ev_thread if args.scope == "post" else ev_post
        body_n = post_n if args.scope == "post" else thread_n

        flags, mcounts, bcounts = ev["flags"], ev["mcounts"], ev["bcounts"]
        score, score_naive = ev["score"], ev["score_naive"]

        for k, v in flags.items():
            if v:
                flag_thread_counts[k] += 1
                for alt, rx in RX_FLAG_ALT[k]:
                    if rx.search(body_n):
                        flag_alt_counts["%s::%s" % (k, alt)] += 1
                if k == "q" and title_n.endswith("?"):
                    flag_alt_counts["q::title_ends_with_?"] += 1
        for c in mcounts:
            model_thread_counts[c] += 1
        for b in bcounts:
            brand_thread_counts[b] += 1
        for n, rx in RX_PROBE:
            if rx.search(body_n):
                v2_counts[n] += 1

        if (score >= args.threshold) != (score_naive >= args.threshold):
            naive_flip += 1
        if (score >= args.threshold) != (ev_alt["score"] >= args.threshold):
            scope_flip += 1
        score_hist[score] += 1
        score_hist_alt[ev_alt["score"]] += 1
        size_bucket = next(lab for lo, hi, lab in SIZE_BUCKETS if lo <= len(rs) <= hi)
        size_stats[size_bucket]["threads"] += 1
        size_stats[size_bucket]["score_sum"] += score
        if score >= args.threshold:
            size_stats[size_bucket]["selected"] += 1

        # 화자 지배
        hashes = [r.get("author_id_hash_full") for r in rs]
        if any(not h for h in hashes):
            dominated, n_speakers = "unknown", ""
        else:
            c = collections.Counter(hashes)
            n_speakers = len(c)
            dominated = "true" if c.most_common(1)[0][1] / len(rs) > 0.5 else "false"
        dominated_counts[dominated] += 1

        # A-1: 노드 A 는 제네시스 모델이어야 한다(coding_guide §3-1). "본문 최다 모델"
        # 하나로는 경쟁차가 초점으로 잡혀 모델별 할당이 어긋난다. 열을 둘로 나눈다.
        marque = ev["marque"]
        def _top(pred):
            c = [(k, v) for k, v in mcounts.items() if pred(marque.get(k))]
            return sorted(c, key=lambda kv: (-kv[1], kv[0]))[0][0] if c else ""
        genesis_focus = _top(lambda mq: mq == "Genesis")
        top_partner = _top(lambda mq: mq != "Genesis")
        genesis_focus_counts[genesis_focus or "(없음)"] += 1
        if top_partner:
            top_partner_counts[top_partner] += 1

        # A-2: 상업·시리즈 게시물은 표시하고 선별에서 뺀다. 점수 산식은 건드리지 않는다.
        commercial = bool(RX_COMMERCIAL.search(post_n))
        if commercial:
            n_commercial += 1
            for nm, rx in RX_COMMERCIAL_ALT:
                if rx.search(post_n):
                    commercial_alt_counts[nm] += 1

        out_rows.append({
            "thread_key": tkey,
            "batch": primary,
            "genesis_focus": genesis_focus,
            "top_partner": top_partner,
            "models": ";".join(sorted(mcounts, key=lambda c: (-mcounts[c], c))),
            "brands": ";".join(sorted(bcounts, key=lambda b: (-bcounts[b], b))),
            "n_rows": len(rs),
            "n_comments": n_comments,
            "n_speakers": n_speakers,
            "screen_score": score,
            "flags": "+".join(k for k in ("cmp", "fp", "q", "deal", "qual") if flags[k]),
            "commercial_series": "true" if commercial else "false",
            "dominated": dominated,
            # 화자 해시가 없어 같은 사람의 발화를 구분할 수 없다. 소넷이 채운다(검토 §4).
            "same_speaker_suspect": "",
            "dup_of": dup_of,
            "first_120_chars": post_n[:120],
        })

    # --- 출력: 순위를 매기지 않는다. thread_key 순으로만 쓴다 ---
    cols = ["thread_key", "batch", "genesis_focus", "top_partner", "models", "brands",
            "n_rows", "n_comments", "n_speakers", "screen_score", "flags", "commercial_series",
            "dominated", "same_speaker_suspect", "dup_of", "first_120_chars"]
    csv_path = os.path.join(args.outdir, "screen_rows.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(out_rows)

    over_threshold = [r for r in out_rows if r["screen_score"] >= args.threshold]
    selected = [r for r in over_threshold if r["commercial_series"] != "true"]
    with open(os.path.join(args.outdir, "selected_threads.txt"), "w", encoding="utf-8") as fh:
        for r in sorted(selected, key=lambda r: r["thread_key"]):
            fh.write(r["thread_key"] + "\n")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "dictionary_version": DICT_VERSION,
        "dictionary_arg": args.dict,
        "select_threshold": args.threshold,
        "note_ranking": "순위를 매기지 않는다. 점수는 임계값 판정에만 쓴다.",
        "input_files": files,
        "unit_rules_per_file": unit_rules,
        "dedup": dedup,
        "threads_total": len(out_rows),
        "rows_after_dedup": dedup["rows_kept"],
        "text_scope": {
            "applied": args.scope,
            "meaning": "post = 게시물 본문만. coding_guide 는 '본문'을 댓글의 반대말로 쓴다(§3-1·§3-9).",
            "why_not_thread": "스레드 전체를 붙이면 긴 스레드가 자동으로 전 플래그를 켜 점수가 길이의 대리 지표가 된다.",
            "threads_whose_selection_flips_under_other_scope": scope_flip,
        },
        "score_histogram": {str(k): score_hist[k] for k in sorted(score_hist)},
        "score_histogram_other_scope": {str(k): score_hist_alt[k] for k in sorted(score_hist_alt)},
        "size_bias_check": {
            lab: {"threads": v["threads"], "selected": v["selected"],
                  "selected_share": round(v["selected"] / v["threads"], 3) if v["threads"] else 0,
                  "mean_score": round(v["score_sum"] / v["threads"], 2) if v["threads"] else 0}
            for lab, v in sorted(size_stats.items(), key=lambda kv: [b[2] for b in SIZE_BUCKETS].index(kv[0]))
        },
        "selected_over_threshold": len(over_threshold),
        "selected_count": len(selected),
        "commercial_series": {
            "rule": "본문에 (n/n)·deep dive·auction·export 가 있으면 true. 점수는 그대로 두고 선별에서만 뺀다.",
            "threads_flagged": n_commercial,
            "excluded_from_selection": len(over_threshold) - len(selected),
            "alternative_hits": dict(commercial_alt_counts.most_common()),
        },
        "genesis_focus_distribution": dict(genesis_focus_counts.most_common()),
        "top_partner_distribution": dict(top_partner_counts.most_common()),
        "same_speaker_suspect": "열만 두고 값은 비운다. 화자 해시가 없어 코드가 판정할 수 없다 — 소넷이 채운다(검토 §4).",
        "selected_share": round(len(selected) / len(out_rows), 4) if out_rows else 0,
        "brand_rule": {
            "applied": "cross_marque — 매칭된 모델의 마크와 다른 브랜드만 '모델+브랜드'로 인정",
            "reason": "Genesis 가 거의 모든 행에 나와 순진한 규칙은 임계값을 무의미하게 만든다",
            "threads_whose_selection_flips_under_naive_rule": naive_flip,
        },
        "flag_thread_counts": dict(flag_thread_counts.most_common()),
        "flag_alternative_hits": dict(flag_alt_counts.most_common()),
        "flag_patterns": FLAG_PATTERNS,
        "dominated_counts": dict(dominated_counts.most_common()),
        "model_thread_counts": dict(model_thread_counts.most_common()),
        "brand_thread_counts": dict(brand_thread_counts.most_common()),
        "dictionary_next_probe_not_scored": dict(v2_counts.most_common()),
        "outputs": {
            "rows_csv": csv_path,
            "selected_threads": os.path.join(args.outdir, "selected_threads.txt"),
        },
    }
    with open(os.path.join(args.outdir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    # 본문은 절대 stdout 으로 내보내지 않는다 — 건수만.
    print("threads=%d  rows_in=%d  rows_kept=%d  selected(>=%d)=%d"
          % (len(out_rows), dedup["rows_in"], dedup["rows_kept"], args.threshold, len(selected)))
    print("wrote %s, manifest.json, selected_threads.txt" % csv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
