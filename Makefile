.DEFAULT_GOAL := help

export NAME ?=

all: renumber

renumber:
	./.scripts/renumber.sh

all new:
	./.scripts/new.sh "$${NAME}"

help:
	@echo 'make new [NAME=learning-c]'
	@echo 'make all [NAME=learning-c]'
	@echo 'make renumber'
	@echo 'make test'

test:
	python3 -m unittest discover -s tests -v

.PHONY: new all renumber help test
