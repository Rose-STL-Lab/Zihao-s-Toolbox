from toolbox.kubeutils import create_config, batch, settings
from toolbox.utils import load_env_file
import yaml
import argparse
import os


if __name__ == '__main__':
    
    arg = argparse.ArgumentParser()
    arg.add_argument("--mode", type=str, default="job")
    config = arg.parse_args()
    
    with open("config/launch.yaml", "r") as f:
        launch_settings = yaml.safe_load(f)
        if "dataset" not in launch_settings:
            launch_settings["dataset"] = {"": {}}
        assert "model" in launch_settings, "model is a required field in kube.yaml"
        for model in launch_settings["model"]:
            if launch_settings["model"][model] is None:
                launch_settings["model"][model] = {}
            if "command" not in launch_settings["model"][model]:
                launch_settings["model"][model]["command"] = ""
        
    if config.mode == "pod":
        name = f"{settings['user']}-{launch_settings['project_name']}-interactive-pod"
        config = create_config(
            name=name,
            command="",
            interactive=True,
            env=load_env_file(),
            **launch_settings
        )
        yaml.Dumper.ignore_aliases = lambda *args : True
        with open(f"build/{name}.yaml", "w") as f:
            yaml.dump(config, f)
        os.system(f"kubectl apply -f build/{name}.yaml")
    else:
        if 'run' in launch_settings:
            run_configs = launch_settings['run']
        else:
            run_configs = {
                "model": list(launch_settings['model'].keys()),
                "dataset": list(launch_settings['dataset'].keys()),
            }
        
        batch(
            run_configs=run_configs,
            dataset_configs=launch_settings['dataset'],
            model_configs=launch_settings['model'],
            env=load_env_file(),
            mode=config.mode,
            **launch_settings
        )
