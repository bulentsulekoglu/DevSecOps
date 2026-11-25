import pytest
from fastapi.testclient import TestClient

import main

USER = {"X-Remote-User": "test.kullanici"}


@pytest.fixture()
def client():
    """Gerçek PostgreSQL'e karşı çalışır; her testten önce tablolar boşaltılır."""
    with TestClient(main.app) as c:
        with main.db() as conn:
            conn.execute("TRUNCATE movements, products, loans RESTART IDENTITY CASCADE")
        c.headers.update(USER)
        yield c
