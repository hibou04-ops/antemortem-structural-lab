# Release validation

## v0.6.0a1 — E6 Stateful Mold

원격 기준 main f269ba9와 v0.5.0a1 tag를 확인한 뒤 별도 작업 사본·브랜치를 사용했습니다. 기존250개 회귀는 보존했습니다. 실제 결과와 범위는 [E6 구현](E6_INTEGRATION.md), [평가 보고](E6_EVALUATION_REPORT.md), [공개 집계](E6_RESULTS.json)로 구분합니다.

- Native stateful → 평가 전 등록 → 최소 개발 증거 → 공유 Version Space → qualified query → freeze → native shrink/2replay의 CLI를 실제 실행했습니다.
- list와 deque의 다른 이름·내부 구현에서 frozen 계획을 별도 독립 Model로 검사했습니다.
- cold clean profile은 동일 spec/contract/target/Model hash·입력 순서·각24회 전이에서 불필요 pool 생성0.245초→0을 확인했습니다. 단일 기능 프로파일이며 연구 속도 우위는 아닙니다.
- 전체 source tests는 기존250개와 신규 temporal/native/efficiency/CLI/boundary/evaluator/publication 검사를 포함합니다. 최종 실행 수·시간은 실제 JUnit과 CI에서 확인합니다.
- 정보 경계 독립 감사는 raw source/actual/expected/final label/subjective score, frozen 등록·feedback, 재해시한 snapshot 변조를 전송 전에 차단했습니다.
- 최종 전 평가기의 baseline 경로 동결·모든 기준선 control 오탐·CrossHair Oracle 오류 전파를 수정해 독립 재감사했습니다. 모델 family·expected fault·case label은 Generator public specification에 포함하지 않습니다.
- 로컬 Docker daemon은 미가용입니다. 실제 E4/E5/E6 container 검증은 각각 정상 CI job으로 수행합니다. 기본 subprocess는 LOGICAL_ISOLATION_ONLY, 대상·Model은 신뢰된 host code입니다.
- wheel/sdist·installed-wheel CLI·README·공개 범위·annotated tag/draft/asset hash 검증을 별도 게이트로 실행합니다. E5의 draft 조회 회귀도 재사용합니다.

개발 연구 결과는 NO_IMPROVEMENT입니다. E6 stateful14/15 vs강한 black-box15/15, source OUT_OF_GRAMMAR1·NO_FAILURE1, 대표 후보12/13 반증을 모두 보존했습니다. 알려진 last-pop 표현 회귀와 전체 문법·외적 일반화를 구분합니다. 기존 소비 holdout은 새 blind evidence로 재사용하지 않습니다.

[릴리스 노트](releases/v0.6.0a1.md) · [CI](https://github.com/hibou04-ops/antemortem-structural-lab/actions). 최종 gate 결과와 원격 자산은 완료 보고서와 release receipt로 readback합니다.


## v0.5.0a1 — E5 unified engine

2026-10-27 KST, Windows/Python 3.12에서 실제 실행한 local gate입니다. 연구 결과는 [평가 aggregate](E5_RESULTS.json)와 [한국어 평가 보고](E5_EVALUATION_REPORT.md)로 분리합니다.

| Gate | 실제 local 결과 |
| --- | --- |
| 기존 기능 회귀 | 기존 145 tests 보존·통과 |
| 전체 source tests | 243 passed / failures 0 / errors 0 / skips 0, 17.965s |
| 실제 README CLI | 영문 15 + 한국어 15 = 30/30; Docker와 설치 URL은 local CLI 검사에서 제외 |
| E5 end-to-end | sequence native/Z3 + state trace + frozen renamed plan; 실제 call/축소/재실행 포함 |
| 배포 실패 차단 | offline 6 tests: draft hash/download 실패 시 publish 금지, 기존 annotated tag·assets 보존 |
| wheel/sdist | 0.5.0a1 build 및 twine metadata check PASS |
| base wheel | 깨끗한 별도 환경의 no-index 설치, pip check, 기존 bundled CLI·Claim·Mold PASS |
| optional QA wheel | 정상 CI에서 새 환경 설치·native discovery/Z3/state 검사를 필수 실행 |
| 공개 범위 | source·명시 staged blobs·wheel/sdist의 credential/private-path scan; raw final source/answers/logs 미포함 |
| 최종 동결 평가 | 63 attempts: 48 COMPLETE / E4 15 NOT_COMPARABLE; 오류·timeout 0, feedback 0, once-only |
| 연구 판정 | 개발·최종 모두 NO_IMPROVEMENT, 외부 실제 프로젝트 generalization NOT_EXECUTED |
| 실제 Docker 접근 통제 | local daemon 사용 불가; E4/E5 별도 Actions job의 결과로 판정 |

Generator strict protocol·allowlist·동결 차단은 local 통합 테스트로 검사했습니다. 기본 subprocess는 LOGICAL_ISOLATION_ONLY이며 Docker 통과를 local 실행으로 주장하지 않습니다. source 40 files·계약·fixture·27 source molds·새 final suite가 동결됐고 최종 결과에 따라 제품을 변경하거나 같은 suite를 재평가하지 않았습니다. 독립감사에서 평가 전체성·deadline 버그 2건을 최종 실행 전에 수정했습니다. source/contract/holdout은 동결 후 보존됐습니다.

공개 릴리스는 [CI](https://github.com/hibou04-ops/antemortem-structural-lab/actions)의 main 8개 필수 검사 성공 후 별도 job에서 annotated tag·verified draft·public asset download를 검사하도록 강제합니다. 해당 release job의 실제 성공 여부와 [v0.5.0a1](https://github.com/hibou04-ops/antemortem-structural-lab/releases/tag/v0.5.0a1) 원격 자산은 release readback 증거로 따로 확인합니다. 과거 태그와 E1~E4 원본은 덮어쓰지 않습니다.


## v0.3.0a1 — E3 integration

This section separates implementation, bounded research performance, packaging and public-release status. Checks below were executed on Windows with Python 3.12.10 on 2026-10-27 KST. A passing unit suite alone is not a generalization result.

| Check | Observed result |
| --- | --- |
| Source tests, including existing functionality | `python -m pytest -q`: 76 passed, no failures or skips in the reviewed environment |
| Distribution build | Wheel and sdist for `0.3.0a1` built successfully |
| Fresh wheel environment | Dependency check, packaged demo, claim compilation/search/replay, Mold imports/demo and frozen mapped plan passed outside the source checkout |
| README runtime examples | All 14 literal CLI commands from the Korean and English READMEs exited successfully in separate public-source copies; expected output states verified |
| Documentation links | Final nine-document audit checked 47 relative-link occurrences with none missing |
| Independent E3 evaluation | 7,040 candidate Oracle calls, all 5,120 final candidates frozen before evaluation, no final feedback |
| Independent ledger review | A second agent recomputed 7,040 rows from literal target formulas and records without importing the target or engine; all matched |
| Freeze preservation | All 10 frozen engine/spec files and all three benchmark source commitments unchanged after evaluation |
| PR CI | [Run 40355976452](https://github.com/hibou04-ops/antemortem-structural-lab/actions/runs/40355976452): all seven jobs passed; Ubuntu and Windows with Python 3.11/3.12/3.13 exercised source tests, builds, metadata/content checks and clean wheel installation |
| Docker access controls | Same run's generator-isolation job passed: host sentinel unreadable, public code not writable, external connection unavailable, UID 65534, private host environment absent; 24 end-to-end development calls completed |
| Final main and published assets | The update script requires successful final-main CI and matching source HEAD before tagging; validates draft asset sizes and SHA-256 before publication. Final commit/tag runs are available in [Actions](https://github.com/hibou04-ops/antemortem-structural-lab/actions), and public assets in [v0.3.0a1](https://github.com/hibou04-ops/antemortem-structural-lab/releases/tag/v0.3.0a1) |

The new checks cover competing hypotheses and refutations, active-query and diversity behavior, justified and rejected transfer, frozen-state protection, JSON process communication, existing CLI compatibility and installed-wheel execution. The optional Docker boundary is evaluated separately from the default `LOGICAL_ISOLATION_ONLY` subprocess path. Targets and Oracles remain trusted host code.

E1 and E2 remain `E1_EXECUTED_NO_IMPROVEMENT` and `E2_EXECUTED_NO_IMPROVEMENT`. E2 used 26,880 candidate Oracle calls and produced A/B/C/D discovery sums of 76/75/72/76, with 16 distinct injected task sites per arm across seeds. D and A had identical final candidate and Oracle records; no new portable constraint was learned. Those consumed data are not fresh E3 evaluation data.

E3's final comparison used 2,560 calls per arm across eight tasks and five seeds. Uniform/Mold discovery sums were 30/30, distinct injected task sites 6/6, and failure events 452/1,104. Mean first-discovery calls across all 40 trials per arm were 21.025/17.5, with non-discoveries censored at 65. This descriptive reduction of about 16.8% did not meet the preregistered joint success criterion, which also required at least two additional task-seed discoveries and at least 10% greater discovery breadth. The bounded verdict is `NO_IMPROVEMENT`; broader generalization remains `GENERALIZATION_UNKNOWN`.

The applicability gate allowed 35 Mold task-seed probes and returned `UNKNOWN` for five contract mismatches. Clean controls produced no false failures. These are synthetic paired-transfer integration checks, not newly discovered real-world defects. The local benchmark used `LOGICAL_ISOLATION_ONLY`. See the [E3 evaluation description](E3_EVALUATION.md).

Publication checks inspect explicit staged paths and the contents of the wheel, sdist and release assets. Private evaluation files, raw records, E1/E2 evidence ZIPs, personal paths and credentials are excluded. This is a bounded inspection of reviewed content, not a universal guarantee against sensitive material.

See the [v0.3.0a1 release notes](releases/v0.3.0a1.md) and [security model](../SECURITY.md).

## Historical first-publication validation

Local checks on 2026-10-25 used Windows and Python 3.12.10. This document describes the checked fixtures and distribution boundaries.

| Source snapshot | pytest | Distribution check |
| --- | --- | --- |
| v0.1.0 | 21 passed | Rebuilt wheel installed separately; explicit-path example and replay succeeded |
| v0.1.1 | 29 passed | Rebuilt wheel installed separately; explicit-path example and replay succeeded |
| v0.2.0 | 45 passed | Rebuilt wheel installed separately; bundled demo, claim compilation, counterexample, replay and small claim benchmark succeeded |

The English and Korean README examples were executed, and all 18 relative links resolved in the source tree. Their claim examples encode the same swap relation. Each finds the supplied `(17, -3)` / `(-3, 17)` witness, with results 15 / 14. The language-specific contract hashes differ by design because the source claim text is part of the hash.

CrossHair 0.0.112 found the three supplied relation violations using the assert-based comparison fixture. Its counterexample exit code was 1. This checks those relations and fixtures; no comparative speed, general defect-finding advantage or independent natural-language semantic fidelity is established. No live Jev call was made for these publication checks.

The pre-publication checks found two portability defects. A test read UTF-8 evidence using the Windows locale encoding; it now states UTF-8 explicitly. The old wheel omitted the examples used by bundled commands; v0.2.0 includes and locates them after installation. A fresh-environment wheel check covers this path. Git attributes fix text line endings so source blobs and distribution files can be compared byte for byte across platforms. Probe and claim algorithms were not changed.

The historical v0.1.0 and v0.1.1 tag objects remain unchanged. Their READMEs retain the archived wording, including references to generated results that were intentionally excluded. The release notes explain how to generate fresh evidence and use the historical wheels with explicit example paths.

The complete reachable Git history was inspected for credentials, private research material, personal filesystem paths and accidental output files. The pattern scan and manual review found none in the reviewed public content. This is a bounded inspection, not a guarantee against every possible sensitive string. First-party runtime code uses the Python standard library; see [third-party materials](THIRD_PARTY.md).

The [GitHub Actions matrix](https://github.com/hibou04-ops/antemortem-structural-lab/actions) runs source tests, source/wheel builds and a fresh wheel installation on Ubuntu and Windows with Python 3.11, 3.12 and 3.13. Its actual run status is reported by Actions.
