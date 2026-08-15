.PHONY: proof test reproduce benchmark verify forest-xai-test forest-xai-verify forest-xai-public-verify forest-xai-reconstruction-verify clean-generated

proof:
	python3 scripts/proof_summary.py --root .

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

forest-xai-verify: forest-xai-public-verify forest-xai-reconstruction-verify

forest-xai-public-verify:
	python3 -m research.forest_xai.scripts.verify_public_demo

forest-xai-reconstruction-verify:
	python3 -m research.forest_xai.scripts.verify_reconstruction

clean-generated:
	python3 -c 'import shutil; shutil.rmtree("artifacts/generated", ignore_errors=True); shutil.rmtree("artifacts/generated-benchmarks", ignore_errors=True)'
