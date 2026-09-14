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

## ① screen.py

스레드 단위로 묶어 선별 점수를 매긴다. 순위는 매기지 않는다 — 점수는 임계값(≥3)
판정에만 쓰고, 점수 분포는 manifest에 남긴다. 본문은 파일에서 파일로만 흐른다.
