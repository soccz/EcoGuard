.PHONY: test reproduce benchmark verify clean-generated

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

reproduce:
	./scripts/reproduce.sh

benchmark:
	PYTHONPATH=src python3 -m ecoguard benchmark --root . --output artifacts/generated-benchmarks

verify:
	./scripts/verify_release.sh

clean-generated:
	python3 -c 'import shutil; shutil.rmtree("artifacts/generated", ignore_errors=True); shutil.rmtree("artifacts/generated-benchmarks", ignore_errors=True)'
