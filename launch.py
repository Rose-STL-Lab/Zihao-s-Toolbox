from toolbox.kubeutils import create_config, batch
from toolbox.utils import load_env_file
import yaml
import argparse
import os


if __name__ == '__main__':
    
    arg = argparse.ArgumentParser()
    arg.add_argument("--mode", type=str, default="job")
    config = arg.parse_args()
    
    with open("config/launch.yaml", "r") as f:
        settings = yaml.safe_load(f)
        
    if config.mode == "pod":
        name = "interactive-pod"
        config = create_config(
            name=name,
            command="",
            interactive=True,
            env=load_env_file(),
            **settings
        )
        yaml.Dumper.ignore_aliases = lambda *args : True
        with open(f"build/{name}.yaml", "w") as f:
            yaml.dump(config, f)
        os.system(f"kubectl apply -f build/{name}.yaml")
    else:
        if 'run' in settings:
            run_configs = settings['run']
        else:
            run_configs = {
                "model": list(settings['model'].keys()),
                "dataset": list(settings['dataset'].keys()),
            }
        
        batch(
            run_configs=run_configs,
            dataset_configs=settings['dataset'],
            model_configs=settings['model'],
            env=load_env_file(),
            mode=config.mode,
            **settings
        )
