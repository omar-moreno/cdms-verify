# syntax=docker/dockerfile:1.4
# ---- Build stage -------------------------------------------------------
FROM python:3.12 as intermediate

LABEL org.opencontainers.image.authors="Omar Moreno <omoreno@slac.stanford.edu>"

# Add a label that identifies this as an intermediate layer.
LABEL stage=intermediate

# Install packages required for SSH-based git clone.
RUN apt-get update && \
    apt-get install -y --no-install-recommends git openssh-client && \
    rm -rf /var/lib/apt/lists/*

# Clone private repos using BuildKit SSH forwarding.
RUN --mount=type=ssh mkdir -p /root/.ssh && \
    chmod 700 /root/.ssh && \
    ssh-keyscan -t ed25519 gitlab.com github.com > /root/.ssh/known_hosts && \
    git clone git@gitlab.com:supercdms/DataHandling/DataCat.git && \
    git clone git@github.com:omar-moreno/cdms-verify.git

# This is final base image
FROM python:3.12

# Update the image and install dependencies.
RUN apt-get update && \
    apt-get install -y --no-install-recommends openssl && \
    rm -rf /var/lib/apt/lists/*

# Install all external packages into /opt.
WORKDIR /opt

# Copy the data catalog repo from the intermediate image.
COPY --from=intermediate /DataCat DataCat

# Install the data catalog module.
RUN cd DataCat && \
    pip install .

WORKDIR /opt

COPY --from=intermediate /cdms-verify cdms-verify

RUN cd cdms-verify && \
    pip install .

WORKDIR cdms-verify
ENTRYPOINT ["cdms-verify"]
