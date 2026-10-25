# Third-party materials

The runtime modules use Python's standard library. No third-party Python implementation is vendored in the source tree. The project is distributed under Apache-2.0; see the root LICENSE.

pytest is used for tests. CrossHair is an optional external comparison tool: the assert-based fixtures in baselines/ express the same relations used by the examples. Neither tool is bundled in the wheel. Jev is an optional remote service adapter, with service access and billing governed separately by its provider.

GitHub Actions uses actions/checkout and actions/setup-python. These actions and build/test dependencies retain their own licenses. This notice records the observed distribution boundary; it does not assert independent novelty or replace dependency license terms.
