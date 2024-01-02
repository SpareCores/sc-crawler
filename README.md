docker run --rm -ti -v $PWD:/data python:3.11 bash
pip install -y alembic

# Prepare env
$ make editable-env

# Init DB
$ make init_db

# Fill it up
python -m sc_crawler.main

# Example query
```python
import sc_crawler
sc_crawler.main.query_dc()
```