# Check for __init__.py in the current directory
ifneq ("$(wildcard ./__init__.py)","")
$(error "__init__.py is present in the current directory. Please install this as a submodule under src/toolbox and then run 'ln -s src/toolbox/Makefile Makefile'")
endif

.PHONY: clean data lint requirements yaml test help kube
.PHONY: prompt_for_file interactive find fd list ls download down upload up remove rm
.PHONY: local job pod dryrun delete

#################################################################################
# GLOBALS                                                                       #
#################################################################################

-include project.mk

-include .env

ifneq ("$(wildcard .env)","")
	export $(shell sed 's/=.*//' .env)
endif

SHELL = /bin/bash
PROJECT_DIR := $(shell dirname $(realpath $(lastword $(MAKEFILE_LIST))))
PROFILE = default

PYTHON_INTERPRETER = python3
RESULT_DIR = results/

export PYTHONPATH = src:$$PYTHONPATH

ifeq (,$(shell which conda))
HAS_CONDA=False
else
HAS_CONDA=True
endif

ifneq ("$(wildcard config/kube.yaml)","")
	PROJECT_NAME := $(shell python -c "import yaml; print(yaml.safe_load(open('config/kube.yaml'))['project_name'])")
	export PROJECT_NAME
	USER_NAME := $(shell python -c "import yaml; print(yaml.safe_load(open('config/kube.yaml'))['user'])")
	export USER_NAME
	NAMESPACE := $(shell python -c "import yaml; print(yaml.safe_load(open('config/kube.yaml'))['namespace'])")
	export NAMESPACE
endif

kube:
ifndef PROJECT_NAME
	$(error "config/kube.yaml is not found. kube-related commands will not work.")
else
	@mkdir -p build/
endif

#################################################################################
# COMMANDS                                                                      #
#################################################################################

## Delete all compiled Python files
clean:
	find . -type f -name "*.py[co]" -delete
	find . -type d -name "__pycache__" -delete

## Lint using flake8
lint:
	flake8 --max-line-length=120 --ignore=E402,E731,F541,W291,E122,E127,F401,E266,E241,C901,E741,W293,F811,W504 src

## Debugging
test:
	echo "Hello World!"

#################################################################################
# Baseline + other related                                                      #
#################################################################################

#################################################################################
# Kubernetes related                                                            #
#################################################################################

# Define a function to call python script with the supplied command
define launch_command
	@if [ -n "$(PROJECT_NAME)" ]; then \
		CONDA_ENV_ROOT=$$(if echo $$CONDA_PREFIX | grep -q '/envs/'; then echo $$CONDA_PREFIX | sed 's|/envs/.*|/|'; else echo $$CONDA_PREFIX; fi); \
		source $$CONDA_ENV_ROOT/etc/profile.d/conda.sh && \
		if ls $$CONDA_ENV_ROOT/envs | grep -q "$(PROJECT_NAME)"; then \
			conda activate $(PROJECT_NAME) --no-stack; \
		fi; \
	fi; \
	python launch.py --mode $(1)
endef

local: kube
	$(call launch_command,local)

job: kube
	$(call launch_command,job)

pod: kube
	$(call launch_command,pod)

dryrun: kube
	$(call launch_command,dryrun)

delete_job:
	@echo "You are going to delete the following jobs:"
	@kubectl -n $(NAMESPACE) get jobs -l user=$(USER_NAME) -l project=$(PROJECT_NAME)
	@read -p "Are you sure you want to continue? [y/N]: " confirm && [ "$$confirm" = "y" ] || exit 1
	@echo "Deleting jobs..."
	@kubectl -n $(NAMESPACE) delete jobs -l user=$(USER_NAME) -l project=$(PROJECT_NAME)

delete_pod:
	@echo "You are going to delete the following pods:"
	@kubectl -n $(NAMESPACE) get pods -l user=$(USER_NAME) -l project=$(PROJECT_NAME)
	@read -p "Are you sure you want to continue? [y/N]: " confirm && [ "$$confirm" = "y" ] || exit 1
	@echo "Deleting pods..."
	@kubectl -n $(NAMESPACE) delete pods -l user=$(USER_NAME) -l project=$(PROJECT_NAME)

delete: kube delete_pod delete_job

#################################################################################
# S3 related                                                                    #
#################################################################################

# Define a function to call python script with the supplied command
define s3_command
	@if [ -n "$(PROJECT_NAME)" ]; then \
		CONDA_ENV_ROOT=$$(if echo $$CONDA_PREFIX | grep -q '/envs/'; then echo $$CONDA_PREFIX | sed 's|/envs/.*|/|'; else echo $$CONDA_PREFIX; fi); \
		source $$CONDA_ENV_ROOT/etc/profile.d/conda.sh && \
		if ls $$CONDA_ENV_ROOT/envs | grep -q "$(PROJECT_NAME)"; then \
			conda activate $(PROJECT_NAME) --no-stack; \
		fi; \
	fi; \
	python src/toolbox/s3utils.py --$(1) $(file)
endef

# Define a function to request file input if it's not set
define request_file_input
$(if $(file),,$(eval file := '$(shell read -p "Please enter the S3 path (support wildcards): " filepath; echo "$$filepath")'))
endef

# Default target for prompting file input
prompt_for_file:
	$(call request_file_input)

## Interactive mode with s3 file or folder
interactive: prompt_for_file
	$(call s3_command,interactive)

## Find s3 custom file or folder
find: prompt_for_file
	$(call s3_command,find)
fd: find

## List s3 custom file or folder
list: prompt_for_file
	$(call s3_command,list)
ls: list

## Download custom file or folder
download: prompt_for_file
	$(call s3_command,download)
down: download

## Upload custom file or folder
upload: prompt_for_file
	$(call s3_command,upload)
up: upload

## Upload and possibly overwrite custom file or folder
overwrite: prompt_for_file
	$(call s3_command,remove)
	$(call s3_command,upload)
ow: overwrite

## Remove s3 custom file or folder
remove: prompt_for_file
	$(call s3_command,remove)
rm: remove

#################################################################################
# Environment related                                                           #
#################################################################################

## Set up python interpreter environment
create_environment: kube
	conda-lock install --name ${PROJECT_NAME}
	conda run -n ${PROJECT_NAME} poetry install --no-root

## Test python environment is setup correctly
test_environment:
	@$(PYTHON_INTERPRETER) src/toolbox/testenv.py
	@poetry check
	@echo ">>> Poetry is setup correctly!"

#################################################################################
# Self Documenting Commands                                                     #
#################################################################################

.DEFAULT_GOAL := help

# Inspired by <http://marmelab.com/blog/2016/02/29/auto-documented-makefile.html>
# sed script explained:
# /^##/:
# 	* save line in hold space
# 	* purge line
# 	* Loop:
# 		* append newline + line to hold space
# 		* go to next line
# 		* if line starts with doc comment, strip comment character off and loop
# 	* remove target prerequisites
# 	* append hold space (+ newline) to line
# 	* replace newline plus comments by `---`
# 	* print line
# Separate expressions are necessary because labels cannot be delimited by
# semicolon; see <http://stackoverflow.com/a/11799865/1968>
help:
	@echo "$$(tput bold)Available rules:$$(tput sgr0)"
	@echo
	@sed -n -e "/^## / { \
		h; \
		s/.*//; \
		:doc" \
		-e "H; \
		n; \
		s/^## //; \
		t doc" \
		-e "s/:.*//; \
		G; \
		s/\\n## /---/; \
		s/\\n/ /g; \
		p; \
	}" ${MAKEFILE_LIST} \
	| LC_ALL='C' sort --ignore-case \
	| awk -F '---' \
		-v ncol=$$(tput cols) \
		-v indent=19 \
		-v col_on="$$(tput setaf 6)" \
		-v col_off="$$(tput sgr0)" \
	'{ \
		printf "%s%*s%s ", col_on, -indent, $$1, col_off; \
		n = split($$2, words, " "); \
		line_length = ncol - indent; \
		for (i = 1; i <= n; i++) { \
			line_length -= length(words[i]) + 1; \
			if (line_length <= 0) { \
				line_length = ncol - indent - length(words[i]) - 1; \
				printf "\n%*s ", -indent, " "; \
			} \
			printf "%s ", words[i]; \
		} \
		printf "\n"; \
	}' \
	| more $(shell test $(shell uname) = Darwin && echo '--no-init --raw-control-chars')
