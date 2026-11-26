"""Etapa 3 - Mineracao de Dados e Visualizacao.

Tecnicas aplicadas (e por que):
  1. CLASSIFICACAO (Random Forest) - prever se um pedido recebera avaliacao
     ruim (nota 1 ou 2). Escolhida porque a pergunta de negocio e "quais
     fatores levam o cliente a ficar insatisfeito?" e a floresta aleatoria
     lida bem com relacoes nao-lineares e mostra a importancia de cada fator.
  2. CLUSTERIZACAO (K-Means sobre RFM) - segmentar clientes por Recencia,
     Frequencia e Valor. Nao ha rotulo pronto de "tipo de cliente": o
     agrupamento descobre os perfis sozinho. O k e escolhido pelo
     coeficiente de silhueta.
  3. MINERACAO DE TEXTO (frequencia de termos) - comparar as palavras dos
     comentarios de clientes insatisfeitos x satisfeitos, para confirmar
     com a voz do cliente o que o modelo aprendeu com os numeros.

Saidas: reports/resultados.json e reports/figuras/*.png
"""
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (classification_report, roc_auc_score,
                             silhouette_score)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

RAIZ = Path(__file__).resolve().parents[1]
PROC = RAIZ / "data" / "processed"
REPORTS = RAIZ / "reports"
FIG = REPORTS / "figuras"
SEED = 42

# Paleta (validada para daltonismo): azul = dado principal, laranja = destaque
AZUL, LARANJA, CINZA = "#2a78d6", "#eb6834", "#b9b8b2"
TXT, TXT2, FUNDO = "#0b0b0b", "#52514e", "#ffffff"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 20,
    "axes.titlesize": 20, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "axes.titlepad": 16, "axes.labelsize": 20, "axes.labelcolor": TXT2,
    "axes.edgecolor": CINZA, "axes.spines.top": False, "axes.spines.right": False,
    "xtick.color": TXT2, "ytick.color": TXT2, "figure.facecolor": FUNDO,
    "axes.facecolor": FUNDO, "savefig.dpi": 200, "savefig.bbox": "tight",
    "text.color": TXT,
})


def salvar(fig, nome):
    fig.savefig(FIG / nome)
    plt.close(fig)


def pct(v):
    return f"{v:.0f}%" if v >= 10 else f"{v:.1f}%"


# --------------------------------------------------------------------------
def analise_descritiva(p, res):
    res["descritiva"] = {
        "pedidos_analisados": int(len(p)),
        "nota_media": round(p["review_score"].mean(), 2),
        "insatisfeitos_pct": round(100 * p["insatisfeito"].mean(), 1),
        "atrasados_pct": round(100 * p["atrasou"].mean(), 1),
        "dias_entrega_mediana": round(p["dias_entrega"].median(), 1),
        "prazo_prometido_mediana": round(p["prazo_prometido_dias"].median(), 1),
        "entrega_antes_do_prazo_media_dias": round(-p["dias_atraso"].mean(), 1),
        "insatisfeitos_no_prazo_pct": round(100 * p.loc[p.atrasou == 0, "insatisfeito"].mean(), 1),
        "insatisfeitos_atrasados_pct": round(100 * p.loc[p.atrasou == 1, "insatisfeito"].mean(), 1),
        "nota_media_no_prazo": round(p.loc[p.atrasou == 0, "review_score"].mean(), 2),
        "nota_media_atrasados": round(p.loc[p.atrasou == 1, "review_score"].mean(), 2),
    }

    # Pedidos por mes (Velocidade)
    mes = p.groupby(p["order_purchase_timestamp"].dt.to_period("M")).size()
    mes = mes[(mes.index >= pd.Period("2017-01", "M")) & (mes.index <= pd.Period("2018-08", "M"))]
    fig, ax = plt.subplots(figsize=(11, 5))
    x = mes.index.to_timestamp()
    ax.plot(x, mes.values, color=AZUL, lw=2.5)
    ax.fill_between(x, mes.values, color=AZUL, alpha=0.08)
    pico = mes.idxmax()
    ax.scatter([pico.to_timestamp()], [mes.max()], s=80, color=LARANJA, zorder=3,
               edgecolor=FUNDO, linewidth=2)
    ax.annotate(f"Pico: {mes.max():,} pedidos".replace(",", ".") + f"\n(Black Friday, {pico.strftime('%m/%Y')})",
                (pico.to_timestamp(), mes.max()), xytext=(-250, -10), textcoords="offset points",
                fontsize=19, color=TXT)
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%Y"))
    ax.set_ylabel("pedidos / mês")
    ax.grid(axis="y", color="#ececea")
    ax.set_ylim(0)
    salvar(fig, "01_pedidos_por_mes.png")
    res["pedidos_por_mes"] = {str(k): int(v) for k, v in mes.items()}

    # Insatisfacao por faixa de atraso (insight principal)
    faixas = pd.cut(p["dias_atraso"], [-1000, -10, -3, 0, 3, 7, 14, 1000],
                    labels=["10+ dias\nadiantado", "3-10\nadiantado", "0-3\nadiantado",
                            "1-3\natrasado", "4-7\natrasado", "8-14\natrasado", "15+ dias\natrasado"])
    tab = p.groupby(faixas, observed=True)["insatisfeito"].agg(["mean", "size"])
    tab["mean"] *= 100
    fig, ax = plt.subplots(figsize=(13, 6))
    cores = [AZUL if i < 3 else LARANJA for i in range(len(tab))]
    barras = ax.bar(range(len(tab)), tab["mean"], color=cores, width=0.68)
    for b, v in zip(barras, tab["mean"]):
        ax.text(b.get_x() + b.get_width() / 2, v + 1.2, pct(v), ha="center", fontsize=21,
                fontweight="bold", color=TXT)
    ax.set_xticks(range(len(tab)), tab.index, fontsize=17)
    ax.set_yticks([])
    ax.spines["left"].set_visible(False)
    ax.set_xlabel("entrega em relação ao prazo prometido")
    ax.set_ylabel("% com nota 1 ou 2")
    salvar(fig, "02_insatisfacao_por_atraso.png")
    res["insatisfacao_por_faixa_atraso"] = {k.replace("\n", " "): round(v, 1) for k, v in tab["mean"].items()}

    # Curiosidade: pedidos com mais de um vendedor
    vend = p.groupby(np.where(p["qtd_vendedores"] > 1, "2+ vendedores", "1 vendedor"))["insatisfeito"].mean() * 100
    res["curiosidade_vendedores"] = {k: round(v, 1) for k, v in vend.items()}
    multi = p[p["qtd_vendedores"] > 1]
    res["curiosidade_vendedores"]["pedidos_multivendedor"] = int(len(multi))
    res["curiosidade_vendedores"]["atrasados_multivendedor_pct"] = round(100 * multi["atrasou"].mean(), 1)
    res["curiosidade_vendedores"]["atrasados_1_vendedor_pct"] = round(100 * p.loc[p.qtd_vendedores == 1, "atrasou"].mean(), 1)
    # O que dizem os insatisfeitos de pedidos multi-vendedor? (entrega parcial)
    neg_multi = multi.loc[multi.review_score <= 2, "review_comment_message"].dropna().str.lower()
    parcial = neg_multi.str.contains(r"falt|apenas|só um|so um|somente|um dos|uma das|outro|"
                                     r"não recebi|nao recebi|ainda não|ainda nao")
    res["curiosidade_vendedores"]["comentarios_neg_multivendedor"] = int(len(neg_multi))
    res["curiosidade_vendedores"]["citam_entrega_parcial_pct"] = round(100 * parcial.mean(), 1)

    # Por estado
    est = p.groupby("customer_state").agg(atraso=("atrasou", "mean"), insat=("insatisfeito", "mean"),
                                         n=("order_id", "size"))
    est = est[est.n >= 300]
    res["estados"] = {
        "maior_atraso": est["atraso"].idxmax(), "maior_atraso_pct": round(100 * est["atraso"].max(), 1),
        "menor_atraso": est["atraso"].idxmin(), "menor_atraso_pct": round(100 * est["atraso"].min(), 1),
        "corr_atraso_insatisfacao": round(est["atraso"].corr(est["insat"]), 2),
    }


# --------------------------------------------------------------------------
FEATURES = {
    "dias_entrega": "Dias até a entrega",
    "dias_atraso": "Atraso vs. prazo (dias)",
    "prazo_prometido_dias": "Prazo prometido (dias)",
    "valor_itens": "Valor dos itens (R$)",
    "valor_frete": "Valor do frete (R$)",
    "frete_pct": "Frete / valor dos itens",
    "qtd_itens": "Quantidade de itens",
    "qtd_vendedores": "Nº de vendedores",
    "peso_total_g": "Peso total (g)",
    "parcelas": "Nº de parcelas",
}


def classificacao(p, res):
    X = p[list(FEATURES)].fillna(0)
    y = p["insatisfeito"]
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, stratify=y, random_state=SEED)

    base = DummyClassifier(strategy="stratified", random_state=SEED).fit(Xtr, ytr)
    rf = RandomForestClassifier(n_estimators=300, max_depth=12, min_samples_leaf=20,
                                class_weight="balanced", n_jobs=-1, random_state=SEED).fit(Xtr, ytr)
    prob = rf.predict_proba(Xte)[:, 1]
    rep = classification_report(yte, rf.predict(Xte), output_dict=True)
    imp = pd.Series(rf.feature_importances_, index=list(FEATURES)).sort_values()

    res["classificacao"] = {
        "modelo": "Random Forest (300 árvores, class_weight=balanced)",
        "treino": int(len(Xtr)), "teste": int(len(Xte)),
        "auc_modelo": round(roc_auc_score(yte, prob), 3),
        "auc_baseline_aleatorio": round(roc_auc_score(yte, base.predict_proba(Xte)[:, 1]), 3),
        "recall_insatisfeitos": round(rep["1"]["recall"], 3),
        "precisao_insatisfeitos": round(rep["1"]["precision"], 3),
        "acuracia": round(rep["accuracy"], 3),
        "importancia": {FEATURES[k]: round(v, 3) for k, v in imp[::-1].items()},
    }

    top = imp.tail(6)
    fig, ax = plt.subplots(figsize=(10, 5.4))
    cores = [LARANJA if k in ("dias_atraso", "dias_entrega") else AZUL for k in top.index]
    ax.barh([FEATURES[k] for k in top.index], top.values * 100, color=cores, height=0.62)
    for i, v in enumerate(top.values * 100):
        ax.text(v + 0.5, i, f"{v:.0f}%", va="center", fontsize=21, fontweight="bold")
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    ax.tick_params(axis="y", labelsize=20, length=0)
    ax.text(0, -0.1, "importância de cada fator para prever nota 1-2 (Random Forest)",
            transform=ax.transAxes, fontsize=18, color=TXT2)
    salvar(fig, "03_importancia_fatores.png")


# --------------------------------------------------------------------------
def clusterizacao(rfm, res):
    X = np.column_stack([
        np.log1p(rfm["recencia_dias"]),
        np.log1p(rfm["frequencia"]),
        np.log1p(rfm["valor_total"]),
        rfm["nota_media"],
    ])
    Xs = StandardScaler().fit_transform(X)
    amostra = np.random.default_rng(SEED).choice(len(Xs), size=min(15000, len(Xs)), replace=False)
    sil = {}
    for k in range(3, 8):
        km = KMeans(n_clusters=k, n_init=10, random_state=SEED).fit(Xs)
        sil[k] = silhouette_score(Xs[amostra], km.labels_[amostra])
    k = max(sil, key=sil.get)
    km = KMeans(n_clusters=k, n_init=10, random_state=SEED).fit(Xs)
    rfm = rfm.assign(cluster=km.labels_)

    perfil = rfm.groupby("cluster").agg(
        clientes=("customer_unique_id", "size"),
        recencia=("recencia_dias", "median"),
        frequencia=("frequencia", "mean"),
        valor=("valor_total", "median"),
        valor_soma=("valor_total", "sum"),
        nota=("nota_media", "mean"),
    )
    perfil["pct_clientes"] = 100 * perfil["clientes"] / perfil["clientes"].sum()
    perfil["pct_receita"] = 100 * perfil["valor_soma"] / perfil["valor_soma"].sum()

    def nomear(r):
        if r.frequencia > 1.5:
            return "Fiéis (recompram)"
        if r.nota < 2.5:
            return "Insatisfeitos (risco)"
        if r.recencia < perfil["recencia"].median():
            return "Satisfeitos recentes"
        return "Satisfeitos antigos"

    perfil["segmento"] = perfil.apply(nomear, axis=1)
    # Desambigua nomes repetidos
    vistos = Counter()
    nomes = []
    for s in perfil["segmento"]:
        vistos[s] += 1
        nomes.append(s if vistos[s] == 1 else f"{s} ({vistos[s]})")
    perfil["segmento"] = nomes
    perfil = perfil.sort_values("pct_receita", ascending=False)

    res["clusterizacao"] = {
        "algoritmo": "K-Means sobre log(Recência, Frequência, Valor) + nota média, padronizados",
        "silhueta_por_k": {str(a): round(b, 3) for a, b in sil.items()},
        "k_escolhido": int(k),
        "segmentos": [
            {"segmento": r.segmento, "clientes": int(r.clientes), "pct_clientes": round(r.pct_clientes, 1),
             "pct_receita": round(r.pct_receita, 1), "recencia_mediana_dias": int(r.recencia),
             "frequencia_media": round(r.frequencia, 2), "valor_mediano": round(r.valor, 2),
             "nota_media": round(r.nota, 2)}
            for r in perfil.itertuples()
        ],
    }

    # Grafico: % clientes x % receita por segmento (barras agrupadas)
    fig, ax = plt.subplots(figsize=(10, 5.4))
    y = np.arange(len(perfil))
    h = 0.36
    ax.barh(y - h / 2 - 0.01, perfil["pct_clientes"], height=h, color=CINZA, label="% dos clientes")
    ax.barh(y + h / 2 + 0.01, perfil["pct_receita"], height=h, color=AZUL, label="% da receita")
    for i, (c, r) in enumerate(zip(perfil["pct_clientes"], perfil["pct_receita"])):
        ax.text(c + 0.5, i - h / 2, pct(c), va="center", fontsize=18, color=TXT2)
        ax.text(r + 0.5, i + h / 2, pct(r), va="center", fontsize=18, fontweight="bold")
    ax.set_yticks(y, perfil["segmento"], fontsize=21)
    ax.invert_yaxis()
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.legend(frameon=False, loc="lower right", fontsize=18)
    salvar(fig, "04_segmentos_clientes.png")


# --------------------------------------------------------------------------
STOP = set("""a o e de da do das dos em no na nos nas um uma uns umas que com por para pra
pelo pela se ao aos as os eu me meu minha mas foi ja nao sim muito mais ate como esta
estava este essa esse isso isto ele ela eles foram ser ter tem tinha tive sao seu sua
voce vcs vc so ou sem entao qdo quando la aqui ai pois porem tambem fiz fico ficou
""".split())


def normalizar(t):
    t = unicodedata.normalize("NFKD", str(t).lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.findall(r"[a-z]{3,}", t)


def mineracao_texto(p, res):
    com = p.dropna(subset=["review_comment_message"])
    def top(df, n=12):
        c = Counter(w for t in df["review_comment_message"] for w in normalizar(t) if w not in STOP)
        return c.most_common(n), sum(c.values())
    neg, total_neg = top(com[com.review_score <= 2])
    posi, total_pos = top(com[com.review_score >= 4])
    res["texto"] = {
        "comentarios_analisados": int(len(com)),
        "top_insatisfeitos": [w for w, _ in neg],
        "top_satisfeitos": [w for w, _ in posi],
    }
    # % de comentarios negativos que citam entrega/recebimento
    entrega_re = re.compile(r"receb|entreg|chegou|chegar|prazo|aguard")
    negs = com[com.review_score <= 2]["review_comment_message"].str.lower()
    poss = com[com.review_score >= 4]["review_comment_message"].str.lower()
    res["texto"]["neg_citam_entrega_pct"] = round(100 * negs.str.contains(entrega_re).mean(), 1)
    res["texto"]["pos_citam_entrega_pct"] = round(100 * poss.str.contains(entrega_re).mean(), 1)

    palavras = [w for w, _ in neg[:10]][::-1]
    valores = [100 * c / total_neg for w, c in neg[:10]][::-1]
    fig, ax = plt.subplots(figsize=(10, 5.4))
    cores = [LARANJA if re.match(r"receb|entreg|cheg|prazo|aguard", w) else AZUL for w in palavras]
    ax.barh(palavras, valores, color=cores, height=0.62)
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    ax.tick_params(axis="y", labelsize=20, length=0)
    ax.text(0, -0.1, "palavras mais frequentes nos comentários de nota 1-2 (laranja = entrega)",
            transform=ax.transAxes, fontsize=18, color=TXT2)
    salvar(fig, "05_palavras_insatisfeitos.png")


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    p = pd.read_parquet(PROC / "pedidos.parquet")
    rfm = pd.read_parquet(PROC / "clientes_rfm.parquet")
    res = {}
    analise_descritiva(p, res)
    print("descritiva ok")
    classificacao(p, res)
    print("classificacao ok")
    clusterizacao(rfm, res)
    print("clusterizacao ok")
    mineracao_texto(p, res)
    print("texto ok")
    (REPORTS / "resultados.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
