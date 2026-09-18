# market-research_discovery-001

담론 수집 데이터의 스레드 단위 선별·코딩·관계 분석 파이프라인.

## 파이프라인

```
sealed/records ─▶ ① screen.py          정규식·사전만. 점수·중복·화자지배 (LLM 호출 없음)
              ─▶ ② 스레드 단위 관계 추출(경량 코딩, 5필드)  ─▶ relation_lite.jsonl
              ─▶ ③ 추출 품질 게이트(표본 검사, 정의 표류)    ─▶ 통과/반려
              ─▶ ④ 선별 스레드 정식 코딩(coding_guide §5, 코더 A·B) ─▶ coding_rows_final
              ─▶ ⑤ relation_analyzer.py  쌍 행렬·독립 계수·교차 관측·그래프·감도
              ─▶ ⑥ ig_reaction.py + 반응 코딩 (엣지 아님, 별도 층)
```

## 디렉터리 규약

| 경로 | 내용 | 버전 관리 |
|---|---|---|
| `sealed/records/` | 수집 원문 jsonl (봉인 층) | ❌ gitignore |
| `ref/` | 키워드 사전 · 코딩 가이드 | ❌ gitignore |
| `work/` | 선별표 · manifest · 코딩 산출물 | ❌ gitignore |
| `scripts/` | 파이프라인 스크립트 | ✅ |

> 이 저장소는 **public**이다. 원문·작성자 해시·본문 발췌·내부 방법론 문서는
> 커밋하지 않는다. 자료는 세션 로컬 또는 비공개 보관소에 둔다.

## ⓪-0 recollect.py — 재수집 진입점

터미널에서 이 셋만 쓰면 된다. 셸 문법을 타지 않아 OS 를 가리지 않고,
추가 설치할 패키지가 없다(표준 라이브러리만).

```
python3 scripts/recollect.py doctor   # 환경 진단 — 빠진 것을 한국어로 알려준다
python3 scripts/recollect.py gv80     # 수집 → 파싱 → 검증
python3 scripts/recollect.py g70
```

절차와 환경변수는 `RUNBOOK_reddit_recollect.md` 의 «빠른 시작».

## ⓪-1 reddit_fetch.py · reddit_parse.py

레딧 재수집기. **API 원응답을 먼저 `sealed/raw/` 에 보관하고** 그다음 파싱한다 —
1차 배치의 계정명·`parent_id`·URL 소실은 전부 원응답을 버려서 생겼다.
절차는 `RUNBOOK_reddit_recollect.md`, 오프라인 검증은 `test_reddit_pipeline.py`(44개 점검).

```
python3 scripts/test_reddit_pipeline.py                      # 네트워크 없이 돈다
python3 scripts/reddit_fetch.py targets --ids work/targets_GV80.txt \
        --raw sealed/raw/GV80 --loop
python3 scripts/reddit_parse.py --raw sealed/raw/GV80 --model GV80 \
        --window 202601_202608 --since 2026-01-01 --until 2026-08-31 \
        --out work --sealed sealed/records
```

## ⓪ cleanse_reddit_v1.py · run_cleanse_reddit.py · verify_reddit_batch.py

수집기가 낸 schema 1.2 배치를 가이드 v2.2 §4·§5 규격(schema 1.6)으로 클렌징한다.
키 재부여 · 답글 계층 · 권역 고정 · 마스킹 · 중복 · 충돌 필터 · 전동화 근접 매칭 ·
§3-3 manifest 재작성까지. `verify_reddit_batch.py` 가 §8 점검표를 자동 판정한다.

```
python3 scripts/run_cleanse_reddit.py <입력디렉터리> work sealed/records
python3 scripts/verify_reddit_batch.py GV80 G70
```

복원 불가능한 결함은 고치지 않는다 — `known_nulls` 와 리포트에 사실대로 남긴다.

## ① screen.py

스레드 단위로 묶어 선별 점수를 매긴다. 순위는 매기지 않는다 — 점수는 임계값(≥3)
판정에만 쓰고, 점수 분포는 manifest에 남긴다. 본문은 파일에서 파일로만 흐른다.
