#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""레딧 배치 클렌징 — community_collection_cleansing_guide v2.2 §4·§5 적용.

입력: 수집기가 낸 schema 1.2 records/sealed/manifest
출력: schema 1.6 작업층 + 봉인층 + §3-3 틀 manifest + 클렌징 리포트

복원 불가능한 결함(G70 답글 계층, GV80 솔트 원본)은 고치지 않는다.
known_nulls 와 리포트에 사실대로 남긴다 — 추론으로 메우지 않는다(가이드 §0).
"""
import json, re, sys, hashlib, unicodedata, collections, datetime, os

RULE_VERSION   = "reddit-cleanse-v1 (2026-09-17)"
SCHEMA_VERSION = "1.6"

# ---------------------------------------------------------------- 정규화·마스킹 (§4-5)
ZW      = re.compile(r'[​‌‍‎‏  ﻿]')
NBSP    = re.compile(r'[   ]')
URL     = re.compile(r'https?://([^\s/)\]]+)(/[^\s)\]]*)?')
MD_LINK = re.compile(r'\[([^\]]{1,120})\]\(\s*<?(https?://[^\s)>]+)>?\s*\)')
UMENT   = re.compile(r'(?<![A-Za-z0-9])(/?u/)[A-Za-z0-9_\-]{3,20}')
EMAIL   = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]{2,}')
PHONE   = re.compile(r'(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)')
PLATE_KR= re.compile(r'\d{2,3}[가-힣]\d{4}')
SPACES  = re.compile(r'[ \t]{2,}')
NEWLINE = re.compile(r'\n{3,}')

def normalize(t: str):
    """NFC · 제로폭 제거 · nbsp→공백 · 연속공백 1개. 개행 구조는 보존(통글 보존 §0-1)."""
    t = unicodedata.normalize('NFC', t or '')
    t = ZW.sub('', t)
    t = NBSP.sub(' ', t)
    t = t.replace('\r\n', '\n').replace('\r', '\n')
    t = SPACES.sub(' ', t)
    t = NEWLINE.sub('\n\n', t)
    return t.strip()

def mask(t: str):
    """§4-5. 인명 추정 고유명사는 건드리지 않는다(과잉 마스킹 금지)."""
    applied = collections.Counter()
    def _md(m):
        applied['link'] += 1
        dom = re.sub(r'^www\.', '', m.group(2).split('//', 1)[1].split('/')[0])
        return '%s [link:%s]' % (m.group(1), dom)
    t = MD_LINK.sub(_md, t)
    def _url(m):
        applied['link'] += 1
        return '[link:%s]' % re.sub(r'^www\.', '', m.group(1))
    t = URL.sub(_url, t)
    def _u(m):
        applied['user'] += 1
        return '%s[user]' % m.group(1)
    t = UMENT.sub(_u, t)
    t, n = EMAIL.subn('[contact]', t);   applied['contact'] += n
    t, n = PHONE.subn('[contact]', t);   applied['contact'] += n
    t, n = PLATE_KR.subn('[plate]', t);  applied['plate']   += n
    t = SPACES.sub(' ', t)          # 마스킹으로 생긴 연속 공백을 다시 접는다
    return t.strip(), applied

# ---------------------------------------------------------------- 자동 태깅 (§5)
BOT = re.compile(r'(I am a bot|this action was performed automatically|please contact the moderators'
                 r'|take the time to flair|AutoModerator|beep boop|Thanks for posting on /r/'
                 r'|Please review our most \[Frequently Asked Questions\]'
                 r'|This comment is a copy of your post)', re.I)
COMMERCIAL = re.compile(r'(\(\d+/\d+\)|deep dive|\bauction\b|\bexport\b|inspection service'
                        r'|pre-?purchase inspection|check us out at|DM me if interested'
                        r'|LEASE SPECIAL|\$0 DOWN)', re.I)
SPONSOR_DECL = re.compile(r'(#ad\b|#sponsored|paid partnership|includes paid promotion|#협찬|#광고)', re.I)

# §5-6 전동화 근접 매칭. 느슨한 "본문 어디든 EV" 규칙은 쓰지 않는다.
EV_SIG = r'(?:electrified|electric|EV)'
def ev_hit(text, model):
    mo = re.escape(model)
    pats = [rf'{EV_SIG}.{{0,3}}{mo}\b', rf'\b{mo}.{{0,3}}{EV_SIG}',
            rf'\be{mo}\b', rf'\b{mo}e\b']
    return any(re.search(p, text, re.I) for p in pats)

# §5-5 섀시코드·동음 모델코드 충돌. G70 = BMW 7시리즈 섀시코드 + 모토로라/캐논 제품코드.
BMW7   = re.compile(r'\b(alpina|\bb7\b|7\s?series|7er|750i|760i|740i|i7\b|g11|g12)\b', re.I)
NONCAR = re.compile(r'\b(moto\s?g70|motorola|canon|legria|camcorder|camrecorder|stylus|tab\s?g70)\b', re.I)
GENESIS= re.compile(r'genesis|جينيسيس|제네시스', re.I)

def sha(t): return hashlib.sha256(t.encode('utf-8')).hexdigest()

# --------------------------------------------------------------- parent_id 계단 복구
# 수집기가 재넘버링할 때 record_id 만 새로 매기고 parent_id 는 옛 번호를 남겼다.
# 제거된 레코드 수가 스레드 순서를 따라 누적되므로 오프셋이 계단 함수가 된다.
# 계단 값·전이 지점은 데이터에서 역도출하고(§5 판단 금지 — 사전·규칙 매칭만),
# 같은 스레드 · 선행 position · 선행 posted_at 셋을 모두 만족할 때만 채택한다.
def _num(rid):
    try: return int(str(rid).split('-')[-1])
    except Exception: return None

def build_parent_offsets(rows, candidates=(0, 8, 14, 16)):
    idx = {}
    for r in rows:
        n = _num(r['record_id'])
        if n is not None: idx[n] = r
    th = collections.defaultdict(list)
    for r in rows: th[r['thread_id']].append(r)
    order = sorted(th, key=lambda t: min(_num(r['record_id']) or 0 for r in th[t]))
    off, prev, stats = {}, 0, collections.Counter()
    for t in order:
        kids = [r for r in th[t] if r.get('parent_id')]
        if not kids:
            off[t] = prev; continue
        best = (-1, prev)
        for d in candidates:
            ok = 0
            for r in kids:
                p = idx.get((_num(r['parent_id']) or 0) - d)
                if (p and p['thread_id'] == t
                        and p.get('position', 0) < r.get('position', 0)
                        and (p.get('posted_at') or '') <= (r.get('posted_at') or '')):
                    ok += 1
            if ok > best[0]: best = (ok, d)
        off[t] = best[1]; prev = best[1]
        stats[best[1]] += 1
    return idx, off, dict(stats)

def resolve_parent(r, idx, off):
    """복구된 부모 레코드를 돌려준다. 검증에 실패하면 None."""
    if not r.get('parent_id'): return None
    p = idx.get((_num(r['parent_id']) or 0) - off.get(r['thread_id'], 0))
    if (p and p['thread_id'] == r['thread_id']
            and p.get('position', 0) < r.get('position', 0)
            and (p.get('posted_at') or '') <= (r.get('posted_at') or '')):
        return p
    return None

# ---------------------------------------------------------------- 본체
def run(model, rec_path, sealed_path, out_dir, sealed_dir, window, thread_key_donor=None):
    rep = collections.Counter()
    rows = [json.loads(l) for l in open(rec_path, encoding='utf-8') if l.strip()]
    sealed_in = {}
    if sealed_path and os.path.exists(sealed_path):
        for l in open(sealed_path, encoding='utf-8'):
            if l.strip():
                s = json.loads(l); sealed_in[s['record_id']] = s

    batch_id = f"reddit-GLOBAL-{window}-{model}"
    prefix   = f"RD-GLOBAL-{model}"

    # 1) 스레드 묶기
    th = collections.defaultdict(list)
    for r in rows: th[r['thread_id']].append(r)

    # 1b) parent_id 계단 복구 테이블 (§4-2) — parent_id 가 있는 배치에만 해당
    has_parent = any(r.get('parent_id') for r in rows)
    pidx, poff, pstats = build_parent_offsets(rows) if has_parent else ({}, {}, {})
    rep["parent_offset_steps"] = pstats or None

    # 2) 스레드 단위 오염 판정 (§5-5) — 본문 제거 전에 먼저 한다
    dropped_threads = {}
    for t, rs in th.items():
        sec  = rs[0].get('section', '')
        full = ' '.join(x.get('text') or '' for x in rs)
        post = rs[0].get('text') or ''
        if GENESIS.search(full) or sec.lower().startswith('r/genesis'):
            continue                                   # 제네시스 서브·명시 언급은 필터를 타지 않는다
        if NONCAR.search(full):
            dropped_threads[t] = 'collision_noncar'
        elif BMW7.search(full) and model == 'G70':
            dropped_threads[t] = 'collision_bmw_chassis'

    # 3) 본문 길이 미달 스레드 (§2)
    for t, rs in th.items():
        if t in dropped_threads: continue
        post = next((x for x in rs if x.get('unit') == 'post'), None)
        if post is not None and len(normalize(post.get('text') or '')) < 20:
            dropped_threads[t] = 'length_short_post'

    # 4) 스레드 정렬 → 게시일순, 스레드 안은 본문 → 댓글 오래된 순 (§4-2)
    keep = {t: rs for t, rs in th.items() if t not in dropped_threads}
    def tkey(item):
        t, rs = item
        p = next((x for x in rs if x.get('unit') == 'post'), rs[0])
        return (p.get('posted_at') or '', t)
    ordered = sorted(keep.items(), key=tkey)

    out_records, out_sealed = [], []
    seq = 0
    thread_hash_index = {}          # 스레드 간 near-dup 탐지용
    masking_total = collections.Counter()
    author_coverage = 0
    ev_flags = collections.Counter()

    for t, rs in ordered:
        rs = sorted(rs, key=lambda x: (0 if x.get('unit') == 'post' else 1,
                                       x.get('posted_at') or '', x.get('position', 0)))
        post = rs[0]
        # thread_key — 봉인층 URL에서 레딧 글 id를 뽑는다. 없으면 배치 한정 키 + known_null.
        tk = None
        su = sealed_in.get(post['record_id'], {}).get('thread_url')
        if su:
            m = re.search(r'/comments/([a-z0-9]+)/', su)
            if m: tk = f"rd:{m.group(1)}"
        if tk is None and thread_key_donor:
            tk = thread_key_donor.get(sha(normalize(post.get('text') or '')))
        if tk is None:
            tk = f"rd:{model.lower()}#{t}"
            rep['thread_key_fallback'] += 1

        oldnew   = {}                 # 원 record_id → 새 record_id
        authors  = {}
        seen_hash = {}
        buf = []
        for r in rs:
            txt = normalize(r.get('text') or '')
            unit = r.get('unit')
            if unit == 'comment' and len(txt) < 5:
                rep['excl_length_short_comment'] += 1; continue
            txt, ap = mask(txt)
            masking_total.update(ap)
            limit = 5000 if unit == 'post' else 2000
            truncated = len(txt) > limit
            if truncated:
                txt = txt[:limit]; rep['truncated'] += 1
            ch = sha(txt)
            if ch in seen_hash:                                   # §4-6 스레드 안에서만 중복 판정
                rep['excl_dup_in_thread'] += 1; continue
            seen_hash[ch] = True
            seq += 1
            rid = f"{prefix}-{seq:06d}"
            oldnew[r['record_id']] = rid
            buf.append((r, rid, txt, ch, truncated))

        # 화자 식별자 (§4-4)
        post_author = None
        for r, rid, txt, ch, tr in buf:
            a = r.get('author_hash')
            if a in ('', None, '[deleted]'): a = None
            ak = None
            if a is not None:
                ak = f"reddit:{a}" if not re.fullmatch(r'[0-9a-f]{16}', str(a)) else f"reddit_testsalt:{a}"
            authors[r['record_id']] = ak
            if r.get('unit') == 'post': post_author = ak

        for r, rid, txt, ch, tr in buf:
            ak = authors[r['record_id']]
            if ak: author_coverage += 1
            # 답글 계층 (§4-2)
            parent_id, position, reply_to_key = None, None, None
            parent_resolved = None
            if r.get('unit') == 'post':
                position = None
            elif not has_parent:
                parent_id = oldnew.get(post['record_id'])          # 원자료에 parent_id 필드 자체가 없다
                position = None; parent_resolved = False
                rep['parent_missing_source'] += 1
            else:
                p = resolve_parent(r, pidx, poff)
                if p is None:
                    parent_id = oldnew.get(post['record_id'])
                    position = 'top' if not r.get('parent_id') else 'reply'
                    parent_resolved = False
                    rep['parent_unresolved'] += 1
                elif p['record_id'] == post['record_id']:
                    parent_id = oldnew.get(post['record_id'])
                    position = 'top'; parent_resolved = True
                    rep['parent_top'] += 1
                else:
                    parent_id = oldnew.get(p['record_id']) or oldnew.get(post['record_id'])
                    position = 'reply'
                    reply_to_key = authors.get(p['record_id'])
                    parent_resolved = parent_id is not None
                    rep['parent_reply'] += 1

            mm = list(r.get('model_mentions') or [])
            mm2 = []
            for x in mm:
                if x in ('GV70', 'G80', 'GV60') and ev_hit(txt, x):
                    mm2.append(f"Electrified {x}"); ev_flags[x] += 1
            mm = mm + mm2
            isbot = bool(BOT.search(txt))
            if isbot: rep['bot_flagged'] += 1
            comm = bool(COMMERCIAL.search(txt))
            if comm: rep['commercial_series'] += 1

            nd = thread_hash_index.get(ch)
            if nd is None: thread_hash_index[ch] = rid
            else: rep['near_dup_cross_thread'] += 1

            eng = r.get('engagement') or {}
            out_records.append({
                "record_id": rid, "record_id_orig": r['record_id'], "thread_key": tk,
                "unit": r.get('unit'), "position": position, "parent_id": parent_id,
                "platform": "reddit", "section": r.get('section'),
                "region": "GLOBAL", "region_basis": "platform_global",
                "region_confidence": None,
                "region_note": (r.get('region') if r.get('region_basis') in ('text_cue', 'section') else None),
                "lang": r.get('lang'), "lang_conf": r.get('lang_conf'),
                "text": txt, "text_len": len(txt), "truncated": tr,
                "posted_at": r.get('posted_at'), "posted_at_precision": r.get('posted_at_precision'),
                "author_key": ak,
                "author_is_op": (None if ak is None or post_author is None
                                 else (ak == post_author and r.get('unit') != 'post')),
                "reply_to_key": reply_to_key, "same_speaker_suspect": None,
                "parent_resolved": parent_resolved,
                "engagement": {"likes": eng.get('likes'), "replies": eng.get('replies'),
                               "views": eng.get('views')},
                "media_count": r.get('media_count'), "media_types": r.get('media_types') or [],
                "model_mentions": mm, "thread_model_mentions": r.get('thread_model_mentions') or [],
                "brand_mentions": r.get('brand_mentions') or [],
                "brand_only": r.get('brand_only'), "context_suspect": r.get('context_suspect'),
                "sponsored_flag": ("declared" if SPONSOR_DECL.search(txt) else r.get('sponsored_flag', 'none')),
                "official_source_flag": bool(r.get('official_source_flag')) or isbot,
                "official_source_provisional": True,
                "bot_flag": isbot,
                "minor_flag": bool(r.get('minor_flag')), "commercial_series": comm,
                "attrs_prefill": r.get('attrs_prefill'),
                "trim_variant_prefill": r.get('trim_variant_prefill', 'none'),
                "query_codes": r.get('query_codes') or [], "window": r.get('window'),
                "batch_id": batch_id, "content_hash": ch,
                "near_dup_of": (nd if nd and nd != rid else None),
                "comment_coverage": r.get('comment_coverage'),
                "access_method": r.get('access_method'), "collected_at": r.get('collected_at'),
                "schema_version": SCHEMA_VERSION,
            })
            s_in = sealed_in.get(r['record_id'], {})
            out_sealed.append({
                "record_id": rid, "record_id_orig": r['record_id'], "thread_key": tk,
                "url": s_in.get('url'), "thread_url": s_in.get('thread_url'),
                "media_ids": s_in.get('media_ids', []),
                "raw_text": s_in.get('raw_text', r.get('text')),
                "author_display": (r.get('author_hash')
                                   if not re.fullmatch(r'[0-9a-f]{16}', str(r.get('author_hash')))
                                   else None),
                "author_id_hash_full": s_in.get('author_id_hash_full'),
            })

    os.makedirs(out_dir, exist_ok=True); os.makedirs(sealed_dir, exist_ok=True)
    rp = f"{out_dir}/records_{batch_id}.jsonl"
    sp = f"{sealed_dir}/sealed_{batch_id}.jsonl"
    with open(rp, 'w', encoding='utf-8') as f:
        for r in out_records: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(sp, 'w', encoding='utf-8') as f:
        for r in out_sealed: f.write(json.dumps(r, ensure_ascii=False) + "\n")

    rep['threads_in'] = len(th); rep['threads_out'] = len(set(r['thread_key'] for r in out_records))
    rep['records_in'] = len(rows); rep['records_out'] = len(out_records)
    rep['author_key_coverage'] = author_coverage
    for t, why in dropped_threads.items(): rep['drop_' + why] += 1
    rep['dropped_records'] = sum(len(th[t]) for t in dropped_threads)
    return dict(rep), dict(masking_total), dict(ev_flags), out_records, dropped_threads, rp, sp

if __name__ == '__main__':
    print("import 전용 — run_cleanse.py 에서 호출한다")
