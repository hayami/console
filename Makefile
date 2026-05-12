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
	@echo 'make check-all'
	@echo 'make check-js'
	@echo 'make check-py'
	@echo 'make run-test'
	@echo 'make run-pyz'

.PHONY:	distclean
distclean:
	git clean -fdx

.PHONY:	clean
clean:
	git clean -fdx --exclude=consoleserver.pyz

.PHONY:	check-all
check-all: check-js check-py

.PHONY:	check-js
check-js: node_modules
	npm run lint
	npm run check

node_modules:
	npm install --cache npm-cache --quiet --save-dev

.PHONY:	check-py
check-py: venv/bin/flake8 venv/bin/mypy
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

.PHONY:	run-pyz
run-pyz: consoleserver.pyz
	$(python) consoleserver.pyz

consoleserver.pyz:
	rm -rf consoleserver.pkgs consoleserver.pyz
	PIP_DISABLE_PIP_VERSION_CHECK=1 $(pip) install \
	    --quiet --no-cache-dir -r requirements.txt \
            --target consoleserver.pkgs
	cp -a consoleserver consoleserver.pkgs
	rm -rf consoleserver.pkgs/consoleserver/__pycache__
	$(python) -m zipapp consoleserver.pkgs \
	    -m consoleserver.main:main -o consoleserver.pyz

.PHONY:	consoleserver/staticfiles-manifest.json
consoleserver/staticfiles-manifest.json:
	@(printf '{'						&& \
	    dir='consoleserver/staticfiles'			&& \
	    comma=''						&& \
	    (cd $$dir && find $$(ls -A)  -type f -print) | sort -u \
	    | while read file; do				   \
	        et=$$(openssl dgst -sha256 < $$dir/$$file	   \
	              | sed 's/^.*[^0-9A-Fa-f]//')		&& \
	        cl=$$(wc -c  < $$dir/$$file)			&& \
	        case "$$file" in				   \
	        *.css)  t='css'					;; \
	        *.html) t='html'				;; \
	        *.js)   t='javascript'				;; \
	        esac						&& \
	        ct="text/$$t; charset=utf-8"			&& \
	        printf '%s\n' "$$comma"				&& \
	        printf '    "%s": {\n' "$$file"			&& \
	        printf '        "etag": "\\"%s\\"",\n' "$$et"	&& \
	        printf '        "content-length": %d,\n' "$$cl"	&& \
	        printf '        "content-type": "%s"\n' "$$ct"	&& \
	        printf '    }'					&& \
	        comma=','					;  \
	    done						&& \
	printf '\n}\n') > $@
