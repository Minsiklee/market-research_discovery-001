#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Arctic Shift 아카이브에서 수집한다 — 레딧 직접 접속의 대안.

레딧이 익명 접속을 막고 OAuth 도 통과가 안 될 때 쓴다. 도메인이 달라
사내망 차단도 따로 받는다(막힐 수도, 열릴 수도 있다 — probe 로 확인한다).

왜 이쪽이 오히려 나은가
  · author · parent_id 가 원본 그대로 들어 있다. 우리가 1차 배치에서 잃은 둘이다
  · _meta.was_deleted_later 가 있어 "나중에 지워진 글"을 정확히 가려낸다.
    실시간 레딧은 [deleted] 로만 보여서 언제 지워졌는지 알 수 없다
  · 글 id 500개를 한 번에 조회한다. GV80 230개가 요청 한 번이다
  · 검색에 250건 상한이 없다. G70 의 탐색 문제가 풀린다
  · 인증이 필요 없다

한계 — 정직하게
  · 게시 후 36시간 시점의 스냅샷이다. 그 뒤의 수정은 _meta.is_edited 로만 알 수 있다
  · 비공개·격리 서브레딧은 들어 있지 않다
  · 무료 서비스다. "초당 두어 건" 이 예의다(README 의 표현)

산출물은 reddit_fetch.py 와 같은 모양이라 reddit_parse.py 가 그대로 읽는다.
"""
import argparse, collections, datetime, json, os, sys, time
import urllib.request, urllib.error, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _console; _console.setup()

BASE = os.environ.get("ARCTIC_BASE", "https://arctic-shift.photon-reddit.com")
UA = os.environ.get("REDDIT_USER_AGENT",
                    "python:genesis-discourse-research:v1.0 (set REDDIT_USER_AGENT)")
DEFAULT_MAX_RECORDS = 200


class Api:
    """초당 2건으로 스스로 조인다. 429 면 X-RateLimit-Reset 을 따른다."""

    def __init__(self, qps=2.0):
        self.gap = 1.0 / qps
        self.last = 0.0
        self.backoff = 0.0
        self.stats = collections.Counter()
        self._diag_shown = False

    def get(self, path, params, tries=5):
        url = BASE + path + "?" + urllib.parse.urlencode(params)
        for attempt in range(tries):
            wait = self.gap + self.backoff - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            req = urllib.request.Request(url)
            req.add_header("User-Agent", UA)
            req.add_header("Accept", "application/json")
            try:
                with urllib.request.urlopen(req, timeout=90) as r:
                    body = r.read()
                if body.strip()[:1] not in (b"{", b"["):
                    self.stats["notjson"] += 1
                    self._diagnose(body, url)
                    self.backoff = min(max(self.backoff * 2, 2.0), 60.0)
                    continue
                self.stats["ok"] += 1
                self.backoff = max(0.0, self.backoff * 0.5)
                return json.loads(body.decode("utf-8"))
            except urllib.error.HTTPError as e:
                self.stats["http_%d" % e.code] += 1
                if e.code == 429:
                    reset = (e.headers.get("X-RateLimit-Reset") if e.headers else None)
                    try:
                        self.backoff = max(self.backoff, float(reset))
                    except (TypeError, ValueError):
                        self.backoff = min(max(self.backoff * 2, 5.0), 120.0)
                elif e.code in (400, 404):
                    return None
                else:
                    self.backoff = min(max(self.backoff * 2, 2.0), 60.0)
            except Exception as e:
                self.stats["neterr"] += 1
                self.backoff = min(max(self.backoff * 2, 2.0), 60.0)
                if attempt == tries - 1:
                    print("[fail] %s — %s" % (path, str(e)[:120]), file=sys.stderr)
        self.stats["gaveup"] += 1
        return None

    def _diagnose(self, body, url):
        if self._diag_shown:
            return
        self._diag_shown = True
        head = body[:600].decode("utf-8", "replace")
        print("\n[진단] Arctic Shift 가 JSON 이 아닌 것을 돌려줬습니다.", file=sys.stderr)
        print("[진단] 주소: %s" % url, file=sys.stderr)
        for line in head.splitlines()[:6]:
            if line.strip():
                print("       %s" % line.strip()[:110], file=sys.stderr)
        print("", file=sys.stderr)


def items(doc):
    """응답 껍데기가 {"data": [...]} 든 [...] 든 알맹이만 꺼낸다."""
    if doc is None:
        return []
    if isinstance(doc, list):
        return doc
    d = doc.get("data")
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        return [d]
    return []


def flatten_tree(nodes, out):
    """댓글 트리를 평평하게 편다.

    Arctic 이 {kind,data} 로 싸서 주든 알맹이만 주든 둘 다 받는다.
    중첩은 풀어도 된다 — parent_id 가 남아 있어 관계는 그걸로 다시 세운다."""
    for n in nodes or []:
        if not isinstance(n, dict):
            continue
        kind = n.get("kind")
        if kind == "more":
            continue                       # limit=9999 면 거의 안 나온다
        d = n.get("data") if (kind or "data" in n) and isinstance(n.get("data"), dict) else n
        if not isinstance(d, dict) or not d.get("id"):
            continue
        replies = d.get("replies")
        out.append({k: v for k, v in d.items() if k != "replies"})
        if isinstance(replies, dict):
            flatten_tree(((replies.get("data") or {}).get("children")) or [], out)
        elif isinstance(replies, list):
            flatten_tree(replies, out)


def to_reddit_shape(post, comments):
    """reddit_fetch.py 가 내는 것과 같은 모양으로 맞춘다 — 파서를 안 고치려고."""
    return {
        "listing": [
            {"kind": "Listing", "data": {"children": [{"kind": "t3", "data": post}]}},
            {"kind": "Listing", "data": {"children": []}},
        ],
        "morechildren": [{"kind": "t1", "data": c} for c in comments],
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "auth": "arctic_shift", "source": "arctic_shift",
    }


def mode_targets(a):
    ids = [l.split()[0] for l in open(a.ids, encoding="utf-8")
           if l.strip() and not l.startswith("#")]
    os.makedirs(a.raw, exist_ok=True)
    cur_path = os.path.join(a.raw, "_cursor.json")
    cur = json.load(open(cur_path, encoding="utf-8")) if os.path.exists(cur_path) else {"done": []}
    done = set(cur["done"])
    api = Api(a.qps)
    tally = collections.Counter()

    todo = [i for i in ids if i not in done]
    posts = {}
    for i in range(0, len(todo), 100):                  # 상한 500 이지만 100 이 안전하다
        chunk = todo[i:i + 100]
        doc = api.get("/api/posts/ids", {"ids": ",".join(chunk)})
        for p in items(doc):
            if p.get("id"):
                posts[p["id"]] = p
        print("  글 정보 %d/%d" % (len(posts), len(todo)), file=sys.stderr)
    print("[arctic] 글 %d개 확보 (요청 %d회)" % (len(posts), (len(todo) + 99) // 100),
          file=sys.stderr)

    n = 0
    for tid in todo:
        post = posts.get(tid)
        if not post:
            tally["gone"] += 1
            done.add(tid)
            continue
        doc = api.get("/api/comments/tree", {"link_id": "t3_" + tid, "limit": 9999})
        comments = []
        flatten_tree(items(doc), comments)
        with open(os.path.join(a.raw, tid + ".json"), "w", encoding="utf-8") as f:
            json.dump(to_reddit_shape(post, comments), f, ensure_ascii=False)
        tally["ok"] += 1
        tally["comments"] += len(comments)
        done.add(tid)
        n += 1
        if n % 10 == 0:
            print("  %d/%d  %s" % (len(done), len(ids), dict(tally)), file=sys.stderr)
            cur["done"] = sorted(done)
            json.dump(cur, open(cur_path, "w", encoding="utf-8"), ensure_ascii=False)
        if a.max_records and n >= a.max_records and not a.loop:
            break
    cur["done"] = sorted(done)
    json.dump(cur, open(cur_path, "w", encoding="utf-8"), ensure_ascii=False)
    print(json.dumps({"targets": len(ids), "fetched": len(done), "tally": dict(tally),
                      "http": dict(api.stats)}, ensure_ascii=False))


def mode_discover(a):
    """서브레딧별로 글과 댓글을 훑어 대상 글 id 를 모은다.

    레딧 검색과 달리 250건 상한이 없다. 댓글 본문 검색까지 되므로
    '본문엔 없고 댓글에만 모델명이 나오는 스레드'도 잡힌다(가이드 §2)."""
    subs = [s.strip().lstrip("r/") for s in open(a.subs, encoding="utf-8")
            if s.strip() and not s.startswith("#")]
    api = Api(a.qps)
    found, log = {}, []

    def sweep(endpoint, sub, keyfield):
        after, tried, kept, rounds = a.since, 0, 0, 0
        while rounds < a.max_pages:
            p = {"subreddit": sub, "after": after, "before": a.until,
                 "limit": 100, "sort": "asc"}
            p[keyfield] = a.query
            doc = api.get(endpoint, p)
            rows = items(doc)
            if not rows:
                break
            tried += len(rows)
            for r in rows:
                if endpoint.startswith("/api/posts"):
                    pid = r.get("id")
                else:
                    pid = (r.get("link_id") or "").replace("t3_", "")
                if pid and pid not in found:
                    found[pid] = {"id": pid, "sub": sub, "via": endpoint}
                    kept += 1
            last = max((r.get("created_utc") or 0) for r in rows)
            if len(rows) < 100:
                break
            after = int(last) + 1
            rounds += 1
        return tried, kept

    for sub in subs:
        t1, k1 = sweep("/api/posts/search", sub, "query")
        t2, k2 = sweep("/api/comments/search", sub, "body")
        log.append({"query": a.query, "subreddit": "r/" + sub,
                    "posts_tried": t1, "posts_kept": k1,
                    "comments_tried": t2, "comments_kept": k2,
                    "source": "arctic_shift"})
        print("  r/%-28s 글 %4d→%3d · 댓글 %4d→%3d" % (sub, t1, k1, t2, k2), file=sys.stderr)

    with open(a.out, "w", encoding="utf-8") as f:
        for v in found.values():
            f.write("%s\t%s\n" % (v["id"], v["sub"]))
    if a.log:
        json.dump({"attempted_searches": log, "unique_threads": len(found),
                   "source": "arctic_shift", "http": dict(api.stats)},
                  open(a.log, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps({"subs": len(subs), "unique_threads": len(found),
                      "http": dict(api.stats)}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--qps", type=float, default=2.0, help="초당 요청 수 (기본 2)")
    sp = ap.add_subparsers(dest="mode", required=True)

    t = sp.add_parser("targets")
    t.add_argument("--ids", required=True)
    t.add_argument("--raw", required=True)
    t.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    t.add_argument("--loop", action="store_true")
    t.set_defaults(func=mode_targets)

    d = sp.add_parser("discover")
    d.add_argument("--subs", required=True)
    d.add_argument("--query", required=True)
    d.add_argument("--since", required=True)
    d.add_argument("--until", required=True)
    d.add_argument("--out", required=True)
    d.add_argument("--log", default=None)
    d.add_argument("--max-pages", type=int, default=30)
    d.set_defaults(func=mode_discover)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
