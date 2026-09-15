# market-research_discovery-001

담론 수집 데이터의 스레드 단위 선별·코딩·관계 분석 파이프라인.

## 파이프라인

```
sealed/candidates ─▶ ⓞ anonymize_candidates.py  url 제거 · handle→SPK · 대화→CONV ─▶ work/anon
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
| `sealed/candidates/` | 후보 원본 jsonl — url·handle 포함 (봉인 층) | ❌ gitignore |
| `sealed/ledger/` | 가명 대응표 (SPK·CONV ↔ 실제 값) | ❌ gitignore |
| `work/anon/` | 워커 전달용 가명 사본 | ❌ gitignore |
| `ref/` | 키워드 사전 · 코딩 가이드 | ❌ gitignore |
| `work/` | 선별표 · manifest · 코딩 산출물 | ❌ gitignore |
| `scripts/` | 파이프라인 스크립트 | ✅ |

> 이 저장소는 **public**이다. 원문·작성자 해시·본문 발췌·내부 방법론 문서는
> 커밋하지 않는다. 자료는 세션 로컬 또는 비공개 보관소에 둔다.

## ① screen.py

스레드 단위로 묶어 선별 점수를 매긴다. 순위는 매기지 않는다 — 점수는 임계값(≥3)
판정에만 쓰고, 점수 분포는 manifest에 남긴다. 본문은 파일에서 파일로만 흐른다.

## ⓞ anonymize_candidates.py

워커에게는 가명 사본만 준다. 원본은 봉인 층에 남는다.

- `url` 을 지운다.
- `handle` 을 권역 안 등장 순서대로 `SPK-{권역}-X-001…` 로 바꾼다. 순서 기준은
  (파일명, 줄번호) — 한 권역이 여러 파일로 쪼개져도 재현된다. 같은 handle 이 두 권역에
  나오면 권역마다 다른 번호를 받는다(권역 안 번호이므로). 대응은 대장에 남는다.
- `in_reply_to_url` 은 `url ↔ in_reply_to_url` 간선으로 묶은 대화마다 `CONV-001…` 로
  바꾼다. 번호는 전역 일련번호다. 부모가 후보셋 밖에 있어도 같은 부모를 가리키면 한 대화다.
  null 은 null 로 둔다 — 답글인지 아닌지는 이 필드로 그대로 읽힌다.
- `conv_id` 를 새로 붙인다. 대화에 속한 모든 레코드가 받는다 — 원글도 받는다. 원글은
  `in_reply_to_url` 이 null 이라 그 필드만으로는 자기 대화를 가리키지 못한다.
- 한 계정이 두 권역에 나오면 권역마다 다른 번호를 받는다. manifest 의 `speaker_aliases`
  에 가명끼리의 동일 관계만 적는다(실제 handle 은 적지 않는다) — 워커가 한 화자를
  둘로 세지 않게 한다.
- 배치를 더해 다시 돌릴 때 이미 발급한 번호가 바뀌면 중단한다. 대장의 최신 판과
  대조한다 — 워커가 이미 받은 사본과 번호가 어긋나면 안 된다.
- 대응표는 `sealed/ledger/` 에만 쓴다. 사본과 manifest 에는 실제 값이 없다.
- 쓰기 전에 누출 검사(`https?://`, `x.com/`, `@handle`)를 건다. 한 건이라도 걸리면
  아무 파일도 쓰지 않고 중단한다.
