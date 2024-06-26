import os
import glob
import boto3
import fnmatch
from botocore.exceptions import ClientError
from botocore import UNSIGNED
from botocore.client import Config
import shutil
import sys


S3_ENDPOINT_URL = os.getenv('S3_ENDPOINT_URL')
S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME')
if not S3_ENDPOINT_URL or not S3_BUCKET_NAME:
    raise EnvironmentError("Please set the S3_ENDPOINT_URL and S3_BUCKET_NAME environment variables.")

# Check if credentials are provided
if os.getenv('AWS_ACCESS_KEY_ID') and os.getenv('AWS_SECRET_ACCESS_KEY'):
    # Credentials are provided, use them to create the client
    s3_client = boto3.client('s3', endpoint_url=S3_ENDPOINT_URL)
else:
    # Credentials are not provided, use anonymous access
    s3_client = boto3.client('s3', endpoint_url=S3_ENDPOINT_URL, config=Config(signature_version=UNSIGNED))


def run_s5cmd_and_log(s5cmd_command, log_file_path="download.log"):
    os.system(
        s5cmd_command
        + ' 2>&1 | awk \'BEGIN{RS=" "; ORS=""} {print $0 (/\\n/ ? "" : " "); if(tolower($0) ~ /%/) print "\\n"}\' | tee -a '
        + log_file_path
    )


def run_s5cmd_interactive(s5cmd_command):
    os.system(s5cmd_command)


def run_s5cmd(s5cmd_command, log_file_path="download.log"):
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
        prefix = os.path.dirname(s3_path)
        pattern = os.path.basename(s3_path)
    else:
        prefix = s3_path[:wildcard_index]
        if '/' in prefix:
            prefix = os.path.dirname(prefix)
            pattern = s3_path[len(prefix) + 1:]
        else:
            prefix = '.'
            pattern = s3_path
        
    prefix = os.path.normpath(os.path.join(local_path, prefix))
    local_files = glob.glob(prefix + "/**", recursive=True)
    
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
    """
    for s3_key in s3_objects:
        # Construct the full local filepath
        local_file_path = os.path.join(local_path, s3_key)

        # Create directory if it doesn't exist
        local_file_dir = os.path.dirname(local_file_path)
        if not os.path.exists(local_file_dir):
            os.makedirs(local_file_dir)

        # Download the file from S3
        try:
            if os.path.exists(local_file_path):
                print(f"File {local_file_path} already exists")
                continue
            s3_client.download_file(S3_BUCKET_NAME, s3_key, local_file_path)
            print(f"Downloaded {s3_key} to {local_file_path}")
        except ClientError as e:
            print(f"Failed to download {s3_key}: {e}")


def download_s3_path(s3_path, local_path='./'):
    """
    Download all files in the S3 path to the local file system.
    """
    if shutil.which('s5cmd'):
        s3_path = s3_path.rstrip('/')
        prefix = f"s3://{S3_BUCKET_NAME}/{s3_path}"
        output = os.popen(f"s5cmd ls {prefix}").read()
        # Is directory?
        if "\n" not in output.strip() and os.path.basename(s3_path) in output:
            s5cmd_command = f"s5cmd cp -n --sp '{prefix}/*' {os.path.join(local_path, s3_path)}/"
        else:
            s5cmd_command = f"s5cmd cp -n --sp {prefix} {os.path.join(local_path, s3_path)}"
        run_s5cmd(s5cmd_command)
    else:
        s3_objects = get_s3_objects(s3_path)
        download_s3_objects(s3_objects, local_path)


def list_s3_objects(s3_path):
    """
    List all directories / files in S3 bucket under the given path.
    """
    prefix = s3_path.lstrip('/')

    paginator = s3_client.get_paginator('list_objects_v2')
    page_iterator = paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=prefix, Delimiter='/')
    objects = []
    directories = []

    for page in page_iterator:
        directories.extend(page.get('CommonPrefixes', []))
        objects.extend(page.get('Contents', []))

    for d in directories:
        print(f"Directory: {d['Prefix']}")

    for obj in objects:
        print(f"File: {obj['Key']}")


def delete_local_files(local_files):
    """
    Delete local files.
    """
    for file in local_files:
        os.remove(file)
        print(f"Deleted {file}")
        ## Delete empty folders if any
        folder = os.path.dirname(file)
        if not os.listdir(folder):
            os.rmdir(folder)
            print(f"Deleted {folder}")


def print_folders(files):
    """
    Print folders of files, assuming the files are sorted by folder.
    """
    last_folder = None
    for file in files:
        folder = "/".join(file.split("/")[:-1]) + '/'
        if folder != last_folder:
            print(folder)
            last_folder = folder


def remove_s3_objects(objects_to_delete):
    """
    Remove objects in S3.
    """
    objects_to_delete = [{'Key': obj} for obj in objects_to_delete]
    if objects_to_delete:
        s3_client.delete_objects(Bucket=S3_BUCKET_NAME, Delete={'Objects': objects_to_delete})
        for obj in objects_to_delete:
            print(f"Removed {obj['Key']} from S3")


def remove_s3_path(s3_path):
    """
    Remove all files in the S3 path.
    """
    s3_objects = get_s3_objects(s3_path)
    remove_s3_objects(s3_objects)


def upload_s3_objects(local_files, local_path='./'):
    """
    Upload local files to S3.
    """
    for local_file in local_files:
        if os.path.isfile(local_file):
            s3_key = os.path.relpath(local_file, os.path.dirname(local_path))
            s3_key = os.path.normpath(s3_key)
            try:
                s3_client.head_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
                print(f"File {s3_key} already exists in S3")
            except ClientError:
                s3_client.upload_file(local_file, S3_BUCKET_NAME, s3_key)
                print(f"Uploaded {local_file} to {s3_key}")


def upload_s3_path(s3_path, local_path='./'):
    """
    Upload all files in the local path to the S3 path.
    """
    if shutil.which('s5cmd'):
        s3_path = s3_path.rstrip('/')
        local_path = os.path.join(local_path, s3_path)
        if os.path.isdir(local_path):
            local_path += os.sep
            s3_path += '/'
        s5cmd_command = f"s5cmd cp -n --sp {local_path} s3://{S3_BUCKET_NAME}/{s3_path}"
        run_s5cmd(s5cmd_command)
    else:
        local_files = get_local_files(s3_path, local_path)
        upload_s3_objects(local_files, local_path)


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
    
    print(f"Local {filetype} matching pattern:")
    local_files = get_local_files(s3_path, local_path)
    
    if filetype == "folders":
        print_folders(local_files)
    else:
        for file in local_files:
            print(file)

    print(f"\nS3 {filetype} matching pattern:")
    s3_objects = get_s3_objects(s3_path)
    
    if filetype == "folders":
        print_folders(s3_objects)
    else:
        for file in s3_objects:
            print(file)

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
        print("Invalid action")


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
    parser.add_argument("path", help="The S3 or local path pattern", type=str)

    args = parser.parse_args()

    s3_path = args.path
    local_path = args.local_path

    if args.find:
        file_type = "folders" if s3_path.endswith("/") else "files"
        s3_objects = get_s3_objects(s3_path + "**" if file_type == "folders" else s3_path)
        if file_type == "folders":
            print_folders(s3_objects)
        else:
            for obj in s3_objects:
                print(obj)
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
