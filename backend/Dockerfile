# The ACDOS backend as one container (#148). Built from the repository root,
# because the app reads data/ (the RF's training data and the zone matrix):
#
#     az acr build --registry <registry> --image acdos-api:<tag> --file backend/Dockerfile .
#
# Secrets are not here: DATABASE_URL comes from the host's settings at run
# time (README, "Deploy").
FROM python:3.14.2-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/backend

# Dependencies first, so a code change does not reinstall them.
COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# Only what the app reads at run time: the code and data/.
COPY data /app/data
COPY backend/app ./app

# Train the Random Forest now, so the image ships the model and a start does
# not train it, and print its fingerprint (app/ml/fingerprint.py) to compare
# with a local build.
RUN python -m app.ml.fingerprint

# Not root. The model cache stays readable; nothing writes to the image.
RUN useradd --create-home --uid 10001 acdos
USER acdos

EXPOSE 8000

# One uvicorn process: the job runner and its solver pool live in it, and
# fail_unfinished at startup assumes no other process (README). The pool
# size is SOLVER_POOL_SIZE (default 2).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
