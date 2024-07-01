import json
import subprocess
import os
import re
from argparse import ArgumentParser


def extract_and_clean_python_command(s):
    # Step 1: Split into lines and prepare to process
    lines = s.split('\n')
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


def main(target):
    command = extract_command(target)
    if command:
        program, args = parse_python_command(command)
        launch_configuration = create_launch_json(target, program, args)
        config = json.dumps(launch_configuration, indent=4)
        # Add the config to the `.vscode/launch.json` file, configurations section
        if os.path.exists('.vscode/launch.json'):
            # Append to the configurations section
            with open('.vscode/launch.json', 'r') as f:
                # Remove // comments first 
                s = f.read()
                s = re.sub(r'//.*', '', s)
                data = json.loads(s)
                
                # Make sure there is no existing section with the same name
                for config in data['configurations']:
                    if config['name'] == target:
                        print(f"Configuration '{target}' already exists")
                        break
                else:
                    data['configurations'].append(launch_configuration)
                    with open('.vscode/launch.json', 'w') as f:
                        json.dump(data, f, indent=4)
                        print(f"Configuration '{target}' added to launch.json")
    else:
        print(f"Target '{target}' not found")


if __name__ == "__main__":
    argparser = ArgumentParser()
    argparser.add_argument('target', help='The target to extract the command from')
    args = argparser.parse_args()
    
    main(args.target)
