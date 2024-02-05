## Requirements

boto3

## Usage:

Add this Git repo as a submodule of your project repo.

```bash
git submodule add <repo-git> src/utils
```

### S3 Utilities

Add `.env` under your project repo with the following values:

```bash
S3_BUCKET_NAME=<your_s3_bucket_name_without_s3://>
AWS_ACCESS_KEY_ID=<your_access_key>
AWS_SECRET_ACCESS_KEY=<your_secret_key>
S3_ENDPOINT_URL=https://...
```

Then s3 files can be queried, downloaded, uploaded, or removed using wildcard, e.g.,

```bash
❯ python src/utils/s3utils.py --interactive 'Model/*t5*wise*419*'
Local files matching pattern:

S3 files matching pattern:
Model/Yelp/t5_model_12weeks_wise-sky-249-northern-dawn-288_epoch_1419/config.json
...

Choose an action [delete (local), remove (S3), download, upload, exit]:
```

Note that * can match arbitrary levels of directories. Remember to use single-quote to avoid wildcard expansion in shell.

The S3 bucket is syncing with your current directory by default. Download/Upload will preserve original file structure and create intermediate directories if needed.


### Kube Utilities

#### Assumption

Kube utilities assume 

* Your job image is stored in a gitlab-registry
* In the image, you have installed a conda environment with name `project_name` under `<conda_home>/envs/`.

#### Create Single Pod / Interactive

First, create `config/kube.yaml` containing shared information across all your kube workloads.

```yaml
project_name: <project-name>
namespace: <your-assigned-kube-namespace>
user: <your-user-name>
conda_home: <conda-home-folder-no-trailing-slash>
registry_host: <registry-of-docker-image>
registry_port: <registry-port>
tolerations: 
  - <no-schedule-toleration-just-the-key>
gpu_whitelist:
  - <list-of-usable-gpus>
hostname_blacklist:
  - <list-of-unusable-node-hostnames>
```

Make sure you specify one and only one of `gpu_whitelist` and `gpu_blacklist`. Likewise, specify one of `hostname_blacklist` and `hostname_whitelist`. 

The project name should be the same across your:

- gitlab repository name
- conda environment name
- image pull secret name (`<project_name>-read-registry`)
- s3 config name (`<project_name>-s3cfg`)

As a result, avoid using hyphen or underline in your `project_name`.

The user name shall be your gitlab user name and will also be used to mark your kube workloads (`label: <user>`).

Registry_host is in the format of `gitlab-registry...`, without https header. For details, see https://docs.gitlab.com/ee/administration/packages/container_registry.html.

Now, we can create a example pod with the following Python script:

```python
from utils.kubeutils import create_config
from utils.utils import load_env_file

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

This will create `build/example.yaml` and launch a pod on the node `examplenode.net`. `sleep infinity` will be automatically appended. The conda environment will be activated by default. Alternatively, you can specify `interactive=False` and launch the command as a job.

#### Launch a batch of workloads

First, create `config/launch.yaml` that contain all running hyperparameter commands for experiments. 

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

`hparam` can be empty for model and dataset. By default, the script will run all possible combinations of model and dataset with all possible combinations of hyperparameters. In the given example, this means running 
```bash
python src/modelA.py A 1 3
python src/modelA.py A 1 4
python src/modelA.py A 2 3
python src/modelA.py A 2 4
...
```

if `hparam` in the `run` section is specified, then all runs with `hp2 != 3` will be skipped. This make it easier to rerun a small subset of experiments.