## Requirements

boto3

## Usage:

Add the following Git repository as a submodule to your project repository:

```bash
git submodule add <repo-git> src/utils
```

### S3 Utilities

Create a .env file in your project repository with these values:

```bash
S3_BUCKET_NAME=<your_s3_bucket_name>
AWS_ACCESS_KEY_ID=<your_access_key>
AWS_SECRET_ACCESS_KEY=<your_secret_key>
S3_ENDPOINT_URL=https://...
```

You can perform wildcard searches, downloads, uploads, or deletions on S3 files:

```bash
❯ python src/utils/s3utils.py --interactive 'Model/*t5*wise*419*'
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
registry_host: <docker-image-registry>
registry_port: <registry-port>
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
from utils.kubeutils import batch
from utils.utils import load_env_file
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