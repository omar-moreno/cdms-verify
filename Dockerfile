# ---- Build stage -------------------------------------------------------
FROM python:3.12 as intermediate

MAINTAINER Omar Moreno <omoreno@slac.stanford.edu>

# Add a label that identifies this as an intermediate layer.
LABEL stage=intermediate

# The SSH key is passed as a build argument.
ARG SSH_KEY

# * Create an SSH directory.
# * Populate the private key file.
# * Set the correct permissions.
# * Add gitlab to the list of known host.
RUN mkdir -p /root/.ssh/ && \
    echo "$SSH_KEY" > /root/.ssh/id_ed25519 && \
    chmod -R 700 /root/.ssh/ && \
    ssh-keyscan -t ed25519 gitlab.com github.com > /root/.ssh/known_hosts

# Clone the data catalog repo into the itermediate image.
RUN git clone git@gitlab.com:supercdms/DataHandling/DataCat.git

# Clone the verification package
RUN git clone git@github.com:omar-moreno/cdms-verify.git

# This is final base image
FROM python:3.12

# Update the image and install dependencies.
RUN apt-get update &&  \
    apt-get install -y \ 
        openssl

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
