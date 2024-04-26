FROM gitlab-registry.nrp-nautilus.io/prp/jupyter-stack/minimal

USER root

# Install dependency (You may add other dependencies here)
RUN apt update && apt install -y make rsync git vim

# Add ssh key
RUN mkdir -p /root/.ssh
ADD .ssh/id_rsa /root/.ssh/id_rsa
ADD .ssh/config /root/.ssh/config
ADD .ssh/known_hosts /root/.ssh/known_hosts
RUN chmod 400 /root/.ssh/id_rsa

# Pull the latest project
WORKDIR /root/
RUN git clone --depth=1 PROJECT_SSH_URL
WORKDIR /root/PROJECT_NAME/

# Handle git submodule
RUN git config --global url."https://github.com/".insteadOf git@github.com:; \
    git config --global url."https://".insteadOf git://; \
    git submodule update --init --recursive

# Install conda environment
RUN conda update --all
RUN conda env create -n PROJECT_NAME --file environment.yml
RUN conda clean -qafy

# Activate the new conda environment and install poetry
SHELL ["/opt/conda/bin/conda", "run", "-n", "PROJECT_NAME", "/bin/bash", "-c"]
RUN poetry install --no-root
