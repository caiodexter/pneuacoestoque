
from pathlib import Path
import os
import sqlite3
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

eng = create_engine(url, pool_pre_ping=True)

with sqlite3.connect(src) as con:
    produtos = pd.read_sql_query("SELECT * FROM produtos", con)

with eng.begin() as conn:
    conn.execute(text("""
    CREATE TABLE IF NOT EXISTS produtos (
        id BIGSERIAL PRIMARY KEY,
        origem TEXT NOT NULL DEFAULT 'PNEUS COM NOTA',
        descricao TEXT NOT NULL,
        marca TEXT NOT NULL,
        preco_unitario NUMERIC NOT NULL DEFAULT 0,
        quantidade INTEGER NOT NULL DEFAULT 0,
        ativo BOOLEAN DEFAULT TRUE,
        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """))
    conn.execute(text("""
    CREATE TABLE IF NOT EXISTS movimentacoes (
        id BIGSERIAL PRIMARY KEY,
        produto_id BIGINT NOT NULL,
        tipo TEXT NOT NULL,
        quantidade INTEGER NOT NULL,
        usuario TEXT,
        nf TEXT,
        fornecedor_destino TEXT,
        observacao TEXT,
        estoque_anterior INTEGER,
        estoque_atual INTEGER,
        data_movimento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """))
    conn.execute(text("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id BIGSERIAL PRIMARY KEY,
        nome TEXT UNIQUE NOT NULL,
        senha TEXT NOT NULL,
        ativo BOOLEAN DEFAULT TRUE
    )
    """))
    count = conn.execute(text("SELECT COUNT(*) FROM produtos")).scalar_one()
    if count == 0:
        produtos = produtos.drop(columns=[c for c in ["id","criado_em","atualizado_em"] if c in produtos.columns])
        produtos["ativo"] = produtos["ativo"].astype(bool)
        produtos.to_sql("produtos", conn, if_exists="append", index=False)
    ucount = conn.execute(text("SELECT COUNT(*) FROM usuarios")).scalar_one()
    if ucount == 0:
        conn.execute(text("INSERT INTO usuarios(nome,senha,ativo) VALUES ('admin','admin123',TRUE)"))

print("Migração concluída.")
