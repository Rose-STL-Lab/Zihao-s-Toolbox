import json
import subprocess
import os
import re
from argparse import ArgumentParser


def extract_and_clean_python_command(s):
    # Step 1: Split into lines and prepare to process
    lines = re.split(r'\n|&&|;', s)
    python_line = ""
    capturing = False

    # Step 2 & 3: Loop over lines to find the line with 'python' and handle line continuations
    for line in lines:
        current_line = line.strip()
        if capturing or 'python' in current_line:
            # Start capturing if 'python' is found
            capturing = True
            python_line += current_line
            # If the line ends with a backslash, it's continued, so remove the backslash and continue appending
            if python_line.endswith('\\'):
                python_line = python_line[:-1] + ' '  # Remove backslash and continue
            else:
                # No continuation backslash; Python command is fully captured
                break

    # Step 4: Clean up the command
    # Removing leading settings such as 'VAR=value' or 'conda run'
    parts = python_line.split()
    for i, part in enumerate(parts):
        if 'python' in part:
            python_line = ' '.join(parts[i + 1:])
            break

    return python_line


def extract_command(target):
    try:
        if target == 'local-dryrun':
            command = ['make', target]
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            rtn = result.stdout
        else:
            command = ['make', '-n', target]
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            rtn = extract_and_clean_python_command(result.stdout)
        return rtn
    except subprocess.CalledProcessError as e:
        print("An error occurred while executing make")
        print(e.stderr)


def parse_python_command(command):
    # Remove the '@$(PYTHON)' placeholder and strip leading/trailing spaces
    command = command.replace('@$(PYTHON)', '').strip()
    
    # Split the command by spaces considering quoted arguments
    parts = []
    accumulator = []
    in_quotes = False
    for char in command:
        if char == ' ' and not in_quotes:
            if accumulator:
                parts.append(''.join(accumulator))
                accumulator = []
        elif char in "\"'":
            in_quotes = not in_quotes
        else:
            accumulator.append(char)
    
    if accumulator:
        parts.append(''.join(accumulator))

    # Remove all parts before last python / python3
    last_python_index = None
    for i, part in enumerate(parts):
        if part in ["python", "python3"] and parts[i + 1].endswith(".py"):
            last_python_index = i

    if last_python_index is not None:
        parts = parts[last_python_index + 1:]
        
    # Remove all parts after last new line
    for i, part in enumerate(parts):
        if '\n' in part:
            last = part.split('\n')[0]
            parts = parts[:i]
            parts.append(last)
            break

    program = parts[0]
    args = parts[1:]
    
    return program, args


def create_launch_json(target, program, args):
    configuration = {
        "name": target,
        "type": "debugpy",
        "request": "launch",
        "program": program,
        "args": args,
        "console": "integratedTerminal",
        "envFile": "${workspaceFolder}/.env",
        "env": {
            "WANDB_MODE": "offline"
        }
    }
    return configuration


def add_command_to_launch_json(target, command, overwrite=False):
    program, args = parse_python_command(command)
    launch_configuration = create_launch_json(target, program, args)
    config = json.dumps(launch_configuration, indent=4)

    if os.path.exists('.vscode/launch.json'):
        with open('.vscode/launch.json', 'r') as f:
            s = f.read()
            s = re.sub(r'//.*', '', s)
            data = json.loads(s)
            
            # Check if a configuration with the same name already exists
            for i, config in enumerate(data['configurations']):
                if config['name'] == target:
                    if overwrite:
                        # Overwrite the existing configuration
                        data['configurations'][i] = launch_configuration
                        with open('.vscode/launch.json', 'w') as f:
                            json.dump(data, f, indent=4)
                            print(f"Configuration '{target}' overwritten in launch.json")
                    else:
                        print(f"Configuration '{target}' already exists")
                    break
            else:
                # If no existing configuration found, append the new configuration
                data['configurations'].append(launch_configuration)
                with open('.vscode/launch.json', 'w') as f:
                    json.dump(data, f, indent=4)
                    print(f"Configuration '{target}' added to launch.json")
    else:
        # If `.vscode/launch.json` doesn't exist, create a new file with the configuration
        data = {
            "version": "0.2.0",
            "configurations": [launch_configuration]
        }
        os.makedirs('.vscode', exist_ok=True)
        with open('.vscode/launch.json', 'w') as f:
            json.dump(data, f, indent=4)
            print(f"Configuration '{target}' added to launch.json")


def debug_target(target, overwrite=False):
    command = extract_command(target)
    if command:
        add_command_to_launch_json(target, command, overwrite)
    else:
        print(f"Target '{target}' not found")


def debug_launch():
    commands = extract_command('local-dryrun')
    lines = [line for line in commands.split('\n') if ':' in line]
    command_dicts = {
        key.strip(): value.strip() for key, value in [line.split(':', 1) for line in lines]
    }
    command_dicts = {
        key: extract_and_clean_python_command(value) for key, value in command_dicts.items() if 'python' in value
    }
    # Move existing `launch.json`, if any, to `launch.json.bak`
    if os.path.exists('.vscode/launch.json'):
        print("Backing up existing launch.json to launch.json.bak ...")
        os.rename('.vscode/launch.json', '.vscode/launch.json.bak')
    empty_config = {"version": "0.2.0", "configurations": []}
    with open('.vscode/launch.json', 'w') as f:
        json.dump(empty_config, f, indent=4)
    for target, command in command_dicts.items():
        add_command_to_launch_json(target, command)


if __name__ == "__main__":
    argparser = ArgumentParser()
    argparser.add_argument('target', help='The target to extract the command from')
    argparser.add_argument('overwrite', help='Overwrite existing target')
        
    args = argparser.parse_args()
    args.overwrite = args.overwrite.lower() == 'true'
    
    if args.target == 'launch.yaml':
        debug_launch()
    else:
        debug_target(args.target, args.overwrite)
