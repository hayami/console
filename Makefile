py3ver	= 3.14
python3	= python$(py3ver)
python	= $(python3)
pip3	= pip$(py3ver)
pip	= $(pip3)

.PHONY:	default
default: usage

.PHONY:	usage
usage:
	@echo 'make usage'
	@echo 'make distclean'
	@echo 'make clean'
	@echo 'make check'
	@echo 'make js-check'
	@echo 'make py-check'
	@echo 'make run-test'
	@echo 'make run-using-pyz'

.PHONY:	distclean
distclean:
	git clean -fdx

.PHONY:	clean
clean:
	git clean -fdx --exclude=console.pyz

.PHONY:	check
check: js-check py-check

.PHONY:	js-check
js-check: node_modules
	npm run lint
	npm run check

node_modules:
	npm install --cache npm-cache --quiet --save-dev

.PHONY:	py-check
py-check: venv/bin/flake8 venv/bin/mypy
	venv/bin/flake8 consoleserver/
	venv/bin/mypy --strict --ignore-missing-imports \
	    --python-version $(py3ver) consoleserver/

venv/bin/flake8: venv/bin/$(pip)
	venv/bin/$(pip) install --quiet flake8

venv/bin/mypy: venv/bin/$(pip)
	venv/bin/$(pip) install --quiet mypy

venv/bin/$(pip):
	$(python) -m venv venv

.PHONY:	run-test
run-test: pybase
	PYTHONUSERBASE=$(PWD)/pybase $(python) -B -m consoleserver

pybase:
	PYTHONUSERBASE=$(PWD)/pybase $(pip) install \
	    --quiet --no-cache-dir -r requirements.txt \
	    --user --break-system-packages --no-warn-script-location

.PHONY:	run-using-pyz
run-using-pyz: console.pyz
	$(python) -B console.pyz

.PHONY:	console.pyz
console.pyz:
	rm -rf console.pkgs console.pyz
	PIP_DISABLE_PIP_VERSION_CHECK=1 $(pip) install \
	    --quiet --no-cache-dir -r requirements.txt --target console.pkgs
	cp -a consoleserver console.pkgs
	$(python) -B -m zipapp console.pkgs \
	    -m consoleserver.main:main -o console.pyz
