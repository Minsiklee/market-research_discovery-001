# 레딧 재수집 런북 — GV80 먼저, G70 나중

## 빠른 시작 — 명령 세 줄

터미널에 익숙하지 않아도 된다. **셸 문법을 타지 않으므로 macOS·Windows·리눅스에서 명령이 똑같다.**
추가로 설치할 패키지도 없다(파이썬 표준 라이브러리만 쓴다).

```
# 0) 받아오기 — 한 번만
git clone https://github.com/Minsiklee/market-research_discovery-001.git
cd market-research_discovery-001
git checkout claude/trusting-goodall-exr1d3

# 1) 받으신 targets_GV80.txt 를 work/ 폴더에 넣는다
#    (또는 1차 배치 sealed 파일로 다시 만든다:
#     python3 scripts/make_targets.py --sealed <sealed_...GV80.jsonl>)

# 2) 환경 진단 — 무엇이 빠졌는지 한국어로 알려준다
python3 scripts/recollect.py doctor

# 3) 실행
python3 scripts/recollect.py gv80
```

`doctor` 가 초록불이 될 때까지 시키는 대로 고친 다음 `gv80` 을 친다.
`gv80` 은 수집 → 파싱 → 검증까지 알아서 이어 돈다.
**중간에 끊겨도 같은 명령을 다시 치면 이어서 돈다** — 이미 받은 스레드는 건너뛴다.

### 환경변수 두 개

`doctor` 가 요구하는 것은 이 둘이다. 터미널을 새로 열면 사라지므로 그때마다 다시 친다
(매번 치기 싫으면 macOS 는 `~/.zshrc`, Windows 는 시스템 환경변수에 넣는다).

**macOS · 리눅스**
```bash
export REDDIT_USER_AGENT="python:genesis-research:v1.0 (by /u/본인계정)"
export REDDIT_CLIENT_ID="..."        # 선택 — 있으면 4배 빠르다
export REDDIT_CLIENT_SECRET="..."    # 선택
```

**Windows PowerShell**
```powershell
$env:REDDIT_USER_AGENT="python:genesis-research:v1.0 (by /u/본인계정)"
$env:REDDIT_CLIENT_ID="..."
$env:REDDIT_CLIENT_SECRET="..."
```

`REDDIT_USER_AGENT` 는 **필수**다. 레딧이 기본 User-Agent 를 차단한다.
자격증명은 https://www.reddit.com/prefs/apps 에서 "create app" → **script** 타입으로 만든다.
없어도 돌아가지만 분당 10회로 조여진다(GV80 20~40분 vs 5~10분).

### 막히면

`doctor` 나 실행 중 메시지를 **그대로 복사해서** 물어보면 된다. 흔한 것 셋.

| 증상 | 원인 | 조치 |
|---|---|---|
| `[2] 연결 실패` | 사내망·VPN·방화벽 | 개인 네트워크에서 시도 |
| `HTTP 403` 반복 | User-Agent 미설정 | 위 환경변수 설정 |
| `http_429` 가 계속 | 속도 제한 | 그대로 두면 스스로 느려지며 회복한다. 자격증명을 넣으면 거의 사라진다 |

---

이 저장소의 세션에서는 레딧 egress가 조직 정책으로 막혀 있다.
아래는 **네트워크가 열린 환경**(로컬 PC 등)에서 그대로 따라 하는 절차다.

## 0. 왜 재수집하나

1차 배치가 원응답을 버리고 가공 결과만 남겨서 셋을 잃었다.

| 잃은 것 | GV80 | G70 |
|---|---|---|
| 작성자 계정명 | 임시 솔트 해시만 남아 복원 불가 | 평문으로 남아 있음(단 층 분리 위반) |
| `parent_id` | 옛 번호를 가리켜 35.7%가 오결합 | **필드 자체가 없음** |
| URL | 봉인층에 있음 | **봉인층 미납품 — 전량 소실** |
| 결손 댓글 | 1,239건 | 831건 |

그래서 이번 수집기는 **원응답을 먼저 파일로 보관**한다. 규칙이 바뀌어도
재크롤링 없이 다시 파싱하면 된다.

## 1. 준비 (자세히)

```bash
export REDDIT_USER_AGENT="python:genesis-discourse-research:v1.0 (by /u/<계정>)"
# 선택 — 있으면 분당 100회, 없으면 분당 10회로 스스로 조인다
export REDDIT_CLIENT_ID=...
export REDDIT_CLIENT_SECRET=...
```

레딧 앱 등록: https://www.reddit.com/prefs/apps → "script" 타입.
**OAuth를 쓰는 편이 훨씬 빠르고 429도 적다**(GV80 5~10분 vs 20~40분).

먼저 오프라인 테스트가 통과하는지 본다. 네트워크를 타지 않는다.

```bash
python3 scripts/test_reddit_pipeline.py     # 44개 점검
```

## 2. GV80 — 아는 글 id 를 다시 긁는다

`work/targets_GV80.txt` 에 1차 배치 봉인층에서 복원한 글 id 230개가 있다.

```bash
python3 scripts/reddit_fetch.py targets \
    --ids work/targets_GV80.txt \
    --raw sealed/raw/GV80 \
    --loop
```

- 200건마다 `sealed/raw/GV80/_cursor.json` 에 커서를 남긴다(가이드 §1).
  중간에 끊겨도 같은 명령을 다시 치면 이어서 돈다.
- 이미 받은 스레드는 건너뛴다.
- 삭제·비공개는 `gone` 으로 집계된다. 8개월 지난 글이라 5~10% 예상.

이어서 파싱한다. 네트워크를 타지 않으므로 몇 번이든 다시 돌려도 된다.

```bash
python3 scripts/reddit_parse.py \
    --raw sealed/raw/GV80 --model GV80 \
    --window 202601_202608 --since 2026-01-01 --until 2026-08-31 \
    --out work --sealed sealed/records

python3 scripts/verify_reddit_batch.py GV80
```

`verify` 가 §8 점검표를 판정한다. 통과 기준은 이 셋이 핵심이다.

- 3 화자 식별자 — `author_key` 가 전 레코드에 있어야 한다
- 4b 답글 계층 — `position` 에 `reply` 가 있어야 한다
- 5 댓글 커버리지 — 평균 0.8 이상

## 3. G70 — 글 id 부터 다시 찾는다

URL이 없으므로 먼저 찾아야 한다. `work/subs_G70.txt` 가 시작 목록이다
(1차 배치에서 실제로 건진 52개 + 429로 실패했던 4개).
**원 수집의 175개 서브레딧 목록이 있으면 그것으로 교체한다 — 더 넓다.**

```bash
python3 scripts/reddit_fetch.py discover \
    --subs work/subs_G70.txt --query G70 \
    --since 2026-01-01 --until 2026-08-31 \
    --out work/targets_G70.txt \
    --log work/attempted_searches_G70.json

python3 scripts/reddit_fetch.py targets \
    --ids work/targets_G70.txt --raw sealed/raw/G70 --loop

python3 scripts/reddit_parse.py \
    --raw sealed/raw/G70 --model G70 \
    --window 202601_202608 --since 2026-01-01 --until 2026-08-31 \
    --out work --sealed sealed/records

python3 scripts/verify_reddit_batch.py G70
```

`--log` 산출물을 manifest의 `attempted_searches` 에 옮겨 적는다 — 1차 배치에
비어 있던 칸이고, "담론이 얇다"와 "우리가 덜 찾았다"를 가르는 유일한 근거다(§3-3).

검색이 쿼리당 250건 상한에 닿으면 새글목록으로 자동 보완하고 그 사실을 로그에 남긴다.

## 4. 끝난 뒤

```bash
# 두 배치를 합칠 때 — thread_key 로 중복 스레드를 1건 처리한다
python3 - <<'EOF'
import json, collections
tk = {}
for m in ("GV80", "G70"):
    p = "work/records_reddit-GLOBAL-202601_202608-%s.jsonl" % m
    tk[m] = {json.loads(l)["thread_key"] for l in open(p, encoding="utf-8")}
print("공유 스레드:", len(tk["GV80"] & tk["G70"]))
EOF
```

`author_key` 가 양쪽 다 `reddit:{계정명}` 이 되므로 **이제 배치 간 화자 연결이 된다**
(1차 배치에서는 교집합이 0이었다). 최종 산출에 해시·가명으로 바꿀지는 관리자 단계에서 정한다 — 수집·클렌징의 범위가 아니다(§4-4).

## 5. 주의

- `sealed/` 와 `work/` 는 gitignore 대상이다. 원문·URL·닉네임을 저장소에 올리지 않는다.
- `sealed/raw/` 는 **버리지 않는다.** 이번 사고의 원인이 바로 그것이다.
- 목표에 미달해도 **기준을 풀어 채우지 않는다.** 미달 사실과 확보 건수를 그대로 적는다(§1·§5-6).
