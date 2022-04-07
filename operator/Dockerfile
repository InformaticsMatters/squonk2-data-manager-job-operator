FROM python:3.9.12-slim

# Labels
LABEL maintainer='Alan Christie <achristie@informaticsmatters.com>'

# Force the binary layer of the stdout and stderr streams
# to be unbuffered
ENV PYTHONUNBUFFERED 1

# Namespaced operator.
ENV JO_NAMESPACE data-manager-api

COPY requirements.txt ./
RUN pip install -r requirements.txt

WORKDIR /src
COPY handlers.py /src/

CMD kopf run ./handlers.py --verbose --log-format=full --namespace=${JO_NAMESPACE}
