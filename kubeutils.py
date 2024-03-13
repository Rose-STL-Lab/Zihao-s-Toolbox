import yaml
import os
import copy
import itertools
import subprocess
import json
from copy import deepcopy
from typing import List


with open("config/kube.yaml", "r") as f:
    settings = yaml.safe_load(f)
    

def check_job_status(name):
    # Get the job information in JSON format
    result = subprocess.run(
        ["kubectl", "--namespace=" + settings["namespace"], "get", "job", name, "-o=json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode == 0:
        job_info = json.loads(result.stdout)
        for condition in job_info.get("status", {}).get("conditions", []):
            if condition.get("type") == "Failed":
                return "failed"
        if job_info.get("status", {}).get("succeeded", 0) > 0:
            return "succeeded"
        if job_info.get("status", {}).get("active", 0) > 0:
            return "running"
        if job_info.get("status", {}).get("failed", 0) > 0:
            return "failed"
        
        return "unknown"
    else:
        return "not_found"
    

def delete_job(name):
    subprocess.run(["kubectl", "--namespace=" + settings["namespace"], "delete", "job", name])


def create_job(name):
    subprocess.run(["kubectl", "--namespace=" + settings["namespace"], "create", "-f", f"build/{name}.yaml"])


def create_config(
    ## Pod config
    name: str,
    command: str,
    gpu_count: int = 0,
    cpu_count: int = 0,
    memory: int = 0,
    env: dict = {},
    project_name: str = None,
    interactive: bool = False,
    server_command: str = "sleep infinity",
    startup_script: str = None,
    registry_host: str = None,
    ssh_host: str = None,
    ssh_port: int = None,
    tolerations: List[str] = None,
    volumes: dict[str, str] = None,
    
    ## User config
    namespace: str = None,
    user: str = None,
    image: str = None,
    image_pull_secrets: str = None,
    
    ## Node config
    hostname_blacklist: List[str] = None,
    hostname_whitelist: List[str] = None,
    gpu_blacklist: List[str] = None,
    gpu_whitelist: List[str] = None,
    
    ## Omit undefined kwargs
    **ignored
):
    assert startup_script is None or "sleep infinity" not in startup_script
    assert "sleep infinity" not in command
    
    for key, value in ignored.items():
        if key != "hparam":
            print(f"[Warning] Key {key}={value} is unknown. Ignoring it.")
    
    ## Initialization
    if namespace is None:
        namespace = settings["namespace"]
    if user is None:
        user = settings["user"]
    if project_name is None:
        project_name = settings["project_name"]
    if image is None:
        if "image" in settings:
            image = settings["image"]
        else:
            if registry_host is None:
                if "registry_host" in settings:
                    registry_host = settings["registry_host"]
                else:
                    raise ValueError("[Error] registry_host is a required field in kube.yaml if image undefined")
            image = f"{settings['registry_host']}/{user}/{project_name}:latest"
    if image_pull_secrets is None:
        if "image_pull_secrets" in settings:
            image_pull_secrets = settings["image_pull_secrets"]
        else:
            image_pull_secrets = f"{project_name}-read-registry"
    if gpu_blacklist is None and gpu_whitelist is None:
        if "gpu_blacklist" in settings:
            gpu_blacklist = settings["gpu_blacklist"]
        if "gpu_whitelist" in settings:
            gpu_whitelist = settings["gpu_whitelist"]
    if hostname_blacklist is None and hostname_whitelist is None:
        if "hostname_blacklist" in settings:
            hostname_blacklist = settings["hostname_blacklist"]
        if "hostname_whitelist" in settings:
            hostname_whitelist = settings["hostname_whitelist"]
    if startup_script is None:
        if "startup_script" in settings:
            startup_script = settings["startup_script"]
            if not startup_script.endswith(";"):
                startup_script += ";"
        else:
            if "conda_home" in settings:
                conda_home = settings['conda_home']
            else:
                raise ValueError(("[Error] conda_home is a required field in kube.yaml"
                                  "if startup_script undefined"))
            
            if ssh_host is None or ssh_port is None:
                if "ssh_host" in settings and "ssh_port" in settings:
                    ssh_port = settings["ssh_port"]
                    ssh_host = settings["ssh_host"]
                else:
                    raise ValueError(("[Error] ssh_host and ssh_port are required fields in kube.yaml "
                                      "if startup_script undefined"))
            
            startup_script = (
                f'ssh-keyscan -t ecdsa -p {ssh_port} -H {ssh_host} '
                '> /root/.ssh/known_hosts; git fetch --all --prune; '
                'git reset --hard origin/$(git remote show origin | grep "HEAD branch" | cut -d" " -f5); '
                'git submodule update --init --recursive; '
                f'echo "conda activate {project_name}" >> ~/.bashrc; '
                f'export PATH="{conda_home}/envs/{project_name}/bin/:$PATH"; '
            )
    if tolerations is None:
        if "tolerations" in settings:
            tolerations = settings["tolerations"]
        else:
            tolerations = []
    if volumes is None:
        if "volumes" in settings:
            volumes = settings["volumes"]
        else:
            volumes = {}
    if "PYTHONPATH" not in env:
        env["PYTHONPATH"] = "src"
    elif "src" not in env["PYTHONPATH"].split(":"):
        env["PYTHONPATH"] += ":src"
    if "WANDB_MODE" in env:
        env["WANDB_MODE"] = "online"  # Always use online mode in the cluster
        
    env = [{'name': k, 'value': v} for k, v in env.items()]
    
    metadata = {
        "namespace": namespace,
        "labels": {"user": user, "project": project_name}
    }

    template = {
        "containers": [
            {
                "name": "gpu-container",
                "image": image,
                "command": [
                    "conda", 
                    "run", 
                    "-n", 
                    project_name, 
                    "/bin/bash", 
                    "-c", 
                    ((startup_script + server_command) if interactive else (startup_script + command))
                ],
                "resources": {
                    "limits": {
                        "nvidia.com/gpu": str(gpu_count),
                        "memory": f"{memory * 2}G",
                        "cpu": str(cpu_count * 2)
                    },
                    "requests": {
                        "nvidia.com/gpu": str(gpu_count),
                        "memory": f"{memory}G",
                        "cpu": str(cpu_count)
                    }
                },
                "volumeMounts": [
                    {"mountPath": "/dev/shm", "name": "dshm"},
                ] + ([
                    {"mountPath": volumes[volume], "name": volume}
                for volume in volumes]),
                "env": [
                    {"name": "PYTHONUNBUFFERED", "value": "1"},
                    {"name": "PYTHONIOENCODING", "value": "UTF-8"},
                    *env
                ]
            }
        ],
        "imagePullSecrets": [
            {
                "name": image_pull_secrets
            }
        ],
        "restartPolicy": "Never",
        "affinity": {
            "nodeAffinity": {
                "requiredDuringSchedulingIgnoredDuringExecution": {
                    "nodeSelectorTerms": [
                        {
                            "matchExpressions": [expression for expression in [
                                {
                                    "key": "kubernetes.io/hostname",
                                    "operator": "NotIn",
                                    "values": hostname_blacklist
                                } if hostname_blacklist else {
                                    "key": "kubernetes.io/hostname",
                                    "operator": "In",
                                    "values": hostname_whitelist
                                } if hostname_whitelist else {}, {
                                    "key": "nvidia.com/gpu.product",
                                    "operator": "In",
                                    "values": gpu_whitelist
                                } if gpu_whitelist else {
                                    "key": "nvidia.com/gpu.product",
                                    "operator": "NotIn",
                                    "values": gpu_blacklist
                                } if gpu_blacklist else {}
                            ] if expression != {}]
                        }
                    ]
                },
            }
        },
        "tolerations": [
            {
                "key": key, 
                "operator": "Equal", 
                "value": "true", 
                "effect": "NoSchedule"
            }
        for key in tolerations],
        "volumes": [
            {
                "name": "dshm",
                "emptyDir": {"medium": "Memory"}
            }
        ] + [
            {
                "name": volume,
                "persistentVolumeClaim": {"claimName": volume}
            }
        for volume in volumes]
    }
    
    if interactive:
        container = template["containers"][0]
        for entry in ["limits", "requests"]:
            container["resources"][entry]["nvidia.com/gpu"] = "1"
            container["resources"][entry]["memory"] = "16G"
            container["resources"][entry]["cpu"] = "8"
        config = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": name, **metadata},
            "spec": template
        }
        return config
    else:
        config = {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {"name": name, **metadata},
            "spec": {"backoffLimit": 0, "template": {
                "metadata": metadata,
                "spec": template
            }}
        }
        return config
    

def fill_val_helper(config, key, value):
    # Helper function to replace a single value
    if key.startswith("_"):
        key = key[1:]
    if isinstance(config, dict):
        for k, v in config.items():
            if isinstance(v, (dict, list)):
                fill_val_helper(v, key, value)
            elif isinstance(v, str):
                config[k] = v.replace(f"<{key}>", str(value))
    elif isinstance(config, list):
        for i in range(len(config)):
            if isinstance(config[i], (dict, list)):
                fill_val_helper(config[i], key, value)
            elif isinstance(config[i], str):
                config[i] = config[i].replace(f"<{key}>", str(value))


def fill_val(original_config, vals):
    # Main function to replace all values and return a list of configs
    for key, value in vals.items():
        if type(value) is not list:
            vals[key] = [value]
    val_combination = list(itertools.product(*vals.values()))
    configs = []
    for combination in val_combination:
        new_config = copy.deepcopy(original_config)
        for key, value in zip(vals.keys(), combination):
            fill_val_helper(new_config, key, value)
        configs.append(new_config)
    val_combination = [dict(zip(vals.keys(), combination)) for combination in val_combination]
    return configs, val_combination


def batch(
    run_configs: dict, 
    dataset_configs: dict, 
    model_configs: dict, 
    project_name: str = None, 
    mode: str = "job",
    **kwargs
):  
    """
    mode: str
        mode=job: Create jobs in the Kubernetes cluster
        mode=local: Runs jobs locally
        mode=dryrun: Only creates the job files without running them
    """
    ## Initialization
    if project_name is None:
        project_name = settings["project_name"]
    
    assert mode in ["job", "local", "dryrun"]
        
    for dataset in run_configs["dataset"]:
        for model in run_configs["model"]:
            hparam = {}
            if "hparam" in dataset_configs[dataset]:
                hparam.update(dataset_configs[dataset]["hparam"])
            if "hparam" in model_configs[model]:
                hparam.update(model_configs[model]["hparam"])
            
            for config, hparam_dict in zip(*fill_val(model_configs[model], hparam)):
                if "prefix" in settings:
                    if settings["prefix"] == "":
                        name = f"{project_name}-{model}-{dataset}"
                    else:
                        name = f"{settings['prefix']}-{project_name}-{model}-{dataset}"
                else:
                    name = f"{settings['user']}-{project_name}-{model}-{dataset}"
                for key, value in hparam_dict.items():
                    if not key.startswith("_"):
                        name += f"-{key}-{value}"
                    if "hparam" in run_configs and key in run_configs["hparam"] and \
                    value not in run_configs["hparam"][key]:
                        break
                else:
                    if "hparam" in run_configs and "hparam" in config:
                        del config["hparam"]
                    
                    config_kwargs = deepcopy(kwargs['model'][model])
                    config_kwargs.update(kwargs['dataset'][dataset])
                    config_kwargs.update(config)
                    if 'env' in config_kwargs:
                        config_kwargs['env'].update(kwargs['env'])
                    else:
                        config_kwargs['env'] = kwargs['env']
                    
                    # Remove projectwise keys
                    for key in ["project_name", "user", "namespace", "prefix"]:
                        if key in config_kwargs:
                            print(f"[Warning] Key {key}={config_kwargs[key]} is not allowed in {name}. Ignoring it.")
                            del config_kwargs[key]

                    if mode == "local":
                        if "local_command" in config_kwargs:
                            model_configs[model]['command'] = model_configs[model]['local_command']
                        command = fill_val({'_': model_configs[model]['command']}, hparam_dict)[0][0]['_']
                        command = 'export $(cat .env | xargs) && ' + command
                        print(f"Running {hparam_dict} ... > {command}")
                        os.system(command)
                        continue
                            
                    if "local_command" in config_kwargs:
                        del config_kwargs["local_command"]
                    
                    config = create_config(
                        name=name,
                        project_name=project_name,
                        **config_kwargs
                    )
                    yaml.Dumper.ignore_aliases = lambda *_ : True
                    if not os.path.exists("build"):
                        os.makedirs("build")
                    with open(f"build/{name}.yaml", "w") as f:
                        yaml.dump(config, f)
                    if mode == "job":
                        status = check_job_status(name)
                        
                        if status == "succeeded" or status == "running":
                            print(f"Job '{name}' is already {status}. Doing nothing.")
                        elif status == "failed":
                            print(f"Job '{name}' has failed. Deleting the job.")
                            delete_job(name)
                            print(f"Creating job '{name}'.")
                            create_job(name)
                        elif status == "not_found":
                            print(f"Job '{name}' not found. Creating the job.")
                            create_job(name)


if __name__ == "__main__":
    pass
