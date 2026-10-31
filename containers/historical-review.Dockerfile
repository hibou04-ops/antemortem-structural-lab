FROM python:3.12-slim
RUN python -m pip install --no-cache-dir hypothesis==6.170.11
ENV PYTHONDONTWRITEBYTECODE=1 HYPOTHESIS_STORAGE_DIRECTORY=/tmp/hypothesis
USER 65534:65534
WORKDIR /tmp
