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

## ③ coding_tools.py — 추출 품질 게이트

② 산출(`relation_lite`)을 병합·검사·집계하고, 오푸스 게이트에 넘길 표본 팩을 만든다.

```
python3 scripts/coding_tools.py merge    --lite work/relation_lite_out --out work/gate
python3 scripts/coding_tools.py validate --lite work/relation_lite_out --out work/gate
python3 scripts/coding_tools.py stats    --lite work/relation_lite_out --out work/gate
python3 scripts/coding_tools.py pack     --lite work/relation_lite_out \
                                         --chunks work/relation_lite --out work/gate
```

- `merge` — `(thread_key, record_id)` 복합키. `record_id` 단독으로는 스레드가 섞인다.
- `validate` — enum · 인용 15단어 · direction(`CO`=null, `SUB-review`=`?`,
  `SUB-choice`·`TR`=`→`) · node_a 목록. 위반이 있으면 종료 코드 1.
  node_a 허용 목록은 `--node-a-list` 로 갈아끼운다.
- `stats` — 건수만. 비율·경향은 내지 않는다.
- `pack` — 청크마다 5 스레드(관계 최다 1 · `relations:[]` 1 · 무작위 3), 오푸스 세션당 2 청크.
  팩에는 **통글과 소넷 산출 줄 둘뿐**이다. manifest·검토 문서·판정 문서 §1 은 넣지 않는다 —
  §1 은 `prompts/gate_opus_v1.md` 안에 들어간다. 자물쇠가 매번 확인한다.
  무작위 3은 청크 이름으로 시드를 고정해 같은 입력이면 같은 표본이 나온다.

산출은 전부 `work/` 아래 — 인용을 담고 있어 커밋하지 않는다.

## ① screen.py

스레드 단위로 묶어 선별 점수를 매긴다. 순위는 매기지 않는다 — 점수는 임계값(≥3)
판정에만 쓰고, 점수 분포는 manifest에 남긴다. 본문은 파일에서 파일로만 흐른다.
