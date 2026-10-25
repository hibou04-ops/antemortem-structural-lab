# C1 별도 검토 기록

기준일: 2026-10-26 (Asia/Seoul). 상태: **RESOLVED — 아래 5개 재현의 수정 확인 완료**.
이는 명시한 개발 평가 범위의 수정 확인이며 일반 자연어 의미 정확도 인증이 아니다.

검토자는 선행연구 조사, blind direct 생성과 별도 turn의 same-agent self-review를
완료·봉인한 뒤 코드 리뷰 역할로 전환했다. 생성 당시 읽은 입력은 지정된
`blind_generation_prompts.json`과 본인 direct artifact뿐이었다. 이 리뷰 단계에서는
공개 개발 계약·gold·코어·평가 코드를 읽었다. 봉인 holdout archive는 열지 않았고
생성 baseline과 코어 알고리즘을 수정하지 않았다. 역할 분리는 외부 인간 검토나
서로 독립된 model family를 뜻하지 않는다. 인간 의미 검토는 0건이다.

## 독립 Boolean soundness 점검

`tests/test_c1_boolean_soundness.py`는 두 Boolean 변수의 네 입력 상태에서 가능한
모든 claim/obligation truth membership를 각각 4-bit mask로 나타낸다. 16×16개의
C/O 쌍, 공통 `forall`/`exists`, 전수 성공 제출과 네 개별 실패 witness를 합쳐
총 **2,560건**의 `adjudicate` 결론을 검사한다.

정답은 생산 DSL interpreter로 계산하지 않고 mask membership에서 직접 구한다.
`REFUTED`이면 해당 양화 C가 거짓인지, `PROVED_BOUNDED`이면 참인지, 원문 자연어
상태가 항상 `UNKNOWN / NOT_ESTABLISHED`인지 확인한다. 최초 수동 실행에서
잘못된 결론은 0건이었다. 저장한 테스트 실행 receipt는 아래에 기록한다.

이 점검은 불리언 네 상태, 빈 전제·예외, 단일 상태의 **형식 결론 soundness**만
다룬다. 정수 전체, 임의 전이·전제, 자원 제한, UNKNOWN completeness 또는 원문
자연어 의미의 정확성을 증명하지 않는다. 모든 경우에 UNKNOWN을 반환하는 구현도
soundness 조건만 만족할 수 있으므로 기존 relation/coverage 테스트와 함께 읽어야 한다.

## 발견 사항과 수정 확인

아래 줄 번호는 최초 검토 snapshot의 위치다. 수정 후 위치와 재현 결과를 덧붙인다.

1. **P1 — LLM 생성과 unsafe lifting 정책의 혼합** (`evaluate.py:93`, `219–224`).
   Q02의 생성 결과는 존재 양화 문맥의 `x>=0`이다. 평가 harness가 `x=-1` 하나를
   골라 `FAIL→REFUTED`로 올리므로 정확한 번역에도 wrong-refuted가 기록된다.
   이는 생성 LLM이 내린 반증 선언이 아니다. `LLM-generated O + unsafe lifting`
   정책으로 이름과 범위를 명시하고, 동일 후보의 authority 적용 결과와 paired
   비교하거나 양화사에 맞는 O 실행과 unsafe lift ablation을 분리해야 한다.
   **수정 확인: RESOLVED** (`evaluate.py:127–136`, `275–292`, `324–325`).
   실제 봉인 direct/self-review 후보의 Q02는 양화사에 맞춰 전수 성공으로 처리되어
   guarded/unguarded 모두 `PROVED_BOUNDED`다. 같은 생성 O와 증거를 쓰는 authority
   paired arm이 추가되었다. 결과 reason에 unguarded lifting 정책이 명시된다.
   두 실제 LLM arm의 false REFUTED는 **각각 0/23 → 0/23**으로, 이 자료에서 감소를
   관측했다고 주장할 수 없다.
2. **P2 — witness 필드의 명제 반증 오표기** (`evaluate.py:107–108`, `120`).
   Q02에서 `claim_true_bounded=True`와 `witness_refutes_formal_claim=True`가 함께
   반환된다. 계산한 것은 점별 claim predicate 위반이며 존재 명제 반증이 아니다.
   predicate 위반과 quantified claim refutation을 별도 필드로 기록해야 한다.
   **수정 확인: RESOLVED** (`evaluate.py:159–162`).
   원래 Q02의 실패 witness `x=-1`을 별도로 제출해 재현했을 때
   `witness_violates_claim_predicate=True`, `quantified_claim_refutation_valid=False`다.
3. **P2 — 평가 row에서 자연어 승격 방어 정보 손실** (`evaluate.py:113–121`).
   코어 결과의 `conclusion_target=SUPPLIED_FORMAL_CLAIM`,
   `natural_language_status=UNKNOWN`, `semantic_fidelity=NOT_ESTABLISHED`가
   report row로 전달되지 않는다. 개별 REFUTED row를 분리해 소비할 때도 원문
   상태를 오해하지 않도록 row와 report에 보존해야 한다.
   **수정 확인: RESOLVED** (`evaluate.py:163–164`, `327–328`).
   실제 direct/self-review의 guarded/unguarded 모든 row에서 세 필드를 확인했고
   report 최상위에도 동일한 한정이 보존된다.
4. **P2 — 관측된 생성 시간 receipt 연결 누락** (`evaluate.py:232–235`).
   봉인 artifact는 `provenance.elapsed_seconds`에 direct 60.244초, self-review
   31.307초를 기록하지만 evaluator는 `generation_elapsed_seconds`를 읽어 null을
   반환한다. 필드 연결을 맞춰 이미 관측된 시간을 보고해야 한다. token·금액의
   null은 관측 불가능하다는 뜻이며 0으로 채우면 안 된다.
   **수정 확인: RESOLVED** (`evaluate.py:297–308`).
   실제 artifact의 direct 60.244초, self-review 31.307초가 각각 연결된다.
   token·금액은 관측값이 없어 null을 유지한다. guarded arm은 생성 비용을
   원래 unguarded arm과 공유하며 새 생성 run을 0으로 표시한다.

추가 **P2 — oracle와 생산 DSL의 자원 수용 경계 차이** (`evaluate.py:42–75`).
oracle는 깊이는 제한하지만 생산 checker의 노드·정수·중간값·work 제한을 공유하지
않는다. 다음 작은 식의 `h`는 150 bit이고 oracle는 `h==h`를 수용하지만 코어는
`ARITHMETIC_RESOURCE_LIMIT / UNKNOWN`으로 거절한다.

```text
h = ["*", ["*", 1000000000, 1000000000],
     ["*", ["*", 1000000000, 1000000000], 1000000000]]
O = ["==", h, h]
```

현재 봉인 후보에서 관측한 오류는 아니지만 새로운 후보 artifact의 공정한 평가와
DoS 통제에는 중요한 경계다. 독립 gold evaluator를 유지하면서 별도 입력 수용
검사를 적용하거나 명시적으로 다른 평가 언어임을 기록해야 한다.
**수정 확인: RESOLVED** (`evaluate.py:24–36`, `52–96`, `103–114`).
동일한 150-bit 식은 이제 `oracle intermediate integer limit`으로 거절된다.
리터럴·노드·깊이·상태·work 제한과 파일 읽기 전 byte cap도 별도 구현으로 추가되었다.
이는 공통 실험 한도에서의 수용 통제이며 OS 수준의 보안 격리 주장이 아니다.

## 저장된 테스트 실행 receipt

- 별도 의존성 환경에서 새 Boolean audit 테스트: **1 passed in 0.13s**.
- 같은 환경의 기본 전체 suite, `python -m pytest --basetemp ../pytest-review`:
  **190 passed in 0.95s** (evaluator 수정 확인 전 snapshot).
- 이 실행은 trusted fixtures와 data-only DSL을 사용했다. 별도 Python 환경은
  의존성 분리이며 OS 보안 격리를 뜻하지 않는다.
- 후속 evaluator 수정은 위 190-pass receipt로 검증된 것으로 간주하지 않는다.
- evaluator 수정 후 필요한 범위만 다시 실행:
  `python -m pytest tests/test_c1_boolean_soundness.py tests/test_c1_evaluation.py --basetemp ../pytest-review-followup`
  → **104 passed in 0.24s**.
- 재확인한 `evaluate.py` 원본 byte SHA256:
  `f8cdd3efdfe1a19acf48702e8d1a0994217d873db828fc2cc4a01c81d5795da1`.
- 실제 LLM paired 비교에서 false REFUTED 개선은 0건이다. P03의 모순된 전제에서는
  unguarded `PROVED_BOUNDED`가 guarded `UNKNOWN`으로 바뀐다. P03의 형식 C 진릿값은
  정의되지 않아 `claim_true_bounded=None`이며 `wrong_proved_count`에는 포함되지 않는다.
  따라서 이를 “wrong_proved_count 1→0”이라고 보고하면 안 된다. 정확한 관측은
  **일관성 없는 전제에서 근거 없는 유한 증명 선언 1건을 보류했다**는 것이다.
