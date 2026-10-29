.PHONY: all test verify clean run

all:
	python3 pipeline.py run

run:
	python3 pipeline.py run

test:
	python3 pipeline.py test

verify:
	python3 pipeline.py test

clean:
	python3 pipeline.py clean
