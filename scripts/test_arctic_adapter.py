#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Arctic Shift 어댑터 검증 — 네트워크 없이 돈다.

응답 껍데기를 눈으로 본 적이 없으므로(호스트가 막힌 환경에서 만들었다)
그럴듯한 두 모양을 모두 넣고, 어느 쪽이 와도 같은 결과가 나오는지 본다.
  A) 레딧처럼 {kind, data} 로 싸고 replies 가 Listing 인 모양
  B) 알맹이만 주고 replies 가 그냥 배열인 모양
"""
import datetime, json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _console; _console.setup()
import arctic_fetch as A

T0 = datetime.datetime(2026, 3, 1, tzinfo=datetime.timezone.utc).timestamp()

POST = {"id": "aaa111", "subreddit": "GenesisMotors", "author": "alice_owner",
        "title": "Traded my BMW 330i for a GV80",
        "selftext": "Picked up a 2026 GV80 Prestige after cross-shopping the X5.",
        "created_utc": T0, "score": 11, "num_comments": 4,
        "permalink": "/r/GenesisMotors/comments/aaa111/x/"}


def c(cid, parent, author, body, off, extra=None):
    d = {"id": cid, "parent_id": parent, "link_id": "t3_aaa111", "author": author,
         "body": body, "created_utc": T0 + off, "score": 2,
         "permalink": "/r/GenesisMotors/comments/aaa111/x/%s/" % cid}
    d.update(extra or {})
    return d


def shape_a():
    """레딧과 같은 {kind,data} + replies:Listing"""
    def w(d, replies=None):
        dd = dict(d)
        dd["replies"] = ({"kind": "Listing", "data": {"children": replies}}
                         if replies else "")
        return {"kind": "t1", "data": dd}
    return {"data": [
        w(c("c1", "t3_aaa111", "bob_driver", "How does it compare to the X5?", 60),
          [w(c("c2", "t1_c1", "alice_owner", "Quieter, worse infotainment.", 120),
             [w(c("c3", "t1_c2", "carol_ev", "I went Electrified GV70 instead.", 180))])]),
        w(c("c4", "t3_aaa111", "dave_x", "Later deleted by the author.", 240,
            {"_meta": {"was_deleted_later": True, "removal_type": "deleted"}})),
    ]}


def shape_b():
    """알맹이만 + replies 가 배열"""
    n3 = dict(c("c3", "t1_c2", "carol_ev", "I went Electrified GV70 instead.", 180))
    n2 = dict(c("c2", "t1_c1", "alice_owner", "Quieter, worse infotainment.", 120)); n2["replies"] = [n3]
    n1 = dict(c("c1", "t3_aaa111", "bob_driver", "How does it compare to the X5?", 60)); n1["replies"] = [n2]
    n4 = dict(c("c4", "t3_aaa111", "dave_x", "Later deleted by the author.", 240,
                {"_meta": {"was_deleted_later": True, "removal_type": "deleted"}}))
    return [n1, n4]


def run_shape(name, doc):
    tmp = tempfile.mkdtemp(prefix="arctic-test-")
    raw = os.path.join(tmp, "raw")
    os.makedirs(raw)
    flat = []
    A.flatten_tree(A.items(doc), flat)
    with open(os.path.join(raw, "aaa111.json"), "w", encoding="utf-8") as f:
        json.dump(A.to_reddit_shape(POST, flat), f, ensure_ascii=False)
    r = subprocess.run([sys.executable, os.path.join(HERE, "reddit_parse.py"),
                        "--raw", raw, "--model", "GV80", "--window", "202601_202608",
                        "--since", "2026-01-01", "--until", "2026-08-31",
                        "--out", os.path.join(tmp, "work"),
                        "--sealed", os.path.join(tmp, "sealed")],
                       capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        shutil.rmtree(tmp)
        return None, None, len(flat)
    bid = "reddit-GLOBAL-202601_202608-GV80"
    R = [json.loads(l) for l in open(os.path.join(tmp, "work", "records_%s.jsonl" % bid),
                                     encoding="utf-8")]
    M = json.load(open(os.path.join(tmp, "work", "manifest_%s.json" % bid), encoding="utf-8"))
    shutil.rmtree(tmp)
    return R, M, len(flat)


fails = []
checked = []


def ck(label, cond, detail=""):
    print("  %-4s %-50s %s" % ("PASS" if cond else "FAIL", label, detail))
    checked.append(label)
    if not cond:
        fails.append(label)


for name, doc in (("A · 레딧과 같은 {kind,data}", shape_a()), ("B · 알맹이만 + 배열", shape_b())):
    print("\n[응답 모양 %s]" % name)
    R, M, nflat = run_shape(name, doc)
    if R is None:
        ck("파싱", False, "파서가 실패했다")
        continue
    by = {r["record_id"]: r for r in R}
    orig = {r["record_id_orig"]: r for r in R}
    ck("트리를 평평하게 폈다", nflat == 4, "댓글 %d개" % nflat)
    ck("삭제 예정 댓글 제외 (_meta)", "c4" not in orig,
       "excl_deleted_later=%s" % M["excluded"].get("excl_deleted_later"))
    ck("본문 + 살아있는 댓글만 남았다", len(R) == 4, "레코드 %d" % len(R))
    ck("최상위 댓글 → 본문", orig["c1"]["position"] == "top"
       and by[orig["c1"]["parent_id"]]["unit"] == "post")
    ck("대댓글 → 상위 댓글", orig["c2"]["parent_id"] == orig["c1"]["record_id"]
       and orig["c2"]["position"] == "reply")
    ck("3단 중첩 보존", orig["c3"]["parent_id"] == orig["c2"]["record_id"])
    ck("reply_to_key", orig["c2"]["reply_to_key"] == "reddit:bob_driver")
    ck("author_key 는 계정명", orig["c1"]["author_key"] == "reddit:bob_driver")
    ck("author_is_op", orig["c2"]["author_is_op"] is True)
    ck("출처가 기록된다", orig["c1"].get("source") == "arctic_shift"
       and M["source_counts"].get("arctic_shift") == 4, json.dumps(M["source_counts"]))
    ck("전동화 근접 매칭", "Electrified GV70" in orig["c3"]["model_mentions"],
       str(orig["c3"]["model_mentions"]))
    ck("region GLOBAL", {r["region"] for r in R} == {"GLOBAL"})

print("\n%s  (%d개 점검, 실패 %d)"
      % ("통과" if not fails else "실패: " + ", ".join(sorted(set(fails))), len(checked), len(fails)))
sys.exit(1 if fails else 0)
