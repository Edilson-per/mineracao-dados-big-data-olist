"""Etapa 1 - Coleta (Extract).

Baixa os 9 arquivos CSV do dataset publico da Olist (e-commerce brasileiro,
2016-2018) direto do repositorio oficial da empresa no GitHub e registra
as metricas de Volume, Variedade e Velocidade em reports/tres_vs.json.
"""
import json
import time
import urllib.request
from pathlib import Path

import pandas as pd

BASE_URL = "https://raw.githubusercontent.com/olist/work-at-olist-data/master/datasets/"
ARQUIVOS = [
    "olist_customers_dataset.csv",
    "olist_geolocation_dataset.csv",
    "olist_order_items_dataset.csv",
    "olist_order_payments_dataset.csv",
    "olist_order_reviews_dataset.csv",
    "olist_orders_dataset.csv",
    "olist_products_dataset.csv",
    "olist_sellers_dataset.csv",
    "product_category_name_translation.csv",
]

RAIZ = Path(__file__).resolve().parents[1]
RAW = RAIZ / "data" / "raw"
REPORTS = RAIZ / "reports"


def baixar(nome: str, tentativas: int = 3) -> Path:
    destino = RAW / nome
    if destino.exists() and destino.stat().st_size > 0:
        print(f"  [cache] {nome}")
        return destino
    for i in range(1, tentativas + 1):
        try:
            print(f"  baixando {nome} (tentativa {i})...")
            urllib.request.urlretrieve(BASE_URL + nome, destino)
            return destino
        except Exception as erro:  # rede instavel: tenta de novo
            print(f"    falhou: {erro}")
            time.sleep(2 * i)
    raise RuntimeError(f"Nao foi possivel baixar {nome}")


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    print("Coletando dataset Olist...")

    inventario = []
    for nome in ARQUIVOS:
        caminho = baixar(nome)
        df = pd.read_csv(caminho)
        inventario.append({
            "arquivo": nome,
            "tamanho_mb": round(caminho.stat().st_size / 1_048_576, 2),
            "linhas": int(len(df)),
            "colunas": int(df.shape[1]),
            "tipos": sorted({str(t) for t in df.dtypes}),
        })

    # Velocidade: taxa de geracao de pedidos e avaliacoes no periodo
    pedidos = pd.read_csv(RAW / "olist_orders_dataset.csv",
                          parse_dates=["order_purchase_timestamp"])
    ts = pedidos["order_purchase_timestamp"]
    dias = (ts.max() - ts.min()).days
    por_mes = pedidos.groupby(ts.dt.to_period("M")).size()

    tres_vs = {
        "volume": {
            "arquivos": len(inventario),
            "total_mb": round(sum(i["tamanho_mb"] for i in inventario), 1),
            "total_linhas": sum(i["linhas"] for i in inventario),
            "por_arquivo": inventario,
        },
        "variedade": {
            "formatos": ["CSV estruturado", "texto livre (comentarios)",
                         "datas/horarios", "geolocalizacao (lat/lng)",
                         "categoricos", "numericos (preco, frete, peso)"],
            "tabelas_relacionais": len(inventario),
        },
        "velocidade": {
            "periodo_inicio": str(ts.min().date()),
            "periodo_fim": str(ts.max().date()),
            "dias": int(dias),
            "pedidos_por_dia_medio": round(len(pedidos) / dias, 1),
            "pico_pedidos_mes": int(por_mes.max()),
            "mes_pico": str(por_mes.idxmax()),
        },
    }
    (REPORTS / "tres_vs.json").write_text(
        json.dumps(tres_vs, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"OK: {tres_vs['volume']['total_linhas']:,} linhas, "
          f"{tres_vs['volume']['total_mb']} MB em {len(inventario)} arquivos.")


if __name__ == "__main__":
    main()
