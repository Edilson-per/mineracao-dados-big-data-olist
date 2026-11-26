"""Etapa 2 - Tratamento (Transform + Load) e Governanca.

Limpa, integra e prepara os dados brutos. Gera:
  data/processed/pedidos.parquet   -> 1 linha por pedido (com avaliacao, frete, atraso)
  data/processed/clientes_rfm.parquet -> 1 linha por cliente unico (Recencia, Frequencia, Valor)
  reports/governanca.json          -> o que foi encontrado e corrigido (qualidade dos dados)
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
RAW = RAIZ / "data" / "raw"
PROC = RAIZ / "data" / "processed"
REPORTS = RAIZ / "reports"

DATAS_PEDIDO = ["order_purchase_timestamp", "order_approved_at",
                "order_delivered_carrier_date", "order_delivered_customer_date",
                "order_estimated_delivery_date"]


def ler(nome, **kw):
    return pd.read_csv(RAW / f"olist_{nome}_dataset.csv", **kw)


def main():
    PROC.mkdir(parents=True, exist_ok=True)
    gov = {}

    # ---------- Extract ----------
    pedidos = ler("orders", parse_dates=DATAS_PEDIDO)
    itens = ler("order_items")
    pagamentos = ler("order_payments")
    reviews = ler("order_reviews", parse_dates=["review_creation_date"])
    clientes = ler("customers")
    produtos = ler("products")
    traducao = pd.read_csv(RAW / "product_category_name_translation.csv")

    # ---------- Diagnostico de qualidade (antes) ----------
    gov["nulos_antes"] = {
        "pedidos_sem_data_entrega": int(pedidos["order_delivered_customer_date"].isna().sum()),
        "produtos_sem_categoria": int(produtos["product_category_name"].isna().sum()),
        "reviews_sem_comentario": int(reviews["review_comment_message"].isna().sum()),
        "reviews_total": int(len(reviews)),
    }

    # ---------- Transform ----------
    # 1) Reviews duplicadas: mesmo pedido avaliado mais de uma vez -> fica a mais recente
    antes = len(reviews)
    reviews = (reviews.sort_values("review_creation_date")
                      .drop_duplicates("order_id", keep="last"))
    gov["reviews_duplicadas_removidas"] = int(antes - len(reviews))

    # 2) Inconsistencias temporais: entrega antes da compra
    inconsist = (pedidos["order_delivered_customer_date"] < pedidos["order_purchase_timestamp"]).sum()
    gov["entregas_antes_da_compra"] = int(inconsist)

    # 3) Mantem apenas pedidos entregues com data de entrega valida
    status = pedidos["order_status"].value_counts().to_dict()
    gov["status_pedidos"] = {k: int(v) for k, v in status.items()}
    entregues = pedidos[(pedidos["order_status"] == "delivered")
                        & pedidos["order_delivered_customer_date"].notna()
                        & (pedidos["order_delivered_customer_date"] >= pedidos["order_purchase_timestamp"])].copy()
    gov["pedidos_descartados"] = int(len(pedidos) - len(entregues))

    # 4) Categorias: preenche faltantes e traduz
    produtos["product_category_name"] = produtos["product_category_name"].fillna("sem_categoria")
    produtos = produtos.merge(traducao, on="product_category_name", how="left")

    # 5) Agrega itens por pedido (valor, frete, qtd, categoria principal)
    itens = itens.merge(produtos[["product_id", "product_category_name", "product_weight_g"]],
                        on="product_id", how="left")
    agg_itens = itens.groupby("order_id").agg(
        valor_itens=("price", "sum"),
        valor_frete=("freight_value", "sum"),
        qtd_itens=("order_item_id", "count"),
        qtd_vendedores=("seller_id", "nunique"),
        peso_total_g=("product_weight_g", "sum"),
        categoria=("product_category_name", "first"),
    ).reset_index()
    agg_pag = pagamentos.groupby("order_id").agg(
        valor_pago=("payment_value", "sum"),
        parcelas=("payment_installments", "max"),
        tipo_pagamento=("payment_type", "first"),
    ).reset_index()

    # 6) Features derivadas
    e = entregues
    e["dias_entrega"] = (e["order_delivered_customer_date"] - e["order_purchase_timestamp"]).dt.total_seconds() / 86400
    e["dias_atraso"] = (e["order_delivered_customer_date"] - e["order_estimated_delivery_date"]).dt.total_seconds() / 86400
    e["atrasou"] = (e["dias_atraso"] > 0).astype(int)
    e["prazo_prometido_dias"] = (e["order_estimated_delivery_date"] - e["order_purchase_timestamp"]).dt.total_seconds() / 86400

    base = (e.merge(agg_itens, on="order_id", how="inner")
             .merge(agg_pag, on="order_id", how="left")
             .merge(reviews[["order_id", "review_score", "review_comment_message"]], on="order_id", how="inner")
             .merge(clientes[["customer_id", "customer_unique_id", "customer_state"]], on="customer_id", how="left"))
    base["frete_pct"] = base["valor_frete"] / base["valor_itens"].replace(0, np.nan)
    base["insatisfeito"] = (base["review_score"] <= 2).astype(int)

    # 7) Outliers de tempo de entrega (> 120 dias) sao ruido operacional
    outl = (base["dias_entrega"] > 120).sum()
    base = base[base["dias_entrega"] <= 120]
    gov["outliers_entrega_removidos"] = int(outl)

    # 8) Pagamento faltante -> usa soma de itens + frete
    falt_pag = base["valor_pago"].isna().sum()
    base["valor_pago"] = base["valor_pago"].fillna(base["valor_itens"] + base["valor_frete"])
    base["parcelas"] = base["parcelas"].fillna(1)
    base["tipo_pagamento"] = base["tipo_pagamento"].fillna("desconhecido")
    gov["pagamentos_faltantes_imputados"] = int(falt_pag)
    gov["peso_faltante_imputado"] = int(base["peso_total_g"].isna().sum())
    base["peso_total_g"] = base["peso_total_g"].fillna(base["peso_total_g"].median())

    # ---------- Load ----------
    base.to_parquet(PROC / "pedidos.parquet", index=False)

    # Tabela RFM por cliente unico (para clusterizacao)
    ref = base["order_purchase_timestamp"].max() + pd.Timedelta(days=1)
    rfm = base.groupby("customer_unique_id").agg(
        recencia_dias=("order_purchase_timestamp", lambda s: (ref - s.max()).days),
        frequencia=("order_id", "nunique"),
        valor_total=("valor_pago", "sum"),
        nota_media=("review_score", "mean"),
        estado=("customer_state", "first"),
    ).reset_index()
    rfm.to_parquet(PROC / "clientes_rfm.parquet", index=False)

    gov["linhas_finais_pedidos"] = int(len(base))
    gov["clientes_unicos"] = int(len(rfm))
    gov["clientes_que_compraram_mais_de_uma_vez_pct"] = round(100 * (rfm["frequencia"] > 1).mean(), 2)
    (REPORTS / "governanca.json").write_text(json.dumps(gov, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(gov, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
