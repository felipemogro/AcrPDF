
PYTHON  ?= /usr/bin/python3
UV      ?= $(shell command -v uv || echo $(HOME)/.local/bin/uv)
VENV    := .venv
PY      := $(VENV)/bin/python
VERSION := $(shell sed -n 's/^__version__ = "\(.*\)"/\1/p' src/acrpdf/__init__.py)
ARCH    := $(shell dpkg --print-architecture 2>/dev/null || echo amd64)
LANGS   := es fr pt
DEB     := releases/acrpdf_$(VERSION)_$(ARCH).deb

.DEFAULT_GOAL := help
.PHONY: help venv run test lint pot update-po mo deb install uninstall dist clean

help:  ## Show this help
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[1m%-11s\033[0m %s\n", $$1, $$2}'

$(PY):
	$(UV) venv --python $(PYTHON) $(VENV)
	$(UV) pip install --python $(PY) -e ".[dev]"

venv: $(PY)  ## Create the development environment (.venv)

run: $(PY) mo  ## Start the application from the source tree
	$(PY) -m acrpdf

test: $(PY)  ## Run the test suite
	QT_QPA_PLATFORM=offscreen $(PY) -m pytest

lint: $(PY)  ## Static checks
	$(PY) -m pyflakes src tests

pot: $(PY)  ## Extract translatable strings to po/acrpdf.pot
	$(VENV)/bin/pybabel extract -F babel.cfg -k _ -k N_ -k ngettext:1,2 --no-location --sort-output \
		--project "ACRPDF Reader" --version $(VERSION) -o po/acrpdf.pot .

update-po: pot  ## Merge new strings into po/<lang>.po
	@for l in $(LANGS); do $(VENV)/bin/pybabel update -i po/acrpdf.pot -o po/$$l.po -l $$l --no-wrap; done

mo: $(PY)  ## Compile translations into the package
	@for l in $(LANGS); do \
		mkdir -p src/acrpdf/locale/$$l/LC_MESSAGES; \
		$(VENV)/bin/pybabel compile -i po/$$l.po -o src/acrpdf/locale/$$l/LC_MESSAGES/acrpdf.mo -l $$l >/dev/null; \
	done

deb: mo test  ## Build the Debian package in releases/
	packaging/build-deb.sh

install: $(DEB)  ## Install the Debian package (asks for sudo)
	sudo apt install ./$(DEB)

uninstall:  ## Remove the installed package
	sudo apt remove acrpdf

dist:  ## Source tarball in releases/
	mkdir -p releases
	tar --exclude=./build --exclude=./releases --exclude=./$(VENV) --exclude='__pycache__' \
		--exclude='*.mo' --exclude='.pytest_cache' --transform 's,^\.,acrpdf-$(VERSION),' \
		-czf releases/acrpdf-$(VERSION).tar.gz .

$(DEB):
	$(MAKE) deb

clean:  ## Remove build artifacts
	rm -rf build .pytest_cache src/acrpdf/locale
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
