#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""레딧 수집기 — API 원응답을 먼저 보관한다.

1차 배치의 사고(계정명 소실·parent_id 소실·URL 소실)는 전부 **원응답을 버리고
가공 결과만 남겨서** 생겼다. 그래서 이 수집기는 두 단계를 엄격히 나눈다.

    reddit_fetch.py   네트워크 → raw/{글id}.json   (API 응답 그대로, 무가공)
    reddit_parse.py   raw → records/sealed/manifest  (언제든 다시 돌릴 수 있다)

raw 를 남겨두면 스키마가 바뀌어도, 해시 규칙이 바뀌어도, 솔트가 바뀌어도
재크롤링 없이 다시 만들 수 있다. raw 는 봉인 층이다 — 저장소에 올리지 않는다.

사용
    # 1) GV80: 이미 아는 글 id 를 다시 긁는다
    python3 scripts/reddit_fetch.py targets --ids work/targets_GV80.txt \
            --raw sealed/raw/GV80 --loop

    # 2) G70: 서브레딧별 검색·새글목록으로 글 id 를 찾는다
    python3 scripts/reddit_fetch.py discover --subs work/subs.txt --query G70 \
            --since 2026-01-01 --until 2026-08-31 \
            --out work/targets_G70.txt --log work/attempted_searches_G70.json

인증 (가이드 §1 — 공식 API 우선)
    REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET 가 있으면 OAuth(분당 100회).
    없으면 공개 .json 페이지로 떨어지고 분당 약 10회로 스스로 조인다.
    REDDIT_USER_AGENT 는 반드시 설명적으로 — 레딧이 기본 UA 를 차단한다.
"""
import argparse, json, os, sys, time, hashlib, collections, datetime, urllib.parse
import urllib.request, urllib.error

UA = os.environ.get("REDDIT_USER_AGENT",
                    "python:genesis-discourse-research:v1.0 (contact: set REDDIT_USER_AGENT)")
CID = os.environ.get("REDDIT_CLIENT_ID")
CSEC = os.environ.get("REDDIT_CLIENT_SECRET")

# 가이드 §1 — 한 실행 상한 200 레코드. 닿으면 커서를 저장하고 멈춘다.
DEFAULT_MAX_RECORDS = 200


class Limiter:
    """OAuth 100 QPM / 비인증 10 QPM. 429 는 Retry-After 를 따르고 지수 백오프."""

    def __init__(self, qpm):
        self.interval = 60.0 / max(qpm, 1)
        self.last = 0.0
        self.backoff = 0.0

    def wait(self):
        now = time.time()
        gap = self.interval + self.backoff - (now - self.last)
        if gap > 0:
            time.sleep(gap)
        self.last = time.time()

    def penalise(self, retry_after=None):
        if retry_after:
            self.backoff = max(self.backoff, float(retry_after))
        else:
            self.backoff = min(max(self.backoff * 2, 2.0), 120.0)

    def relax(self):
        self.backoff = max(0.0, self.backoff * 0.5)


class Client:
    def __init__(self):
        self.token = None
        self.oauth = bool(CID and CSEC)
        self.limiter = Limiter(100 if self.oauth else 10)
        self.stats = collections.Counter()
        if self.oauth:
            self._auth()

    def _auth(self):
        data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
        req = urllib.request.Request("https://www.reddit.com/api/v1/access_token", data=data)
        raw = ("%s:%s" % (CID, CSEC)).encode()
        import base64
        req.add_header("Authorization", "Basic " + base64.b64encode(raw).decode())
        req.add_header("User-Agent", UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            self.token = json.load(r)["access_token"]
        print("[auth] OAuth 토큰 획득 — 분당 100회", file=sys.stderr)

    def get(self, path, params=None, tries=6):
        """path 는 '/comments/abc123' 처럼 선행 슬래시를 포함한 경로."""
        params = dict(params or {})
        params.setdefault("raw_json", 1)
        base = "https://oauth.reddit.com" if self.oauth else "https://old.reddit.com"
        suffix = "" if self.oauth else ".json"
        url = base + path + suffix + "?" + urllib.parse.urlencode(params)
        for attempt in range(tries):
            self.limiter.wait()
            req = urllib.request.Request(url)
            req.add_header("User-Agent", UA)
            if self.oauth:
                req.add_header("Authorization", "Bearer " + self.token)
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    body = r.read()
                self.stats["ok"] += 1
                self.limiter.relax()
                return json.loads(body.decode("utf-8"))
            except urllib.error.HTTPError as e:
                self.stats["http_%d" % e.code] += 1
                if e.code == 429:
                    self.limiter.penalise(e.headers.get("Retry-After"))
                elif e.code in (401,) and self.oauth:
                    self._auth()
                elif e.code in (403, 404):
                    return None                     # 삭제·비공개 — 재시도해도 같다
                else:
                    self.limiter.penalise()
            except Exception as e:                  # 연결 끊김·타임아웃
                self.stats["neterr"] += 1
                self.limiter.penalise()
                if attempt == tries - 1:
                    print("[fail] %s — %s" % (path, e), file=sys.stderr)
        self.stats["gaveup"] += 1
        return None


# ------------------------------------------------------------------ 댓글 완전 수집
def _walk_more(node, acc):
    """접힌 'more' 스텁의 자식 id 를 모은다. 이게 커버리지 결손의 원인이다."""
    if not isinstance(node, dict):
        return
    kind, data = node.get("kind"), node.get("data") or {}
    if kind == "more":
        acc.extend(data.get("children") or [])
        return
    replies = data.get("replies")
    if isinstance(replies, dict):
        for ch in (replies.get("data") or {}).get("children") or []:
            _walk_more(ch, acc)


def fetch_thread(cli, tid, raw_dir):
    """한 스레드를 원응답 그대로 저장한다. 접힌 댓글은 morechildren 으로 채운다."""
    out = os.path.join(raw_dir, tid + ".json")
    if os.path.exists(out):
        return "cached"
    doc = cli.get("/comments/" + tid, {"limit": 500, "sort": "old", "depth": 20})
    if doc is None:
        return "gone"
    more_ids = []
    for ch in ((doc[1].get("data") or {}).get("children") or []):
        _walk_more(ch, more_ids)
    extra = []
    while more_ids:
        chunk, more_ids = more_ids[:100], more_ids[100:]
        mc = cli.get("/api/morechildren",
                     {"api_type": "json", "link_id": "t3_" + tid,
                      "children": ",".join(chunk), "limit_children": "false"})
        if not mc:
            break
        things = (((mc.get("json") or {}).get("data") or {}).get("things")) or []
        extra.extend(things)
        for t in things:
            _walk_more(t, more_ids)
    payload = {"listing": doc, "morechildren": extra,
               "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "auth": "oauth" if cli.oauth else "public_page"}
    os.makedirs(raw_dir, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return "ok"


# ------------------------------------------------------------------ 모드: targets
def mode_targets(a):
    ids = []
    for line in open(a.ids, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#"):
            ids.append(line.split()[0])
    os.makedirs(a.raw, exist_ok=True)
    cur_path = os.path.join(a.raw, "_cursor.json")
    cur = json.load(open(cur_path, encoding="utf-8")) if os.path.exists(cur_path) else {"done": []}
    done = set(cur["done"])
    cli = Client()
    tally = collections.Counter()
    while True:
        todo = [i for i in ids if i not in done]
        if not todo:
            break
        n = 0
        for tid in todo:
            st = fetch_thread(cli, tid, a.raw)
            tally[st] += 1
            done.add(tid)
            n += 1
            if n % 10 == 0:
                print("  %d/%d  %s" % (len(done), len(ids), dict(tally)), file=sys.stderr)
            if a.max_records and n >= a.max_records:
                break
        cur["done"] = sorted(done)
        json.dump(cur, open(cur_path, "w", encoding="utf-8"), ensure_ascii=False)
        print("[checkpoint] %d/%d  %s  http=%s"
              % (len(done), len(ids), dict(tally), dict(cli.stats)), file=sys.stderr)
        if not a.loop:
            break
    print(json.dumps({"targets": len(ids), "fetched": len(done),
                      "tally": dict(tally), "http": dict(cli.stats)}, ensure_ascii=False))


# ------------------------------------------------------------------ 모드: discover
def mode_discover(a):
    """서브레딧별 검색 + 새글목록 훑기. 가이드 §1 — 쿼리당 250건 상한을 새글목록으로 보완."""
    subs = [s.strip().lstrip("r/") for s in open(a.subs, encoding="utf-8")
            if s.strip() and not s.startswith("#")]
    since = datetime.datetime.strptime(a.since, "%Y-%m-%d").replace(
        tzinfo=datetime.timezone.utc).timestamp()
    until = datetime.datetime.strptime(a.until, "%Y-%m-%d").replace(
        tzinfo=datetime.timezone.utc).timestamp() + 86399
    cli = Client()
    found, log = {}, []

    def take(children, src):
        kept = 0
        for ch in children or []:
            d = ch.get("data") or {}
            if ch.get("kind") != "t3":
                continue
            c = d.get("created_utc") or 0
            if since <= c <= until:
                found.setdefault(d["id"], {"id": d["id"], "sub": d.get("subreddit"),
                                           "created_utc": c, "src": src})
                kept += 1
        return kept

    for sub in subs:
        tried = kept = 0
        after, pages = None, 0
        while pages < a.search_pages:
            p = {"q": a.query, "restrict_sr": 1, "sort": "new", "limit": 100,
                 "t": "all", "include_over_18": "on"}
            if after:
                p["after"] = after
            doc = cli.get("/r/%s/search" % sub, p)
            if not doc:
                break
            data = doc.get("data") or {}
            ch = data.get("children") or []
            tried += len(ch)
            kept += take(ch, "search:%s" % sub)
            after = data.get("after")
            pages += 1
            if not after or not ch:
                break
        capped = tried >= 250
        log.append({"query": a.query, "subreddit": "r/" + sub,
                    "tried": tried, "kept": kept, "hit_250_cap": capped})
        # 250건 상한에 닿았으면 새글목록으로 보완한다
        if capped and a.listing_pages:
            after, pages, ltried, lkept = None, 0, 0, 0
            while pages < a.listing_pages:
                p = {"limit": 100}
                if after:
                    p["after"] = after
                doc = cli.get("/r/%s/new" % sub, p)
                if not doc:
                    break
                data = doc.get("data") or {}
                ch = data.get("children") or []
                ltried += len(ch)
                lkept += take([c for c in ch
                               if a.query.lower() in json.dumps(c.get("data") or {}).lower()],
                              "listing:%s" % sub)
                oldest = min([(c.get("data") or {}).get("created_utc") or 0 for c in ch] or [0])
                after = data.get("after")
                pages += 1
                if not after or not ch or oldest < since:
                    break
            log.append({"query": a.query + " (새글목록 보완)", "subreddit": "r/" + sub,
                        "tried": ltried, "kept": lkept, "pages": pages})
        print("  r/%-28s 검색 %4d → %3d%s" % (sub, tried, kept, "  [250 상한]" if capped else ""),
              file=sys.stderr)

    with open(a.out, "w", encoding="utf-8") as f:
        for v in sorted(found.values(), key=lambda x: x["created_utc"]):
            f.write("%s\t%s\n" % (v["id"], v["sub"]))
    if a.log:
        json.dump({"attempted_searches": log, "unique_threads": len(found),
                   "http": dict(cli.stats)},
                  open(a.log, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps({"subs": len(subs), "unique_threads": len(found),
                      "http": dict(cli.stats)}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="mode", required=True)

    t = sp.add_parser("targets", help="아는 글 id 를 원응답째 다시 긁는다")
    t.add_argument("--ids", required=True)
    t.add_argument("--raw", required=True)
    t.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS,
                   help="한 구간 상한(가이드 §1). 0 이면 무제한")
    t.add_argument("--loop", action="store_true", help="커서를 저장하며 끝까지 이어 돈다")
    t.set_defaults(func=mode_targets)

    d = sp.add_parser("discover", help="서브레딧별 검색·새글목록으로 글 id 를 찾는다")
    d.add_argument("--subs", required=True)
    d.add_argument("--query", required=True)
    d.add_argument("--since", required=True)
    d.add_argument("--until", required=True)
    d.add_argument("--out", required=True)
    d.add_argument("--log", default=None, help="attempted_searches 기록 (manifest §3-3)")
    d.add_argument("--search-pages", type=int, default=3)
    d.add_argument("--listing-pages", type=int, default=10)
    d.set_defaults(func=mode_discover)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
