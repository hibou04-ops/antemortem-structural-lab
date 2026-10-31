# E9-R1 실제 역사적 결함 자료

이 자료는 공개 저장소의 **이미 알려진 비보안 결함 재발견**을 위한 검토된 자료다. 새 취약점 발견이나 현재 배포판 결함을 뜻하지 않는다. 원래 함수의 고정된 buggy/fixed revision에서 필요한 AST 원문 단락과 표준 라이브러리 바인딩만 추출했다. Work에서 외부 원본 함수를 실행하지 않는다. 실제 실행은 검증된 CI Docker 경계에서만 허용된다.

`manifest.json`은 원본 저장소·경로·함수·revision·Git blob SHA, 원문 단락 SHA, 캡슐 SHA, 라이선스 출처, 공개 입력 계약과 독립 Oracle의 적용 범위를 기록한다. `candidate-catalog.json`은 3개 프로젝트의 검토 후보 15개 중 Source 2개와 Target 6개의 선정, 나머지 7개의 제외 이유를 기록한다. 고정 revision의 정상 대조 6개는 같은 함수의 수정본이며 독립 구현으로 세지 않는다. 방법별 성능 실행을 보고 사례를 선정하거나 교체하지 않는다.

| 역할 | 원래 함수 / 공개 근거 | 실제 입력과 적용 범위 |
|---|---|---|
| Source | toolz `interpose`, [PR 635](https://github.com/pytoolz/toolz/pull/635) | 정수열, 구분자 0. 빈 입력의 `StopIteration` 처리 |
| Source | more-itertools `bucket`, [issue 1308](https://github.com/more-itertools/more-itertools/issues/1308) | 정수열, 공개 회귀 사례의 비어 있는 callable `AllowedKeys` validator. 매번 새 bucket |
| Target | more-itertools `windowed`, [issue 462](https://github.com/more-itertools/more-itertools/issues/462) | 정수열, 폭 2·step 1·padding `None`. 빈 입력은 빈 결과 |
| Target | toolz `accumulate`, [PR 410](https://github.com/pytoolz/toolz/pull/410) | 정수열, 덧셈·초깃값 없음. Python 3의 PEP 479 동작 포함 |
| Target | boltons `split_iter`, [공식 수정](https://github.com/mahmoud/boltons/commit/4aa77cddb5d06def130df6f09aefab4018fa487c) | 정수열, 공개 `maxsplit=0` 설정의 중첩 수준. 이 고정 설정은 전체 API가 아니다 |
| Target | boltons `split_punct_ws`, [issue 492](https://github.com/mahmoud/boltons/issues/492) | 문자열, 선언된 ASCII 문자·구두점·공백 범위의 정규식 escaping |
| Target | boltons `iter_splitlines`, [issue 475](https://github.com/mahmoud/boltons/issues/475) | 문자열, 선언된 문자와 Unicode 줄 구분자. 마지막 빈 줄을 보존하는 원래 계약 |
| Target | boltons `bytes2human`, [PR 525](https://github.com/mahmoud/boltons/pull/525) | 유한 float −2048..2048, 공개 `ndigits=0`의 표시 반올림 후 B/K 단위 선택. 비유한값 처리 PR 508과 다른 결함 |

각 Oracle는 수정본 함수의 출력을 호출하지 않고 공개 계약을 별도로 구현한다. 수정본은 보조 정상 대조다. 변환은 공개 고정 인자 전달과 iterator의 list materialization뿐이며 입력 타입 위장·출력 수정·정답 주입을 하지 않는다. `bytes2human`의 float 입력 및 `bucket`의 callable validator는 원래 API가 사용하는 값으로 명시한다.

Source는 정수열만 포함한다. 문자열·float Target은 타입 fallback과 routing 대조이며, 이 자료만으로 해당 타입의 양의 구조 전이를 주장하지 않는다. 6개 Target 중 4개가 boltons에 속하므로 프로젝트 분포도 균등하지 않다. `split_iter(maxsplit=0)`는 모든 입력에서 쉽게 재현될 수 있는 고정 설정이다. 그런 포화 결과도 숨기거나 성능을 본 뒤 사례를 바꾸지 않는다.

원본 캡슐은 전체 프로젝트를 설치하거나 가져오지 않는다. `benchmarks/historical.py`의 `cases(load=False)`는 JSON·AST·해시만 읽는다. `load=True`, `load_case`, 원본 호출은 모두 `tomolab.historical.require_reviewed_container()`를 거친다. 실제 Docker 검사 없이 환경 변수나 파일의 해시 재계산만으로 실행을 허용하지 않는다. catalog와 factory 자체의 승인 digest는 실행 준비·동결 영수증에 별도로 묶는다.

평가자 전용 재현 입력은 manifest에 보존하되 worker의 생성기 요청으로 보내지 않는다. worker에는 원본 함수, 패치, Oracle, 재현 입력을 전달하지 않는다. 원본 함수의 실제 진입 관측과 논리적인 Target 호출 수를 분리한다. generator의 재개 이벤트는 새 Target 호출로 세지 않는다. MRI는 투명 adapter의 root만 분석하며 원래 함수 내부의 분기 구조를 분석한 것으로 보고하지 않는다.

전체 원문과 실행 증거는 별도의 감사·CI 산출물이다. 이 디렉터리는 실행이 완료됐다는 주장이나 방법 D의 우위 판정 자체를 포함하지 않는다. 실제 실행·회귀·방법 비교의 PASS/FAIL과 범위는 별도 CI 영수증으로 판정한다.

MIT / BSD-3-Clause 원저작자 라이선스 전문은 `vendor/*-LICENSE.txt`에 보존했다. 이 자료는 패키지의 Apache-2.0 라이선스로 원본 저작권을 바꾸지 않는다.
