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


def load_class(info: dict, init=True):
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
    
    if not init:
        return cls
    else:
        instance = cls(**init_args)
        return instance


def increase_u_limit():
    import resource

    rlimit = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (65536, rlimit[1]))


def plotly_to_png(fig):
    import plotly.io as pio
    import cairosvg
    from PIL import Image
    import tempfile

    # Assuming 'fig' is defined elsewhere in your code
    svg = pio.to_image(fig, format='svg')

    # Use tempfile for managing temporary files/directories
    with tempfile.TemporaryDirectory() as tmpdirname:
        svg_path = f"{tmpdirname}/tmp.svg"
        png_path = f"{tmpdirname}/tmp.png"
        # Write SVG to a temporary file
        with open(svg_path, "wb") as tmp_svg:
            tmp_svg.write(svg)
        # Convert SVG to PNG using cairosvg
        cairosvg.svg2png(url=svg_path, write_to=png_path, scale=2)
        # Open the PNG image
        img = Image.open(png_path)

    return img


def pretty_table(df):
    from rich.console import Console
    from rich.table import Table
    
    table = Table(show_header=True, header_style="bold magenta")
    for col in df.columns:
        table.add_column(col)
    for row in df.itertuples():
        table.add_row(*[str(getattr(row, col)) for col in df.columns])
    
    console = Console()
    console.print(table)


def compare_nested_dicts(d1, d2, path=""):
    """Compare nested dictionaries d1 and d2. Returns True if all nested entries in d2 are equal to the corresponding entries in d1."""
    if isinstance(d1, dict) and isinstance(d2, dict):
        for key in d2:
            if key not in d1:
                return False
            if not compare_nested_dicts(d1[key], d2[key], path + str(key) + " -> "):
                return False
        return True
    else:
        return d1 == d2
    

def loadable_artifacts(
    hparams: dict,
    artifact_type: str,
    artifact_name: str,
):
    """Find all artifacts of a given type and name that have the same hparams as the given dictionary."""
    import wandb 
    from loguru import logger

    api = wandb.Api()
    artifacts = api.artifacts(type_name=artifact_type, name=artifact_name)
    loadable = {}
    for art in reversed(artifacts):
        run = art.logged_by()
        conf = run.config
        if compare_nested_dicts(conf, hparams):
            loadable[run.id] = {
                'artifact': art,
                'conf': run.config,
                'tags': run.tags
            }
            logger.info(f"Found matching config in run {run.id}, with tags{run.tags}")
    return loadable


def load_wandb_artifact(
    model_cls: type,
    artifact  # wandb.Artifact
):
    """Load single artifact from wandb and return the model."""
    from loguru import logger
    import tempfile
    import os
    
    with tempfile.TemporaryDirectory() as tmp:
        # Download the checkpoint to the temporary file
        logger.debug(f"Downloading artifact {artifact.name} to {tmp}...")
        artifact.download(tmp)
        # Assuming there's only one file in the directory, get its name
        tmpfile_name = os.listdir(tmp)[0]
        # Construct the full path to the file
        tmpfile_path = os.path.join(tmp, tmpfile_name)
        model = model_cls.load_from_checkpoint(checkpoint_path=tmpfile_path)
    return model
