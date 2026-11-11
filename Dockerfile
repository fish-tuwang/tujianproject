ARG PYTHON_IMAGE=public.ecr.aws/docker/library/python:3.12-slim
FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir -r requirements.lock && useradd --uid 10001 --create-home catalog
COPY backend /app/backend
COPY scripts/acceptance.py scripts/check_release.py scripts/check_toolchain.py /app/scripts/
COPY docs /app/docs
COPY miniprogram /app/miniprogram
COPY pyproject.toml package.json package-lock.json /app/
RUN mkdir -p /app/artifacts/acceptance && chown -R catalog:catalog /app/artifacts
USER 10001:10001
EXPOSE 8092
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8092"]
FROM runtime AS test
CMD ["python", "-m", "pytest", "backend/tests", "-q"]
FROM runtime AS app
