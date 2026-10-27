# Third-party materials

E4 directly integrates [Hypothesis](https://hypothesis.readthedocs.io/en/latest/reference/api.html)
through the optional `qa` extra. Hypothesis retains its MPL-2.0 license and is
installed as a separate dependency; no third-party implementation is vendored.
The local integration environment used Hypothesis 6.170.11 and Z3 5.3.2.0.
The dependency ranges in `pyproject.toml` are authoritative. Hypothesis `find`,
strategies and shrinking, Python AST and Z3 are established tools, not newly
invented techniques attributed to this project.

The default runtime uses Python's standard library. The optional `solver` extra installs [Z3](https://github.com/Z3Prover/z3) to check bounded satisfiability and disagreement witnesses. No third-party Python implementation is vendored in the source tree. The project is distributed under Apache-2.0; see the root LICENSE. Z3 retains its own license and is not copied into this wheel.

pytest is used for tests. CrossHair is an optional external comparison tool: the assert-based fixtures in baselines/ express the same relations used by the examples. Neither tool is bundled in the wheel. Jev is an optional remote service adapter, with service access and billing governed separately by its provider.

GitHub Actions uses actions/checkout and actions/setup-python. These actions and build/test dependencies retain their own licenses. This notice records the observed distribution boundary; it does not assert independent novelty or replace dependency license terms.

The optional container boundary uses an explicitly installed [Docker](https://docs.docker.com/engine/containers/run/) runtime and a separately pulled Python image. The image is not redistributed with the package; its content-addressed image ID is recorded in each container receipt. No image is pulled implicitly by a Mold command.

CEGIS, version spaces, disagreement-based active learning and diversity archives are established techniques integrated here in a narrow finite grammar. The archive retains representatives by structural family; it is not an implementation of a general MAP-Elites optimizer. Hypothesis and [CrossHair](https://crosshair.readthedocs.io/en/latest/) were independent tools in the historical E3 comparison. E4 adds Hypothesis as an optional dependency without changing those E3 results.
