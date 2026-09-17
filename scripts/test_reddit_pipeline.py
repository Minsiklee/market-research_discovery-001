#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reddit_parse.py 오프라인 검증 — 네트워크 없이 돈다.

레딧 원응답 모양을 손으로 만든 픽스처로 재현하고, 1차 배치가 어겼던 항목을
하나씩 되짚는다. 수집기를 열린 네트워크로 옮기기 전에 여기서 먼저 통과시킨다.
"""
import json, os, re, subprocess, sys, tempfile, shutil, time, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
T0 = datetime.datetime(2026, 3, 1, tzinfo=datetime.timezone.utc).timestamp()


def cm(cid, parent, author, body, off, replies=None, ):
    d = {"id": cid, "parent_id": parent, "author": author, "body": body,
         "created_utc": T0 + off, "score": 3, "permalink": "/r/GenesisMotors/comments/t1/%s/" % cid,
         "replies": ""}
    if replies:
        d["replies"] = {"kind": "Listing", "data": {"children": replies}}
    return {"kind": "t1", "data": d}


def thread(tid, sub, title, selftext, author, comments, more=None, num_comments=None,
           created=T0, extra_things=None):
    listing = [
        {"kind": "Listing", "data": {"children": [{"kind": "t3", "data": {
            "id": tid, "subreddit": sub, "title": title, "selftext": selftext,
            "author": author, "created_utc": created, "score": 11,
            "num_comments": num_comments if num_comments is not None else len(comments) + len(more or []),
            "permalink": "/r/%s/comments/%s/x/" % (sub, tid)}}]}},
        {"kind": "Listing", "data": {"children": comments + (
            [{"kind": "more", "data": {"children": more}}] if more else [])}},
    ]
    return {"listing": listing,
            "morechildren": extra_things or [],
            "fetched_at": "2026-09-17T00:00:00+00:00", "auth": "oauth"}


def build(raw_dir):
    os.makedirs(raw_dir, exist_ok=True)

    # A. 정상 스레드 — 2단 중첩 + 접힌 댓글 + 삭제 계정 + 봇 + 마스킹 대상
    a = thread(
        "aaa111", "GenesisMotors", "Traded my BMW 330i for a GV80",
        "Picked up a 2026 GV80 Prestige last week after cross-shopping the X5. "
        "Reach me at buyer@example.com or https://imgur.com/gallery/abc?utm=1 for photos.",
        "alice_owner",
        [cm("c1", "t3_aaa111", "bob_driver", "How does it compare to the X5? u/alice_owner", 60,
            replies=[cm("c2", "t1_c1", "alice_owner", "Quieter than the X5, worse infotainment.", 120,
                        replies=[cm("c3", "t1_c2", "carol_ev", "I went with an Electrified GV70 instead.", 180)])]),
         cm("c4", "t3_aaa111", "[deleted]", "Congrats on the new ride!", 240),
         cm("c5", "t3_aaa111", "AutoModerator",
            "Please take the time to flair your post accordingly. I am a bot.", 300)],
        more=["c6"], num_comments=6,
        extra_things=[cm("c6", "t1_c1", "dave_lease", "Lease numbers on the GV80 are rough right now.", 360)])
    json.dump(a, open(os.path.join(raw_dir, "aaa111.json"), "w"))

    # B. BMW 7시리즈 섀시코드 오염 — genesis 무언급
    b = thread("bbb222", "AiCarArt", "What if Alpina made a G70 B7",
               "Rendered this 7 series on air suspension, xDrive drivetrain.", "render_guy",
               [cm("d1", "t3_bbb222", "bmwfan", "That G70 B7 front end is wild.", 60)])
    json.dump(b, open(os.path.join(raw_dir, "bbb222.json"), "w"))

    # C. 비자동차 모델코드 충돌
    c = thread("ccc333", "motorola", "What stylus for Tab G70 LTE",
               "I bought the motorola g70 lte two years ago without any stylus.", "tabuser",
               [cm("e1", "t3_ccc333", "helper", "Any capacitive stylus works fine.", 60)])
    json.dump(c, open(os.path.join(raw_dir, "ccc333.json"), "w"))

    # D. 본문 20자 미만 (§2 제외)
    d = thread("ddd444", "GenesisMotors", "GV80", "", "shortposter",
               [cm("f1", "t3_ddd444", "someone", "Nice car, congrats on the GV80.", 60)])
    json.dump(d, open(os.path.join(raw_dir, "ddd444.json"), "w"))

    # E. 구간 밖 (2025-11 게시)
    e = thread("eee555", "GenesisMotors", "Old GV80 thread from last year",
               "This one is outside the collection window entirely.", "olduser",
               [cm("g1", "t3_eee555", "x", "Still a great GV80 deal.", 60)],
               created=datetime.datetime(2025, 11, 1, tzinfo=datetime.timezone.utc).timestamp())
    json.dump(e, open(os.path.join(raw_dir, "eee555.json"), "w"))


def main():
    tmp = tempfile.mkdtemp(prefix="reddit-test-")
    raw, out, sealed = os.path.join(tmp, "raw"), os.path.join(tmp, "work"), os.path.join(tmp, "sealed")
    build(raw)
    r = subprocess.run([sys.executable, os.path.join(HERE, "reddit_parse.py"),
                        "--raw", raw, "--model", "GV80", "--window", "202601_202608",
                        "--since", "2026-01-01", "--until", "2026-08-31",
                        "--out", out, "--sealed", sealed],
                       capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr); sys.exit(1)
    print("parser:", r.stdout.strip())
    bid = "reddit-GLOBAL-202601_202608-GV80"
    R = [json.loads(l) for l in open(os.path.join(out, "records_%s.jsonl" % bid), encoding="utf-8")]
    S = [json.loads(l) for l in open(os.path.join(sealed, "sealed_%s.jsonl" % bid), encoding="utf-8")]
    M = json.load(open(os.path.join(out, "manifest_%s.json" % bid), encoding="utf-8"))
    by = {x["record_id"]: x for x in R}
    fails = []

    checked = []

    def ck(label, cond, detail=""):
        print("  %-4s %-52s %s" % ("PASS" if cond else "FAIL", label, detail))
        checked.append(label)
        if not cond:
            fails.append(label)

    print("\n[구조]")
    ck("대상 모델 무언급 스레드 제외 (BMW 7시리즈)",
       all(r["thread_key"] != "rd:bbb222" for r in R))
    ck("비자동차 코드 충돌 제외 (Moto G70)",
       all(r["thread_key"] != "rd:ccc333" for r in R),
       "collision=%d" % M["collision_check"]["contaminated"])
    ck("본문 20자 미만 스레드 제외", all(r["thread_key"] != "rd:ddd444" for r in R))
    ck("구간 밖 스레드 제외", all(r["thread_key"] != "rd:eee555" for r in R))
    ck("접힌 댓글(morechildren) 회수", any(r["record_id_orig"] == "c6" for r in R))

    print("\n[§4-2 답글 계층 — 1차 배치가 잃은 것]")
    c2 = next(r for r in R if r["record_id_orig"] == "c2")
    c3 = next(r for r in R if r["record_id_orig"] == "c3")
    c1 = next(r for r in R if r["record_id_orig"] == "c1")
    ck("최상위 댓글 position=top", c1["position"] == "top" and by[c1["parent_id"]]["unit"] == "post")
    ck("대댓글이 상위 댓글을 가리킨다", c2["parent_id"] == c1["record_id"] and c2["position"] == "reply")
    ck("3단 중첩도 보존", c3["parent_id"] == c2["record_id"])
    ck("reply_to_key 가 대상 화자", c2["reply_to_key"] == c1["author_key"], c2["reply_to_key"])
    ck("접힌 댓글의 부모도 해결", next(r for r in R if r["record_id_orig"] == "c6")["parent_id"] == c1["record_id"])
    ck("parent_resolved 전건 true", all(r.get("parent_resolved") is not False for r in R))

    print("\n[§4-1 · §4-4 키와 화자]")
    ck("record_id 에 배치 포함·전역 유일",
       len({r["record_id"] for r in R}) == len(R) and all(r["record_id"].startswith("RD-GLOBAL-GV80-") for r in R))
    ck("record_id_orig 보존", all(r.get("record_id_orig") for r in R))
    ck("author_key 는 계정명", c1["author_key"] == "reddit:bob_driver", c1["author_key"])
    ck("삭제 계정은 author_key=null",
       next(r for r in R if r["record_id_orig"] == "c4")["author_key"] is None)
    ck("author_is_op 판정", c2["author_is_op"] is True and c1["author_is_op"] is False)
    ck("배치 간 연결 가능 표시", M["author_key_cross_batch_linkable"] is True)

    print("\n[§3-2 · §4-5 층 분리와 마스킹]")
    post = next(r for r in R if r["unit"] == "post")
    ck("작업층에 URL 키 없음", all("url" not in r and "thread_url" not in r for r in R))
    ck("작업층에 닉네임 원문 키 없음", all("author_display" not in r for r in R))
    ck("이메일 마스킹", "[contact]" in post["text"] and "buyer@example.com" not in post["text"])
    ck("URL 도메인화·쿼리 제거",
       "[link:imgur.com]" in post["text"] and "utm=1" not in post["text"])
    ck("u/멘션 마스킹", "u/[user]" in c1["text"] and "u/alice_owner" not in c1["text"])
    ck("봉인층에 원문 보존",
       any("buyer@example.com" in (s.get("raw_text") or "") for s in S))
    ck("봉인층에 닉네임 원문", any(s.get("author_display") == "alice_owner" for s in S))
    ck("봉인층에 URL", all(s.get("thread_url", "").startswith("https://") for s in S))

    print("\n[§4-3 · §5]")
    ck("region GLOBAL 고정", {r["region"] for r in R} == {"GLOBAL"})
    ck("모델 매칭은 dictionary_v2", "GV80" in post["model_mentions"], post["model_mentions"])
    ck("브랜드 매칭", "BMW" in post["brand_mentions"], post["brand_mentions"])
    ck("전동화 근접 매칭", "Electrified GV70" in c3["model_mentions"], c3["model_mentions"])
    ck("댓글에 문맥 상속 금지",
       next(r for r in R if r["record_id_orig"] == "c4")["model_mentions"] == []
       and post["thread_model_mentions"] != [])
    ck("봇 플래그", next(r for r in R if r["record_id_orig"] == "c5")["bot_flag"] is True)

    print("\n[§3-3 manifest]")
    for k in ("window_type", "known_nulls", "author_key_rule_version", "author_key_coverage",
              "keyword_dict_version", "collision_check", "ev_split", "parent_id_rule",
              "posted_at_range", "checksums"):
        ck("칸 %s" % k, M.get(k) not in (None, "", [], {}))
    ck("커버리지 기록", M["comment_coverage_mean"] is not None, str(M["comment_coverage_mean"]))

    # 같은 픽스처를 G70 배치로 다시 파싱해 섀시코드 필터(§5-5)를 검증한다.
    # G70 배치에서는 BMW 7시리즈 글의 'G70' 이 사전에 실제로 걸리므로,
    # 관련성 관문이 아니라 충돌 필터가 잡아내야 한다.
    out2 = os.path.join(tmp, "work_g70")
    r2 = subprocess.run([sys.executable, os.path.join(HERE, "reddit_parse.py"),
                         "--raw", raw, "--model", "G70", "--window", "202601_202608",
                         "--since", "2026-01-01", "--until", "2026-08-31",
                         "--out", out2, "--sealed", os.path.join(tmp, "sealed_g70")],
                        capture_output=True, text=True)
    M2 = json.load(open(os.path.join(out2, "manifest_reddit-GLOBAL-202601_202608-G70.json"),
                        encoding="utf-8"))
    print("\n[§5-5 섀시코드 — G70 배치로 재파싱]")
    ck("BMW 7시리즈 스레드를 충돌로 판정",
       M2["excluded"].get("drop_collision_chassis", 0) == 1, json.dumps(M2["excluded"]))
    ck("severity 기록", M2["collision_check"]["severity"] == "moderate")

    shutil.rmtree(tmp)
    print("\n%s  (%d개 점검, 실패 %d)" % ("통과" if not fails else "실패: " + ", ".join(fails),
                                        len(checked), len(fails)))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
