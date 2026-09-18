#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""납품 전 점검표 (가이드 §8) 자동 판정."""
import json, sys, re, collections, statistics, unicodedata, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _console; _console.setup()
ZW=re.compile(r'[​-‏  ﻿ ]')
def load(p): return [json.loads(l) for l in open(p,encoding='utf-8') if l.strip()]

def check(rec_path, sealed_path, man_path):
    R=load(rec_path); S=load(sealed_path) if os.path.exists(sealed_path) else []
    M=json.load(open(man_path,encoding='utf-8'))
    out=[]
    def ok(n,label,cond,detail=""): out.append((n,label,"PASS" if cond else "FAIL",detail))
    ok(1,"파일 3종", bool(R) and bool(S) and bool(M), f"records {len(R)} / sealed {len(S)} / manifest {'있음' if M else '없음'}")
    url=sum(1 for r in R if 'url' in r or 'thread_url' in r)
    disp=sum(1 for r in R if 'author_display' in r)
    ok(2,"작업층에 URL·닉네임 원문 없음", url==0 and disp==0, f"url키 {url} / author_display키 {disp}")
    nk=sum(1 for r in R if not r.get('author_key'))
    ok(3,"화자 식별자", nk==0 or bool(M.get('known_nulls')), f"author_key 빈 레코드 {nk}")
    pair=collections.Counter((r['thread_key'],r['record_id']) for r in R)
    ok(4,"(thread_key, record_id) 유일", all(v==1 for v in pair.values()), f"중복 {sum(v-1 for v in pair.values() if v>1)}")
    cov=[]
    for r in R:
        if r['unit']!='post': continue
        m=re.fullmatch(r'(\d+)/(\d+)',str(r.get('comment_coverage') or ''))
        if m and int(m.group(2)): cov.append(int(m.group(1))/int(m.group(2)))
    mean=statistics.mean(cov) if cov else 0
    ok(5,"댓글 커버리지 평균 ≥0.8", mean>=0.8, f"평균 {mean:.3f} / 0.8미만 스레드 {sum(1 for x in cov if x<0.8)}/{len(cov)}")
    ok(6,"posted_at 창 라벨", M.get('window_type')=='posted_date' and all(r.get('posted_at') for r in R), f"window_type={M.get('window_type')}")
    ok(7,"파일명 ASCII", all(ord(c)<128 for c in os.path.basename(rec_path)), os.path.basename(rec_path))
    junk=sum(1 for r in R if ZW.search(r['text']) or r['text']!=unicodedata.normalize('NFC',r['text']))
    ok(8,"찌꺼기(제로폭·NFC)", junk==0, f"잔존 {junk}")
    plain=sum(1 for s in S if s.get('author_display'))
    ok("8b","봉인층 닉네임 필드", True, f"author_display 채워진 레코드 {plain}/{len(S)}")
    ok("8c","식별자 일관성", bool(M.get('author_key_rule_version')), f"rule={M.get('author_key_rule_version')} / cross_batch_linkable={M.get('author_key_cross_batch_linkable')}")
    ok("8d","섀시코드", bool(M.get('collision_check')), json.dumps(M.get('collision_check',{}).get('severity')))
    ok("8e","전동화", M.get('ev_split',{}).get('applied') is True, json.dumps(M.get('ev_split',{}).get('passed'),ensure_ascii=False))
    reg=collections.Counter(r['region'] for r in R)
    ok(9,"권역 GLOBAL 고정", set(reg)== {'GLOBAL'}, dict(reg))
    need=["window_type","attempted_searches","known_nulls","author_key_rule_version","author_key_coverage","keyword_dict_version"]
    miss=[k for k in need if k not in M]; nullv=[k for k in need if M.get(k) is None]
    ok(10,"manifest 칸", not miss, f"누락 {miss} / 값이 null {nullv}")
    # 계층
    pos=collections.Counter(r.get('position') for r in R if r['unit']=='comment')
    unres=sum(1 for r in R if r.get('parent_resolved') is False)
    ok("4b","답글 계층", pos.get('reply',0)>0, f"{dict(pos)} / parent_resolved=false {unres}")
    return out

for model in sys.argv[1:]:
    print("="*72); print(model)
    res=check(f"work/records_reddit-GLOBAL-202601_202608-{model}.jsonl",
              f"sealed/records/sealed_reddit-GLOBAL-202601_202608-{model}.jsonl",
              f"work/manifest_reddit-GLOBAL-202601_202608-{model}.json")
    for n,l,st,d in res: print(f" {str(n):>3} {l:<28} {st:4}  {d}")
