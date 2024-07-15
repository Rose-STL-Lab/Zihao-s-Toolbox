#!/bin/bash

monitor() {
    local folder_path="$1"
    local interval="$2"

    # Convert the relative path to an absolute path
    folder_path="$(realpath "$folder_path")"

    # Check if the path is indeed a relative path
    if [[ "$folder_path" != "$(pwd)"/* ]]; then
        echo "Please provide a relative path: $folder_path" >&2
        return 1
    fi

    # Create the folder if it doesn't exist
    if [[ ! -d "$folder_path" ]]; then
        echo "Folder '$folder_path' doesn't exist. Creating it..."
        mkdir -p "$folder_path"
    fi

    # Initial check for existing files
    last_seen_files="$(find "$folder_path" -type f)"
    echo "Initial files: $last_seen_files" >&2

    added_files=""

    while true; do
        sleep "$interval"
        current_files="$(find "$folder_path" -type f)"
        new_files=$(comm -13 <(echo "$last_seen_files" | sort) <(echo "$current_files" | sort))
        removed_files=$(comm -23 <(echo "$last_seen_files" | sort) <(echo "$current_files" | sort))

        # Update added_files with new files
        added_files+=$'\n'"$new_files"

        for file in $added_files; do
            echo "New file detected: $file" >&2
            modification_time=$(stat -c %Y "$file")
            current_time=$(date +%s)
            time_diff=$((current_time - modification_time))
            echo "Time since last modification: $time_diff seconds" >&2

            if ((time_diff > interval)); then
                echo "New file detected and stable: $file"
                if command -v s5cmd >/dev/null 2>&1; then
                    s5cmd cp -n --sp "$file" "s3://$S3_BUCKET_NAME/$file"
                else
                    make upload file="$file"
                fi
                # Remove the file from added_files
                added_files=$(echo "$added_files" | sed "\|$file|d")
            fi
        done

        for file in $removed_files; do
            echo "File removed: $file"
            if command -v s5cmd >/dev/null 2>&1; then
                s5cmd rm "s3://$S3_BUCKET_NAME/$file"
            else
                make remove file="$file"
            fi
        done

        last_seen_files="$current_files"
    done
}

# Check if the required arguments are provided
if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <path> <interval>"
    exit 1
fi

path="$1"
interval="$2"

# Call the monitor function with the provided arguments
monitor "$path" "$interval"
