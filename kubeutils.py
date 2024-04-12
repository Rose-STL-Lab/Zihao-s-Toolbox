import yaml
import os
import copy
import itertools
import subprocess
import json
from copy import deepcopy
from typing import List
import os
import base64
import sys


with open("config/kube.yaml", "r") as f:
    settings = yaml.safe_load(f)
    
    
# Function to base64 encode the content of a given file
def base64_encode_file_content(file_path):
    with open(file_path, 'rb') as file:
        file_content = file.read()
        # Base64 encode the binary data
        base64_content = base64.b64encode(file_content).decode('utf-8')
    return base64_content


def is_binary_file(file_path):
    try:
        with open(file_path, 'rb') as file:
            chunk = file.read(1024)  # Read first 1024 bytes
        text_chars = bytearray({7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x100)) - {0x7f})
        if not chunk:  # Empty files are considered text files
            return False
        return bool(chunk.translate(None, text_chars))
    except Exception as e:
        print(f"[Error] Could not read file {file_path}: {e}")
        return True
    

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
    ephermal_storage: int = 0,
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
    prefix: str = None,
    
    ## Node config
    hostname_blacklist: List[str] = None,
    hostname_whitelist: List[str] = None,
    gpu_blacklist: List[str] = None,
    gpu_whitelist: List[str] = None,
    
    ## Files to map
    file: List[str] = [],
    
    ## Omit undefined kwargs
    **ignored
):
    assert startup_script is None or "sleep infinity" not in startup_script
    assert "sleep infinity" not in command
    
    for key, value in ignored.items():
        if key != "hparam":
            print(f"[Warning] Key {key}={value} is unknown. Ignoring it.")
    
    ## Initialization
    if prefix is None:
        name = f"{settings['user']}-{name}"
    else:
        if not prefix == "":
            name = f"{prefix}-{name}"
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
            
            # Add the commands to regenerate the config files
            commands = ''
            for root, _, files in os.walk('config'):
                for file_name in files:
                    # Construct the full file path
                    file_path = os.path.join(root, file_name)
                    # Base64 encode the file content
                    encoded_content = base64_encode_file_content(file_path)
                    file_name = file_name.replace("'", "'\\''")
                    # Generate the command
                    command = f"echo {encoded_content} | base64 -d | tr -d '\\r' > config/{file_name} && echo >> config/{file_name}; \n"
                    # Print the command
                    commands += command
            
            if os.path.exists('.env'):
                file_path = '.env'
                encoded_content = base64_encode_file_content(file_path)
                commands += f"echo {encoded_content} | base64 -d | tr -d '\\r' > .env && echo >> .env; \n"
            
            startup_script = (
                f"""mkdir -p config; 
ssh-keyscan -t ecdsa -p {ssh_port} -H {ssh_host} > /root/.ssh/known_hosts; git fetch --all --prune; 
git reset --hard origin/$(git remote show origin | grep "HEAD branch" | cut -d" " -f5); 
git submodule update --init --recursive; 
echo "conda activate {project_name}" >> ~/.bashrc; 
export PATH="{conda_home}/envs/{project_name}/bin/:$PATH"; 
"""
            )
    if '.env' not in file:
        file.append('.env')
    if not any(f.startswith('config') for f in file):
        file.append('config')
    if 'config/kube.yaml' not in file:
        file.append('config/kube.yaml')
        
    for f in file:
        normalized_path = os.path.normpath(f)
        if not os.path.exists(normalized_path):
            print(f"[Error] File or directory {normalized_path} does not exist. Quitting...")
            sys.exit(1)

        if os.path.isdir(normalized_path):
            for root, _, files in os.walk(normalized_path):
                for file_name in files:
                    file_path = os.path.join(root, file_name)
                    if is_binary_file(file_path):
                        print(f"[Warning] Skipping binary file: {file_path}")
                        continue
                    encoded_content = base64_encode_file_content(file_path)
                    # Make sure the directories exist in the startup script
                    relative_dir = os.path.relpath(root, normalized_path)
                    if relative_dir != ".":
                        startup_script += f"mkdir -p '{relative_dir}'\n"
                    escaped_f = file_path.replace("'", "'\\''")
                    startup_script += f"echo '{encoded_content}' | base64 -d | tr -d '\\r' > '{escaped_f}' && echo >> '{escaped_f}'; \n"
        else:
            if is_binary_file(normalized_path):
                print(f"[Warning] Skipping binary file: {normalized_path}")
                continue
            encoded_content = base64_encode_file_content(normalized_path)
            escaped_f = normalized_path.replace("'", "'\\''")
            startup_script += f"echo '{encoded_content}' | base64 -d | tr -d '\\r' > '{escaped_f}' && echo >> '{escaped_f}'; \n"

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
    # Map the S3 endpoint to the internal endpoint
    nautilus_s3_map = {
        'https://s3-west.nrp-nautilus.io': 'http://rook-ceph-rgw-nautiluss3.rook',
        'https://s3-central.nrp-nautilus.io': 'http://rook-ceph-rgw-centrals3.rook-central',
        'https://s3-east.nrp-nautilus.io': 'http://rook-ceph-rgw-easts3.rook-east',
        'https://s3-haosu.nrp-nautilus.io': 'http://rook-ceph-rgw-haosu.rook-haosu',
        'https://s3-tide.nrp-nautilus.io': 'http://rook-ceph-rgw-tide.rook-tide'
    }
    if "S3_ENDPOINT_URL" in env and env["S3_ENDPOINT_URL"] in nautilus_s3_map:
        env["S3_ENDPOINT_URL"] = nautilus_s3_map[env["S3_ENDPOINT_URL"]]
        
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
                        "cpu": str(cpu_count * 2),
                        "ephemeral-storage": f"{ephermal_storage}G"
                    },
                    "requests": {
                        "nvidia.com/gpu": str(gpu_count),
                        "memory": f"{memory}G",
                        "cpu": str(cpu_count),
                        "ephemeral-storage": f"{ephermal_storage}G"
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
                    {
                        "name": "NODE_NAME",
                        "valueFrom": {
                            "fieldRef": {"fieldPath": "spec.nodeName"}
                        }
                    },
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
            container["resources"][entry]["memory"] = "0G"
            container["resources"][entry]["cpu"] = "0"
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
                model_n = model.replace('_', '-').replace(' ', '-').replace('/', '-')
                dataset_n = dataset.replace('_', '-').replace(' ', '-').replace('/', '-')
                name = f"{project_name}-{model_n}-{dataset_n}"
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
                    for key in ["project_name", "user", "namespace"]:
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
                    name = config["metadata"]["name"]
                    yaml.Dumper.ignore_aliases = lambda *_: True
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
