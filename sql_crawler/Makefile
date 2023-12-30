alembic-init:
	@alembic init schema

init_db:
	@python -c "from sc_crawler.models import init_db; init_db()"

editable-env:
	@pip install --editable .

.PHONY: alembic-init editable-env init_db