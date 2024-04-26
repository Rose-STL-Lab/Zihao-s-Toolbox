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
```bash
vim .env
```
```ini
S3_BUCKET_NAME=example
S3_ENDPOINT_URL=https://s3-west.nrp-nautilus.io
```

Setup your Kubernetes configuration in `config/kube.yaml` (replace `<NAMESPACE>` and `<USER>` with your details):
```bash
mkdir -p config; vim config/kube.yaml
```
```yaml
project_name: example
namespace: <NAMESPACE>
user: <USER>
registry_host: gitlab-registry.nrp-nautilus.io
ssh_host: gitlab-ssh.nrp-nautilus.io
ssh_port: 30622
conda_home: /opt/conda
image: gitlab-registry.nrp-nautilus.io/zihaozhou/example
```

> Note: Here we created the image for you. If you want to create your own image, please refer to Section 4. After creation of your own image, you no longer need to specify the `image` field in `kube.yaml`. (unless you are collaborating with others and the repo is created under their accounts)

Define the experiment configurations in `config/launch.yaml`:

```bash
vim config/launch.yaml
```
```yaml
project_name: example
model:
  average:
    # <fn> will be automatically replaced by hparam values
    command: >-
      [](make download file=data/;) python src/avg.py <fn>
    # # Model can also have hparam, hparam could be either list or single value
    # hparam:
    #   hid_dim: [256, 512]
    #   ...
    # # Override *non-projectwise* kube config, see Section 2
    gpu_count: 0
    # memory: 8  # 8GiB
    # image: gitlab-registry.nrp-nautilus.io/prp/jupyter-stack/minimal
    # ...
  median:
    command: >-
      [](make download file=data/;) python src/med.py <fn>
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

> #### Understanding Launch Configuration
> - `[](make download file=data/;)` is a syntax sugar. Sometimes, we expect slight difference between local and remote commands (like we don't need to re-download data in local runs). Here we use `[]` to indicate the local command (which is doing nothing here), and `()` to indicate the remote command.
> - In `python src/med.py <fn>`, `<fn>` will be replaced by the values defined in `hparam` section. Hypermeters can be defined in both `model` and `dataset` sections. They are placeholders such that you don't need to copy and paste the same command with slight modifications.
> - `gpu_count` are model-wise / dataset-wise kubernetes configurations that can be overridden in `launch.yaml`. See Section 2 for all overridable fields. If you don't specify them, they will be inherited from `kube.yaml`. If you specify the same field in both `model` and `dataset`, the one in `model` will take precedence.
> - `run` section specifies the combinations of experiments to run. You can also add `hparam` to the `run` section to specify the hyperparameters you want to run. If you don't specify the `hparam`, all possible combinations of hyperparameters will be run.
> #### Advanced Configuration
> - You can specify an additional file section. (example: `file: [src/temp.py]`). Then, when you run `make pod` or `make job`, the specified files will be automatically uploaded (and possibly overrides the preexisting file) to the pod or job. This is particularly useful when you are debugging and don't want to make git commit. You can also run `make copy_files pod_name=<pod_name>` to upload files to a running pod.
>   - This only supports a limited number of **text files**. If you need to upload other types of files or large text files, please consider using S3. Otherwise the pod would fail due to command length limit.
> - The hparam sections can be a list of hparam dictionaries with the *same keys*. See below for an example. Why do we need this? Sometimes we don't want to run all combinations of hyperparameters, but only a subset of them. In this case, `make` will create three jobs, `train=paper`, `train=original`, and `train=scale`.
> ```
> hparam:
>     train:
>         paper:
>           _learning_rate: 0.000000008192
>           _lr_scheduler: linear
>           _lr_warmup_steps: 0
>         original:
>           _learning_rate: 1e-5
>           _lr_scheduler: constant
>           _lr_warmup_steps: 500
>         scale:
>           _learning_rate: 1e-5
>           _lr_scheduler: constant
>           _lr_warmup_steps: 500
> ```
> 
> - Overridable kube fields can also be directly specified at the root level of `launch.yaml`. Examples are 
> ```
> model: ...
> dataset: ...
> run: ...
> gpu_count: 1
> ```
>   They will override the corresponding fields in `kube.yaml`.

#### Running Locally

Execute the following command to run experiments locally: `make local`

Example output:

```
Running {
    "_fn": "data/1.txt"
} ... 

python src/avg.py data/1.txt

2.0
```

Change the run section in `config/launch.yaml` to

```
run:
   dataset: [data1, data2]
   model: [average, median]
```

and execute `make local` to run all possible combinations of experiments sequentially.

```
Running {
    "_fn": "data/1.txt"
} ... 

python src/avg.py data/1.txt

2.0
Running {
    "_fn": "data/1.txt"
} ... 

python src/med.py data/1.txt

2.0
Running {
    "_fn": "data/2.txt"
} ... 

python src/avg.py data/2.txt

5.0
Running {
    "_fn": "data/2.txt"
} ... 

python src/med.py data/2.txt

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
pod/<YOUR-USERNAME>-example-interactive-pod created
```

You can now navigate to the shell of the pod by running: `kubectl exec -it <YOUR-USERNAME>-example-interactive-pod -- /bin/bash`. Now, run `make download file=data/; make local`. You should see exactly the same output as running locally.

### Remote Batch Jobs


To run all possible combinations of experiments in parallel with Nautilus, run: `make job`

Example output:

```bash
Job 'example-average-data1' not found. Creating the job.
job.batch/example-average-data1 created
Job 'example-median-data1' not found. Creating the job.
job.batch/example-median-data1 created
Job 'example-average-data2' not found. Creating the job.
job.batch/example-average-data2 created
Job 'example-median-data2' not found. Creating the job.
job.batch/example-median-data2 created
```

After a while, you can run `kubectl logs -f <YOUR-USERNAME>-example-average-data1` to check the logs of the job. You would see
```
Downloaded data/1.txt to ./data/1.txt
Downloaded data/2.txt to ./data/2.txt
2.0
```

Finally, run `make delete` to cleanup all workloads.

> Be careful: `make delete` operates by removing all pods and jobs under your user label.

---

## 2. Kube Utilities Specification

`config/kube.yaml`:

```yaml
##### Project-wise configuration, should be the same across all experiments
# Will not be overwritten by the launch.yaml
project_name: str, required
user: str, required
namespace: str, required

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
## Prefix of the names of your workloads
prefix: str
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

Load environment by `export $(grep -v '^#' .env | xargs -d '\n')` or through `make` commands.

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
- A Github account, where you can register at [here](https://github.com).
- A Nautilus Gitlab account, where you can register at [here](https://gitlab.nrp-nautilus.io/).
- Familiarity with SSH, docker container, continuous integration and deployment (CI/CD) concepts

### Steps

1. Create a git repo at Nautilus [Gitlab](https://gitlab.nrp-nautilus.io/) with the name `example`. Don't initialize the repository with any file. If you want to use a different name, remember to replace `example` with your repo name in the following steps. Also, make sure your name is all lowercase and without any special characters.
2. Create a git repo with the same name at Github. 
3. Generate an SSH key pair with the name `example` on your local machine using the following command: `ssh-keygen -f example -N ""`.
4. Generate an SSH key pair with the name `example-write` on your local machine using the following command: `ssh-keygen -f example-write -N ""`.

> Note: The `example` key is kept in the image for pulling the code from the private repository, while the `example-write` key is used for mirroring the code to Gitlab. Be careful — if you accidentially dropped the `example-write` key in the image and later make it public, anyone can push code to your repository.

5. Add the public key `example.pub` to Gitlab Repo - Settings - **Deploy Keys**. Title: `example`, **don't** grant write permission.
6. Add the public key `example-write.pub` to Gitlab Repo - Settings - **Deploy Keys**. Title: `example-write`, grant write permission.
7. Add the public key `example.pub` to Github Repo - Settings - **Deploy Keys**. Title: `example`, **don't** grant write permission.
7. Deploy tokens are used to securely download (pull) Docker images from your GitLab registry without requiring sign-in. Under Gitlab Repo - Settings - Repository - **Deploy Tokens**, create new deploy token with name `example-write-registry`. Grant both `write_registry` and `read_registry` access. Take a note of the `username` and `password` for this token for Gitlab CI. 
8. Create new deploy token with name `example-read-registry`. Grant `read_registry` access. Take a note of the `username` and `password` for this token for Kubernetes experiments.

> Note: The `example-write-registry` token is used for pushing the image to the registry from Github, while the `example-read-registry` token is used in the kube cluster to pull the image.

9. Run the follow command to upload the read tokens to the cluster. 
```bash
kubectl create secret docker-registry example-read-registry \
    --docker-server=gitlab-registry.nrp-nautilus.io \
    --docker-username=<username> \
    --docker-password=<password>
```
10. In **Github** Repo - Settings - Secrets and variables - **Actions**, enter the following repository secrets:
  - SSH_CONFIG: `SG9zdCBnaXRodWIuY29tCiAgSG9zdE5hbWUgZ2l0aHViLmNvbQogIFVzZXIgZ2l0CiAgSWRlbnRpdHlGaWxlIH4vLnNzaC9pZF9yc2EKCkhvc3QgZ2l0bGFiLXNzaC5ucnAtbmF1dGlsdXMuaW8KICBIb3N0TmFtZSBnaXRsYWItc3NoLm5ycC1uYXV0aWx1cy5pbwogIFVzZXIgZ2l0CiAgUG9ydCAzMDYyMgogIElkZW50aXR5RmlsZSB+Ly5zc2gvaWRfcnNhCgo=`, which is the base64 encoding of
  ```
Host github.com
  HostName github.com
  User git
  IdentityFile ~/.ssh/id_rsa

Host gitlab-ssh.nrp-nautilus.io
  HostName gitlab-ssh.nrp-nautilus.io
  User git
  Port 30622
  IdentityFile ~/.ssh/id_rsa
  ```
  - DOCKER_PASSWORD: the write `password` from the previous step.
  - DOCKER_USERNAME: the write `username` from the previous step.
  - GIT_DEPLOY_KEY: base64 encode the **read** deploy key you created (`base64 -i example`, don't include any new lines).
  - GITLAB_DEPLOY_KEY: base64 encode the **write** deploy key you created (`base64 -i example-write`, don't include any new lines).
  - GITLAB_USER_NAME: your gitlab user name, which is in the middle of your gitlab repo URL.
7. Create the following files under your repo:
  - `environment.yml`
```yaml
name: example
channels:
  - conda-forge
  - nvidia
dependencies:
  - python=3.11.*
  - pip
  - poetry=1.*
```
  - `Dockerfile` 
    - Can be copied using `cp src/toolbox/Dockerfile .`
    - Can be copied using `mkdir -p .github/workflows; cp src/toolbox/workflows/docker.yml .github/workflows/docker.yml`
    - Can be copied using `mkdir -p .github/workflows; cp src/toolbox/workflows/mirror.yml .github/workflows/mirror.yml`

You shall verify the environment creation on your local machine:

```bash
conda env create -n example --file environment.yml
conda activate example
poetry init
## Add dependencies interactively or through poetry add
## Examples:
poetry source add --priority=explicit pytorch-gpu-src https://download.pytorch.org/whl/<cuda_version>
poetry add --source pytorch-gpu-src torch
poetry add numpy==1.26.2
...
## Run code on your local machine to make sure all required dependencies are installed.
```
This procedure creates the lock file, `poetry.lock`. Commit it to the git repository. Push to the Github will compile the image. Any modification of the environment related files (see workflow file) will trigger the image update. 

You may check out `https://github.com/ZihaoZhou/example` and `https://gitlab.nrp-nautilus.io/ZihaoZhou/example` as a reference.
