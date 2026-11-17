# Isolated terraform fmt/validate runner (G16). Holds no database access and
# no customer credentials -- see runner.py's docstring for why it is separate
# from the API. Deploy as its own Railway service; staging first.
FROM python:3.11-slim

ARG TERRAFORM_VERSION=1.14.8
# From https://releases.hashicorp.com/terraform/1.14.8/terraform_1.14.8_SHA256SUMS
ARG TERRAFORM_SHA256=56a5d12f47cbc1c6bedb8f5426ae7d5df984d1929572c24b56f4c82e9f9bf709

RUN apt-get update && apt-get install -y --no-install-recommends curl unzip ca-certificates git \
    && curl -fsSLo /tmp/tf.zip "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" \
    && echo "${TERRAFORM_SHA256}  /tmp/tf.zip" | sha256sum -c - \
    && unzip /tmp/tf.zip -d /usr/local/bin && rm /tmp/tf.zip \
    && apt-get purge -y curl unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 runner \
    && mkdir -p /var/cache/terraform-plugins && chown runner /var/cache/terraform-plugins

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY runner.py app.py ./

USER runner
ENV TF_PLUGIN_CACHE_DIR=/var/cache/terraform-plugins
EXPOSE 8080
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
