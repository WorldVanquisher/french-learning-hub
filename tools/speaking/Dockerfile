# Speaking model image: data preparation, evaluation, training and the local
# transcription service. TORCH_INDEX=cpu builds the CPU variant (local runs and
# the CPU service); the default installs torch from PyPI (CUDA runtime bundled)
# for a GPU training job. No model weights or audio are baked in.
FROM python:3.12-slim@sha256:6c4dd321d176d61ea848dc8c73a4f7dbae8f70e0ee48bb411ea2f045b599fa8e
ARG TORCH_INDEX=pypi
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/opt/program HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
# Every package, version and wheel hash comes from the lock of the variant
# (scripts/lock_from_report.py); requirements.txt names the direct ones.
COPY requirements.txt requirements-*.lock /opt/program/
RUN if [ "$TORCH_INDEX" = cpu ]; then IDX="--index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple"; LOCK=cpu; else IDX=""; LOCK=gpu; fi \
 && pip install --no-cache-dir --require-hashes --no-deps $IDX -r /opt/program/requirements-$LOCK.lock \
 && pip check \
 && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin speaker
COPY flh_speaking /opt/program/flh_speaking
RUN python3 -c "import flh_speaking, torch, transformers, av, numpy"
WORKDIR /opt/program
USER 10001
ENTRYPOINT ["python3", "-B", "-m", "flh_speaking"]
