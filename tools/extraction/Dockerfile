# Knowledge-extractor SFT image (SageMaker: docker run IMAGE train).
# TORCH_INDEX=cpu builds the CPU variant used for local smoke tests; the
# default installs torch from PyPI (CUDA runtime included) for GPU jobs.
FROM python:3.12-slim@sha256:6c4dd321d176d61ea848dc8c73a4f7dbae8f70e0ee48bb411ea2f045b599fa8e
ARG TORCH_INDEX=pypi
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/opt/program HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
COPY requirements-train.txt /opt/program/requirements-train.txt
RUN if [ "$TORCH_INDEX" = cpu ]; then IDX="--index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple"; else IDX=""; fi \
 && pip install --no-cache-dir $IDX -r /opt/program/requirements-train.txt \
 && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin trainer
COPY flh_extraction /opt/program/flh_extraction
RUN python3 -c "import flh_extraction.sagemaker_entry, torch, transformers, peft"
WORKDIR /opt/program
ENTRYPOINT ["python3", "-B", "-m", "flh_extraction.sagemaker_entry"]
