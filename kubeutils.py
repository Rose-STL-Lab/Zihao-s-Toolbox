import yaml
import os
import copy
import itertools
import subprocess
import json
from copy import deepcopy
import inspect
from typing import List, Dict, Any, get_type_hints
import os
import base64
import sys
import re
import platform
import hashlib
from .utils import CustomLogger


with open("config/kube.yaml", "r") as f:
    settings = yaml.safe_load(f)

logger = CustomLogger()


def merge_lists(*lists):
    from collections import defaultdict, deque

    # Step 1: Create a graph to represent dependencies
    graph = defaultdict(set)
    indegree = defaultdict(int)
    all_elements = set()

    for lst in lists:
        for i in range(len(lst)):
            all_elements.add(lst[i])
            if i > 0:
                if lst[i] not in graph[lst[i - 1]]:
                    graph[lst[i - 1]].add(lst[i])
                    indegree[lst[i]] += 1

    # Step 2: Topological Sort using Kahn's Algorithm
    zero_indegree = deque([elem for elem in all_elements if indegree[elem] == 0])
    result = []

    while zero_indegree:
        current = zero_indegree.popleft()
        result.append(current)
        for neighbor in graph[current]:
            indegree[neighbor] -= 1
            if indegree[neighbor] == 0:
                zero_indegree.append(neighbor)

    return result


def get_leading_int(string):
    match = re.match(r'^(\d+)', string)
    if match:
        return int(match.group(1))
    else:
        return None
    

def init_helper(current, key, settings, default):
    if current is None:
        return default if (settings is None or key not in settings or settings[key] is None) else settings[key]
    else:
        return current
    
    
def update_helper(config, key, dest_config):
    """
    Copies the config key to the new config
    if the config exists and the key is present
    """
    if config is not None and key in config and config[key] is not None:
        dest_config.update(config[key])


def markdown_link_handler(command, return_type):
    result = ""
    i = 0
    while i < len(command):
        if command[i] == '[':
            j = i + 1
            bracket_count = 1
            while j < len(command):
                if command[j] == '[':
                    bracket_count += 1
                elif command[j] == ']':
                    bracket_count -= 1
                    if bracket_count == 0:
                        break
                j += 1
            if j + 1 < len(command) and command[j + 1] == '(':
                k = j + 2
                paren_count = 1
                while k < len(command):
                    if command[k] == '(':
                        paren_count += 1
                    elif command[k] == ')':
                        paren_count -= 1
                        if paren_count == 0:
                            if return_type == 2:
                                result += command[j + 2:k]
                            else:
                                result += command[i + 1:j]
                            i = k + 1
                            break
                    k += 1
                else:
                    result += command[i:j + 1]
                    i = j + 1
            else:
                result += command[i:j + 1]
                i = j + 1
        else:
            result += command[i]
            i += 1
    return result


def is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


def normalize(s):
    if type(s) is not str:
        s = str(s)
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
        if '.env' in file_path:
            # Remove CUDA_VISIBLE_DEVICES from .env file
            file_content = re.sub(b'^CUDA_VISIBLE_DEVICES=.*\n', b'', file_content, flags=re.MULTILINE)
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
        logger.error(f"Could not read file {file_path}: {e}")
        return True


# Create script to copy files
def file_to_script(file):
    file_copy_script = []
    for f in file:
        normalized_path = os.path.normpath(f)
        if not os.path.exists(normalized_path):
            logger.error(f"File or directory {normalized_path} does not exist. Quitting...")
            sys.exit(1)

        if os.path.isdir(normalized_path):
            for root, _, files in os.walk(normalized_path):
                for file_name in files:
                    file_path = os.path.join(root, file_name)
                    if is_binary_file(file_path):
                        logger.warning(f"Skipping binary file: {file_path}")
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
                logger.warning(f"Skipping binary file: {normalized_path}")
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


def deploy_job(name, overwrite=False):
    status = check_job_status(name)

    if (status == "succeeded" or status == "running") and not overwrite:
        logger.info(f"Job '{name}' is already {status}. Doing nothing.")
    elif status == "failed":
        logger.info(f"Job '{name}' has failed. Deleting the job.")
        delete_job(name)
        logger.info(f"Creating job '{name}'.")
        create_job(name)
    elif status == "not_found":
        logger.info(f"Job '{name}' not found. Creating the job.")
        create_job(name)
    elif overwrite:
        logger.info(f"Job is already {status}, overwriting...")
        delete_job(name)
        logger.info(f"Creating job '{name}'.")
        create_job(name)
        
        
def validate(command):
    # Split the command into individual words
    words = command.split()

    # Initialize variables to track the presence of 'make' or 'python'
    command_found = False
    start_idx = 0

    # Iterate through each word in the command
    for i, word in enumerate(words):
        # Index in the original command
        idx = command.find(word, sum(len(w) + 1 for w in words[:i]))
        if 'python' in word or 'make' in word:
            # If 'make' or 'python' was found previously without ';' or '&&' in between
            if command_found:
                end_idx = idx + len(word)
                logger.critical("You may have forgotten to separate different lines of commands with ; or &&: "
                                f"... {command[start_idx:end_idx]} ...")
                return
            command_found = True
            start_idx = idx
        elif ';' in word or '&' in word:
            # Reset the flag when ';' or '&' is encountered
            command_found = False
       
            
def build_and_create_shared_jobs(shared_pool, project_name, mode, overwrite):
    """
    Build and create shared jobs from the given shared pool configurations.

    This function processes a dictionary of shared job configurations, merges them based on shared resources,
    and writes the merged configurations to YAML files. It also logs the operations and deploys the jobs if required.

    Args:
        shared_pool (dict): A dictionary containing the shared job configurations.
        project_name (str): The name of the project.
        mode (str): The mode of operation, job or dryrun.
        overwrite (bool): Whether to overwrite existing jobs.
    """
    AGG = {"cpu": sum, "memory": max, "ephemeral-storage": sum}
    UNIT = {"cpu": "", "memory": "Gi", "ephemeral-storage": "Gi"}
    
    if shared_pool:
        for key, shared_configs in shared_pool.items():
            to_merge = []
            total = 0
            while shared_configs:
                shared_config = shared_configs.pop()
                to_merge.append(shared_config)
                total += shared_config['shared']
                
                if not shared_configs or total + shared_configs[-1]['shared'] > 1.0:
                    prefix = (shared_config['prefix'] + '-') if shared_config['prefix'] != '' else ''
                    merge_name = f"{prefix}{project_name}-shared"
                    log = "Jobs "
                    
                    merge_cmd = ""
                    echo_cmd = ""
                    
                    total_resources = {
                        'limits': {rname: 0 for rname in AGG},
                        'requests': {rname: 0 for rname in AGG}
                    }
                    for i, shared_config in enumerate(to_merge):
                        name = shared_config['name']
                        shared = shared_config['shared']
                        config = shared_config['config']
                        
                        merge_name += "-" + name[-5:]
                        log += f"{name}[{shared}], "
                        cmds = config["spec"]["template"]["spec"]["containers"][0]["command"]
                        env = cmds[3]  # conda run -n {env}
                        cmd = cmds[-1]
                        if "source startup.sh;" in cmd:
                            split_pattern = "source startup.sh;"
                            idx = cmd.index(split_pattern) + len(split_pattern)
                            startup_cmd = cmd[:idx]
                            cmd = cmd[idx:].strip()
                            cmd = f'#!/bin/bash\n{cmd}'
                            file_encoding = base64.b64encode(bytes(cmd, 'utf-8')).decode('utf-8')
                            echo_cmd += f"echo {file_encoding} | base64 -d > {name}.sh && chmod +x {name}.sh && "
                        if i == 0:
                            merge_cmd += startup_cmd + f" parallel --line-buffer --jobs {len(to_merge)} --tag :::"
                        sleep_time = i * 10
                        merge_cmd += f" \"sleep {sleep_time} && conda run -n {env} /bin/bash `pwd`/{name}.sh\""

                        # GPU container's resources 
                        resources = config["spec"]["template"]["spec"]["containers"][0]["resources"]
                            
                        for lr in ["limits", "requests"]:
                            for rname, agg in AGG.items():
                                total_resources[lr][rname] = agg([
                                    total_resources[lr][rname], 
                                    get_leading_int(resources[lr][rname])
                                ])
                            
                    config["metadata"]["name"] = merge_name
                    config["spec"]["template"]["spec"]["containers"][0]["command"] = [
                        "/bin/bash",
                        "-c",
                        echo_cmd + merge_cmd
                    ]
                    
                    for lr in ["limits", "requests"]:
                        for rname, unit in UNIT.items():
                            resources[lr][rname] = f"{total_resources[lr][rname]}{unit}"
                        
                    to_merge = []
                    total = 0
                    
                    with open(f"build/{merge_name}.yaml", "w") as f:
                        yaml.dump(config, f, indent=2, width=float("inf"))
                        log = log[:-2] + f" are merged into {merge_name} and saved to build/{merge_name}.yaml."
                        logger.debug(log)
                    if mode == "job":
                        deploy_job(merge_name, overwrite)
                        
                        
def update_env(env):
    """
    Update the environment variables with the necessary variables for the job.
    """
    if "PYTHONPATH" not in env:
        env["PYTHONPATH"] = "src"
    elif "src" not in env["PYTHONPATH"].split(":"):
        env["PYTHONPATH"] += ":src"
    if "WANDB_MODE" in env:
        env["WANDB_MODE"] = "online"  # Always use online mode in the cluster
    if "CUDA_VISIBLE_DEVICES" in env:
        del env["CUDA_VISIBLE_DEVICES"]  # Always use all GPUs in the cluster
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
    return env
    

def create_config(
    # Pod config
    name: str,
    command: str,
    gpu_count: int = 0,
    cpu_count: int = 5,
    ephemeral_storage: int = 100,
    memory: int = 32,
    env: dict = {},
    project_name: str = None,
    conda_env_name: str = None,
    interactive: bool = False,
    server_command: str = "sleep infinity",
    startup_script: str = None,
    extra_startup_script: str = None,
    registry_host: str = None,
    ssh_host: str = None,
    ssh_port: int = None,
    tolerations: List[str] = None,
    volumes: dict[str, str] = None,
    shared: float = 1.0,

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
    
    # Extra background server for the command
    server: Dict[str, Any] = {},

    # Omit undefined kwargs
    **ignored
):
    # Prevent sleep infinity in job
    assert startup_script is None or "sleep infinity" not in startup_script
    assert "sleep infinity" not in command

    for key, value in ignored.items():
        if key != "hparam":
            logger.warning(f"Key {key}={value} is unknown. Ignoring it.")

    # Required entries
    user = settings["user"]
    namespace = settings["namespace"]
    project_name = settings["project_name"]
    
    prefix = init_helper(prefix, "prefix", settings, settings["user"])
    gitlab_user = init_helper(gitlab_user, "gitlab_user", settings, user)
    conda_env_name = init_helper(conda_env_name, "conda_env_name", settings, project_name)
    registry_host = init_helper(registry_host, "registry_host", settings, "gitlab-registry.nrp-nautilus.io")
    image = init_helper(image, "image", settings, f"{registry_host}/{gitlab_user}/{project_name}:latest")
    image_pull_secrets = init_helper(image_pull_secrets, "image_pull_secrets", settings, f"{project_name}-read-registry")
    hostname_blacklist = init_helper(hostname_blacklist, "hostname_blacklist", settings, None)
    hostname_whitelist = init_helper(hostname_whitelist, "hostname_whitelist", settings, None)
    special_gpu = init_helper(special_gpu, "special_gpu", settings, None)
    if special_gpu is not None:
        gpu_blacklist = init_helper(gpu_blacklist, "gpu_blacklist", settings, None)
        gpu_whitelist = init_helper(gpu_whitelist, "gpu_whitelist", settings, None)
    ssh_port = init_helper(ssh_port, "ssh_port", settings, "30622")
    ssh_host = init_helper(ssh_host, "ssh_host", settings, "gitlab-ssh.nrp-nautilus.io")
    conda_home = init_helper(None, "conda_home", settings, "/opt/conda")
    conda_env_path = f"{conda_home}/envs/{conda_env_name}" if conda_env_name != "base" else f"{conda_home}"
    startup_script = init_helper(startup_script, "startup_script", settings, f"""#!/bin/bash
mkdir -p config
git pull
git submodule update --init --recursive
echo "conda activate {conda_env_name}; " >> ~/.bashrc
export PATH="{conda_env_path}/bin/:$PATH"
echo 'if [ -f "$HOME/src/toolbox/s3region.sh" ]; then source "$HOME/src/tool outbox/s3region.sh"; fi' >> ~/.bashrc
if [ -f src/toolbox/s3region.sh ]; then
    chmod +x src/toolbox/s3region.sh
    source src/toolbox/s3region.sh
fi
""")
    extra_startup_script = init_helper(extra_startup_script, "extra_startup_script", settings, None)
    if extra_startup_script is not None:
        startup_script += extra_startup_script
        if not extra_startup_script.endswith("\n"):
            startup_script += "\n"
    file = init_helper(file, "file", settings, [])
    if '.env' not in file:
        file.append('.env')
    if 'config/kube.yaml' not in file:
        file.append('config/kube.yaml')
    if 'config/launch.yaml' not in file:
        file.append('config/launch.yaml')
    startup_script += "\n".join(file_to_script(file))
    
    # Save startup script to build/
    with open(f"build/{name}.sh", "w") as f:
        f.write(startup_script)
    startup_encoding = base64.b64encode(
        bytes(startup_script, 'utf-8')).decode('utf-8')
    load_startup_script = f"echo {startup_encoding} | base64 -d > startup.sh && chmod +x startup.sh && source startup.sh; "

    tolerations = init_helper(tolerations, "tolerations", settings, [])
    volumes = init_helper(volumes, "volumes", settings, {})
    env = update_env(env)
    
    metadata = {
        "namespace": namespace,
        "labels": {"user": user, "project": project_name}
    }
    
    # Handle syntax sugar for command
    command = re.sub(r'##(.*?)##', '', command)
    command = markdown_link_handler(command, 2).strip()
    
    gpu_container = {
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
                if interactive else (load_startup_script + command)).replace("\n", " ").strip()
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
                **({"ephemeral-storage": f"{ephemeral_storage}G"} if ephemeral_storage != 0 else {})
            },
            "requests": {
                **(
                    {"nvidia.com/gpu": str(gpu_count)} 
                    if special_gpu is None 
                    else {f"nvidia.com/{special_gpu}": str(gpu_count)}
                ),
                "memory": f"{memory}G",
                "cpu": str(cpu_count),
                **({"ephemeral-storage": f"{ephemeral_storage}G"} if ephemeral_storage != 0 else {})
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
    
    # Extra server container
    base_volumes = [
        {
            "name": "dshm",
            "emptyDir": {"medium": "Memory"}
        }
    ]
    server_containers = []
    if server is not None:
        for server_name, server_config in server.items():
            server_name = normalize(server_name)
            server_container = deepcopy(gpu_container)
            server_container["command"] = [
                "conda",
                "run",
                "-n",
                conda_env_name,
                "/bin/bash",
                "-c",
                (load_startup_script + server_config['command']).replace("\n", " ").strip()
            ]
            server_container["name"] = server_name
            memory = server_config.get("memory", 32)
            cpu_count = server_config.get("cpu_count", 5)
            gpu_count = server_config.get("gpu_count", 0)
            ephemeral_storage = server_config.get("ephemeral_storage", 100)
            server_container["resources"]["limits"] = {
                "memory": f"{int(memory * 1.2)}G",
                "cpu": str(int(cpu_count * 1.2)),
                "nvidia.com/gpu": str(gpu_count),
                **({"ephemeral-storage": f"{ephemeral_storage}G"} if ephemeral_storage != 0 else {})
            }
            server_container["resources"]["requests"] = {
                "memory": f"{memory}G",
                "cpu": str(cpu_count),
                "nvidia.com/gpu": str(gpu_count),
                **({"ephemeral-storage": f"{ephemeral_storage}G"} if ephemeral_storage != 0 else {})
            }
            server_container["ports"] = [
                {"containerPort": int(server_config["port"]), "name": server_name}
            ]
            for volume_name, volume_path in server_config.get("volumes", {}).items():
                server_container["volumeMounts"].append(
                    {"mountPath": volume_path, "name": volume_name}
                )
                gpu_container["volumeMounts"].append(
                    {"mountPath": volume_path, "name": volume_name}
                )
                base_volumes.append(
                    {
                        "name": volume_name,
                        "emptyDir": {}
                    }
                )
            server_containers.append(server_container)

    template = {
        "containers": [
            gpu_container,
            *server_containers
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
        "volumes": base_volumes + [
            {
                "name": volume,
                "persistentVolumeClaim": {"claimName": volume}
            }
            for volume in volumes
        ]
    }

    # If affinity is empty
    if (
        len(
            template["affinity"]["nodeAffinity"][
                "requiredDuringSchedulingIgnoredDuringExecution"
            ]["nodeSelectorTerms"]
        ) == 1
        and len(
            template["affinity"]["nodeAffinity"][
                "requiredDuringSchedulingIgnoredDuringExecution"
            ]["nodeSelectorTerms"][0]["matchExpressions"]
        ) == 0
    ):
        del template["affinity"]

    if interactive:
        gpu_limit = 2
        memory_limit = 32
        cpu_limit = 16
        # Suppress resource to be under the total limit
        total_gpu = sum(int(container["resources"]["limits"].get("nvidia.com/gpu", 0)) for container in template["containers"])
        total_memory = sum(int(get_leading_int(container["resources"]["limits"].get("memory", "0Gi"))) for container in template["containers"])
        total_cpu = sum(float(container["resources"]["limits"].get("cpu", 0)) for container in template["containers"])

        if total_gpu > gpu_limit or total_memory > memory_limit or total_cpu > cpu_limit:
            gpu_ratio = gpu_limit / total_gpu if total_gpu > gpu_limit else 1
            memory_ratio = memory_limit / total_memory if total_memory > memory_limit else 1
            cpu_ratio = cpu_limit / total_cpu if total_cpu > cpu_limit else 1

            for container in template["containers"]:
                for entry in ["limits", "requests"]:
                    if "nvidia.com/gpu" in container["resources"][entry]:
                        container["resources"][entry]["nvidia.com/gpu"] = str(int(int(container["resources"][entry]["nvidia.com/gpu"]) * gpu_ratio))
                    if "memory" in container["resources"][entry]:
                        memory = int(get_leading_int(container["resources"][entry]["memory"]))
                        memory_ = int(memory * memory_ratio)
                        if memory_ == 0:
                            memory_ = 1
                        container["resources"][entry]["memory"] = f"{memory_}Gi"
                    if "cpu" in container["resources"][entry]:
                        container["resources"][entry]["cpu"] = str(float(container["resources"][entry]["cpu"]) * cpu_ratio)

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
    overwrite: bool = False,
    **kwargs
):
    """
    mode: str
        mode=job:          Create jobs in the Kubernetes cluster
        mode=local:        Runs jobs locally
        mode=dryrun:       Only creates the job files without deploying them
        mode=local-first:  Runs the first job locally
        mode=local-dryrun: Only prints the local commands without running them
    """
    # Initialization
    if project_name is None:
        project_name = settings["project_name"]

    assert mode in ["job", "local", "dryrun", "local-dryrun", "local-first", "pod-dryrun"]

    if "hparam" in run_configs:
        for key, val in run_configs["hparam"].items():
            if type(val) is str:
                run_configs["hparam"][key] = [val]
                
    shared_pool = {}  # Pool for shared GPU configs
    
    for dataset in run_configs["dataset"]:
        for model in run_configs["model"]:
            hparam = {}
            update_helper(dataset_configs[dataset], "hparam", hparam)
            update_helper(model_configs[model], "hparam", hparam)

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
                    if len(name) + 5 + len(hash_object.hexdigest()[:5]) > 63:
                        name = name[:63 - 5 - len(hash_object.hexdigest()[:5])].lower()
                    name += '-' + hash_object.hexdigest()[:5]

                    if "hparam" in run_configs and "hparam" in config:
                        del config["hparam"]

                    config_kwargs = deepcopy(kwargs)
                    for key in ["model", "dataset", "hparam"]:  # Remove runwise keys
                        if key in config_kwargs:
                            del config_kwargs[key]
                            
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
                            logger.warning(f"Key {key}={config_kwargs[key]} is not allowed in {name}. Ignoring it.")
                            del config_kwargs[key]

                    # Remove comments between ## and ##
                    model_configs[model]['command'] = re.sub(r'##(.*?)##', '', model_configs[model]['command'])
                    if "local" in mode:
                        if "local_command" in config_kwargs:
                            model_configs[model]['command'] = model_configs[model]['local_command']
                        cmd = fill_val({'_': model_configs[model]['command']}, hparam_dict)[0][0]['_']
                        if "NODE_NAME" in os.environ:
                            # make local inside the node
                            cmd = markdown_link_handler(cmd, 2).strip()
                        else:
                            cmd = markdown_link_handler(cmd, 1).strip()
                        
                        system_type = platform.system()
                        if system_type == 'Linux':
                            cmd = 'export $(grep -v \'^#\' .env | xargs -d \'\\n\') && ' + cmd
                        elif system_type in ['Darwin', 'FreeBSD']:
                            cmd = 'export $(grep -v \'^#\' .env | xargs -0) && ' + cmd
                        else:
                            raise Exception("Unsupported OS")
                        if mode == "local":
                            logger.info(f"Running {json.dumps(hparam_dict, indent=2)} ... \n```\n{cmd}\n```")
                            validate(cmd)
                            os.system(cmd)
                            continue
                        elif mode == "local-first":
                            logger.info(f"Running {json.dumps(hparam_dict, indent=2)} ... \n```\n{cmd}\n```")
                            validate(cmd)
                            os.system(cmd)
                            return
                        else:
                            assert mode == "local-dryrun", "Invalid mode"
                            # Not using logger for redirection
                            print(f"{name}: {cmd}")
                            continue

                    if "local_command" in config_kwargs:
                        del config_kwargs["local_command"]

                    hparam_dict = {k[1:] if k.startswith(
                        "_") else k: v for k, v in hparam_dict.items()}
                    
                    def override_helper(hparam, key, value_type, dest_config):
                        if key in hparam and hparam(key) is not None:
                            if value_type is None:
                                dest_config[key] = hparam(key)
                            elif value_type is list or value_type is List[str] or value_type is List:
                                if type(hparam(key)) is str:
                                    dest_config[key] = [hparam(key)]
                                else:
                                    dest_config[key] = hparam(key)
                            else:
                                dest_config[key] = value_type(hparam(key))
                            logger.debug(f"{key} overriden by hparam: {hparam(key)}")
                    
                    create_config_signature = inspect.signature(create_config)
                    
                    # Override the k8s config with hparam
                    for param_name, param_type in create_config_signature.parameters.items():
                        override_helper(hparam_dict, param_name, param_type.annotation, config_kwargs)
                        
                    if "shared" in config_kwargs:
                        shared = config_kwargs['shared']
                    elif "shared" in config:
                        shared = config['shared']
                    else:
                        shared = 1.0

                    config = create_config(
                        name=name,
                        project_name=project_name,
                        **config_kwargs
                    )

                    cmd = config["spec"]["template"]["spec"]["containers"][0]["command"][-1].strip()

                    if "source startup.sh;" in cmd:
                        cmd = cmd[cmd.index("source startup.sh;"):]
                    logger.info(f"Generated kube config {json.dumps(hparam_dict, indent=2)} ... ")
                    logger.debug(f"```\n{cmd}\n```\nand saved to build/{name}.yaml")
                    validate(cmd)

                    name = config["metadata"]["name"]
                    yaml.Dumper.ignore_aliases = lambda *_: True
                    if not os.path.exists("build"):
                        os.makedirs("build")
                    with open(f"build/{name}.yaml", "w") as f:
                        yaml.dump(config, f, indent=2, width=float("inf"))
                    
                    # For two jobs to share the same node, they must have same
                    # GPU count, ephermeral storage, volume, affinity, prefix, and tolerations
                    shared_metrics = [
                        "gpu_count",
                        "volumes",
                        "special_gpu",
                        "gpu_whitelist",
                        "gpu_blacklist",
                        "hostname_whitelist",
                        "hostname_blacklist",
                        "tolerations",
                        "prefix"
                    ]
                    
                    key = json.dumps({
                        k: v for k, v in config_kwargs.items() if k in shared_metrics
                    }, sort_keys=True)
                    
                    if 'prefix' not in config_kwargs:
                        prefix = settings['user']
                    else:
                        prefix = config_kwargs['prefix']
                    
                    if shared < 1.0:
                        if key not in shared_pool:
                            shared_pool[key] = []
                        shared_pool[key].append({
                            'name': name, 
                            'config': config, 
                            'shared': shared, 
                            'prefix': prefix
                        })
                    else:
                        if mode == "job":
                            deploy_job(name, overwrite)
    
    build_and_create_shared_jobs(shared_pool, project_name, mode, overwrite)


if __name__ == "__main__":
    pass
