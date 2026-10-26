# Security model / 보안 모델

## 신뢰하는 코드만 실행

대상 Python 코드와 Oracle은 평가기 호스트에서 현재 사용자 권한으로 실행됩니다. `--allow-local-execution`은 사용자가 실행을 허용했다는 표시이며 **보안 샌드박스가 아닙니다**. 직접 작성했거나 독립적으로 검토한 코드에만 사용하세요. 임의 저장소, 적대적 코드, 권한 없는 시스템을 검사하는 용도로 사용하지 마세요.

기존 `run`, `replay`, `claim-run`, `claim-replay`의 실행 모델도 같습니다. 새 Docker 선택은 **생성기의 정보 접근**을 제한하는 기능이며 대상 함수의 실행 위치를 바꾸지 않습니다.

## Generator와 Oracle의 경계

| Backend | 실제 경계 | 기록되는 수준 |
| --- | --- | --- |
| `subprocess` | JSON 메시지를 주고받는 별도 프로세스. 호스트 파일 권한 공유 | `LOGICAL_ISOLATION_ONLY` |
| `docker` | 공개 패키지 코드만 읽기 전용 mount, 표준입력의 공개 명세·허용된 증거, 비루트 사용자, 네트워크 차단·읽기 전용 root·권한 축소 | `CONTAINER_BOUNDARY` |

생성기 메시지에는 대상 소스, Oracle 소스, 비공개 정답, 임의 실행 코드가 필요하지 않습니다. 최종 후보는 평가 전에 동결하고 최종 평가 결과를 생성기로 전달하지 않습니다. 동결은 학습 상태 변경을 차단하며 Python 대상의 악의적 동작까지 막는 기능은 아닙니다.

Snapshot의 SHA-256과 상태 재계산은 내용의 일관성을 검사합니다. Oracle 증거의 작성자나 진실성을 보증하는 디지털 서명이 아니므로 외부 snapshot은 호출자가 출처를 확인하고 승인한 자료만 사용해야 합니다.

Docker Engine이 사용 가능하고 기본 이미지를 미리 받은 환경에서 다음과 같이 실행합니다.

```bash
docker pull python:3.12-slim
python -m tomolab mold-demo --backend docker --solver enumeration --budget 32 --output results/mold-container.json
```

이미지 다운로드는 위의 명시적 단계입니다. 런타임이 실패한 Docker 실행을 일반 subprocess로 조용히 바꾸거나 이미지를 자동으로 받지 않습니다. 기본 이미지는 Z3를 포함하지 않습니다. 이미지와 Docker 호스트도 신뢰 경계에 포함됩니다. 컨테이너는 완벽한 보안 증명이 아닙니다. 실제 접근 거부 검증은 [릴리스 검증 기록](docs/RELEASE_VALIDATION.md)과 해당 Actions 결과를 확인하세요.

## 자료와 비밀정보

실행 결과에는 로컬 경로, 입력, 반환값, 소스 해시가 포함될 수 있습니다. 공유 전에 확인하세요. `results/`, 비공개 연구 디렉터리, `PRIVATE_*`, 이전 E1/E2 증거 ZIP, 원시 홀드아웃과 인증정보를 Git·wheel·sdist·Release 자산에 넣지 않습니다.

API 키는 환경변수로만 전달하고 코드, 로그, 이슈, 지원 요청에 쓰지 마세요. Jev는 선택적 외부 연결이며 사용 시 비용이 발생할 수 있습니다. 기본 Mold와 Claim 실행에는 유료 호출이 없습니다.

이 도구는 무제한 입력에 대한 정확성, 임의 자연어 주장의 참·거짓, LLM 안전성 또는 현실의 진실을 독립적으로 증명하지 않습니다. `UNKNOWN`과 유한 예산 내 미발견은 성공 판정이 아닙니다.

## 취약점 보고

[GitHub 이슈](https://github.com/hibou04-ops/antemortem-structural-lab/issues)에 인증정보나 개인 자료 없는 최소 재현을 작성하세요. 민감한 취약점은 저장소에서 비공개 취약점 보고가 제공되는지 먼저 확인하세요. 유효한 인증정보를 게시하지 마세요.

## English summary

Only run authored or independently trusted targets and Oracles. They execute with evaluator-host privileges; consent flags are not a hostile-code sandbox. The default subprocess generator has logical isolation only. The optional Docker generator limits its filesystem, network and privileges, but does not isolate target execution. Pre-pull the trusted image explicitly. Inspect actual validation and CI boundary tests rather than inferring isolation from a process name. Snapshot hashes and state reconstruction check consistency, not authorship or the truth of Oracle evidence; callers must approve external snapshots. Review evidence before sharing, keep private research and credentials out of artifacts, and preserve `UNKNOWN` and bounded-search limitations.
