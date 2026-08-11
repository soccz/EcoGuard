.PHONY: test reproduce verify clean-generated

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

reproduce:
	./scripts/reproduce.sh

verify:
	./scripts/verify_release.sh

clean-generated:
	python3 -c 'import shutil; shutil.rmtree("artifacts/generated", ignore_errors=True)'
