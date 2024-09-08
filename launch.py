from toolbox.kubeutils import create_config, batch, settings, file_to_script
from toolbox.utils import load_env_file, CustomLogger
import yaml
import argparse
import os
import inspect
from typing import get_type_hints, get_origin, get_args, Dict, List, Any, Union
import subprocess
from copy import deepcopy


logger = CustomLogger()


def is_generic_type(tp):
    """Check if the type is a generic type from the `typing` module."""
    return get_origin(tp) is not None


def modify_pod_name(pod_name):
    """Modify the pod name by incrementing a numeric suffix."""
    if '-' in pod_name:
        base_name, number = pod_name.rsplit('-', 1)
        if number.isdigit():
            return f"{base_name}-{int(number) + 1}"
    return f"{pod_name}-1"  # Default case if no numeric suffix exists


def convert_to_string(data):
    if isinstance(data, dict):
        exception_keys = ['gpu_count', 'cpu_count', 'ephemeral_storage', 'memory', 'ssh_port', 'shared']
        return {k: (v if k in exception_keys else convert_to_string(v)) for k, v in data.items()}
    elif isinstance(data, list):
        return [convert_to_string(item) for item in data]
    elif isinstance(data, (int, float)):
        return str(data)
    else:
        return data


def check_type(key, value, expected_type):
    """Check if the value is of the expected type."""
    # If the expected type is Any, all values are acceptable.
    if expected_type is Any:
        return

    # Check if we're dealing with a Union type.
    if get_origin(expected_type) is Union:
        # Iterate over the types in the Union and pass if any type matches.
        for type_arg in get_args(expected_type):
            try:
                check_type(key, value, type_arg)
                return  # If no exception was raised, the type check passed.
            except TypeError:
                continue
        # If none of the types matched, raise a TypeError.
        valid_types = [t for t in get_args(expected_type)]
        raise TypeError(f"Key '{key}' is expected to be one of the types {valid_types}, "
                        f"but got {type(value).__name__}: {value}")

    if is_generic_type(expected_type):
        origin_type = get_origin(expected_type)
        if origin_type is list:
            if not isinstance(value, list):
                raise TypeError(f"Key '{key}' is expected to be a list, but got {type(value).__name__}")
            res = get_args(expected_type)
            if len(res) == 1:
                expected_element_type = res[0]
                for item in value:
                    check_type(f"{key} element", item, expected_element_type)
        elif origin_type is dict:
            if not isinstance(value, dict):
                raise TypeError(f"Key '{key}' is expected to be a dict, but got {type(value).__name__}")
            res = get_args(expected_type)
            if len(res) == 2:
                expected_key_type, expected_value_type = res
                for k, v in value.items():
                    check_type(f"{key} key", k, expected_key_type)
                    check_type(f"{key}[{k}]", v, expected_value_type)
        else:
            raise TypeError(f"Unsupported generic type: {origin_type}")
    else:
        if not isinstance(value, expected_type):
            raise TypeError(f"Key '{key}' is expected to be of type {expected_type.__name__}, "
                            f"but got {type(value).__name__}: {value}")


def check_key(key, container, expected_type, required=True, header=""):
    if key is None:
        if not isinstance(container, dict):
            raise TypeError(f"[{header}] Model must be a dictionary, but got {type(container).__name__}: {container}")
        for k in container:
            if not isinstance(k, str):
                raise TypeError(f"[{header}] Model keys must be strings, but got {type(k).__name__}: {k}")
            check_type(k, container[k], expected_type)
    else:
        if required and (container is None or key not in container):
            raise ValueError(f"[{header}] Missing required key: {key}")
        if key in container:
            value = container[key]
            if value is None:  # Allow None values if they are acceptable
                return
            check_type(key, value, expected_type)


def validate_launch_settings(launch_settings, create_config_signature):
    # Check if 'model' key exists and is a dict
    check_key('model', launch_settings, dict)
    
    for name, info in {
        'model': {
            'target': launch_settings['model'],
            'required': ['command'],
            'extra': {
                'hparam': Dict[str, Union[str, List[str], Dict[str, Dict]]]
            }
        },
        'dataset': {
            'target': launch_settings['dataset'],
            'extra': {
                'hparam': Dict[str, Union[str, List[str], Dict[str, Dict]]]
            }
        },
        'global': {
            'target': {'launch': launch_settings},
            'extra': {
                'model': Dict[str, Any],
                'dataset': Dict[str, Any],
                'run': Union[Dict[str, Union[List[str], Dict[str, str], Dict[str, Union[str, List[str], Dict[str, Dict]]]]], 
                             List[Dict[str, Union[List[str], Dict[str, str], Dict[str, Union[str, List[str], Dict[str, Dict]]]]]]]
            }
        }
    }.items():
        target = info['target']
        required = info.get('required', [])
        extra = info.get('extra', {})

        for _, entry in target.items():
            # Check required inside each entry
            for key in required:
                check_key(key, entry, str, header=f'{name}, required')
            
            if entry is not None:
                for key in entry:
                    if key in extra:
                        check_key(key, entry, extra[key], header=f'{name}, extra')
                    elif key not in create_config_signature.parameters:
                        raise ValueError(f"Unknown key '{key}' in model configuration")
                    
                for param_name, param in create_config_signature.parameters.items():
                    if param_name in ['name', 'ignored']:
                        continue
                    # Determine the expected type from type hints
                    expected_type = type_hints.get(param_name, type(param.default))
                    # Check for the correct type if the key exists
                    if param_name in entry:
                        check_key(param_name, entry, expected_type, required=False, header=f'{name}, optional')


def check_pod_exists(pod_name, namespace):
    # Construct the command to get the specific pod by name
    cmd = [
        "kubectl", "get", "pod", pod_name, 
        "--namespace=" + namespace,
        "-o=json"
    ]

    # Execute the command
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    # Check if the command executed successfully
    if result.returncode == 0:
        # Successfully got data for pod, meaning pod exists
        return True
    elif "NotFound" in result.stderr:
        # Pod does not exist
        return False
    else:
        # An error occurred, which is not related to the non-existence of the pod
        raise Exception(f"Error querying kubectl: {result.stderr}")


if __name__ == '__main__':
    arg = argparse.ArgumentParser()
    arg.add_argument("--mode", type=str, default="job")
    arg.add_argument("--pod_name", type=str, default=None)
    arg.add_argument("--overwrite", type=str, default="False")
    args = arg.parse_args()
    
    if args.overwrite.lower() == "true":
        args.overwrite = True
    else:
        args.overwrite = False

    with open("config/launch.yaml", "r") as f:
        launch_settings = yaml.safe_load(f)
        create_config_signature = inspect.signature(create_config)
        type_hints = get_type_hints(create_config)
        if "dataset" not in launch_settings:
            launch_settings["dataset"] = {"": {}}
        
        # Convert all int and float in launch_settings to str, recursively
        launch_settings = convert_to_string(launch_settings)
        
        # Perform typechecks
        validate_launch_settings(launch_settings, create_config_signature)
        
        def validate_types(run_settings):
            for key in run_settings:
                if key not in ['model', 'dataset', 'hparam']:
                    raise ValueError(f"Unknown key '{key}' in run configuration")
                if 'model' in run_settings:
                    for model in run_settings['model']:
                        if model not in launch_settings['model']:
                            raise ValueError(f"Model '{run_settings['model']}' not found in model configuration") 
                if 'dataset' in run_settings:
                    for dataset in run_settings['dataset']:
                        if dataset not in launch_settings['dataset']:
                            raise ValueError(f"Dataset '{run_settings['dataset']}' not found in dataset configuration")
            
        if 'run' in launch_settings and launch_settings['run'] is not None:
            run_configs = launch_settings['run']
            if 'model' not in run_configs:
                if type(run_configs) is dict:
                    run_configs['model'] = list(launch_settings['model'].keys())
                else:
                    for run_config in run_configs:
                        if 'model' not in run_config:
                            run_config['model'] = list(launch_settings['model'].keys())
            if 'dataset' not in run_configs:
                if type(run_configs) is dict:
                    run_configs['dataset'] = list(launch_settings['dataset'].keys())
                else:
                    for run_config in run_configs:
                        if 'dataset' not in run_config:
                            run_config['dataset'] = list(launch_settings['dataset'].keys())
        else:
            run_configs = {
                "model": list(launch_settings['model'].keys()),
                "dataset": list(launch_settings['dataset'].keys()),
            }
        if type(run_configs) is dict:
            validate_types(run_configs)
        elif type(run_configs) is list:
            for run_config in run_configs:
                validate_types(run_config)

    mode = args.mode
    if "pod" in mode or mode == "copy_files":
        name = f"{settings['project_name']}-interactive-pod"
        
        if "model" in launch_settings:
            del launch_settings["model"]
        if "dataset" in launch_settings:
            del launch_settings["dataset"]
        if "run" in launch_settings:
            del launch_settings["run"]
            
        pod_settings = deepcopy(settings)
        pod_settings.update(launch_settings)
        
        config = create_config(
            name=name,
            command="",
            interactive=True,
            env=load_env_file(),
            **pod_settings
        )
        yaml.Dumper.ignore_aliases = lambda *_: True
        
        if args.pod_name is not None:
            pod_name = args.pod_name
        else:
            pod_name = config['metadata']['name']
            
        if mode == "copy_files":
            if check_pod_exists(pod_name, settings['namespace']):
                script = " && ".join(file_to_script(launch_settings['file']))
                command_to_run = f"kubectl exec -n {settings['namespace']} {pod_name} -- /bin/bash -c \"{script}\""
                # Execute the command using os.system
                if os.system(command_to_run) != 0:  # os.system returns 0 if successful
                    logger.error(f"Failed to copy files to pod {pod_name}.")
                else:
                    logger.info(f"Files copied successfully to {pod_name}: {launch_settings['file']}")
                    exit(0)
            else:
                raise ValueError("Cannot copy files without a pod.")
        
        elif "pod" in mode:
            # Handle pod creation
            while check_pod_exists(pod_name, settings['namespace']):
                logger.debug(f"Pod '{pod_name}' already exists. Modifying the name to avoid conflicts.")
                pod_name = modify_pod_name(pod_name)
            config['metadata']['name'] = pod_name
            with open(f"build/{name}.yaml", "w") as f:
                yaml.dump(config, f, indent=2, width=float("inf"))
            if mode == "pod":
                os.system(f"kubectl apply -f build/{name}.yaml")
            else:
                assert mode == "pod-dryrun", "Unrecognized mode"
                logger.info(f"Pod configuration written to build/{name}.yaml")
    else:
        if type(run_configs) is dict:
            batch(
                run_configs=run_configs,
                dataset_configs=launch_settings['dataset'],
                model_configs=launch_settings['model'],
                env=load_env_file(),
                mode=mode,
                overwrite=args.overwrite,
                **launch_settings
            )
        else:
            for run_config in run_configs:
                batch(
                    run_configs=run_config,
                    dataset_configs=launch_settings['dataset'],
                    model_configs=launch_settings['model'],
                    env=load_env_file(),
                    mode=mode,
                    overwrite=args.overwrite,
                    **launch_settings
                )
