import yaml
import os
import copy
import itertools
from typing import List


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
    startup_script: str = None,
    registry_host: str = None,
    registry_port: int = None,
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
    **_
):
    ## Initialization
    with open("config/kube.yaml", "r") as f:
        settings = yaml.safe_load(f)
    
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
    assert (gpu_blacklist is None) ^ (gpu_whitelist is None), "Specify one of GPU black and white lists."
    assert (hostname_blacklist is None) ^ (hostname_whitelist is None), "Specify one of Host black and white lists."
    if startup_script is None:
        if startup_script in settings:
            startup_script = settings["startup_script"]
        else:
            conda_home = settings['conda_home']
            startup_script = (
                f'ssh-keyscan -t ecdsa -p {registry_port} -H {registry_host} '
                '> /root/.ssh/known_hosts; git fetch --all --prune; git reset --hard origin/master; '
                'git submodule update --init --recursive; '
                f'echo "conda activate {project_name}" >> ~/.bashrc; '
                f'export PATH="{conda_home}/envs/{project_name}/bin/:$PATH"; '
                'export PYTHONPATH="src:$PYTHONPATH"; '
            )
    if registry_host is None or registry_port is None:
        registry_host = settings["registry_host"]
        registry_port = settings["registry_port"]
    if tolerations is None:
        tolerations = settings["tolerations"]
    if volumes is None:
        volumes = settings["volumes"]
        
    env = [{'name': k, 'value': v} for k, v in env.items()]
    
    metadata = {
        "namespace": namespace,
        "labels": {"user": user}
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
                    startup_script + command
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
                            "matchExpressions": [
                                {
                                    "key": "kubernetes.io/hostname",
                                    "operator": "NotIn",
                                    "values": hostname_blacklist
                                } if hostname_blacklist else {
                                    "key": "kubernetes.io/hostname",
                                    "operator": "In",
                                    "values": hostname_whitelist
                                }, {
                                    "key": "nvidia.com/gpu.product",
                                    "operator": "In",
                                    "values": gpu_whitelist
                                } if gpu_whitelist else {
                                    "key": "nvidia.com/gpu.product",
                                    "operator": "NotIn",
                                    "values": gpu_blacklist
                                }
                            ]
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
        container["command"][-1] += " && sleep infinity"
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
    env: dict, 
    project_name: str = None, 
    dry_run: bool = False
):
    ## Initialization
    if project_name is None:
        try:
            with open("config/kube.yaml", "r") as f:
                settings = yaml.safe_load(f)
            project_name = settings["project_name"]
        except FileNotFoundError:
            raise FileNotFoundError("Please specify project_name in config/kube.yaml.")  
        
    for dataset in run_configs["dataset"]:
        for model in run_configs["model"]:
            hparam = {**dataset_configs[dataset]["hparam"], **model_configs[model]["hparam"]}
            
            for config, hparam_dict in zip(*fill_val(model_configs[model], hparam)):
                name = f"{project_name}-{model}-{dataset}"
                for key, value in hparam_dict.items():
                    if key != "alias":
                        name += f"-{key}-{value}"
                    if "hparam" in run_configs and key in run_configs["hparam"] and value not in run_configs["hparam"]:
                        break
                else:
                    del config["hparam"]
                    config = create_config(
                        name=name,
                        env=env,
                        project_name=project_name,
                        **config,
                    )
                    yaml.Dumper.ignore_aliases = lambda *_ : True
                    with open(f"build/{name}.yaml", "w") as f:
                        yaml.dump(config, f)
                    if not dry_run:
                        os.system(f"kubectl create -f build/{name}.yaml")


if __name__ == "__main__":
    pass
