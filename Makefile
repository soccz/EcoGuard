.PHONY: test reproduce benchmark verify forest-xai-test forest-xai-verify clean-generated

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

reproduce:
	./scripts/reproduce.sh

benchmark:
	PYTHONPATH=src python3 -m ecoguard benchmark --root . --output artifacts/generated-benchmarks

verify:
	./scripts/verify_release.sh

forest-xai-test:
	python3 -m unittest discover -s research/forest_xai/tests -v

forest-xai-verify:
	python3 -m research.forest_xai.scripts.verify_public_demo

clean-generated:
	python3 -c 'import shutil; shutil.rmtree("artifacts/generated", ignore_errors=True); shutil.rmtree("artifacts/generated-benchmarks", ignore_errors=True)'
