# -*- coding: utf-8 -*-
"""③ 추출 품질 게이트 도구 — 경량 코딩(relation_lite) 산출물의 병합·검사·집계·표본 팩.

  merge     (thread_key, record_id) 복합키 병합. record_id 단독 중복을 따로 센다.
  validate  --lite : enum · 인용 15단어 · direction 규칙 · node_a 목록 검사.
  stats     건수 집계. 비율을 내지 않는다 — 판정은 게이트에서 사람이 한다.
  pack      게이트 표본 팩. 청크마다 5 스레드(최다 1 · 빈 1 · 무작위 3),
            팩 = 통글(청크 원문) + 소넷 산출 줄. 그 둘 말고는 넣지 않는다.

본문은 파일에서 파일로만 흐른다. 팩은 work/ 아래에 남고 커밋하지 않는다.
"""
from __future__ import annotations

import argparse
import collections
import csv
import glob
import hashlib
import json
import os
import random
import re
import sys

# ── 규칙 상수 ────────────────────────────────────────────────────────────────
B_TYPES = ("B", "I-G", "I-H", "PT-variant")
EDGES = ("CO", "CP", "SUB-review", "SUB-choice", "TR")
UNITS = ("post", "comment")
CONFIDENCES = ("high", "mid", "low")
QUOTE_MAX_WORDS = 15
ARROW = "→"          # →
MIDDOT = "·"         # ·

# node_a 허용 목록 — 이 배치(G80·G90·GV60Magma)의 제네시스 라인업 차명.
# 코딩 가이드의 목록을 세션 밖에서 확인하지 못했다. 이 기본값은 잠정이며
# --node-a-list 로 갈아끼운다. 목록을 바꾸면 검사 결과가 바뀐다.
NODE_A_ALLOWED = [
    "G70", "G80", "G90",
    "GV60", "GV70", "GV80",
    "Electrified G80", "Electrified GV70",
    "GV60 Magma", "GV80 Coupe",
]
# 차명이 아니라 브랜드 층위. 목록 밖이지만 성격이 달라 따로 센다.
NODE_A_BRAND = ["Genesis"]

PAREN_RE = re.compile(r"^(?P<base>[^()]+?)\s*\((?P<anno>.+)\)$")


# ── 입출력 ───────────────────────────────────────────────────────────────────
def chunk_no(path: str) -> str:
    """파일명에서 청크 번호. 못 찾으면 파일명 그대로."""
    m = re.search(r"chunk_?(\d+)", os.path.basename(path))
    return "%02d" % int(m.group(1)) if m else os.path.basename(path)


def expand(spec: str) -> list:
    """디렉터리 · glob · 파일 경로를 파일 목록으로."""
    if os.path.isdir(spec):
        out = sorted(glob.glob(os.path.join(spec, "*.jsonl")))
    else:
        out = sorted(glob.glob(spec))
    if not out:
        sys.exit("입력 없음: %s" % spec)
    return out


def load_lite(spec: str) -> list:
    """소넷 산출 줄을 읽는다. 줄 하나가 스레드 하나."""
    threads = []
    for path in expand(spec):
        cn = chunk_no(path)
        for i, line in enumerate(open(path, encoding="utf-8"), 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                sys.exit("%s:%d JSON 파싱 실패 — %s" % (path, i, e))
            obj["_chunk"] = cn
            obj["_file"] = os.path.basename(path)
            obj["_line"] = i
            threads.append(obj)
    return threads


def load_src(spec: str) -> dict:
    """청크 원문(통글). thread_key → 원문 스레드."""
    src = {}
    for path in expand(spec):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line:
                o = json.loads(line)
                src[o["thread_key"]] = o
    return src


def rels(threads: list):
    """(스레드, 관계, 관계 인덱스) 평탄화."""
    for t in threads:
        for j, r in enumerate(t.get("relations") or []):
            yield t, r, j


def w(fh, s=""):
    fh.write(s + "\n")


def table(fh, header, rows):
    w(fh, "| " + " | ".join(header) + " |")
    w(fh, "|" + "|".join(["---"] * len(header)) + "|")
    for r in rows:
        w(fh, "| " + " | ".join(str(c) for c in r) + " |")


# ── ① 병합 ───────────────────────────────────────────────────────────────────
def cmd_merge(args):
    threads = load_lite(args.lite)
    merged, dup_pairs = [], []
    by_ckey = {}
    rid_threads = collections.defaultdict(set)   # record_id → {thread_key}
    rid_rows = collections.defaultdict(list)

    for t, r, j in rels(threads):
        tk, rid = t["thread_key"], r["record_id"]
        ck = (tk, rid)
        row = dict(r)
        row["thread_key"] = tk
        row["chunk"] = t["_chunk"]
        row["same_speaker_suspect"] = t.get("same_speaker_suspect")
        row["rel_ix"] = j
        merged.append(row)
        by_ckey.setdefault(ck, []).append(row)
        rid_threads[rid].add(tk)
        rid_rows[rid].append(row)

    # record_id 단독 중복 = 같은 record_id 가 둘 이상의 thread_key 에 걸친 건
    solo = {rid: tks for rid, tks in rid_threads.items() if len(tks) > 1}
    for rid, tks in sorted(solo.items()):
        tk_list = sorted(tks)
        chunks = sorted({r["chunk"] for r in rid_rows[rid]})
        for a in range(len(tk_list)):
            for b in range(a + 1, len(tk_list)):
                dup_pairs.append({
                    "record_id": rid, "thread_a": tk_list[a], "thread_b": tk_list[b],
                    "chunks": "+".join(chunks),
                    "n_rel": len(rid_rows[rid]),
                })

    os.makedirs(args.out, exist_ok=True)
    mpath = os.path.join(args.out, "relation_lite_merged.jsonl")
    with open(mpath, "w", encoding="utf-8") as fh:
        for row in merged:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    rpath = os.path.join(args.out, "merge_report.md")
    with open(rpath, "w", encoding="utf-8") as fh:
        w(fh, "# ① 병합 — (thread_key, record_id) 복합키\n")
        table(fh, ["항목", "건수"], [
            ["입력 파일", len(expand(args.lite))],
            ["스레드", len(threads)],
            ["관계 행", len(merged)],
            ["복합키 (thread_key, record_id)", len(by_ckey)],
            ["record_id 단독 값", len(rid_threads)],
            ["record_id 단독 중복 값", len(solo)],
            ["중복이 낳은 스레드 쌍", len(dup_pairs)],
            ["중복 record_id 가 걸친 관계 행", sum(len(rid_rows[r]) for r in solo)],
        ])
        w(fh, "\n복합키로 묶으면 충돌이 없다. record_id 만으로 묶으면 위 %d 값이 서로 다른 "
              "스레드를 하나로 합친다.\n" % len(solo))
        w(fh, "\n## record_id 단독 중복 — 관련 스레드 쌍\n")
        if dup_pairs:
            table(fh, ["record_id", "스레드 A", "스레드 B", "청크", "관계 행"],
                  [[d["record_id"], d["thread_a"], d["thread_b"], d["chunks"], d["n_rel"]]
                   for d in dup_pairs])
        else:
            w(fh, "없음.")

    with open(os.path.join(args.out, "merge_dup_record_id.csv"), "w",
              encoding="utf-8", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=["record_id", "thread_a", "thread_b", "chunks", "n_rel"])
        wr.writeheader()
        wr.writerows(dup_pairs)

    print("병합 %d행 → %s" % (len(merged), mpath))
    print("record_id 단독 중복 %d값 / 스레드 쌍 %d" % (len(solo), len(dup_pairs)))
    return 0


# ── ② 검사 ───────────────────────────────────────────────────────────────────
def classify_node_a(v: str, allowed: list) -> tuple:
    """(분류, 기준 차명). 분류 = ok | paren | joined | brand | unknown"""
    if MIDDOT in v:
        return "joined", v
    if v in allowed:
        return "ok", v
    if v in NODE_A_BRAND:
        return "brand", v
    m = PAREN_RE.match(v)
    if m:
        base = m.group("base").strip()
        return "paren", base
    return "unknown", v


def cmd_validate(args):
    allowed = list(NODE_A_ALLOWED)
    if args.node_a_list:
        allowed = [l.strip() for l in open(args.node_a_list, encoding="utf-8")
                   if l.strip() and not l.startswith("#")]
    threads = load_lite(args.lite)
    issues = []
    na_kind = collections.Counter()
    na_out = collections.defaultdict(list)   # 분류 → [(값, thread_key, record_id)]

    seen_tk = collections.Counter()
    for t in threads:
        seen_tk[t["thread_key"]] += 1
        if "relations" not in t:
            issues.append((t["_chunk"], t["thread_key"], "", "schema",
                           "relations 칸 없음"))
        if not isinstance(t.get("same_speaker_suspect"), bool):
            issues.append((t["_chunk"], t["thread_key"], "", "schema",
                           "same_speaker_suspect 가 불리언이 아님: %r"
                           % t.get("same_speaker_suspect")))
    for tk, n in seen_tk.items():
        if n > 1:
            issues.append(("", tk, "", "schema", "thread_key 가 %d줄에 중복" % n))

    for t, r, j in rels(threads):
        loc = (t["_chunk"], t["thread_key"], "%s#%d" % (r.get("record_id", "?"), j))

        # enum
        for field, ok in (("unit", UNITS), ("b_type", B_TYPES),
                          ("edge", EDGES), ("confidence", CONFIDENCES)):
            v = r.get(field)
            if v not in ok:
                issues.append(loc + ("enum", "%s=%r 은 허용값 %s 밖" % (field, v, list(ok))))
        if not isinstance(r.get("first_person"), bool):
            issues.append(loc + ("enum", "first_person 이 불리언이 아님: %r"
                                 % r.get("first_person")))
        for field in ("record_id", "node_a", "node_b", "quote"):
            if not isinstance(r.get(field), str) or not r.get(field).strip():
                issues.append(loc + ("schema", "%s 가 비었거나 문자열이 아님" % field))

        # 인용 15단어
        q = r.get("quote") or ""
        nw = len(q.split())
        if nw > QUOTE_MAX_WORDS:
            issues.append(loc + ("quote15", "인용 %d단어 (상한 %d): %s"
                                 % (nw, QUOTE_MAX_WORDS, q)))

        # direction
        e, d = r.get("edge"), r.get("direction")
        if e == "CO":
            if d is not None:
                issues.append(loc + ("direction", "CO 인데 direction=%r (null 이어야 함)" % d))
        elif e == "SUB-review":
            if d != "?":
                issues.append(loc + ("direction", "SUB-review 인데 direction=%r ('?' 이어야 함)" % d))
        elif e in ("SUB-choice", "TR"):
            if not isinstance(d, str) or ARROW not in d:
                issues.append(loc + ("direction", "%s 인데 direction=%r (출발→도착 이어야 함)" % (e, d)))
        elif e == "CP":
            if not isinstance(d, str) or not d.strip():
                issues.append(loc + ("direction", "CP 인데 direction=%r (승자 라벨 또는 '?')" % d))

        # node_a
        v = r.get("node_a") or ""
        kind, base = classify_node_a(v, allowed)
        na_kind[kind] += 1
        if kind != "ok":
            na_out[kind].append((v, t["thread_key"], r.get("record_id"), base))
            tag = {"joined": "node_a_joined", "brand": "node_a_brand",
                   "paren": "node_a_paren", "unknown": "node_a_unknown"}[kind]
            msg = {"joined": "'·' 결합 node_a — 화자 발화 기준이면 행 분할이어야 함",
                   "brand": "브랜드 층위(차명 아님)",
                   "paren": "괄호 표기 — 기준 차명 %s%s" % (
                       base, "" if base in allowed else " (기준 차명도 목록 밖)"),
                   "unknown": "목록 밖"}[kind]
            issues.append(loc + (tag, "node_a=%r — %s" % (v, msg)))

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "validate_issues.csv"), "w",
              encoding="utf-8", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["chunk", "thread_key", "record_id#ix", "rule", "detail"])
        wr.writerows(issues)

    by_rule = collections.Counter(i[3] for i in issues)
    rpath = os.path.join(args.out, "validate_report.md")
    with open(rpath, "w", encoding="utf-8") as fh:
        w(fh, "# ② validate --lite\n")
        w(fh, "검사 대상: 스레드 %d · 관계 %d\n" % (len(threads), sum(1 for _ in rels(threads))))
        w(fh, "\n## 규칙별 위반 건수\n")
        table(fh, ["규칙", "건수"],
              [[k, by_rule[k]] for k in ["enum", "quote15", "direction", "node_a_joined",
                                         "node_a_paren", "node_a_brand", "node_a_unknown",
                                         "schema"]] + [["합계", len(issues)]])
        w(fh, "\n## node_a 분류\n")
        table(fh, ["분류", "건수"],
              [["목록 안(ok)", na_kind["ok"]], ["괄호 표기(paren)", na_kind["paren"]],
               ["'·' 결합(joined)", na_kind["joined"]], ["브랜드 층위(brand)", na_kind["brand"]],
               ["목록 밖(unknown)", na_kind["unknown"]]])

        w(fh, "\n## 목록 밖 node_a 전수 (괄호 표기 포함)\n")
        rows = []
        grouped = collections.defaultdict(list)
        for kind in ("paren", "brand", "unknown"):
            for v, tk, rid, base in na_out[kind]:
                grouped[(kind, v, base)].append((tk, rid))
        for (kind, v, base), where in sorted(grouped.items(), key=lambda x: (x[0][0], -len(x[1]), x[0][1])):
            rows.append([{"paren": "괄호", "brand": "브랜드", "unknown": "미상"}[kind],
                         v, base, len(where),
                         " · ".join("%s/%s" % (a, b) for a, b in where[:4])
                         + (" …" if len(where) > 4 else "")])
        table(fh, ["분류", "node_a", "기준 차명", "건수", "출현(스레드/record_id)"], rows or [["", "없음", "", "", ""]])

        w(fh, "\n## '·' 결합 node_a 전수\n")
        rows = [[v, tk, rid] for v, tk, rid, _ in na_out["joined"]]
        table(fh, ["node_a", "thread_key", "record_id"], rows or [["없음", "", ""]])

        w(fh, "\n## 15단어 초과 인용 전수\n")
        rows = [[i[0], i[1], i[2], i[4]] for i in issues if i[3] == "quote15"]
        table(fh, ["청크", "thread_key", "record_id#ix", "내용"], rows or [["", "없음", "", ""]])

        w(fh, "\n## direction 위반 전수\n")
        rows = [[i[0], i[1], i[2], i[4]] for i in issues if i[3] == "direction"]
        table(fh, ["청크", "thread_key", "record_id#ix", "내용"], rows or [["", "없음", "", ""]])

        w(fh, "\n## enum 위반 전수\n")
        rows = [[i[0], i[1], i[2], i[4]] for i in issues if i[3] == "enum"]
        table(fh, ["청크", "thread_key", "record_id#ix", "내용"], rows or [["", "없음", "", ""]])

        w(fh, "\n적용한 node_a 목록: %s\n" % ", ".join(allowed))
    print("검사 완료 — 위반 %d건 → %s" % (len(issues), rpath))
    for k, v in by_rule.most_common():
        print("  %-16s %d" % (k, v))
    return 1 if issues else 0


# ── ③ 집계 ───────────────────────────────────────────────────────────────────
def cmd_stats(args):
    threads = load_lite(args.lite)
    per_chunk = collections.Counter()
    per_chunk_threads = collections.Counter()
    per_thread = {}
    c_edge = collections.Counter()
    c_btype = collections.Counter()
    c_fp = collections.Counter()
    c_conf = collections.Counter()
    n_qmark = 0
    n_same_speaker = 0

    for t in threads:
        n = len(t.get("relations") or [])
        per_chunk[t["_chunk"]] += n
        per_chunk_threads[t["_chunk"]] += 1
        per_thread[t["thread_key"]] = n
        if t.get("same_speaker_suspect") is True:
            n_same_speaker += 1
    for t, r, j in rels(threads):
        c_edge[r.get("edge")] += 1
        c_btype[r.get("b_type")] += 1
        c_fp[bool(r.get("first_person"))] += 1
        c_conf[r.get("confidence")] += 1
        if r.get("direction") == "?":
            n_qmark += 1

    counts = sorted(per_thread.values())
    n = len(counts)
    median = (counts[n // 2] if n % 2 else (counts[n // 2 - 1] + counts[n // 2]) / 2) if n else 0
    mx = max(counts) if counts else 0
    mx_thread = [k for k, v in per_thread.items() if v == mx]

    os.makedirs(args.out, exist_ok=True)
    rpath = os.path.join(args.out, "stats_report.md")
    with open(rpath, "w", encoding="utf-8") as fh:
        w(fh, "# ③ 집계 — 건수만. 비율·경향을 내지 않는다.\n")
        w(fh, "\n## 청크별 관계 수\n")
        table(fh, ["청크", "스레드", "관계"],
              [[c, per_chunk_threads[c], per_chunk[c]] for c in sorted(per_chunk)]
              + [["합계", sum(per_chunk_threads.values()), sum(per_chunk.values())]])
        w(fh, "\n## 스레드당 관계 수 분포\n")
        table(fh, ["항목", "값"],
              [["스레드", n], ["최대", mx], ["최대 스레드", " · ".join(sorted(mx_thread))],
               ["중앙", median], ["관계 0 스레드", sum(1 for v in counts if v == 0)]])
        w(fh, "\n관계 수별 스레드 수:\n")
        hist = collections.Counter(counts)
        table(fh, ["관계 수", "스레드 수"], [[k, hist[k]] for k in sorted(hist)])
        w(fh, "\n## edge별\n")
        table(fh, ["edge", "건수"], [[k, c_edge[k]] for k in EDGES if c_edge[k]]
              + [[k, v] for k, v in c_edge.items() if k not in EDGES]
              + [["합계", sum(c_edge.values())]])
        w(fh, "\n## b_type별\n")
        table(fh, ["b_type", "건수"], [[k, c_btype[k]] for k in B_TYPES if c_btype[k]]
              + [[k, v] for k, v in c_btype.items() if k not in B_TYPES]
              + [["합계", sum(c_btype.values())]])
        w(fh, "\n## first_person\n")
        table(fh, ["first_person", "건수"], [["true", c_fp[True]], ["false", c_fp[False]]])
        w(fh, "\n## confidence별\n")
        table(fh, ["confidence", "건수"], [[k, c_conf[k]] for k in CONFIDENCES if c_conf[k]]
              + [[k, v] for k, v in c_conf.items() if k not in CONFIDENCES]
              + [["합계", sum(c_conf.values())]])
        w(fh, "\n## 그 밖\n")
        table(fh, ["항목", "건수"],
              [["direction 이 '?' 인 관계", n_qmark],
               ["same_speaker_suspect=true 스레드", n_same_speaker]])
    print("집계 → %s" % rpath)
    return 0


# ── ④ 게이트 표본 팩 ─────────────────────────────────────────────────────────
def pick(threads_of_chunk: list, n_random: int, seed_base: str) -> list:
    """최다 1 + relations:[] 1 + 무작위 n. 청크 이름으로 시드를 고정한다."""
    picks, why = [], {}
    by_key = {t["thread_key"]: t for t in threads_of_chunk}
    ordered = sorted(threads_of_chunk, key=lambda t: t["thread_key"])

    top = max(ordered, key=lambda t: (len(t.get("relations") or []), ))
    # 동률이면 thread_key 사전순 첫째 — 무작위성을 쓰지 않는다
    mx = len(top.get("relations") or [])
    top = min([t for t in ordered if len(t.get("relations") or []) == mx],
              key=lambda t: t["thread_key"])
    picks.append(top["thread_key"]); why[top["thread_key"]] = "관계 최다(%d)" % mx

    empties = [t for t in ordered if not (t.get("relations") or [])]
    rng = random.Random(hashlib.sha256(("gate/" + seed_base).encode()).hexdigest())
    if empties:
        e = rng.choice(empties)
        picks.append(e["thread_key"]); why[e["thread_key"]] = "relations:[]"
    rest = [t["thread_key"] for t in ordered if t["thread_key"] not in picks]
    rng.shuffle(rest)
    for tk in rest[:n_random]:
        picks.append(tk); why[tk] = "무작위"
    return [(tk, why[tk], by_key[tk]) for tk in picks]


def cmd_pack(args):
    threads = load_lite(args.lite)
    src = load_src(args.chunks) if args.chunks else {}
    by_chunk = collections.defaultdict(list)
    for t in threads:
        by_chunk[t["_chunk"]].append(t)

    os.makedirs(args.out, exist_ok=True)
    packdir = os.path.join(args.out, "pack")
    os.makedirs(packdir, exist_ok=True)

    chunks = sorted(by_chunk)
    selection, missing_src = [], []
    picked = {}
    for c in chunks:
        picked[c] = pick(by_chunk[c], args.random, c)

    # 오푸스 세션당 청크 args.per_session 개
    sessions = [chunks[i:i + args.per_session] for i in range(0, len(chunks), args.per_session)]
    for si, sc in enumerate(sessions, 1):
        path = os.path.join(packdir, "gate_pack_session_%02d.jsonl" % si)
        with open(path, "w", encoding="utf-8") as fh:
            for c in sc:
                for tk, why, t in picked[c]:
                    lite = {k: v for k, v in t.items() if not k.startswith("_")}
                    entry = {"thread_key": tk, "chunk": c, "lite": lite}
                    if src:
                        s = src.get(tk)
                        if s is None:
                            missing_src.append((c, tk))
                        else:
                            entry["source"] = s      # 통글 — 청크 원문 그대로
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    selection.append([si, c, tk, why, len(t.get("relations") or []),
                                      "있음" if (src and tk in src) else "없음"])
        print("세션 %02d  청크 %s  %d스레드 → %s"
              % (si, "+".join(sc), sum(len(picked[c]) for c in sc), path))

    # 팩 내용 자물쇠 — 통글과 소넷 산출 줄 말고는 들어가지 못한다.
    # manifest · 검토 문서 · 판정 문서 §1 은 팩에 넣지 않는다. §1 은 오푸스 프롬프트 안에 있다.
    ENTRY_KEYS = {"thread_key", "chunk", "lite", "source"}
    LITE_KEYS = {"thread_key", "relations", "same_speaker_suspect", "note"}
    bad = []
    for path in sorted(glob.glob(os.path.join(packdir, "*.jsonl"))):
        for i, line in enumerate(open(path, encoding="utf-8"), 1):
            o = json.loads(line)
            extra = set(o) - ENTRY_KEYS
            if extra:
                bad.append("%s:%d 팩에 없어야 할 칸 %s" % (os.path.basename(path), i, sorted(extra)))
            extra = set(o.get("lite", {})) - LITE_KEYS
            if extra:
                bad.append("%s:%d lite 에 없어야 할 칸 %s" % (os.path.basename(path), i, sorted(extra)))
    if bad:
        for b in bad:
            print("팩 자물쇠 위반: " + b)
        sys.exit("팩을 쓰지 말 것.")
    print("팩 자물쇠 통과 — 팩에는 통글(source)과 소넷 산출 줄(lite)뿐이다.")

    # 선별 기록은 팩 밖에 둔다 — 팩에는 통글과 소넷 산출 줄 말고 아무것도 넣지 않는다.
    with open(os.path.join(args.out, "gate_selection.csv"), "w",
              encoding="utf-8", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["session", "chunk", "thread_key", "pick_reason", "n_relations", "통글"])
        wr.writerows(selection)
    if missing_src:
        print("통글 없음 %d건 — 청크 원문에서 못 찾은 thread_key" % len(missing_src))
    if not src:
        print("통글 미첨부(--chunks 없음): 팩에 소넷 산출 줄만 들어갔다. "
              "게이트에 쓰기 전에 원문을 붙여야 한다.")
    print("선별 %d스레드 → %s" % (len(selection), os.path.join(args.out, "gate_selection.csv")))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, default_out):
        p.add_argument("--lite", nargs="?", const="work/relation_lite_out",
                       default="work/relation_lite_out",
                       help="소넷 산출 jsonl 디렉터리 · glob · 파일. "
                            "값 없이 --lite 만 써도 기본 경로를 본다.")
        p.add_argument("--out", default=default_out)

    p = sub.add_parser("merge", help="(thread_key, record_id) 복합키 병합")
    common(p, "work/gate"); p.set_defaults(fn=cmd_merge)

    p = sub.add_parser("validate", help="enum · 15단어 · direction · node_a 검사")
    common(p, "work/gate")
    p.add_argument("--node-a-list", help="한 줄 한 차명. 없으면 내장 기본값")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("stats", help="건수 집계")
    common(p, "work/gate"); p.set_defaults(fn=cmd_stats)

    p = sub.add_parser("pack", help="게이트 표본 팩")
    common(p, "work/gate")
    p.add_argument("--chunks", help="청크 원문(통글) 디렉터리 — work/relation_lite")
    p.add_argument("--random", type=int, default=3)
    p.add_argument("--per-session", type=int, default=2)
    p.set_defaults(fn=cmd_pack)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
