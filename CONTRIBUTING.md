# Contributing / 기여 안내

관측한 실행 결과, 명시적인 계약, 유한 영역의 검사, 독립적인 증명을 구분합니다. 새 기능은 재현 가능한 예제와 실패 조건, 지원 범위를 함께 제시해 주세요. 기존 명령의 동작과 공개 버전 이력을 보존합니다.

## 개발 환경

Python 3.11 이상:

```bash
python -m pip install -e ".[qa]"
python -m pip install pytest build twine
python -m pytest -q
python -m build
python -m twine check dist/*
```

Z3 경로를 검사하려면 `python -m pip install -e ".[qa,solver]"`로 선택적 의존성을 설치합니다. 기본 실행은 유한 영역 열거를 사용합니다. Docker 생성기는 Docker Engine과 명시적으로 받은 `python:3.12-slim` 이미지가 필요합니다. 설치한 wheel에서도 새 하위 패키지와 CLI 예제가 실행되는지 확인해야 합니다.

## 변경 검토 기준

- 정상 실행뿐 아니라 잘못된 증거·명세·전이 계약 거부, 경쟁 가설과 반증 기록, 동결 상태 보호를 검사합니다.
- Generator에 평가 소스나 정답을 전달하지 않습니다. 새로운 평가 자료는 엔진·후보 동결 전에 결과를 보고 고르지 않습니다.
- 성능 비교는 같은 예산·명세·판정 기준을 사용하고 실패 입력 수, 독립 결함 수, 반복 시드의 발견 수를 구분합니다.
- 한국어 README와 영어 README의 기능·명령·제한을 함께 수정합니다. 예제 명령과 상대 링크를 실제로 검사합니다.
- `results/`, `research/`, `PRIVATE_*`, 원시 연구 기록, 개인 경로, `.env`, API 키, 이전 증거 ZIP 및 빌드 임시 파일을 커밋하지 않습니다. 파일을 개별 검토해 명시적으로 staging합니다.
- wheel·sdist·Release 자산도 검사합니다. Git에서 제외된 파일이 패키지에도 자동으로 제외된다고 가정하지 않습니다.

[이슈](https://github.com/hibou04-ops/antemortem-structural-lab/issues)에 문제와 기대 동작을 남기거나 PR에 재현·검증 결과를 적어 주세요. 기존 태그를 이동하거나 검토 정책을 우회하지 않습니다. [보안 모델](SECURITY.md), [검증 기록](docs/RELEASE_VALIDATION.md), [라이선스](LICENSE)를 참고하세요.

Contributions must preserve the difference between observed executions, declared contracts, bounded checks and independent proof. Keep Korean and English guidance aligned, test installed artifacts, and do not publish private evidence or infer general superiority from synthetic fixtures.

## 재귀 정책의 제한된 기능 검증

`python -m pytest tests/test_recursive_observe.py tests/test_recursive_policy.py tests/test_recursive_store.py tests/test_recursive_integration.py tests/test_recursive_review.py -q`는 직접 작성한 합성 fixture와 세대 복원만 검증합니다. 실제 연구 실행은 포함하지 않습니다. `python -m tomolab recursive-demo --workspace work/recursive-example --allow-local-execution`은 새 출력 디렉터리가 필요합니다. 지원 범위와 비용·자료 경계는 `docs/RECURSIVE_PROGRESS_20261101.ko.md`를 따릅니다.
