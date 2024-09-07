# Check for __init__.py in the current directory
ifneq ("$(wildcard ./__init__.py)","")
$(error "__init__.py is present in the current directory. Please install this as a submodule under src/toolbox and then run 'ln -s src/toolbox/Makefile Makefile'")
endif

.PHONY: all $(MAKECMDGOALS)
.NOTPARALLEL: all $(MAKECMDGOALS)
.EXPORT_ALL_VARIABLES:

#################################################################################
# GLOBALS                                                                       #
#################################################################################

-include .env
-include project.mk

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
USERNAME := $(shell python -c "import yaml; print(yaml.safe_load(open('config/kube.yaml'))['user'])")
export USERNAME
NAMESPACE := $(shell python -c "import yaml; print(yaml.safe_load(open('config/kube.yaml'))['namespace'])")
export NAMESPACE
else ifneq ("$(S3_BUCKET_NAME)","")
PROJECT_NAME := $(S3_BUCKET_NAME)
export PROJECT_NAME
else
PROJECT_NAME := $(shell grep '^name = ' pyproject.toml | head -n 1 | cut -d '"' -f 2)
export PROJECT_NAME
endif

LOADENV := set -a && source .env && set +a

ifeq ($(CONDA_PREFIX),)
POETRY_CHECK := $(shell python -m poetry run echo 2>&1)
ifneq (,$(findstring No module named poetry,$(POETRY_CHECK)))
$(error "CONDA_PREFIX not set and poetry not found. `pip install poetry` or activate the conda environment.")
else ifneq (,$(findstring unable to find a compatible version,$(POETRY_CHECK)))
$(error "$(POETRY_CHECK)")
else
POETRY_PREFIX := $(shell python -m poetry run python -c "import sys; print(sys.exec_prefix)" 2>/dev/null)
ACTIVATE := source $(POETRY_PREFIX)/bin/activate
export ACTIVATE
PYTHON_PREFIX := $(shell python -c "import sys; print(sys.exec_prefix)" 2>/dev/null)
ifeq ($(POETRY_PREFIX),$(PYTHON_PREFIX))
PYTHON := python
else
PYTHON := python -m poetry run python
endif
export PYTHON
endif
else
CONDA_ENV_ROOT := $(if $(findstring /envs/, $(CONDA_PREFIX)),$(shell echo $(CONDA_PREFIX) | sed 's|/envs/.*|/|'),$(CONDA_PREFIX))
CONDA_ENV_CHECK := $(shell conda env list | grep -q $(PROJECT_NAME) && echo "true" || echo "false")
ifeq ("$(CONDA_ENV_CHECK)","false")
$(error "Conda environment $(PROJECT_NAME) not found. Please create the environment using 'make create_environment', or rename your environment to match the project name.")
endif
export CONDA_ENV_ROOT
ACTIVATE := source $(CONDA_ENV_ROOT)/bin/activate $(PROJECT_NAME) --no-stack
export ACTIVATE
ifeq ($(CONDA_PREFIX),$(CONDA_ENV_ROOT)envs/$(PROJECT_NAME))
PYTHON := python
else
PYTHON := conda run -n $(PROJECT_NAME) python
endif
export PYTHON
endif

kube:
ifeq ("$(wildcard config/kube.yaml)","")
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

target ?= launch.yaml
## Run background task with tmux
tmux:
	$(if $(shell grep -q '^$(target):' $(MAKEFILE_LIST) && echo true), \
		tmux new-session -d -s $(target) "$(MAKE) $(target)", \
		$(error Target '$(target)' does not exist in the Makefile))

## Extract make target python command and put into vscode launch.json
debug:
	@$(PYTHON) src/toolbox/debugutils.py $(target) $(overwrite)

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
	python launch.py $(1)
endef

## Running the commands locally and sequentially
local: kube
	$(PYTHON) launch.py --mode local

## Running the jobs on the cluster in parallel
job: kube
	$(PYTHON) launch.py --mode job --overwrite $(overwrite)

## Launch a single pod for debug
pod: kube
ifdef pod
	$(PYTHON) launch.py --mode pod --pod $(pod)
else
	$(PYTHON) launch.py --mode pod
endif

## Generate the commands for launch batch jobs, but do not actually deploy them
dryrun: kube
	$(PYTHON) launch.py --mode dryrun

## Generate the commands for running locally, but do not actually run them
local-dryrun: kube
	$(PYTHON) launch.py --mode local-dryrun

## Run the first target in the launch.yaml file, but no more than that
local-first: kube
	$(PYTHON) launch.py --mode local-first

## Generate the commands for launch a pod, but do not actually deploy them
pod-dryrun: kube
	$(PYTHON) launch.py --mode pod-dryrun

## Copy files (in file section) from the pod to local
copy: kube
ifdef pod
	$(PYTHON) launch.py --mode copy_files --pod $(pod)
else
	$(PYTHON) launch.py --mode copy_files
endif

## Delete all jobs
delete_job:
	@echo "You are going to delete the following jobs:"
	@kubectl -n $(NAMESPACE) get jobs -l user=$(USERNAME) -l project=$(PROJECT_NAME)
	@read -p "Are you sure you want to continue? [y/N]: " confirm && [ "$$confirm" = "y" ] || exit 1
	@echo "Deleting jobs..."
	@kubectl -n $(NAMESPACE) delete jobs -l user=$(USERNAME) -l project=$(PROJECT_NAME)

## Delete failed jobs
clean_jobs:
	@echo "You are going to delete the following failed jobs:"
	@kubectl -n $(NAMESPACE) get jobs -l user=$(USERNAME) -l project=$(PROJECT_NAME) -o json | jq -r '.items[] | select(.status.failed != null) | .metadata.name' | tee /tmp/failed-jobs.txt
	@[ -s /tmp/failed-jobs.txt ] || { echo "No failed jobs to delete"; exit 1; }
	@read -p "Are you sure you want to continue? [y/N]: " confirm && [ "$$confirm" = "y" ] || exit 1
	@echo "Deleting failed jobs..."
	@cat /tmp/failed-jobs.txt | xargs -I {} kubectl -n $(NAMESPACE) delete job {}
	@rm /tmp/failed-jobs.txt

## Delete all pods
delete_pod:
	@echo "You are going to delete the following pods:"
	@kubectl -n $(NAMESPACE) get pods -l user=$(USERNAME) -l project=$(PROJECT_NAME)
	@read -p "Are you sure you want to continue? [y/N]: " confirm && [ "$$confirm" = "y" ] || exit 1
	@echo "Deleting pods..."
	@kubectl -n $(NAMESPACE) delete pods -l user=$(USERNAME) -l project=$(PROJECT_NAME)

## Delete everything
delete: kube delete_pod delete_job

#################################################################################
# S3 related                                                                    #
#################################################################################

bash ?= false
shell:
ifeq ($(bash)$(wildcard $(HOME)/.oh-my-zsh),false$(HOME)/.oh-my-zsh)
	@zsh --no-rcs -i --nozle <<< 'export ZSH=$$HOME/.oh-my-zsh; ZSH_THEME="robbyrussell"; plugins=(git); [ -d "$$HOME/.zsh/pure" ] && { fpath+=("$$HOME/.zsh/pure"); autoload -U promptinit; promptinit; prompt pure; }; source $$ZSH/oh-my-zsh.sh; alias make="make --no-print-directory"; $(ACTIVATE); set -a; source .env; set +a; exec < /dev/tty; setopt zle'
else
	@bash --rcfile <(echo '. src/toolbox/.bashrc; alias make="make --no-print-directory"; $(ACTIVATE); set -a; source .env; set +a;')
endif
overwrite ?= false
local_path ?= .
api ?= false

## Interactive mode with s3 file or folder
interactive:
	$(if $(file),,$(eval file := '$(shell read -p "Please enter the relative path (support wildcards *): " filepath; echo "$$filepath")'))
	@$(PYTHON) src/toolbox/s3utils.py --interactive $(file) --local_path $(local_path)

## Find s3 custom file or folder
find:
	$(if $(file),,$(eval file := '$(shell read -p "Please enter the relative path (support wildcards *): " filepath; echo "$$filepath")'))
	@$(PYTHON) src/toolbox/s3utils.py --find $(file) --local_path $(local_path)
fd: find

## List s3 custom file or folder
list:
	$(if $(file),,$(eval file := '$(shell read -p "Please enter the relative path (support wildcards *): " filepath; echo "$$filepath")'))
	@$(PYTHON) src/toolbox/s3utils.py --list $(file) --local_path $(local_path)
ls: list

## Download custom file or folder
download:
	$(if $(file),,$(eval file := '$(shell read -p "Please enter the relative path (support wildcards *): " filepath; echo "$$filepath")'))
ifeq ($(overwrite),true)
	rm -rf $(file)
endif
	@$(PYTHON) src/toolbox/s3utils.py --download $(file) --local_path $(local_path) --api $(api)
down: download

## Upload custom file or folder
upload:
	$(if $(file),,$(eval file := '$(shell read -p "Please enter the relative path (support wildcards *): " filepath; echo "$$filepath")'))
ifeq ($(overwrite),true)
	@$(PYTHON) src/toolbox/s3utils.py --remove $(file) --local_path $(local_path) --api $(api)
endif
	@$(PYTHON) src/toolbox/s3utils.py --upload $(file) --local_path $(local_path) --api $(api)
up: upload

## Remove s3 custom file or folder
remove:
	$(if $(file),,$(eval file := '$(shell read -p "Please enter the relative path (support wildcards *): " filepath; echo "$$filepath")'))
	@$(PYTHON) src/toolbox/s3utils.py --remove $(file) --local_path $(local_path) --api $(api)
rm: remove

## Monitor a checkpoint folder for continuous upload & remove
monitor:
	$(if $(file),,$(eval file := '$(shell read -p "Please enter the relative path (support wildcards * *): " filepath; echo "$$filepath")'))
	@$(PYTHON) src/toolbox/s3utils.py --monitor $(file)
mn: monitor

## Run a separate API server for s3 operations
server:
	@$(PYTHON) src/toolbox/s3utils.py --server
sv: server

#################################################################################
# Environment related                                                           #
#################################################################################

## Set up python interpreter environment
create_environment:
	@conda env create -n $(PROJECT_NAME) --file environment.yml
	@poetry install

## Test python environment is setup correctly
test_environment:
	@python -m poetry check
	@echo ">>> Testing python environment..."
	@echo ">>> Python executable: $$(which python)"
	@echo ">>> Python version: $$(python --version)"
	@python -m poetry install | tee poetry_output.txt
	@if grep -q "No dependencies" poetry_output.txt; then \
		echo ">>> All dependencies are present."; \
	else \
		echo ">>> Some dependencies are missing. Please check the output above."; \
		exit 1; \
	fi
	@echo ">>> Poetry is setup correctly!"
	@echo ">>> Run make shell to activate the environment."

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
