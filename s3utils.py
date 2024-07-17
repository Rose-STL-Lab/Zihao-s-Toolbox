import os
import glob
import boto3
import fnmatch
from botocore.exceptions import ClientError
from botocore import UNSIGNED
from botocore.client import Config
import shutil
import sys
from toolbox.utils import CustomLogger, acquire_lock, release_lock
import time
from http.server import SimpleHTTPRequestHandler, HTTPServer
import json
from botocore.exceptions import NoCredentialsError, PartialCredentialsError
from pathlib import Path
import re


S3_ENDPOINT_URL = os.getenv('S3_ENDPOINT_URL')
S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME')
if not S3_ENDPOINT_URL or not S3_BUCKET_NAME:
    raise EnvironmentError("Please set the S3_ENDPOINT_URL and S3_BUCKET_NAME environment variables.")
logger = CustomLogger()


def use_s5cmd():
    """
    Check if s5cmd is available.
    """
    return shutil.which('s5cmd')


# Check if credentials are provided
if os.getenv('AWS_ACCESS_KEY_ID') and os.getenv('AWS_SECRET_ACCESS_KEY'):
    # Credentials are provided, use them to create the client
    s3_client = boto3.client('s3', endpoint_url=S3_ENDPOINT_URL)
else:
    # Credentials are not provided, use anonymous access
    s3_client = boto3.client('s3', endpoint_url=S3_ENDPOINT_URL, config=Config(signature_version=UNSIGNED))


def run_s5cmd_and_log(s5cmd_command, log_file_path="download.log"):
    tail = r' 2>&1 | awk \'BEGIN{RS=" "; ORS=""} {print $0 (/\\n/ ? "" : " "); if(tolower($0) ~ /%/) print "\\n"}\' | tee -a ' + log_file_path
    
    s5cmd_command = re.sub(
        r'(\s*(?:&&|&|;)\s*)', 
        tail + r'\1',
        s5cmd_command
    ) + tail
    os.system(s5cmd_command)


def run_s5cmd_interactive(s5cmd_command):
    os.system(s5cmd_command)


def run_s5cmd(s5cmd_command, log_file_path="download.log"):
    logger.debug(s5cmd_command)
    if sys.stdin.isatty():
        run_s5cmd_interactive(s5cmd_command)
    else:
        run_s5cmd_and_log(s5cmd_command, log_file_path)


def get_local_files(s3_path, local_path):
    """
    Recursively get local files that match the s3_path pattern in the local_path directory.
    """
    wildcard_index = s3_path.find('*')
    if wildcard_index == -1:
        prefix = s3_path
        pattern = "*"
    else:
        prefix = s3_path[:wildcard_index]
        if '/' in prefix:
            prefix = os.path.dirname(prefix)
            pattern = s3_path[len(prefix) + 1:]
        else:
            prefix = '.'
            pattern = s3_path
        
    prefix = os.path.normpath(os.path.join(local_path, prefix))
    if os.path.isdir(prefix):
        local_files = glob.glob(prefix + "/**", recursive=True)
    else:
        local_files = glob.glob(prefix + "**/**", recursive=True)
        local_files += glob.glob(prefix + "**", recursive=True)
        
    filtered_local_files = []
    for file in local_files:
        if os.path.isdir(file):
            continue
        file = os.path.normpath(file)
        if pattern:
            if fnmatch.fnmatch(os.path.relpath(file, prefix), pattern):
                file = os.path.normpath(file)
                filtered_local_files.append(file)
        else:
            filtered_local_files.append(file)
    return filtered_local_files


def get_s3_objects(s3_path):
    """
    Recursively get all objects in S3 bucket that match the s3_path pattern.
    """
    wildcard_index = s3_path.find('*')
    if wildcard_index == -1:
        prefix = s3_path
        pattern = ''
    else:
        prefix = s3_path[:wildcard_index]
        if prefix.endswith('/'):
            prefix = prefix[:-1]
            pattern = s3_path[len(prefix) + 1:]
        else:
            pattern = s3_path[len(prefix):]
    
    paginator = s3_client.get_paginator('list_objects_v2')
    pages = paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=prefix)

    filtered_s3_objects = []
    for page in pages:
        for obj in page.get('Contents', []):
            key = obj['Key']
            if pattern:  # only apply fnmatch if there's a pattern to match
                if fnmatch.fnmatch(key[len(prefix):], pattern):
                    filtered_s3_objects.append(key)
            else:
                filtered_s3_objects.append(key)
    return filtered_s3_objects


def download_s3_objects(s3_objects, local_path='./'):
    """
    Download specified S3 objects to the local file system.

    :param s3_objects: List of S3 keys to download
    :param local_path: Local directory to save the files
    """
    rtn = []
    for s3_key in s3_objects:
        # Construct the full local filepath
        local_file_path = os.path.join(local_path, s3_key)

        # Create directory if it doesn't exist
        local_file_dir = os.path.dirname(local_file_path)
        if not os.path.exists(local_file_dir):
            os.makedirs(local_file_dir)

        # Check if the file already exists locally
        if os.path.exists(local_file_path):
            logger.warning(f"File {local_file_path} already exists. Skipping download.")
            continue

        # Download the file from S3
        try:
            s3_client.download_file(S3_BUCKET_NAME, s3_key, local_file_path)
            logger.info(f"Downloaded {s3_key} to {local_file_path}")
            rtn.append(os.path.normpath(local_file_path))
        except ClientError as e:
            logger.error(f"Failed to download {s3_key}: {e}")
    return rtn


def download_s3_path(s3_path, local_path='./'):
    """
    Download all files in the S3 path to the local file system.
    """
    # Remove the trailing '*' 
    s3_path = s3_path.rstrip('*')
    s3_path = os.path.normpath(s3_path)
    s3_objects = get_s3_objects(s3_path)
    
    # Skip files that already exist locally
    s3_objects = [s3_key for s3_key in s3_objects if not os.path.exists(os.path.join(local_path, s3_key))]
    
    if len(s3_objects) == 0:
        logger.error(f"No new files found in {s3_path}")
        return []
    
    # If there is no wildcard in the middle
    if use_s5cmd():
        if '*' not in s3_path:
            s3_path = s3_path.rstrip('/')
            prefix = f"s3://{S3_BUCKET_NAME}/{s3_path}"
            
            dest = os.path.join(local_path, s3_path)
            if len(s3_objects) == 1 and s3_objects[0] == s3_path:
                # single file
                run_s5cmd(f"s5cmd cp -n --sp {prefix} {dest}")
            elif s3_objects[0].startswith(s3_path + "/"):
                # directory
                run_s5cmd(f"s5cmd cp -n --sp '{prefix}/*' {dest}/")
            else:
                # non-dir prefix
                run_s5cmd(f"s5cmd cp -n --sp '{prefix}*' {os.path.dirname(dest)}")
        else:  # Download one by one
            commands = ""
            for s3_key in s3_objects:
                dest = os.path.join(local_path, s3_key)
                s5cmd_command = f"s5cmd cp -n --sp s3://{S3_BUCKET_NAME}/{s3_key} {dest}"
                commands += s5cmd_command + " && "
            commands = commands[:-4]
            run_s5cmd(commands)
        
        return s3_objects
    else:
        return download_s3_objects(s3_objects, local_path)


def list_s3_objects(s3_path):
    """
    List all directories / files in S3 bucket under the given path.
    """
    if s3_path.startswith('./'):
        s3_path = s3_path[2:]
    prefix = s3_path.lstrip('/')

    paginator = s3_client.get_paginator('list_objects_v2')
    page_iterator = paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=prefix, Delimiter='/')
    objects = []
    directories = []
    rtn = []

    for page in page_iterator:
        directories.extend(page.get('CommonPrefixes', []))
        objects.extend(page.get('Contents', []))

    for d in directories:
        logger.info(f"Directory: {d['Prefix']}")
        rtn.append(d['Prefix'])

    for obj in objects:
        if obj['Key'].endswith('/'):
            # Skip directories, as they are already handled above
            continue
        logger.info(f"File: {obj['Key']}")
        rtn.append(obj['Key'])

    if s3_path.endswith('/'):
        # If s3_path is a directory, list files and directories recursively
        for d in directories:
            sub_path = d['Prefix']
            sub_rtn = list_s3_objects(sub_path)
            rtn.extend(sub_rtn)

    return rtn


def delete_local_files(local_files):
    """
    Delete local files.
    """
    for file in local_files:
        os.remove(file)
        logger.info(f"Deleted {file}")
        ## Delete empty folders if any
        folder = os.path.dirname(file)
        if not os.listdir(folder):
            os.rmdir(folder)
            logger.info(f"Deleted {folder}")


def print_folders(files):
    """
    Print folders of files, assuming the files are sorted by folder.
    """
    last_folder = None
    for file in files:
        folder = "/".join(file.split("/")[:-1]) + '/'
        if folder != last_folder:
            logger.info(folder)
            last_folder = folder


def remove_s3_objects(objects_to_delete):
    """
    Remove objects in S3.
    """
    rtn = []
    objects_to_delete = [{'Key': obj} for obj in objects_to_delete]
    if objects_to_delete:
        s3_client.delete_objects(Bucket=S3_BUCKET_NAME, Delete={'Objects': objects_to_delete})
        for obj in objects_to_delete:
            logger.info(f"Removed {obj['Key']} from S3")
            rtn.append(obj['Key'])
    return rtn


def remove_s3_path(s3_path):
    """
    Remove all files in the S3 path.
    """
    s3_path = os.path.normpath(s3_path)
    s3_objects = get_s3_objects(s3_path)
    return remove_s3_objects(s3_objects)


def upload_s3_objects(local_files, local_path='./'):
    """
    Upload local files to S3.

    :param local_files: List of file paths to upload
    :param local_path: Base path of the local files
    :return: List of S3 URLs of the uploaded files
    """
    rtn = []
    for local_file in local_files:
        if os.path.isfile(local_file):
            # Calculate the relative S3 key from the local file path
            s3_key = os.path.relpath(local_file, os.path.dirname(local_path))
            s3_key = os.path.normpath(s3_key)

            # Check if the file already exists in S3
            response = s3_client.list_objects_v2(Bucket=S3_BUCKET_NAME, Prefix=s3_key)
            if 'Contents' in response:
                logger.warning(f"File {s3_key} already exists in S3")
                continue

            # Upload the file if it does not exist
            try:
                s3_client.upload_file(local_file, S3_BUCKET_NAME, s3_key)
                uploaded_url = f"s3://{S3_BUCKET_NAME}/{s3_key}"
                logger.info(f"Uploaded {local_file} to {uploaded_url}")
                rtn.append(uploaded_url)
            except (NoCredentialsError, PartialCredentialsError) as e:
                logger.error(f"Failed to upload {local_file} due to credential issues: {e}")
            except Exception as e:
                logger.error(f"Failed to upload {local_file}: {e}")

    return rtn


def upload_s3_path(s3_path, local_path='./'):
    """
    Upload all files in the local path to the S3 path.
    """
    # Remove the trailing '*' 
    s3_path = s3_path.rstrip('*')
    s3_path = os.path.normpath(s3_path)
    s3_objects = get_s3_objects(s3_path)
    local_files = get_local_files(s3_path, local_path)
    
    # Skip files that already exist in S3
    local_files = [file for file in local_files if not any(file == s3_key for s3_key in s3_objects)]
    
    if len(local_files) == 0:
        logger.error(f"No new files found in {s3_path}")
        return []
    
    if use_s5cmd():
        # Single file or directory
        if '*' not in s3_path and os.path.exists(os.path.join(local_path, s3_path)):
            s3_path = s3_path.rstrip('/')
            local_path = os.path.join(local_path, s3_path)
            if os.path.isdir(local_path):
                local_path += os.sep
                s3_path += '/'
            dest = os.path.join(local_path, s3_path)
            run_s5cmd(f"s5cmd cp -n --sp {local_path} s3://{S3_BUCKET_NAME}/{s3_path}")
        else:  # Upload one by one
            commands = ""
            for s3_key in local_files:
                dest = f"s3://{S3_BUCKET_NAME}/{s3_key}"
                s5cmd_command = f"s5cmd cp -n --sp {s3_key} {dest}"
                commands += s5cmd_command + " && "
            commands = commands[:-4]
            run_s5cmd(commands)
        return local_files
    else:
        return upload_s3_objects(local_files, local_path)


def interactive_list_and_action(s3_path, local_path):
    """
    List local and S3 files/folders, then ask the user whether to 
    - delete local files
    - upload local files
    - remove s3 files
    - download s3 files
    """
    if s3_path.endswith("/"):
        filetype = "folders"
        s3_path += "*"
    else:
        filetype = "files"
    
    logger.info(f"Local {filetype} matching pattern:")
    local_files = get_local_files(s3_path, local_path)
    
    if filetype == "folders":
        print_folders(local_files)
    else:
        for file in local_files:
            logger.info(file)

    logger.info(f"\nS3 {filetype} matching pattern:")
    s3_objects = get_s3_objects(s3_path)
    
    if filetype == "folders":
        print_folders(s3_objects)
    else:
        for file in s3_objects:
            logger.info(file)

    action = input("\nChoose an action [delete (local), remove (S3), download, upload, exit]: ").strip().lower()
    if action == "delete":
        delete_local_files(local_files)
    elif action == "upload":
        upload_s3_objects(local_files, local_path)
    elif action == "remove":
        remove_s3_objects(s3_objects)
    elif action == "download":
        download_s3_objects(s3_objects, local_path)
    elif action == "exit":
        pass
    else:
        logger.error("Invalid action")
        
        
def list_files(directory):
    """ List all non-hidden files recursively """
    for root, dirs, files in os.walk(directory):
        # Exclude hidden files and directories
        files = [f for f in files if not f.startswith('.')]
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for file in files:
            yield Path(root) / file


def monitor(folder_path, interval, log_file="monitor.log"):
    # Log to monitor.log by default
    logger.add(log_file, rotation="1 week")
    
    # Convert the relative path to an absolute path
    folder_path = Path(folder_path).resolve()
    lock_path = folder_path / ".monitor.lock"
    
    try:
        acquire_lock(lock_path)
        
        # Initial check for existing files
        last_seen_files = set(list_files(folder_path))
        logger.debug(f"Initial files: {last_seen_files}")

        added_files = set()
        while True:
            time.sleep(interval)
            current_files = set(list_files(folder_path))
            added_files.update(current_files - last_seen_files)
            removed_files = last_seen_files - current_files

            for file in added_files.copy():
                # Check if the file has not been modified for at least 'interval' seconds
                file_path = folder_path / file
                file_path = file_path.relative_to(Path.cwd())
                
                logger.debug(f"New file detected: {file_path}")
                logger.debug(f"Time since last modification: {(time.time() - os.path.getmtime(file_path)):.5f}")
                if time.time() - os.path.getmtime(file_path) > interval:
                    logger.info(f"New file detected and stable: {file}")
                    added_files.remove(file)
                    upload_s3_path(file_path)
                    logger.info(f"File uploaded: s3://{S3_BUCKET_NAME}/{file_path}")

            for file in removed_files:
                file_path = folder_path / file
                file_path = file_path.relative_to(Path.cwd())
                
                logger.info(f"File removed: {file_path}")
                remove_s3_path(file_path)

            last_seen_files = current_files

    finally:
        release_lock(lock_path)
    

class RequestHandler(SimpleHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        data = json.loads(post_data)
        
        command = data.get('command')
        path = data.get('path')
        
        if command == 'find':
            response = get_s3_objects(path)
        elif command == 'list':
            response = list_s3_objects(path)
        elif command == 'download':
            response = download_s3_path(path)
        elif command == 'upload':
            response = upload_s3_path(path)
        elif command == 'remove':
            response = remove_s3_path(path)
        else:
            response = "Invalid command"

        # Simulate a delay
        time.sleep(3)

        # Send response
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        
        response = json.dumps({"message": response})
        self.wfile.write(response.encode('utf-8'))
        
        
def run(server_class=HTTPServer, handler_class=RequestHandler, port=57575):
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    print(f"Server started at localhost: {port}")
    httpd.serve_forever()
    

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="S3 utils for managing files and folders."
    )
    parser.add_argument("--find", help="Find S3 files", action="store_true")
    parser.add_argument("--list", help="List S3 files", action="store_true")
    parser.add_argument("--download", help="Download S3 files", action="store_true")
    parser.add_argument(
        "--upload", help="Upload local files to S3", action="store_true"
    )
    parser.add_argument("--remove", help="Remove S3 files", action="store_true")
    parser.add_argument("--delete", help="Delete local files", action="store_true")
    parser.add_argument("--interactive", help="Interactive mode", action="store_true")
    parser.add_argument("--local_path", help="Local path", type=str, default="./")
    parser.add_argument("--monitor", help="Monitor local path for changes", action="store_true")
    parser.add_argument("--server", help="Run as a S3 API server", action="store_true")
    parser.add_argument("--port", type=int, default=57575, help="Port for the HTTP server")
    parser.add_argument("--interval", type=int, default=5, help="Polling interval in seconds.")
    parser.add_argument("path", help="The S3 or local path pattern", type=str, nargs='?')

    args = parser.parse_args()

    s3_path = args.path
    local_path = args.local_path
    
    if not args.server and not args.path:
        parser.error("the following arguments are required: path")
    if args.server:
        run(port=args.port)
    elif args.monitor:
        monitor(args.path, args.interval)
    elif args.find:
        file_type = "folders" if s3_path.endswith("/") else "files"
        s3_objects = get_s3_objects(s3_path + "**" if file_type == "folders" else s3_path)
        if file_type == "folders":
            print_folders(s3_objects)
        else:
            for obj in s3_objects:
                logger.info(obj)
    elif args.list:
        list_s3_objects(s3_path)
    elif args.download:
        download_s3_path(s3_path, local_path)
    elif args.upload:
        upload_s3_path(s3_path, local_path)
    elif args.remove:
        remove_s3_path(s3_path)
    elif args.delete:
        local_files = get_local_files(s3_path, local_path)
        delete_local_files(local_files)
    elif args.interactive:
        interactive_list_and_action(s3_path, local_path)
    else:
        parser.print_help()
