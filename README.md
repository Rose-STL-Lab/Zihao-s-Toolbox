# Kube Toolbox

## 0. Introduction

This toolbox is designed to facilitate the synchronization between a Kubernetes (Kube) cluster and local GPU machines, aiming to streamline the process of running and managing batch experiments. The main advantages of using this toolbox include:

- Synchronization of environment variables (found in `.env` files) between Nautilus cluster executions and local runs, allowing for easy access to credentials via `os.environ`.
- Simplification of the process to load environment variables, Python environments, and startup scripts.
- Data and output folder synchronization through S3 storage.
- Central management of all potential hyperparameters for various datasets and models.
- Compatibility with a wide range of projects, even those already utilizing configuration files.
- Capability to execute all combinations of experiments in parallel with a single command.


## 1. Quick Start (for Nautilus user):

Imagine a scenario where you're handling "machine learning" workloads with two datasets you wish to use both in the cluster and locally, and you have two baseline models to evaluate.

#### Step 1: Set Up Your Project Repository

Start by creating a new git repository with `src` and `data` directories:

```bash
mkdir example; cd example; mkdir src; mkdir data; git init
```

**Add the toolbox repository as a submodule:**

```bash
git submodule add https://github.com/Rose-STL-Lab/Zihao-s-Toolbox.git src/toolbox
```

**Create symbolic links for Makefile and launch.py at the root of your workspace:**

```bash
ln -s src/toolbox/launch.py .
ln -s src/toolbox/Makefile .
```

#### Step 2: Prepare Baselines and Datasets

Generate two baseline files and two datasets as follows:

```bash
echo "1,2,3" > data/1.txt
echo "4,5,6" > data/2.txt
echo "import sys; print(sum(map(float, open(sys.argv[1]).read().split(','))) / 3)" > src/avg.py  # Compute average
echo "import sys, statistics; print(statistics.median(map(float, open(sys.argv[1]).read().strip().split(','))))" > src/med.py  # Compute median
```

Create a .env file with your S3 bucket details:
```ini
S3_BUCKET_NAME=example
S3_ENDPOINT_URL=https://s3-west.nrp-nautilus.io
```

Setup your Kubernetes configuration in `config/kube.yaml` (replace `<NAMESPACE>` and `<USER>` with your details):
```yaml
project_name: base
namespace: <NAMESPACE>
user: <USER>
registry_host: gitlab-registry.nrp-nautilus.io
ssh_host: gitlab-ssh.nrp-nautilus.io
ssh_port: 30622
conda_home: /opt/conda

image: gitlab-registry.nrp-nautilus.io/prp/jupyter-stack/minimal
startup_script: >-
  pip install boto3; mkdir example; cd example; mkdir src; mkdir data; git init; git submodule add https://github.com/Rose-STL-Lab/Zihao-s-Toolbox.git src/toolbox; ln -s src/toolbox/launch.py .; ln -s src/toolbox/Makefile .; echo "import sys; print(sum(map(float, open(sys.argv[1]).read().split(','))) / 3)" > src/avg.py; echo "import sys, statistics; print(statistics.median(map(float, open(sys.argv[1]).read().strip().split(','))))" > src/med.py; echo "cd example" >> ~/.bashrc
```

> Note: For simplicity, Quick Start doesn't cover pushing code to GitLab or building a project image. In a full setup, `startup_script` and `image` fields would be unnecessary as the image would already contain the required dependencies, and the default `startup_script` would ensure the latest codebase. For more information, refer to Section 4.

Define the experiment configurations in `config/launch.yaml`:

```yaml
project_name: base
model:
  average:
    # <fn> will be automatically replaced by hparam values
    command: make download file=data/; python src/avg.py <fn>
    ## If the command running locally is different from the one running remotely
    # local_command: python src/avg.py <fn>  
    # # Model can also have hparam
    # hparam:
    #   hid_dim: 256
    #   ...
    # # Override *non-projectwise* kube config, see Section 2
    gpu_count: 0
    # memory: 8  # 8GiB
    # image: gitlab-registry.nrp-nautilus.io/prp/jupyter-stack/minimal
    # ...
  median:
    command: make download file=data/; python src/med.py <fn>
    gpu_count: 0
dataset:
  data1:
    hparam:
      # Launch will automatically consider all combinations of hparam
      # hparam preceded by _ will NOT appear in the job name
      # If your hparam contain special characters, you must _ them
      _fn: data/1.txt
  data2:
    hparam:
      _fn: data/2.txt
run:
  dataset: [data1]
  model: [average]
```

> Caution: don't put `sleep infinity` in the command. It will violate the cluster policy. `make pod` will automatically replace your command by `sleep infinity`.

#### Running Locally

Execute the following command to run experiments locally: `make local`

Example output:

```
Running {'data_fn': ['data/1.txt']} ... > export $(cat .env | xargs) && python src/avg.py data/1.txt
2.0
```

Comment out the run section in `launch.yaml` and execute `make local` to run all possible combinations of experiments sequentially.

```
Running {'data_fn': ['data/1.txt']} ... > export $(cat .env | xargs) && python src/avg.py data/1.txt
2.0
Running {'data_fn': ['data/1.txt']} ... > export $(cat .env | xargs) && python src/med.py data/1.txt
2.0
Running {'data_fn': ['data/2.txt']} ... > export $(cat .env | xargs) && python src/avg.py data/2.txt
5.0
Running {'data_fn': ['data/2.txt']} ... > export $(cat .env | xargs) && python src/med.py data/2.txt
5.0
```

#### Uploading Data to Remote Storage

If you have an S3 bucket, update the credentials in `.env` and use the following command to upload your dataset: `make upload file=data/`

Example output:

```bash
Uploaded data/1.txt to data/1.txt
Uploaded data/2.txt to data/2.txt
```

For users without an S3 bucket, request access from the Nautilus matrix chat or use buckets provided by `rosedata.ucsd.edu`. You don't need a bucket for this tutorial.

### Remote Pod

To create a remote pod, run: `make pod`

Example output:

```
pod/base-interactive-pod created
```

You can now navigate to the shell of the pod to test the commands (like `python src/avg.py`) before batch running experiments.

### Remote Batch Jobs


To run all possible combinations of experiments in parallel with Nautilus, run: `make job`

Example output:

```bash
Job 'base-average-data1' not found. Creating the job.
job.batch/base-average-data1 created
Job 'base-median-data1' not found. Creating the job.
job.batch/base-median-data1 created
Job 'base-average-data2' not found. Creating the job.
job.batch/base-average-data2 created
Job 'base-median-data2' not found. Creating the job.
job.batch/base-median-data2 created
```

> Be careful: `make delete` operates by removing all pods and jobs under your user label.

Finally, run `make delete` to cleanup all workloads.

---

## 2. Kube Utilities Specification

`config/kube.yaml`:

```yaml
##### Project-wise configuration, should be the same across all experiments
# Will not be overwritten by the launch.yaml
project_name: str, required
user: str, required
namespace: str, required
prefix: str  # Prefix of the names of your workloads, default to user

##### Other field, can be overwritten in launch.yaml #####

# env will be overridden by `.env`, therefore never effective in `kube.yaml`
# however, specify env in `launch.yaml` can add new env variables
env: 
  <env-key>: <env-value>

## [required] If startup_script is not defined, the following fields are required to automatically keep your git repo up-to-date at startup
startup_script: str
conda_home: str
ssh_host: str
ssh_port: int

# Will override sleep-infinity when running interactive pod
server_command: str

## For CPU and Memory, the limit will be twice the requested
gpu_count: int
cpu_count: int
memory: int 

## Mount PVC to path
volumes:
  <pvc-name>: <mount-path>

## If image is not defined, the host are required to automatically find your project image link
image: str
registry_host: str
## If your image is private and your pull secret name does not default to <project-name>-read-registry
image_pull_secrets: str

## Will tolerate no-schedule taints
tolerations: 
  - <toleration-key>
gpu_whitelist:
  - <usable-gpu-list>
hostname_blacklist:
  - <unusable-node-hostnames-list>
```

`gpu_whitelist` and `gpu_blacklist` cannot be both set. If gpu_whitelist is set, only the specified GPUs will be used. If gpu_blacklist is set, all GPUs except the specified ones will be used. The same applies to `hostname_blacklist` and `hostname_whitelist`.

Example GPU list:

```yaml
  - NVIDIA-TITAN-RTX
  - NVIDIA-RTX-A4000
  - NVIDIA-RTX-A5000
  - Quadro-RTX-6000
  - NVIDIA-A40
  - NVIDIA-RTX-A6000
  - Quadro-RTX-8000
  - NVIDIA-GeForce-RTX-3090
  - NVIDIA-GeForce-GTX-1080-Ti
  - NVIDIA-GeForce-GTX-2080-Ti
  - NVIDIA-A10
  - NVIDIA-A100-SXM4-80GB
  - Tesla-V100-SXM2-32GB
  - NVIDIA-A100-PCIE-40GB
  - NVIDIA-A100-SXM4-80GB
  - NVIDIA-A100-80GB-PCIe
```

Ensure consistency in project_name across your GitLab repository (<project_name>.git), conda environment (envs/<project_name>), image pull secret (<project_name>-read-registry), and S3 configuration (<project_name>-s3cfg). Avoid hyphens and underscores in project_name.

Your GitLab username would be used as user to label your kube workloads (label: <user>). For registry details, refer to the GitLab container registry documentation.



## 3. S3 Utilities Specification

### Requirements

```
poetry add boto3
```

### Usage

Create a .env file in your project repository with these values:

```bash
S3_BUCKET_NAME=<your_s3_bucket_name>
AWS_ACCESS_KEY_ID=<your_access_key>
AWS_SECRET_ACCESS_KEY=<your_secret_key>
S3_ENDPOINT_URL=https://...
```

Load environment by `export $(cat .env | xargs)` or through make commands.

You can perform wildcard searches, downloads, uploads, or deletions on S3 files:

```bash
❯ make interactive file='Model/*t5*wise*419*'
Local files matching pattern:

S3 files matching pattern:
Model/Yelp/t5_model_12weeks_wise-sky-249-northern-dawn-288_epoch_1419/config.json
...

Choose an action [delete (local), remove (S3), download, upload, exit]:
```

Use single quotes to prevent shell wildcard expansion. The S3 bucket will sync with your current directory by default, maintaining the original file structure and creating necessary directories.

Beyond Make commands, you can also directly import the functions from `src/toolbox/s3utils.py` to your Python scripts.

```python
from toolbox.s3utils import download_s3_path

folder_path = f"Data/{dataset}"
download_s3_path(folder_path)
```

If your Python script is invoked via `make`, the environment variables will be automatically loaded.


## 4. Example Creation of [Nautilus](https://portal.nrp-nautilus.io/) Gitlab Image

This section will guide you through the process of creating a GitLab Docker image based on your git repo using the Nautilus platform. This is useful for those looking to automate their deployment and integration workflows using GitLab's CI/CD features. The result image can integrate nicely with Kubeutils.

> Note: If Nautilus SSH is no longer `gitlab-ssh.nrp-nautilus.io:30622`, please modifies `SSH_CONFIG` and .`gitlab-ci.yml` correspondingly.

### Prerequisites
Before you begin, make sure you have:
- A Nautilus Gitlab account
- Familiarity with SSH, docker container, continuous integration and deployment (CI/CD) concepts

### Steps

1. Create a git repo at Nautilus [Gitlab](https://gitlab.nrp-nautilus.io/).
2. Generate an SSH key pair on your local machine using the following command: `ssh-keygen -f <project_name>`.
3. Copy the public key `<project_name>.pub` to Gitlab Repo - Settings - **Deploy Keys**. Grant write permission.
4. **(Optional)** Create a Github repo of the same name. Under Settings, add the same public key.
5. Deploy tokens are used to securely download (pull) Docker images from your GitLab registry without requiring sign-in. Under Gitlab Repo - Settings - Repository - **Deploy Tokens**, create new deploy token with name `<project_name>-write-registry`. Grant both `write_registry` and `read_registry` access. Take a note of the `username` and `password` for this token for Gitlab CI. Create new deploy token with name `<project_name>-read-registry`. Grant `read_registry` access. Take a note of the `username` and `password` for this token for Kubernetes experiments.
6. Run the follow command to upload the read tokens to the cluster. 
```bash
kubectl create secret docker-registry <project_name>-read-registry \
    --docker-server=gitlab-registry.nrp-nautilus.io \
    --docker-username=<username> \
    --docker-password=<password>
```
7. In Gitlab Repo - Settings - CI/CD - **Variables**, enter the following variables:
  - SSH_CONFIG: `SG9zdCBnaXRsYWItc3NoLm5ycC1uYXV0aWx1cy5pbwogICAgSG9zdE5hbWUgZ2l0bGFiLXNzaC5ucnAtbmF1dGlsdXMuaW8KICAgIFVzZXIgZ2l0CiAgICBQb3J0IDMwNjIyCiAgICBJZGVudGl0eUZpbGUgL3Jvb3QvLnNzaC9pZF9yc2EK`, which is the base64 encoding of
  ```
  Host gitlab-ssh.nrp-nautilus.io
    HostName gitlab-ssh.nrp-nautilus.io
    User git
    Port 30622
    IdentityFile /root/.ssh/id_rsa
  ```
  - CI_REGISTRY_PASSWORD: the write `password` from the previous step.
  - CI_REGISTRY_USER: the write `username` from the previous step.
  - GIT_DEPLOY_KEY: base64 encode the private key you created in Step 2.
  - GITLAB_USER_EMAIL: your gitlab user email, `git config --get user.email`
  - GITLAB_USER_NAME: your gitlab user email, `git config --get user.name`
  - **(Optional)** GITHUB_REPO: ssh link to your mirror github repo, `git@github.com:....git`
  Remember to mask (and possibly further protect your password and token).
7. Create the following files under your repo:
  - `environment.yml` (modify Python version for your project)
```yaml
name: <project_name>
channels:
  - conda-forge
  - nvidia
dependencies:
  - python=3.11.*
  - pip
  - poetry=1.*
  - conda-lock=1.*
```
  - `Dockerfile` (modify apt dependencies, gitlab_url, and project_name)
```dockerfile
FROM gitlab-registry.nrp-nautilus.io/prp/jupyter-stack/minimal

USER root

# Install dependency
RUN apt update && apt install -y make rsync git ... (other needed dependencies)

# Add ssh key
RUN mkdir -p /root/.ssh
ADD .ssh/id_rsa /root/.ssh/id_rsa
ADD .ssh/config /root/.ssh/config
ADD .ssh/known_hosts /root/.ssh/known_hosts
RUN chmod 400 /root/.ssh/id_rsa

# Pull the latest project
WORKDIR /root/
RUN git clone --depth=1 <gitlab_url>
WORKDIR /root/<project_name>/

# Handle git submodule
RUN git config --global url."https://github.com/".insteadOf git@github.com:; \
    git config --global url."https://".insteadOf git://; \
    git submodule update --init --recursive

# Install conda environment
RUN conda update --all
RUN conda install -c conda-forge conda-lock
RUN conda-lock install --name <project_name> conda-lock.yml
RUN conda clean -qafy

# Activate the new conda environment and install poetry
SHELL ["/opt/conda/bin/conda", "run", "-n", "<project_name>", "/bin/bash", "-c"]
RUN poetry install --no-root
```
- `.gitlab-ci.yml` (The mirror-job is *optional*; it pushes the code to a GitHub mirror for backup purposes. The build-and-push-job compiles the code and pushes the Docker image to the registry.)
```yaml
stages:
  - mirror
  - build-and-push

mirror_to_github:
  stage: mirror
  image: 
    name: alpine/git
  before_script:
    - cd
    - mkdir -p .ssh
    - chmod 700 .ssh
    - eval $(ssh-agent -s)
    - echo "$GIT_DEPLOY_KEY" | base64 -d | tr -d '\r'
      > .ssh/id_rsa
    - echo "$SSH_CONFIG" | base64 -d | tr -d '\r' > .ssh/config
    - ssh-keyscan -p 30622 gitlab-ssh.nrp-nautilus.io >> ~/.ssh/known_hosts
    - chmod 400 .ssh/id_rsa
    - echo "$GIT_DEPLOY_KEY" | base64 -d | tr -d '\r' | ssh-add -
    - git config --global user.email $GITLAB_USER_EMAIL
    - git config --global user.name $GITLAB_USER_NAME
    - git config --global push.default current 
    - git clone --mirror $CI_REPOSITORY_URL
    - ssh-keyscan github.com >> ~/.ssh/known_hosts
    - cd $CI_PROJECT_NAME.git
  script:
    - git remote add github $GITHUB_REPO
    - git push --mirror github
  only:
    - push

build-and-push-job:
  stage: build-and-push
  image: docker:git
  tags:
    - docker
  before_script:
  - mkdir -p .ssh/
  - echo "$GIT_DEPLOY_KEY" | base64 -d | tr -d '\r'
    > .ssh/id_rsa
  - echo "$SSH_CONFIG" | base64 -d | tr -d '\r' > .ssh/config
  - ssh-keyscan -p 30622 gitlab-ssh.nrp-nautilus.io >> .ssh/known_hosts
  - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
  script:
  - cd $CI_PROJECT_DIR && docker build --no-cache -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
  - docker tag $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA $CI_REGISTRY_IMAGE:latest
  - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  - docker push $CI_REGISTRY_IMAGE:latest
  - docker rmi -f $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA $CI_REGISTRY_IMAGE:latest
  - docker builder prune -a -f
  timeout: 10h
  only:
    refs:
      - branches
    changes:
      - .gitlab-ci.yml
      - .gitmodules
      - Dockerfile
      - poetry.lock
      - pyproject.toml
      - conda-lock.yml
```

You shall verify the environment creation on your local machine:

```bash
conda env create -n <project_name> --file environment.yml
conda activate <project_name>
## Lock the conda environment
conda-lock -f environment.yml -p linux-64
poetry init
## Add dependencies interactively or through poetry add
## Examples:
poetry source add --priority=explicit pytorch-gpu-src https://download.pytorch.org/whl/<cuda_version>
poetry add --source pytorch-gpu-src torch
poetry add numpy==1.26.2
...
## Run code on your local machine to make sure all required dependencies are installed.
```
This procedure creates two lock files, `conda-lock.yml` and `poetry.lock`. Commit them to the git repository. Push to the Gitlab will compile the image. Any modification of the environment related files (see `.gitlab-ci.yml`) will trigger the image update.
