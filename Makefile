py3ver	= 3.14
python3	= python$(py3ver)
python	= $(python3)
pip3	= pip$(py3ver)
pip	= $(pip3)

pkgname	= consoleserver

MAKEFLAGS += --no-print-directory

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
	git clean -fdx --exclude=$(pkgname).pyz

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
	venv/bin/flake8 src/
	venv/bin/mypy --strict --ignore-missing-imports \
	    --python-version $(py3ver) --no-sqlite-cache src/

venv/bin/flake8: venv/bin/$(pip)
	venv/bin/$(pip) install --quiet flake8

venv/bin/mypy: venv/bin/$(pip)
	venv/bin/$(pip) install --quiet mypy

venv/bin/$(pip):
	$(python) -m venv venv

.PHONY:	run-test
run-test:
	$(MAKE) pybase
	$(MAKE) manifest
	PYTHONUSERBASE=$(PWD)/pybase $(python) -B -m src

pybase:
	PYTHONUSERBASE=$(PWD)/pybase $(pip) install \
	    --quiet --no-cache-dir -r requirements.txt \
	    --user --break-system-packages --no-warn-script-location

.PHONY:	run-pyz
run-pyz: $(pkgname).pyz
	$(python) $(pkgname).pyz

$(pkgname).pyz:
	$(MAKE) manifest
	rm -rf $(pkgname).pkgs $(pkgname).pyz
	PIP_DISABLE_PIP_VERSION_CHECK=1 $(pip) install \
	    --quiet --no-cache-dir -r requirements.txt \
            --target $(pkgname).pkgs
	cp -a src $(pkgname).pkgs/$(pkgname)
	rm -rf $(pkgname).pkgs/$(pkgname)/__pycache__
	$(python) -m zipapp $(pkgname).pkgs \
	    -m $(pkgname).main:main -o $(pkgname).pyz

.PHONY:	manifest
manifest:
	$(MAKE) fetch-files
	$(MAKE) generate-gzip
	$(MAKE) src/staticfiles-manifest.json

.PHONY:	fetch-files
fetch-files:
	@cat src/staticfiles/_index.html				   \
	    | sed -E -n 's!.*"static/sites/([^"]*)".*!\1!p'		   \
	    | sort -u							   \
	    | while read target; do					   \
	    echo "Fetching: https://$$target"				&& \
	    curl -fsSL https://$$target --create-dirs			   \
	        -o src/staticfiles/static/sites/$$target || ! break	;  \
	done

.PHONY:	generate-gzip
generate-gzip:
	@dir='src/staticfiles'						&& \
	find $$dir -type f ! -name '*.gz' -printf '%P\n' | sort -u	   \
	| while read file; do						   \
	    filepath=$$dir/$$file					&& \
	    echo "Generating gzip for $$file"				&& \
	    gzip < $$filepath > $${filepath}.gz || ! break		;  \
	done

.PHONY:	src/staticfiles-manifest.json
src/staticfiles-manifest.json:
	$(MAKE) fetch-files
	$(MAKE) generate-gzip
	@printf '{' > $@
	@dir='src/staticfiles' && comma=''				&& \
	find $$dir -type f ! -name '*.gz' -printf '%P\n' | sort -u	   \
	| while read file; do						   \
	    filepath=$$dir/$$file					&& \
	    echo "Generating ETag for $$file"				&& \
	    etag=$$(openssl dgst -sha256 < $$filepath			   \
	            | sed 's/^.*[^0-9A-Fa-f]//')			&& \
	    len=$$(wc -c < $$filepath)					&& \
	    if [ -f $${filepath}.gz ]; then				   \
	        gzlen=$$(wc -c < $${filepath}.gz)			;  \
	    else							   \
	        gzlen=0							;  \
	    fi								&& \
	    case "$$filepath" in					   \
	    *.css)  t='css'						;; \
	    *.html) t='html'						;; \
	    *.js)   t='javascript'					;; \
	    *) echo "ERROR: unknown suffix for $$filepath" 1>&2; exit 1	;; \
	    esac							&& \
	    type="text/$$t; charset=utf-8"				&& \
	    (								   \
	        printf '%s\n' "$$comma"					&& \
	        printf '  "%s": {\n' "$$file"				&& \
	        printf '    "etag": "\\"%s\\"",\n' "$$etag"		&& \
	        printf '    "content-length": %d,\n' "$$len"		&& \
	        printf '    "content-type": "%s"' "$$type"		&& \
	        if [ "$$gzlen" -gt 0 ]; then				   \
	            printf ',\n'					&& \
	            printf '    "gzip": {\n'				&& \
	            printf '      "etag": "\\"gzip-%s\\"",\n' "$$etag"	&& \
	            printf '      "content-length": %d\n' "$$gzlen"	&& \
	            printf '    }'					;  \
	        fi							&& \
	        printf '\n  }'						   \
	    ) >> $@							&& \
	    comma=','							;  \
	done
	@printf '\n}\n' >> $@
