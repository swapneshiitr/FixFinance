FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Copy the project (incl. the `app` package) then install it + its dependencies.
# `app` must be present before install because pyproject declares packages = ["app"].
# At runtime ./api is bind-mounted over /app (with --reload), so this build step's
# real job is to bake the third-party dependencies into the image.
COPY . .
RUN pip install --upgrade pip && pip install .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
