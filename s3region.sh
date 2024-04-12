#!/bin/bash

# Path to the JSON file
json_file="src/toolbox/nodeinfo.json"

# Check if the JSON file exists
if [ -f "$json_file" ]; then
    # Check if the NODE_NAME environment variable is set
    if [ -n "$NODE_NAME" ]; then
        # Extract the region for the given NODE_NAME
        node_region=$(python -c "import json; data = json.load(open('$json_file')); print(data.get('$NODE_NAME', {}).get('region', ''))")
        
        # Based on the region, check corresponding environment variables and set AWS credentials
        case $node_region in
            "us-west")
                if [ -n "$AWS_ACCESS_KEY_ID_WEST" ] && [ -n "$AWS_SECRET_ACCESS_KEY_WEST" ] && [ -n "$S3_ENDPOINT_URL_WEST" ]; then
                    export AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID_WEST
                    export AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY_WEST
                    export S3_ENDPOINT_URL=$S3_ENDPOINT_URL_WEST
                fi
                ;;
            "us-central")
                if [ -n "$AWS_ACCESS_KEY_ID_CENTRAL" ] && [ -n "$AWS_SECRET_ACCESS_KEY_CENTRAL" ] && [ -n "$S3_ENDPOINT_URL_CENTRAL" ]; then
                    export AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID_CENTRAL
                    export AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY_CENTRAL
                    export S3_ENDPOINT_URL=$S3_ENDPOINT_URL_CENTRAL
                fi
                ;;
            "us-east")
                if [ -n "$AWS_ACCESS_KEY_ID_EAST" ] && [ -n "$AWS_SECRET_ACCESS_KEY_EAST" ] && [ -n "$S3_ENDPOINT_URL_EAST" ]; then
                    export AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID_EAST
                    export AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY_EAST
                    export S3_ENDPOINT_URL=$S3_ENDPOINT_URL_EAST
                fi
                ;;
        esac
    fi
fi
