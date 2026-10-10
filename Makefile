py3ver	= 3
#py3ver	= 3.12

pkgname	= terminalserver

export	LC_ALL = C
SRCS	:= $(shell find src -type f -print | sort -u)
LOCALS	:= $(shell find docroot -name sites -prune -o -type f -print \
	| grep -E '\.(css|html|js)$$' | sort -u)
REMOTES	:= $(shell sed -E -n 's!.*"(sites/[^"]*)".*!docroot/\1!p' \
	< docroot/_index.html | sort -u)
FONTS	:= $(shell sed -E -n 's!.*"(sites/[^"]*)".*!docroot/\1!p' \
	< docroot/terminal.css | sort -u)
DOCS	= $(LOCALS) $(REMOTES)
GZIPS	= $(DOCS:=.gz)

BIOME_URL = https://github.com/biomejs/biome/releases/download/@biomejs/biome@2.5.14/biome-linux-x64

MAKEFLAGS += --no-print-directory

.PHONY: default
default: usage

.PHONY: usage
usage:
	@echo 'make usage'
	@echo 'make distclean'
	@echo 'make clean'
	@echo 'make check-all'
	@echo 'make check-js'
	@echo 'make check-py'
	@echo 'make run-test-server'
	@echo 'make run-pyz-server'

.PHONY: distclean
distclean:
	git clean -fdx

.PHONY: clean
clean:
	git clean -fdx --exclude=docroot/sites

.PHONY: check-all
check-all: check-js check-py

.PHONY: check-js
check-js:
	@if [ -x ./biome ]; then \
	    biome=./biome; \
	else \
	    if ! biome=$$(which biome 2> /dev/null); then \
	        (set -x; curl -fL $(BIOME_URL) -o biome) \
	        && chmod +x biome \
	        && biome=./biome; \
	    fi; \
	fi; \
	set -x; $$biome check docroot/terminal.js

#.PHONY: format-js
#format-js:
#	biome format --write docroot/terminal.js

.PHONY: check-py
check-py: venv/bin/flake8 venv/bin/mypy
	venv/bin/flake8 src/
	venv/bin/mypy --strict --ignore-missing-imports --no-sqlite-cache src/

venv/bin/flake8: venv/bin/pip$(py3ver)
	venv/bin/pip$(py3ver) install --quiet flake8

venv/bin/mypy: venv/bin/pip$(py3ver)
	venv/bin/pip$(py3ver) install --quiet mypy

venv/bin/pip$(py3ver):
	python$(py3ver) -m venv venv

.PHONY: run-test-server
run-test-server: pybase docroot.json
	PYTHONUSERBASE=$(PWD)/pybase python$(py3ver) -B -m src

pybase: requirements.txt
	PYTHONUSERBASE=$(PWD)/pybase pip3 install \
	    --quiet --no-cache-dir -r requirements.txt \
	    --user --break-system-packages --no-warn-script-location

.PHONY: run-pyz-server
run-pyz-server: $(pkgname).pyz
	python$(py3ver) $(pkgname).pyz

$(pkgname).pyz: docroot.json requirements.txt $(SRCS)
	rm -rf $(pkgname).pkgs $(pkgname).pyz
	PIP_DISABLE_PIP_VERSION_CHECK=1 pip3 install \
	    --quiet --no-cache-dir -r requirements.txt \
	    --target $(pkgname).pkgs
	mkdir $(pkgname).pkgs/$(pkgname)
	cp -a docroot docroot.json src/* $(pkgname).pkgs/$(pkgname)/
	rm -rf $(pkgname).pkgs/$(pkgname)/__pycache__
	python$(py3ver) -m zipapp $(pkgname).pkgs \
	    -m $(pkgname).main:main -o $(pkgname).pyz

docroot.json: $(GZIPS) $(FONTS)
	@printf '{' > $@
	@dir='docroot' && comma=''					&& \
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
	    *.css)  t='text/css'					;; \
	    *.html) t='text/html'					;; \
	    *.js)   t='text/javascript'					;; \
	    *.ttf)  t='font/ttf'					;; \
	    *) echo "ERROR: unknown suffix for $$filepath" 1>&2; exit 1	;; \
	    esac							&& \
	    type="$$t; charset=utf-8"					&& \
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

$(GZIPS): %.gz: %
	@gzip < $< > $@

$(REMOTES) $(FONTS):
	@out=$@ \
	&& url=https://$${out#docroot/sites/} \
	&& echo "Fetching: $$url" \
	&& curl -fL --create-dirs -o $$out $$url
