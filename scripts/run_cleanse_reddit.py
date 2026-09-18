#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GV80·G70 레딧 배치 클렌징 실행 + §3-3 manifest 재작성."""
import json, sys, os, hashlib, collections, re, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _console; _console.setup()
from cleanse_reddit_v1 import run, normalize, sha, RULE_VERSION, SCHEMA_VERSION

IN     = sys.argv[1]
OUT    = sys.argv[2]
SEALED = sys.argv[3]
WINDOW = "202601_202608"

# GV80 봉인층 URL 로 thread_key 를 복원한 뒤, 같은 본문 해시를 가진 G70 스레드에 넘겨준다.
donor = {}
for l in open(f"{IN}/sealed_GV80.jsonl", encoding='utf-8'):
    s = json.loads(l)
    m = re.search(r'/comments/([a-z0-9]+)/', s.get('thread_url') or '')
    if m: donor[sha(normalize(s.get('raw_text') or ''))] = f"rd:{m.group(1)}"

results = {}
for model, rec, sl in [("GV80", "records_GV80.jsonl", "sealed_GV80.jsonl"),
                       ("G70",  "records_G70.jsonl",  None)]:
    rep, msk, ev, recs, dropped, rp, sp = run(
        model, f"{IN}/{rec}", f"{IN}/{sl}" if sl else None, OUT, SEALED, WINDOW,
        thread_key_donor=donor if model == "G70" else None)
    results[model] = dict(rep=rep, masking=msk, ev=ev, path=rp, sealed=sp,
                          dropped=dropped, recs=recs)
    print(f"--- {model} ---")
    for k, v in sorted(rep.items()): print(f"   {k:32s} {v}")
    print("   masking:", msk, "| ev:", ev)

# 배치 간 중복 스레드 표시 (§4-6 near_dup_of)
tk = {m: set(r['thread_key'] for r in d['recs']) for m, d in results.items()}
shared = tk['GV80'] & tk['G70']
print("\n두 배치 공유 thread_key:", len(shared))

for model, d in results.items():
    recs = d['recs']
    src_manifest = json.load(open(f"{IN}/manifest_{model}.json", encoding='utf-8'))
    posts = [r for r in recs if r['unit'] == 'post']
    cov = []
    for r in posts:
        m = re.fullmatch(r'(\d+)/(\d+)', str(r.get('comment_coverage') or ''))
        if m and int(m.group(2)): cov.append(int(m.group(1)) / int(m.group(2)))
    dates = sorted(r['posted_at'][:10] for r in recs if r.get('posted_at'))
    tot = 0
    for r in posts:
        mm = re.fullmatch(r"(\d+)/(\d+)", str(r.get("comment_coverage") or "0/0"))
        if mm: tot += int(mm.group(2))
    cov_str = "%d/%d" % (sum(1 for r in recs if r["unit"] == "comment"), tot)
    kn = ["engagement.views", "media_types(빈 배열 고정)", "minor_flag(발주자 계정목록 미수령·전건 false)",
          "official_source_flag(계정목록 미수령·봇 패턴으로 잠정 표시, provisional=true)",
          "region_confidence(레딧 GLOBAL 고정이라 판정 안 함)"]
    if model == "G70":
        kn += ["parent_id/position(원자료에 답글 계층 없음 — 재수집 전까지 복원 불가)",
               "reply_to_key(동상)",
               "url/thread_url(봉인층 미납품 — 공유 스레드 21건 외에는 복원 불가)"]
    else:
        kn += ["author_display(봉인층에 닉네임 원문 없음 — 솔트 교체 시 재계산 불가)"]

    coll = {"model": model,
            "brand": "BMW (G70=7시리즈 섀시코드)" if model == "G70" else None,
            "sampled": d['rep'].get('threads_in'),
            "contaminated": d['rep'].get('drop_collision_bmw_chassis', 0) + d['rep'].get('drop_collision_noncar', 0),
            "severity": "moderate" if model == "G70" else "none",
            "note": ("수집 단계 필터가 r/BMW 안에서만 적용돼 r/AiCarArt·r/beamng_leakedmods 등에서 누수. "
                     "추가로 Moto G70(모토로라)·Canon HF G70 등 비자동차 제품코드 충돌 확인 — 이번 클렌징에서 제거."
                     if model == "G70" else
                     "GV80 문자열이 없는 스레드 0건. 비자동차·타브랜드 코드 충돌 0건.")}

    man = {
        "schema_version": SCHEMA_VERSION,
        "batch_id": f"reddit-GLOBAL-{WINDOW}-{model}",
        "platform": "reddit", "region": "GLOBAL", "model_label": model,
        "window": WINDOW,
        "window_type": "posted_date",
        "posted_at_range": {"min": dates[0], "max": dates[-1]},
        "attempted_searches": None,
        "target": 100, "collected_posts": len(posts),
        "collected_comments": len(recs) - len(posts), "collected_records": len(recs),
        "target_shortfall_reason": None,
        "excluded": {
            "length_short_post": d['rep'].get('drop_length_short_post', 0),
            "length_short_comment": d['rep'].get('excl_length_short_comment', 0),
            "dup": d['rep'].get('excl_dup_in_thread', 0),
            "collision_bmw_chassis": d['rep'].get('drop_collision_bmw_chassis', 0),
            "collision_noncar": d['rep'].get('drop_collision_noncar', 0),
            "deleted": 0, "minor": 0, "sponsored": 0, "official": 0,
            "upstream_excluded": src_manifest.get('excluded'),
        },
        "relevance_check": {
            "threads": d['rep'].get('threads_in'),
            "threads_with_target_model": d['rep'].get('threads_in') - len(d['dropped']),
            "method": "스레드 전체 텍스트(본문+댓글) 대상 모델명·brand 정규식 + 충돌 패턴 스캔"},
        "collision_check": coll,
        "ev_split": {"applied": True, "rule": "proximity_3chars (§5-6)",
                     "passed": d['ev'], "rejected": None,
                     "note": "수집 단계에서는 미적용이었다 — 클렌징에서 근접 매칭으로 신규 부여."},
        "parent_repair": {
            "issue": "수집기가 재넘버링 시 record_id 만 갱신하고 parent_id 는 옛 번호를 남김",
            "offset_steps": d['rep'].get('parent_offset_steps'),
            "resolved_top": d['rep'].get('parent_top', 0),
            "resolved_reply": d['rep'].get('parent_reply', 0),
            "unresolved": d['rep'].get('parent_unresolved', 0),
            "no_parent_field_in_source": d['rep'].get('parent_missing_source', 0)},
        "unit_rule": "post = 스레드 본문, comment = 상세 페이지의 댓글",
        "parent_id_rule": ("reddit: 최상위 댓글→본문 record_id, 대댓글→상위 댓글 record_id. position=top|reply"
                           if model == "GV80" else
                           "reddit: 원자료에 parent_id 필드 자체가 없어 전건 본문으로 눕힘. position=null. 재수집 필요"),
        "comment_coverage": cov_str,
        "comment_coverage_mean": round(sum(cov) / len(cov), 3) if cov else None,
        "comment_coverage_threads_under_80pct": sum(1 for x in cov if x < 0.8),
        "keyword_dict_version": src_manifest.get('dictionary_version'),
        "author_key_rule_version": ("gv80-testsalt-v0 (임시 솔트 — 원본 계정명 부재로 재계산 불가)"
                                    if model == "GV80" else "reddit-username-plain-v1"),
        "author_key_cross_batch_linkable": False,
        "author_key_coverage": f"{d['rep'].get('author_key_coverage')}/{len(recs)}",
        "masking_applied": sorted([k for k, v in d['masking'].items() if v]),
        "masking_counts": d['masking'],
        "known_nulls": kn,
        "access_method_counts": collections.Counter(r['access_method'] for r in recs),
        "access_note": "레딧 공개 페이지(old.reddit .json). 자동 수집 금지 채널 아님.",
        "cross_batch": {"shared_thread_keys_with_other_batch": len(shared),
                        "note": "GV80·G70 배치에 같은 스레드가 들어 있다. 병합 시 thread_key 로 1건 처리할 것."},
        "cleanse_rule_version": RULE_VERSION,
        "source_manifest_schema_version": src_manifest.get('schema_version'),
        "collected_at": src_manifest.get('collected_at'),
        "cleansed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    man['checksums'] = {
        "records": hashlib.sha256(open(d['path'], 'rb').read()).hexdigest(),
        "sealed": hashlib.sha256(open(d['sealed'], 'rb').read()).hexdigest()}
    p = f"{OUT}/manifest_reddit-GLOBAL-{WINDOW}-{model}.json"
    json.dump(man, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2, default=str)
    print("manifest →", p)
