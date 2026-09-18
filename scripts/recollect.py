#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""레딧 재수집 — 명령 하나로 돌리는 진입점.

터미널에 익숙하지 않아도 이 파일 하나만 쓰면 된다. 셸 문법을 타지 않으므로
macOS · Windows · 리눅스에서 명령이 똑같다.

    python3 scripts/recollect.py doctor     먼저 이것부터. 환경을 진단한다
    python3 scripts/recollect.py gv80       GV80 재수집 → 파싱 → 검증까지
    python3 scripts/recollect.py g70        G70 (글 id 탐색부터)

중간에 끊겨도 같은 명령을 다시 치면 이어서 돈다. 이미 받은 스레드는 건너뛴다.
"""
import argparse, json, os, subprocess, sys, shutil
import urllib.request, urllib.error, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _console; _console.setup()
import _settings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SC = os.path.join(ROOT, "scripts")
WINDOW, SINCE, UNTIL = "202601_202608", "2026-01-01", "2026-08-31"

OK, NO, WARN = _console.marks()


def run(args, title):
    print("\n▶ %s" % title)
    print("   $ %s" % " ".join(a if " " not in a else '"%s"' % a for a in args))
    r = subprocess.run([sys.executable] + args, cwd=ROOT)
    if r.returncode:
        print("\n%s 위 단계에서 멈췄습니다. 메시지를 그대로 복사해 물어보시면 됩니다." % NO)
        sys.exit(r.returncode)


def token_test(cid, csec, timeout=20):
    """자격증명을 실제로 한 번 시험한다. 20분 돌린 뒤에 알면 늦다."""
    import base64
    ua = os.environ.get("REDDIT_USER_AGENT") or "recollect-doctor/1.0"
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request("https://www.reddit.com/api/v1/access_token", data=body)
    req.add_header("Authorization", "Basic " + base64.b64encode(
        ("%s:%s" % (cid, csec)).encode()).decode())
    req.add_header("User-Agent", ua)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            doc = json.load(r)
        return (200, "") if doc.get("access_token") else (None, "토큰이 오지 않음")
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read().decode("utf-8", "replace")[:120]
        except Exception:
            return e.code, e.reason
    except Exception as e:
        return None, str(e)[:100]


def reachable(host):
    try:
        req = urllib.request.Request("https://%s/r/GenesisMotors/about.json" % host)
        req.add_header("User-Agent", os.environ.get("REDDIT_USER_AGENT", "recollect-doctor/1.0"))
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, None
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return None, str(e)[:90]


def doctor(a):
    sp, svals = _settings.ensure(ROOT)[0], _settings.load(ROOT)[1]
    print("레딧 재수집 환경 진단\n" + "=" * 58)
    bad = []
    for d in ("work", "sealed/records", "sealed/raw"):
        os.makedirs(os.path.join(ROOT, d), exist_ok=True)

    v = sys.version_info
    print("\n[1] 파이썬")
    if v >= (3, 8):
        print("%s %d.%d.%d — 충분합니다 (추가 설치할 패키지 없음)" % (OK, v.major, v.minor, v.micro))
    else:
        print("%s %d.%d — 3.8 이상이 필요합니다" % (NO, v.major, v.minor)); bad.append("python")

    print("\n[2] 레딧 접속")
    st, err = reachable("www.reddit.com")
    if st in (200, 403, 429):
        print("%s 연결됨 (HTTP %s)" % (OK, st))
        if st == 403:
            print("%s 403은 대개 User-Agent 문제입니다. [4]를 보세요." % WARN)
    else:
        print("%s 연결 실패 — %s" % (NO, err or ("HTTP %s" % st)))
        print("     회사 네트워크·VPN·방화벽이 막고 있을 수 있습니다.")
        print("     개인 네트워크에서 다시 시도해 보세요.")
        bad.append("network")

    print("\n[3] 레딧 API 자격증명 (선택)")
    cid, csec = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
    if cid and csec:
        code, detail = token_test(cid, csec)
        if code == 200:
            print("%s 정상 — 분당 100회로 돕니다 (GV80 약 5~10분)" % OK)
        elif code == 401:
            print("%s 레딧이 거부했습니다 (401)" % NO)
            print("     client id 를 잘못 짚은 경우가 가장 흔합니다.")
            print("     https://www.reddit.com/prefs/apps 에서 앱을 펼치면,")
            print("     앱 이름 바로 아래 짧은 문자열이 client id,")
            print("     secret 칸 옆 긴 문자열이 secret 입니다.")
            print("     앱 종류가 script 가 아니어도 401 이 납니다.")
            print("")
            print("     ※ 이대로 둬도 수집은 됩니다 — 분당 10회로 느려질 뿐입니다.")
            print("       빨리 시작하려면 settings.txt 의 그 두 줄을 비우세요.")
        elif code is None:
            print("%s 확인 못 했습니다 — %s" % (WARN, detail))
        else:
            print("%s 레딧 응답 HTTP %s — %s" % (WARN, code, detail))
    else:
        print("%s 없음 — 공개 페이지로 분당 10회 (GV80 약 20~40분)" % WARN)
        print("     그래도 돌아갑니다. 빠르게 하려면:")
        print("     https://www.reddit.com/prefs/apps → create app → script 선택")
        print("     → 나온 값 둘을 아래 파일에 적으세요")
        print("       %s" % sp)

    print("\n[4] User-Agent")
    ua = os.environ.get("REDDIT_USER_AGENT")
    if ua and "set REDDIT_USER_AGENT" not in ua:
        print("%s %s" % (OK, ua))
        if "REDDIT_USER_AGENT" in svals:
            print("     (settings.txt 에서 읽었습니다)")
    else:
        print("%s 없음 — 레딧이 기본 UA를 차단합니다. 반드시 설정하세요." % NO)
        print("     가장 쉬운 길 — 아래 파일을 메모장으로 열어 REDDIT_USER_AGENT 줄을 채웁니다")
        print("       %s" % sp)
        print("     (터미널을 쓸 수 있다면)")
        print('       cmd:         set REDDIT_USER_AGENT=python:genesis-research:v1.0 (by /u/내계정)')
        print('       PowerShell:  $env:REDDIT_USER_AGENT="python:genesis-research:v1.0 (by /u/내계정)"')
        bad.append("ua")

    print("\n[5] 수집 대상 목록")
    tg = os.path.join(ROOT, "work", "targets_GV80.txt")
    if os.path.exists(tg):
        n = sum(1 for l in open(tg, encoding="utf-8") if l.strip() and not l.startswith("#"))
        print("%s work/targets_GV80.txt — 글 %d개" % (OK, n))
    else:
        print("%s work/targets_GV80.txt 가 없습니다" % NO)
        print("     받으신 targets_GV80.txt 를 %s 에 넣거나," % os.path.join(ROOT, "work"))
        print("     1차 배치 sealed 파일이 있으면 아래로 다시 만듭니다:")
        print("       python3 scripts/make_targets.py --sealed <sealed_...GV80.jsonl>")
        bad.append("targets")

    print("\n[6] 폴더")
    for d in ("work", "sealed/records", "sealed/raw"):
        print("%s %s/" % (OK, d))
    free = shutil.disk_usage(ROOT).free / 1e9
    print("%s 남은 디스크 %.1f GB (원응답 보관에 약 0.5 GB 필요)" % (OK if free > 1 else WARN, free))

    print("\n[7] 오프라인 자체 점검")
    r = subprocess.run([sys.executable, os.path.join(SC, "test_reddit_pipeline.py")],
                       cwd=ROOT, capture_output=True, text=True)
    last = [l for l in r.stdout.strip().split("\n") if l.strip()][-1] if r.stdout.strip() else ""
    print(("%s %s" % (OK, last)) if r.returncode == 0 else ("%s %s" % (NO, last)))
    if r.returncode:
        bad.append("selftest")

    print("\n" + "=" * 58)
    if not bad:
        print("준비 끝났습니다.  다음:  python3 scripts/recollect.py gv80")
    else:
        print("먼저 고칠 것: %s" % ", ".join(bad))
        print("위에 적힌 안내를 따르시고, 막히면 메시지를 그대로 복사해 물어보세요.")
    return 1 if bad else 0


def gv80(a):
    tg = os.path.join(ROOT, "work", "targets_GV80.txt")
    if not os.path.exists(tg):
        print("%s work/targets_GV80.txt 가 없습니다. 먼저 doctor 를 돌려보세요." % NO)
        sys.exit(1)
    run([os.path.join(SC, "reddit_fetch.py"), "targets", "--ids", tg,
         "--raw", os.path.join("sealed", "raw", "GV80"), "--loop"],
        "1/3 원응답 수집 — 끊겨도 같은 명령으로 이어집니다")
    run([os.path.join(SC, "reddit_parse.py"), "--raw", os.path.join("sealed", "raw", "GV80"),
         "--model", "GV80", "--window", WINDOW, "--since", SINCE, "--until", UNTIL,
         "--out", "work", "--sealed", os.path.join("sealed", "records")],
        "2/3 파싱 — 네트워크를 타지 않습니다. 몇 번이든 다시 돌려도 됩니다")
    run([os.path.join(SC, "verify_reddit_batch.py"), "GV80"], "3/3 납품 전 점검표 (가이드 §8)")
    print("\n끝났습니다. 위 점검표에서 FAIL 이 있으면 그 줄을 그대로 복사해 물어보세요.")


def g70(a):
    subs = os.path.join(ROOT, "work", "subs_G70.txt")
    if not os.path.exists(subs):
        print("%s work/subs_G70.txt 가 없습니다." % NO); sys.exit(1)
    run([os.path.join(SC, "reddit_fetch.py"), "discover", "--subs", subs, "--query", "G70",
         "--since", SINCE, "--until", UNTIL,
         "--out", os.path.join("work", "targets_G70.txt"),
         "--log", os.path.join("work", "attempted_searches_G70.json")],
        "1/4 글 id 탐색 — G70은 URL이 없어 먼저 찾아야 합니다")
    run([os.path.join(SC, "reddit_fetch.py"), "targets",
         "--ids", os.path.join("work", "targets_G70.txt"),
         "--raw", os.path.join("sealed", "raw", "G70"), "--loop"],
        "2/4 원응답 수집")
    run([os.path.join(SC, "reddit_parse.py"), "--raw", os.path.join("sealed", "raw", "G70"),
         "--model", "G70", "--window", WINDOW, "--since", SINCE, "--until", UNTIL,
         "--out", "work", "--sealed", os.path.join("sealed", "records")],
        "3/4 파싱")
    run([os.path.join(SC, "verify_reddit_batch.py"), "G70"], "4/4 납품 전 점검표")
    print("\n끝났습니다. work/attempted_searches_G70.json 을 manifest 의")
    print("attempted_searches 칸에 옮겨 적으세요 — 1차 배치에서 비어 있던 칸입니다.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("doctor", help="환경 진단 — 먼저 이것부터").set_defaults(func=doctor)
    sp.add_parser("gv80", help="GV80 수집 → 파싱 → 검증").set_defaults(func=gv80)
    sp.add_parser("g70", help="G70 탐색 → 수집 → 파싱 → 검증").set_defaults(func=g70)
    a = ap.parse_args()
    sys.exit(a.func(a) or 0)


if __name__ == "__main__":
    main()
