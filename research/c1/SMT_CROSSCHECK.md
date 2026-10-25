# 선택적 Z3 독립 대조

유한 열거 엔진의 결과를 기존 도구 Z3로 대조한다. 기존 runtime 의존성이나
배포 버전을 바꾸지 않는다. 별도 격리 연구 환경에만 설치한다.

```bash
python -m pip install -r research/c1/requirements-research.txt
python -m research.c1.smt_crosscheck --output research/c1/results/smt_crosscheck.json
python -m pytest tests/test_c1_smt_crosscheck.py -q
```

실제 실행 버전은 `z3-solver==5.3.2.0`이다. 각 질의에 기본 1,000 ms 제한을
설정하고 Z3의 `unknown`을 함의 성립으로 해석하지 않는다. 설치되지 않았으면
미검증으로 남기며 성공을 반환하지 않는다. CLI는 공개 개발 fixture 경로만 읽는다.
봉인 평가 자료와 gold label 파일을 읽지 않는다.

독립 visitor가 DSL을 Z3의 정수·불리언 표현식으로 변환한다. production evaluator,
validator, gold truth table을 SMT 식 생성에 재사용하지 않는다. 다음 질의를 각각
해결한 뒤 production `analyze`를 호출해 최종 결과만 대조한다.

1. `A`: 전제·입력 범위·예외를 만족하는 상태가 존재하는가.
2. `A ∧ C ∧ ¬O`: `C ⇒ O`를 깨는 상태가 존재하는가.
3. `A ∧ O ∧ ¬C`: `O ⇒ C`를 깨는 상태가 존재하는가.

SAT이면 Z3 모델의 변수 배정과 해당 모델이 질의를 만족하는지 기록한다.
UNSAT은 해당 유한 범위에서 분리 상태가 없다는 뜻이다. 전제 UNSAT,
모호한 해석, 지원 범위 밖 시간 조건, 혼합 양화사를 별도로 기록한다.

관측된 공개 개발 결과는 46/46건 관계·전제·함의 방향 일치, 그중 40건 실제
SAT/UNSAT 질의 수행, 나머지 6건 경계상태 보류, solver `unknown` 0건이다.
전체 행과 witness는 [결과](results/smt_crosscheck.json)에 있다. 이 검사는 제공된
형식 anchor에 관한 구현 대조다. 원문 자연어의 의미 정확성·현실 프로그램의
올바름을 추가 입증하지 않는다. 두 구현이 공유하는 형식화 오류도 남을 수 있다.

Z3 사용법은 공식 [Python API](https://z3prover.github.io/api/html/namespacez3py.html)와
[Solver API](https://z3prover.github.io/api/html/classz3py_1_1_solver.html)의 `Solver`,
`add`, `check`, `model`, `set`, `reason_unknown`을 확인했다(2026-10-26 조회).
