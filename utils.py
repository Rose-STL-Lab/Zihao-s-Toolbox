def load_env_file(file_path='.env'):
    env_dict = {}
    with open(file_path, 'r') as file:
        for line in file:
            # Remove leading and trailing whitespace, skip blank lines and lines starting with #
            line = line.strip()
            if line == '' or line.startswith('#'):
                continue
            # Split the line into key/value pair, if possible
            try:
                key, value = line.split('=', 1)
                # Strip white spaces and remove any surrounding quotes from the value
                value = value.strip().strip('\'"')
                env_dict[key.strip()] = value
            except ValueError:
                print(f"Warning: Ignoring line as it's not in the KEY=VALUE format: {line}")
    return env_dict


def load_class(info: dict):
    import importlib

    assert 'class_path' in info
    class_path = info['class_path']
    
    if 'init_args' not in info:
        init_args = {}
    else:
        init_args = info['init_args']
    
    # Split the class path into module and class names
    module_name, class_name = class_path.rsplit(".", 1)

    # Import the module
    module = importlib.import_module(module_name)
    
    # Load the class and initialize with the given arguments
    cls = getattr(module, class_name)
    instance = cls(**init_args)
    
    return instance
