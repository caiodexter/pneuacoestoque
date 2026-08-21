from pathlib import Path
import os, sqlite3
import pandas as pd
from sqlalchemy import create_engine, text

BASE = Path(__file__).resolve().parent
src = BASE / "estoque.db"
url = os.getenv("DATABASE_URL")
if not url:
    raise SystemExit("Defina DATABASE_URL antes de executar.")

if url.startswith("postgres://"):
    url = "postgresql+psycopg://" + url[len("postgres://"):]
elif url.startswith("postgresql://"):
    url = "postgresql+psycopg://" + url[len("postgresql://"):]

engine = create_engine(url, pool_pre_ping=True, future=True)

with sqlite3.connect(src) as c:
    produtos = pd.read_sql_query("""
        SELECT origem, descricao, marca, preco_unitario, quantidade
        FROM produtos WHERE ativo=1
    """, c)

with engine.begin() as conn:
    # Mantém os usuários. Substitui somente estoque e histórico antigo.
    conn.execute(text("DELETE FROM movimentacoes"))
    conn.execute(text("DELETE FROM produtos"))
    for r in produtos.to_dict("records"):
        conn.execute(text("""
            INSERT INTO produtos
            (origem, descricao, marca, preco_unitario, quantidade, ativo)
            VALUES (:origem,:descricao,:marca,:preco,:qtd,TRUE)
        """), {
            "origem": r["origem"],
            "descricao": r["descricao"],
            "marca": r["marca"],
            "preco": float(r["preco_unitario"]),
            "qtd": int(r["quantidade"]),
        })
print("Base online atualizada com PNEUS COM NOTA + DIESEL PNEUS.")
