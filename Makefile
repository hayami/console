py3ver	= 3.14
python3	= python$(py3ver)
python	= $(python3)
pip3	= pip$(py3ver)
pip	= $(pip3)

.PHONY:	default
default: usage

.PHONY:	run
run: run-using-zip

.PHONY:	usage
usage:
	@echo 'make usage'
	@echo 'make distclean'
	@echo 'make clean'
	@echo 'make check'
	@echo 'make js-check'
	@echo 'make py-check'
	@echo 'make run'
	@echo 'make run-using-venv'
	@echo 'make run-using-pybase'
	@echo 'make run-using-zip'

.PHONY:	distclean
distclean:
	git clean -fdx

.PHONY:	clean
clean:
	git clean -fdx --exclude=requirements.zip

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
	venv/bin/flake8 terminalserver.py
	venv/bin/mypy --strict --ignore-missing-imports \
	    --python-version $(py3ver) terminalserver.py

venv/bin/flake8: venv/bin/$(pip)
	venv/bin/$(pip) install --quiet flake8

venv/bin/mypy: venv/bin/$(pip)
	venv/bin/$(pip) install --quiet mypy

venv/bin/$(pip):
	$(python) -m venv venv

.PHONY:	run-using-venv
run-using-venv: venv/bin/uvicorn
	venv/bin/$(python) terminalserver.py

venv/bin/uvicorn: venv/bin/$(pip)
	venv/bin/$(pip) install --quiet -r requirements.txt

.PHONY:	run-using-pybase
run-using-pybase: pybase
	PYTHONUSERBASE=$(PWD)/pybase $(python) -B terminalserver.py

pybase:
	PYTHONUSERBASE=$(PWD)/pybase $(pip) install \
	    --break-system-packages --no-warn-script-location \
	    --quiet --user --no-cache-dir -r requirements.txt

.PHONY:	run-using-zip
run-using-zip: requirements.zip
	PYTHONPATH=requirements.zip $(python) -B terminalserver.py

requirements.zip:
	rm -rf requirements.pkgs
	$(pip) install --quiet --no-cache-dir \
	    -r requirements.txt --target requirements.pkgs
	cd requirements.pkgs && zip --quiet -r ../requirements.zip .
