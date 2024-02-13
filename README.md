## Requirements

boto3

## Usage:

Add the following Git repository as a submodule to your project repository:

```bash
git submodule add <repo-git> src/toolbox
```

### S3 Utilities

Create a .env file in your project repository with these values:

```bash
S3_BUCKET_NAME=<your_s3_bucket_name>
AWS_ACCESS_KEY_ID=<your_access_key>
AWS_SECRET_ACCESS_KEY=<your_secret_key>
S3_ENDPOINT_URL=https://...
```

Load environment by `export $(cat .env | xargs)` or through your favorite IDEs.

You can perform wildcard searches, downloads, uploads, or deletions on S3 files:

```bash
❯ python src/toolbox/s3utils.py --interactive 'Model/*t5*wise*419*'
Local files matching pattern:

S3 files matching pattern:
Model/Yelp/t5_model_12weeks_wise-sky-249-northern-dawn-288_epoch_1419/config.json
...

Choose an action [delete (local), remove (S3), download, upload, exit]:
```

Use single quotes to prevent shell wildcard expansion. The S3 bucket will sync with your current directory by default, maintaining the original file structure and creating necessary directories.


### Kube Utilities

#### Assumption

Kube utilities assume:

- Your job image is in a GitLab container registry.
- The image contains a conda environment named project_name located at <conda_home>/envs/.

#### Create Single Pod / Interactive

First, create `config/kube.yaml` containing shared information across all your kube workloads.

```yaml
project_name: <project-name>
namespace: <kube-namespace>
user: <gitlab-user-name>
conda_home: <conda-home-directory>
volumes:
  <pvc-name>: <mount-path>
registry_host: <docker-image-registry>
ssh_host: <gitlab-ssh-host>
ssh_port: <gitlab-ssh-port>
tolerations: 
  - <toleration-key>
gpu_whitelist:
  - <usable-gpu-list>
hostname_blacklist:
  - <unusable-node-hostnames-list>
```

Define either gpu_whitelist or gpu_blacklist and either hostname_blacklist or hostname_whitelist. Ensure consistency in project_name across your GitLab repository (<project_name>.git), conda environment (envs/<project_name>), image pull secret (<project_name>-read-registry), and S3 configuration (<project_name>-s3cfg). Avoid hyphens and underscores in project_name.

Your GitLab username would be used as user to label your kube workloads (label: <user>). For registry details, refer to the GitLab container registry documentation.

To create a pod, use the following Python script:

```python
from toolbox.kubeutils import create_config
from toolbox.utils import load_env_file

if __name__ == '__main__':
    name = "example"
    config = create_config(
        name=name,
        command="echo 'Hello, World!'",
        gpu_count=0,
        hostname_whitelist=['examplenode.net'],
        interactive=True,
        env=load_env_file(),
        volumes={
            'example-vol': '/temp/'
        }
    )
    yaml.Dumper.ignore_aliases = lambda *args : True
    with open(f"build/{name}.yaml", "w") as f:
        yaml.dump(config, f)
    os.system(f"kubectl apply -f build/{name}.yaml")
```

This script creates build/example.yaml and launches a pod on examplenode.net. The pod will run indefinitely after hello-world, and the conda environment will be activated by default. Set interactive=False to launch the command as a job. Don't put sleep infinity in command.

#### Launch a batch of workloads

Create config/launch.yaml with all your experiment commands and hyperparameters:

```yaml
project_name: <project-name>
model: 
  modelA: 
    command: python src/modelA.py <name> <hp1> <hp2>
    hparam: 
      hp1: [1, 2]
    gpu_count: ...
    cpu_count: ...

  modelB:
    command: python src/modelB.py <name> <hp1> <hp2> 
      hp1: [2, 3]
dataset:
  dataA:
    hparam:
      name: A
      hp2: [3, 4]
  dataB:
    hparam:
      name: B
      hp2: [3, 4]
  dataC:
    hparam:
      name: C
      hp2: [3, 4]
run:
  dataset: [dataA, dataB, dataC]
  model: [modelA, modelB]
#   hparam:
#     hp2: [3]
```

Execute experiments with the script below:

```python
from toolbox.kubeutils import batch
from toolbox.utils import load_env_file
import yaml
import os


if __name__ == '__main__':
    
    with open("config/launch.yaml", "r") as f:
        settings = yaml.safe_load(f)

    batch(
        run_configs=settings['run'],
        dataset_configs=settings['dataset'],
        model_configs=settings['model'],
        env=load_env_file(),
        dry_run=True
    )
```

This script will execute all model and dataset combinations with respective hyperparameters. Specifying hparam in the run section allows skipping certain combinations, facilitating targeted experiment reruns. The examples would skip all runs where `hp2 != 3`.

```bash
python src/modelA.py A 1 3
python src/modelA.py A 1 4
python src/modelA.py A 2 3
python src/modelA.py A 2 4
...
```



## Example Creation of [Nautilus](https://portal.nrp-nautilus.io/) Gitlab Image

This tutorial will guide you through the process of creating a GitLab Docker image based on your git repo using the Nautilus platform. This is useful for those looking to automate their deployment and integration workflows using GitLab's CI/CD features. The result image can integrate nicely with Kubeutils.

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
  - SSH_CONFIG: `fDF8akw1ajl5VnFpaEl1OWE5M0RBekluU0hUb3BnPXxsZXNDdmZDTVpNTGpqVTZURjhrQnJTMUE4ZFU9IHNzaC1lZDI1NTE5IEFBQUFDM056YUMxbFpESTFOVEU1QUFBQUlQeGVJaFdpb0F1akhGaEVHc0xDQzRZNStBTEVaRWU4QUd1SnFlM2FhVlR4Cgp8MXxqTzVkQWViQ3Y4LzJBTEE4WlBDYjJzTmJrOVE9fG1NTUpjbkZYRWdrRlBsOFpNZksvTEdISFFobz0gc3NoLWVkMjU1MTkgQUFBQUMzTnphQzFsWkRJMU5URTVBQUFBSVB4ZUloV2lvQXVqSEZoRUdzTENDNFk1K0FMRVpFZThBR3VKcWUzYWFWVHg=`, which is the base64 encoding of
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
