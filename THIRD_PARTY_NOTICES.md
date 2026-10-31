# Third-party notices / 제3자 고지

Antemortem Structural Lab's own code is distributed under [Apache-2.0](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/LICENSE). This license does not replace the licenses of historical source extracts or installed dependencies.

프로젝트 자체 코드는 Apache-2.0이며 아래 원본·의존성의 저작권이나 라이선스를 바꾸지 않습니다. 과거 문서의 “vendored implementation 없음” 설명은 당시 배포 범위의 기록입니다. 현재 역사적 검증 자료에는 다음의 검토된 최소 원문이 포함됩니다.

## Reviewed historical source / 검토된 역사적 원문

| Upstream project | Retained source | License and copyright |
|---|---|---|
| [toolz](https://github.com/pytoolz/toolz) | `interpose`, `concat`, `accumulate` selected statements and reviewed bindings | BSD-3-Clause; Copyright (c) 2013 Matthew Rocklin |
| [more-itertools](https://github.com/more-itertools/more-itertools) | `bucket`, `windowed` selected statements | MIT; Copyright (c) 2012 Erik Rose |
| [boltons](https://github.com/mahmoud/boltons) | `split_iter` and helpers; `split_punct_ws`, `iter_splitlines`, `bytes2human` and required constants | BSD-3-Clause; Copyright (c) 2013 Mahmoud Hashemi |

Full original license text is retained in [toolz-LICENSE.txt](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/benchmarks/historical/vendor/toolz-LICENSE.txt), [more-LICENSE.txt](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/benchmarks/historical/vendor/more-LICENSE.txt), and [boltons-LICENSE.txt](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/benchmarks/historical/vendor/boltons-LICENSE.txt). Applicable license files accompany distribution metadata. Copyright notices are also retained in source capsules.

원본 repository·path·buggy/fixed revision·Git blob identity·선정 단락 SHA·캡슐 SHA·라이선스 출처는 [manifest](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/benchmarks/historical/manifest.json)에 기록합니다. 선택한 함수 본문과 상수의 원문을 보존하고 검토한 표준 라이브러리 바인딩·저작권 안내를 추가했습니다. 전체 텍스트 저장 과정의 CRLF→LF·끝 개행 차이는 upstream Git blob의 정확한 바이트 identity와 구분합니다.

These extracts are historical non-security bug fixtures, not current upstream packages or endorsement by their authors. Source distributions include the reviewed catalog; the ordinary user example does not import or execute it. Their execution requires the separate inspected container gate. The full upstream projects are not installed or automatically collected by the product demo.

역사적 비보안 결함 자료는 현재 upstream 배포판이나 원저작자의 보증을 뜻하지 않습니다. source distribution의 검토 자료와 일반 사용자 예제는 별도입니다. 외부 원문의 실행은 전용 container 게이트를 거치며 제품 데모가 전체 외부 프로젝트를 설치하거나 자동 수집하지 않습니다.

## Dependencies and tools / 의존성과 도구

The authoritative optional dependencies are declared in [pyproject.toml](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/pyproject.toml): Hypothesis and psutil (`qa`), Z3 (`solver`), CrossHair (`analysis`), and SciPy/NumPy (`corr`). They are installed separately and retain their upstream licenses. Their implementation code is not copied into the project's runtime modules. Python's standard library, pytest/build/twine, GitHub Actions, and separately built Docker images retain their respective terms. Dependency and container installation are distinct from shipping the reviewed historical extracts above.

선택 의존성과 개발·CI 도구는 각각의 라이선스를 유지합니다. Hypothesis의 생성·축소, Python AST, Z3, CEGIS·version space·active learning은 기존 기술입니다. 이 프로젝트가 이 원리를 새로 발명했다고 주장하지 않습니다. 이미지나 외부 서비스의 라이선스·비용·권한은 별도이며 기본 예제에 유료 서비스가 필요하지 않습니다.
