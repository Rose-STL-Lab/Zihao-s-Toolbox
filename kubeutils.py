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
import re
import platform
import hashlib


with open("config/kube.yaml", "r") as f:
    settings = yaml.safe_load(f)


def is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


def normalize(s):
    return s.replace('_', '-').replace(' ', '-').replace('/', '-')


def abbreviate(s):
    s = normalize(s)
    if is_number(s):
        return s
    parts = s.split('-')
    if len(parts) > 1:
        return ''.join(part[0] for part in parts)
    else:
        return s[:1]


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
        text_chars = bytearray({7, 8, 9, 10, 12, 13, 27}
                               | set(range(0x20, 0x100)) - {0x7f})
        if not chunk:  # Empty files are considered text files
            return False
        return bool(chunk.translate(None, text_chars))
    except Exception as e:
        print(f"[Error] Could not read file {file_path}: {e}")
        return True


# Create script to copy files
def file_to_script(file):
    file_copy_script = []
    for f in file:
        normalized_path = os.path.normpath(f)
        if not os.path.exists(normalized_path):
            print(
                f"[Error] File or directory {normalized_path} does not exist. Quitting...")
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
                        file_copy_script.append(f"mkdir -p '{relative_dir}' ")
                    escaped_f = file_path.replace("'", "'\\''")
                    file_copy_script.append(
                        f"echo '{encoded_content}' | base64 -d | tr -d '\\r' > '{escaped_f}' && echo >> '{escaped_f}' ")
        else:
            if is_binary_file(normalized_path):
                print(f"[Warning] Skipping binary file: {normalized_path}")
                continue
            encoded_content = base64_encode_file_content(normalized_path)
            escaped_f = normalized_path.replace("'", "'\\''")
            file_copy_script.append(
                f"echo '{encoded_content}' | base64 -d | tr -d '\\r' > '{escaped_f}' && echo >> '{escaped_f}' ")
    return file_copy_script


def check_job_status(name):
    # Get the job information in JSON format
    result = subprocess.run(
        ["kubectl", "--namespace=" + settings["namespace"],
            "get", "job", name, "-o=json"],
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
    subprocess.run(
        ["kubectl", "--namespace=" + settings["namespace"], "delete", "job", name]
    )


def create_job(name):
    subprocess.run(
        [
            "kubectl",
            "--namespace=" + settings["namespace"],
            "create",
            "-f",
            f"build/{name}.yaml",
        ]
    )


def create_config(
    # Pod config
    name: str,
    command: str,
    dev_command: str = None,
    gpu_count: int = 0,
    cpu_count: int = 5,
    ephermal_storage: int = 100,
    memory: int = 32,
    env: dict = {},
    project_name: str = None,
    conda_env_name: str = None,
    interactive: bool = False,
    server_command: str = "sleep infinity",
    startup_script: str = None,
    registry_host: str = None,
    ssh_host: str = None,
    ssh_port: int = None,
    tolerations: List[str] = None,
    volumes: dict[str, str] = None,

    # User config
    namespace: str = None,
    user: str = None,
    gitlab_user: str = None,
    image: str = None,
    image_pull_secrets: str = None,
    prefix: str = None,

    # Node config
    hostname_blacklist: List[str] = None,
    hostname_whitelist: List[str] = None,
    gpu_blacklist: List[str] = None,
    gpu_whitelist: List[str] = None,
    special_gpu: str = None,

    # Files to map
    file: List[str] = [],

    # Omit undefined kwargs
    **ignored
):
    assert startup_script is None or "sleep infinity" not in startup_script
    assert "sleep infinity" not in command

    for key, value in ignored.items():
        if key != "hparam":
            print(f"[Warning] Key {key}={value} is unknown. Ignoring it.")

    # Initialization
    if prefix is None:
        name = f"{settings['user']}-{name}"
    else:
        if not prefix == "":
            name = f"{prefix}-{name}"
    if namespace is None:
        namespace = settings["namespace"]
    if user is None:
        user = settings["user"]
    if gitlab_user is None:
        if "gitlab_user" in settings:
            gitlab_user = settings["gitlab_user"]
        else:
            gitlab_user = user
    if project_name is None:
        project_name = settings["project_name"]
    if conda_env_name is None:
        conda_env_name = project_name
    if image is None:
        if "image" in settings:
            image = settings["image"]
        else:
            if registry_host is None:
                if "registry_host" in settings:
                    registry_host = settings["registry_host"]
                else:
                    registry_host = "gitlab-registry.nrp-nautilus.io"
            image = f"{registry_host}/{gitlab_user}/{project_name}:latest"
    if image_pull_secrets is None:
        if "image_pull_secrets" in settings:
            image_pull_secrets = settings["image_pull_secrets"]
        else:
            image_pull_secrets = f"{project_name}-read-registry"
    if gpu_blacklist is None and gpu_whitelist is None:
        if special_gpu is None and "gpu_blacklist" in settings:
            gpu_blacklist = settings["gpu_blacklist"]
        if special_gpu is None and "gpu_whitelist" in settings:
            gpu_whitelist = settings["gpu_whitelist"]
    if special_gpu is not None:
        gpu_blacklist = None
        gpu_whitelist = None
    if hostname_blacklist is None and hostname_whitelist is None:
        if "hostname_blacklist" in settings:
            hostname_blacklist = settings["hostname_blacklist"]
        if "hostname_whitelist" in settings:
            hostname_whitelist = settings["hostname_whitelist"]
    if startup_script is None:
        if "startup_script" in settings:
            startup_script = settings["startup_script"]
        else:
            if "conda_home" in settings:
                conda_home = settings['conda_home']
            else:
                conda_home = "/opt/conda"

            if ssh_host is None or ssh_port is None:
                if "ssh_host" in settings and "ssh_port" in settings:
                    ssh_port = settings["ssh_port"]
                    ssh_host = settings["ssh_host"]
                else:
                    ssh_port = "30622"
                    ssh_host = "gitlab-ssh.nrp-nautilus.io"
            startup_script = (
                f"""#!/bin/bash
mkdir -p config
git pull
git submodule update --init --recursive
echo "conda activate {conda_env_name}; " >> ~/.bashrc
export PATH="{conda_home}/envs/{conda_env_name}/bin/:$PATH"
echo 'if [ -f "$HOME/src/toolbox/s3region.sh" ]; then source "$HOME/src/tool outbox/s3region.sh"; fi' >> ~/.bashrc
if [ -f src/toolbox/s3region.sh ]; then
    chmod +x src/toolbox/s3region.sh
    source src/toolbox/s3region.sh
fi
"""
            )
    if '.env' not in file:
        file.append('.env')
    if not any(f.startswith('config') for f in file):
        file.append('config')
    if 'config/kube.yaml' not in file:
        file.append('config/kube.yaml')

    startup_script += "\n".join(file_to_script(file))
    # Save startup script to build/
    with open(f"build/{name}.sh", "w") as f:
        f.write(startup_script)
    startup_encoding = base64.b64encode(
        bytes(startup_script, 'utf-8')).decode('utf-8')
    load_startup_script = f"echo {startup_encoding} | base64 -d > startup.sh && chmod +x startup.sh && source startup.sh; "

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
    for env_key in env:
        if env[env_key] in nautilus_s3_map:
            env[env_key] = nautilus_s3_map[env[env_key]]

    env = [{'name': k, 'value': v} for k, v in env.items()]

    metadata = {
        "namespace": namespace,
        "labels": {"user": user, "project": project_name}
    }

    command = re.sub(r'\[(.*?)\]\((.*?)\)', r'\2', command)

    template = {
        "containers": [
            {
                "name": "gpu-container",
                "image": image,
                "command": [
                    "conda",
                    "run",
                    "-n",
                    conda_env_name,
                    "/bin/bash",
                    "-c",
                    ((load_startup_script + server_command)
                     if interactive else (load_startup_script + command))
                ],
                "resources": {
                    "limits": {
                        **(
                            {"nvidia.com/gpu": str(gpu_count)} 
                            if special_gpu is None 
                            else {f"nvidia.com/{special_gpu}": str(gpu_count)}
                        ),
                        "memory": f"{int(memory * 1.2)}G",
                        "cpu": str(int(cpu_count * 1.2)),
                        **({"ephemeral-storage": f"{ephermal_storage}G"} if ephermal_storage != 0 else {})
                    },
                    "requests": {
                        **(
                            {"nvidia.com/gpu": str(gpu_count)} 
                            if special_gpu is None 
                            else {f"nvidia.com/{special_gpu}": str(gpu_count)}
                        ),
                        "memory": f"{memory}G",
                        "cpu": str(cpu_count),
                        **({"ephemeral-storage": f"{ephermal_storage}G"} if ephermal_storage != 0 else {})
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
            for key in container["resources"][entry]:
                if key.startswith("nvidia.com/") and int(container["resources"][entry][key]) > 2:
                    container["resources"][entry][key] = "2"
                    break
            if "memory" in container["resources"][entry] and int(container["resources"][entry]["memory"][:-1]) > 32:
                container["resources"][entry]["memory"] = "32G"
            if "cpu" in container["resources"][entry] and int(container["resources"][entry]["cpu"]) > 16:
                container["resources"][entry]["cpu"] = "16"
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
    keys = list(vals.keys())
    vals_copy = copy.deepcopy(vals)
    vals = {}
    for key, value in vals_copy.items():
        if type(value) is dict:
            new_value = []
            key_idx = keys.index(key)
            prev_keys = None
            for k, v in value.items():
                new_value.append({k: v})
                assert type(v) is dict
                if prev_keys:
                    assert prev_keys == v.keys()
                else:
                    prev_keys = v.keys()
                    for k_ in v.keys():
                        key_idx += 1
                        keys.insert(key_idx, k_)
            vals[key] = new_value
        elif type(value) is not list:
            vals[key] = [value]
        else:
            vals[key] = value
    val_combination = list(itertools.product(*vals.values()))
    val_combination_copy = copy.deepcopy(val_combination)
    val_combination = []
    for combination in val_combination_copy:
        assert type(combination) is tuple
        new_combination = []
        for val in combination:
            if type(val) is dict:
                assert len(val) == 1
                for k, v in val.items():
                    assert type(v) is dict
                    new_combination.append(k)
                    new_combination.extend(v.values())
            else:
                new_combination.append(val)
        val_combination.append(new_combination)
    configs = []
    for combination in val_combination:
        new_config = copy.deepcopy(original_config)
        for key, value in zip(keys, combination):
            fill_val_helper(new_config, key, value)
        configs.append(new_config)
    val_combination = [dict(zip(keys, combination))
                       for combination in val_combination]
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
        mode=dryrun: Only creates the job files without deploying them
        mode=local-dryrun: Only prints the local commands without running them
    """
    # Initialization
    if project_name is None:
        project_name = settings["project_name"]

    assert mode in ["job", "local", "dryrun", "local-dryrun", "pod-dryrun"]

    if "hparam" in run_configs:
        for key, val in run_configs["hparam"].items():
            if type(val) is str:
                run_configs["hparam"][key] = [val]

    for dataset in run_configs["dataset"]:
        for model in run_configs["model"]:
            hparam = {}
            if dataset_configs[dataset] is not None and "hparam" in dataset_configs[dataset]:
                hparam.update(dataset_configs[dataset]["hparam"])
            if model_configs[model] is not None and "hparam" in model_configs[model]:
                hparam.update(model_configs[model]["hparam"])

            for config, hparam_dict in zip(*fill_val(model_configs[model], hparam)):
                model_n = normalize(model)
                dataset_n = normalize(dataset)
                name = f"{project_name}-{model_n}-{dataset_n}"
                name_ = deepcopy(name)

                # Check if the name is too long
                abbrev = False
                for key, value in hparam_dict.items():
                    if not key.startswith("_"):
                        name_ += f"-{normalize(key)}-{normalize(value)}"
                if len(name_) > 63 - 6:  # Exclude hash
                    abbrev = True

                for key, value in hparam_dict.items():
                    if not key.startswith("_"):
                        if abbrev:
                            name += f"-{abbreviate(key)}-{abbreviate(value)}"
                        else:
                            name += f"-{normalize(key)}-{normalize(value)}"
                    else:
                        key = key[1:]
                    if "hparam" in run_configs and key in run_configs["hparam"] and \
                            value not in run_configs["hparam"][key]:
                        break
                else:
                    hash_object = hashlib.sha256(
                        json.dumps(hparam_dict).encode())
                    name += '-' + hash_object.hexdigest()[:5]

                    if "hparam" in run_configs and "hparam" in config:
                        del config["hparam"]

                    config_kwargs = deepcopy(kwargs)
                    if 'model' in config_kwargs:
                        del config_kwargs['model']
                    if 'dataset' in config_kwargs:
                        del config_kwargs['dataset']
                    if 'run' in config_kwargs:
                        del config_kwargs['run']
                    if kwargs['model'][model] is not None:
                        config_kwargs.update(kwargs['model'][model])
                    if kwargs['dataset'][dataset] is not None:
                        config_kwargs.update(kwargs['dataset'][dataset])
                    config_kwargs.update(config)
                    if 'env' in config_kwargs:
                        config_kwargs['env'].update(kwargs['env'])
                    else:
                        config_kwargs['env'] = kwargs['env']

                    # Remove projectwise keys
                    for key in ["project_name", "user", "namespace"]:
                        if key in config_kwargs:
                            print(
                                f"[Warning] Key {key}={config_kwargs[key]} is not allowed in {name}. Ignoring it.")
                            del config_kwargs[key]

                    # Remove comments between ## and ##
                    model_configs[model]['command'] = re.sub(r'##(.*?)##', '', model_configs[model]['command'])
                    if "local" in mode:
                        if "local_command" in config_kwargs:
                            model_configs[model]['command'] = model_configs[model]['local_command']
                        command = fill_val({'_': model_configs[model]['command']}, hparam_dict)[
                            0][0]['_']
                        command = re.sub(
                            r'\[(.*?)\]\(.*?\)', r'\1', command).strip()
                        system_type = platform.system()
                        if system_type == 'Linux':
                            command = 'export $(grep -v \'^#\' .env | xargs -d \'\\n\') && ' + command
                        elif system_type in ['Darwin', 'FreeBSD']:
                            command = 'export $(grep -v \'^#\' .env | xargs -0) && ' + command
                        else:
                            raise Exception("Unsupported OS")
                        if mode == "local":
                            print(f"Running {json.dumps(hparam_dict, indent=4)} ... \n```\n{command}\n```")
                            os.system(command)
                            continue
                        else:
                            assert mode == "local-dryrun", "Invalid mode"
                            print(f"{name}: {command}")
                            continue

                    if "local_command" in config_kwargs:
                        del config_kwargs["local_command"]

                    hparam_dict = {k[1:] if k.startswith(
                        "_") else k: v for k, v in hparam_dict.items()}
                    if "gpu_count" in hparam_dict:
                        print(
                            f"GPU count overriden by hparam: {hparam_dict['gpu_count']}")
                        config_kwargs["gpu_count"] = int(
                            hparam_dict["gpu_count"])
                    if "gpu_whitelist" in hparam_dict:
                        print(
                            f"GPU white list overriden by hparam: {hparam_dict['gpu_whitelist']}")
                        if type(hparam_dict["gpu_whitelist"]) is str:
                            config_kwargs["gpu_whitelist"] = [
                                hparam_dict["gpu_whitelist"]]
                        else:
                            config_kwargs["gpu_whitelist"] = hparam_dict["gpu_whitelist"]
                    if "cpu_count" in hparam_dict:
                        print(
                            f"CPU count overriden by hparam: {hparam_dict['cpu_count']}")
                        config_kwargs["cpu_count"] = int(
                            hparam_dict["cpu_count"])
                    if "memory" in hparam_dict:
                        print(
                            f"Memory overriden by hparam: {hparam_dict['memory']}")
                        config_kwargs["memory"] = int(hparam_dict["memory"])

                    config = create_config(
                        name=name,
                        project_name=project_name,
                        **config_kwargs
                    )

                    original_command = config["spec"]["template"]["spec"]["containers"][0]["command"][-1].strip()
                    if "run_mode" in hparam_dict and "dev" in hparam_dict["run_mode"] and "dev_command" in config_kwargs:
                        config["spec"]["template"]["spec"]["containers"][0]["command"][-1] = re.sub(
                            r'(accelerate launch|python) .*\.py',
                            config_kwargs['dev_command'],
                            config["spec"]["template"]["spec"]["containers"][0]["command"][-1]
                        )
                        print(
                            f"Command overriden by hparam: {config_kwargs['dev_command']}")
                    command = config["spec"]["template"]["spec"]["containers"][0]["command"][-1].strip()

                    if "source startup.sh;" in command:
                        original_command = original_command[original_command.index(
                            "source startup.sh;"):]
                        command = command[command.index("source startup.sh;"):]

                    if "run_mode" in hparam_dict and "dev" in hparam_dict["run_mode"] and "dev_command" in config_kwargs:
                        print(f"Generated kube config {json.dumps(hparam_dict, indent=4)} ... \n"
                              f"\nDEV command: \n```\n{command}\n```"
                              f"\nORIGINAL command: \n```\n{original_command}\n```\nand saved to build/{name}.yaml")
                    else:
                        print(
                            f"Generated kube config {json.dumps(hparam_dict, indent=4)} ... \n```\n{command}\n```")

                    name = config["metadata"]["name"]
                    yaml.Dumper.ignore_aliases = lambda *_: True
                    if not os.path.exists("build"):
                        os.makedirs("build")
                    with open(f"build/{name}.yaml", "w") as f:
                        yaml.dump(config, f)
                    if mode == "job":
                        status = check_job_status(name)

                        if status == "succeeded" or status == "running":
                            print(
                                f"Job '{name}' is already {status}. Doing nothing.")
                        elif status == "failed":
                            print(
                                f"Job '{name}' has failed. Deleting the job.")
                            delete_job(name)
                            print(f"Creating job '{name}'.")
                            create_job(name)
                        elif status == "not_found":
                            print(f"Job '{name}' not found. Creating the job.")
                            create_job(name)


if __name__ == "__main__":
    pass
