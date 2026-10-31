# 0.7 → 0.8 migration / 마이그레이션

The package remains `antemortem-structural-lab`; imports and commands remain `tomolab`. Version `0.8.0a1` is a prerelease. The published `0.7.0a1` files and earlier tags are preserved. Installing 0.7 does not provide the new online/replay interface.

배포·import·CLI 이름은 유지합니다. 기존 `0.7.0a1` 파일과 과거 태그를 변경하지 않습니다. 새 제품 기능의 게시와 기존 연구의 전이·최종 평가 readiness는 별도이며, 역사적 `allow_release=false` 기록을 성공으로 바꾸지 않습니다.

## Installation / 설치

Use a separate environment when keeping 0.7 workflows in use. The online commands require `qa`; the default package still has no mandatory third-party runtime dependency.

```bash
python -m venv lab-08-env
# Activate this environment with your platform's usual command, then:
python -m pip install "antemortem-structural-lab[qa]==0.8.0a1"
python -m tomolab online-run --help
python -m tomolab online-replay --help
```

0.7 작업을 유지한다면 별도 환경을 사용합니다. 기본 설치와 선택 extra를 구분하며, 온라인 경로에는 `qa`가 필요합니다. `solver`, `analysis`, `corr`는 각 기능을 사용할 때만 설치합니다.

## Defaults and examples / 기본값과 예제

The earlier research CLI defaulted to C. The product CLI now defaults to **A**, so scripts requiring the old policy must explicitly pass `--method C`. B/C are optional, and D requires explicit `--method D` plus a reviewed Mold and expected digest. An A/B `online-demo` uses the authored integer example without Source collection or learning. C/D demos retain explicit Source preparation and its measured cost.

기존 연구 CLI의 C 기본값이 제품 CLI에서는 **A**로 바뀝니다. 예전 정책이 필요하면 `--method C`를 명시합니다. A/B 데모는 `examples/product`의 정수 예제를 사용하고 Source 수집·학습을 하지 않습니다. C/D 데모는 Source 준비와 비용을 명시합니다. 의도적으로 넣은 예제 결함을 실제 프로젝트 발견으로 세지 않습니다.

The previous MRI, CAST, Claim-to-Witness, Mold, numerical, and stateful interfaces remain available. Their contracts and evidence do not become broader just because they share a package version.

기존 기능은 유지하되 지원 범위나 연구 성과를 새 버전 번호만으로 확대하지 않습니다. [새 사용자 흐름](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/README.ko.md)을 참고하세요.

## Receipts and replay / 영수증과 재현

New `online-run` receipts bind the target source, Oracle source, and contract. `online-replay` checks those identities before replaying recorded failures. Use new output paths and preserve old receipts. Source changes require a new run, not a rewritten old receipt.

새 `online-run` 영수증은 Target·Oracle 파일과 계약 identity를 연결합니다. `online-replay`는 이를 확인하고 저장된 실패만 재현합니다. 파일이 달라졌다면 새 실행을 기록하며 기존 영수증을 고쳐 맞추지 않습니다.

Older receipts without file bindings are rejected by default. `online-replay --allow-unbound-legacy` is an explicit compatibility path that records the missing binding; it does not certify the old files' identity. Replay status distinguishes `REPRODUCED`, `NOT_REPRODUCED`, and `NO_CONFIRMED_FAILURE`; mismatches are inconclusive rather than success.

파일 연결이 없는 구형 영수증은 기본 거절합니다. `--allow-unbound-legacy`를 명시하면 연결 미검증 상태를 남기는 호환 경로로만 사용합니다. 이를 과거 파일 identity 증명으로 해석하지 않습니다. 미검출도 정확성 증명이 아니며 축소는 예산 안의 감소입니다.

## Research and execution / 연구와 실행

The frozen historical study remains negative for D's added detection/query value and includes negative transfer. Package publication does not establish external generalization. Existing reports retain their original experimental context; they are not instructions to republish old files or rerun consumed evaluations.

역사적 연구의 D 추가 탐지·호출 이득 부재와 음의 전이는 보존합니다. 이전 문서의 미발행·draft 설명은 해당 시점의 기록입니다. 새 도구 게시가 연구 성공을 뜻하지 않으며 소비된 평가의 재실행 승인도 아닙니다. [고정 보고서](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/docs/HISTORICAL_REPORT_KO.md), [제3자 고지](https://github.com/hibou04-ops/antemortem-structural-lab/blob/main/THIRD_PARTY_NOTICES.md)를 참고하세요.

Local opt-in executes reviewed local code, not an OS sandbox. The historical external-source gate remains container-only. No migration requires private archives, credentials, cloud-drive data, or paid API access.

로컬 실행 동의는 OS sandbox가 아닙니다. 외부 역사적 원본의 container 전용 게이트는 유지합니다. 마이그레이션에 비공개 archive·인증 정보·Drive 자료·유료 API는 필요하지 않습니다.
