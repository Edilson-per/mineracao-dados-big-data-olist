"""Exporta os dados tratados e os resultados da pesquisa para Excel.

Gera dados_pesquisa_olist.xlsx com as abas:
  Resumo, Insatisfacao por atraso, Pedidos, Clientes RFM, Governanca, Dicionario
As abas de resumo usam formulas sobre a aba Pedidos, entao recalculam no Excel.
"""
import json
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

RAIZ = Path(__file__).resolve().parents[1]
PROC = RAIZ / "data" / "processed"
REPORTS = RAIZ / "reports"
SAIDA = RAIZ / "dados_pesquisa_olist.xlsx"

FONTE = "Arial"
AZUL_ESCURO = "14213D"
F_TITULO = Font(name=FONTE, size=16, bold=True, color=AZUL_ESCURO)
F_SUB = Font(name=FONTE, size=10, italic=True, color="4A5568")
F_HEAD = Font(name=FONTE, size=10, bold=True, color="FFFFFF")
F_NORMAL = Font(name=FONTE, size=10)
F_BOLD = Font(name=FONTE, size=10, bold=True)
FILL_HEAD = PatternFill("solid", fgColor=AZUL_ESCURO)
FILL_SECAO = PatternFill("solid", fgColor="E8EEF7")
LINHA = Border(bottom=Side(style="thin", color="D8D5CC"))

COLUNAS_PEDIDOS = [
    # (coluna no parquet, cabecalho, formato, largura)
    ("order_id", "ID do pedido", "@", 34),
    ("order_purchase_timestamp", "Data da compra", "dd/mm/yyyy hh:mm", 17),
    ("customer_state", "Estado (UF)", "@", 11),
    ("categoria", "Categoria do produto", "@", 26),
    ("valor_itens", "Valor dos itens (R$)", '#,##0.00', 15),
    ("valor_frete", "Frete (R$)", '#,##0.00', 11),
    ("valor_pago", "Valor pago (R$)", '#,##0.00', 14),
    ("qtd_itens", "Qtd. itens", "0", 9),
    ("qtd_vendedores", "Qtd. vendedores", "0", 12),
    ("prazo_prometido_dias", "Prazo prometido (dias)", "0.0", 14),
    ("dias_entrega", "Dias até a entrega", "0.0", 12),
    ("dias_atraso", "Dias de atraso (negativo = adiantado)", "0.0", 18),
    ("atrasou", "Atrasou?", "@", 9),
    ("review_score", "Nota (1 a 5)", "0", 10),
    ("insatisfeito", "Insatisfeito? (nota 1-2)", "@", 14),
    ("tipo_pagamento", "Tipo de pagamento", "@", 14),
    ("parcelas", "Parcelas", "0", 9),
    ("review_comment_message", "Comentário do cliente", "@", 60),
]


def cabecalho(ws, linha, textos):
    for i, t in enumerate(textos, start=1):
        c = ws.cell(row=linha, column=i, value=t)
        c.font, c.fill = F_HEAD, FILL_HEAD
        c.alignment = Alignment(vertical="center", wrap_text=True)


def aba_tabela(wb, nome, df, colunas, nome_tabela):
    ws = wb.create_sheet(nome)
    cabecalho(ws, 1, [c[1] for c in colunas])
    ws.row_dimensions[1].height = 42
    for linha in df[[c[0] for c in colunas]].itertuples(index=False):
        ws.append([None if (isinstance(v, float) and pd.isna(v)) else v for v in linha])
    n = len(df) + 1
    for j, (_, _, fmt, larg) in enumerate(colunas, start=1):
        letra = get_column_letter(j)
        ws.column_dimensions[letra].width = larg
        for (cel,) in ws.iter_rows(min_row=2, max_row=n, min_col=j, max_col=j):
            cel.number_format = fmt
            cel.font = F_NORMAL
    tab = Table(displayName=nome_tabela, ref=f"A1:{get_column_letter(len(colunas))}{n}")
    tab.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
    ws.add_table(tab)
    ws.freeze_panes = "A2"
    return ws


def main():
    p = pd.read_parquet(PROC / "pedidos.parquet")
    rfm = pd.read_parquet(PROC / "clientes_rfm.parquet")
    gov = json.loads((REPORTS / "governanca.json").read_text(encoding="utf-8"))
    res = json.loads((REPORTS / "resultados.json").read_text(encoding="utf-8"))
    tres = json.loads((REPORTS / "tres_vs.json").read_text(encoding="utf-8"))

    p = p.sort_values("order_purchase_timestamp").copy()
    p["atrasou"] = p["atrasou"].map({1: "Sim", 0: "Não"})
    p["insatisfeito"] = p["insatisfeito"].map({1: "Sim", 0: "Não"})
    p["review_score"] = p["review_score"].astype(int)
    p["parcelas"] = p["parcelas"].astype(int)
    # Dias ficam com precisao total (o formato da celula mostra 1 casa decimal),
    # para as faixas de atraso baterem exatamente com a analise em Python.
    p["review_comment_message"] = (p["review_comment_message"].fillna("")
                                   .str.replace(r"[\r\n]+", " ", regex=True).str.strip())

    wb = Workbook()
    wb.remove(wb.active)

    # ---------------- Resumo ----------------
    ws = wb.create_sheet("Resumo")
    ws["A1"] = "Por que o cliente da Olist fica insatisfeito?"
    ws["A1"].font = F_TITULO
    ws["A2"] = ("Projeto de Mineração de Dados com Big Data · dataset público Olist (2016–2018) · "
                "github.com/olist/work-at-olist-data")
    ws["A2"].font = F_SUB

    def secao(linha, titulo):
        ws.cell(row=linha, column=1, value=titulo).font = F_BOLD
        for col in (1, 2, 3):
            ws.cell(row=linha, column=col).fill = FILL_SECAO

    def item(linha, rotulo, valor, fmt="General", obs=""):
        ws.cell(row=linha, column=1, value=rotulo).font = F_NORMAL
        c = ws.cell(row=linha, column=2, value=valor)
        c.font, c.number_format = F_BOLD, fmt
        c.alignment = Alignment(horizontal="right")
        ws.cell(row=linha, column=3, value=obs).font = F_SUB
        for col in (1, 2, 3):
            ws.cell(row=linha, column=col).border = LINHA

    P = "Pedidos"
    r = 4
    secao(r, "Base analisada (calculado a partir da aba Pedidos)"); r += 1
    item(r, "Pedidos analisados", f"=COUNTA({P}!A:A)-1", "#,##0"); r += 1
    item(r, "Nota média", f"=AVERAGE({P}!N:N)", "0.00"); r += 1
    item(r, "% insatisfeitos (nota 1–2)", f'=COUNTIF({P}!O:O,"Sim")/(COUNTA({P}!A:A)-1)', "0.0%"); r += 1
    item(r, "% pedidos atrasados", f'=COUNTIF({P}!M:M,"Sim")/(COUNTA({P}!A:A)-1)', "0.0%"); r += 1
    item(r, "Mediana de dias até a entrega", f"=MEDIAN({P}!K:K)", "0.0"); r += 1
    item(r, "Mediana do prazo prometido (dias)", f"=MEDIAN({P}!J:J)", "0.0"); r += 1
    r += 1
    secao(r, "Atraso × satisfação (principal insight)"); r += 1
    item(r, "% insatisfeitos quando chega no prazo",
         f'=COUNTIFS({P}!M:M,"Não",{P}!O:O,"Sim")/COUNTIF({P}!M:M,"Não")', "0.0%"); r += 1
    item(r, "% insatisfeitos quando atrasa",
         f'=COUNTIFS({P}!M:M,"Sim",{P}!O:O,"Sim")/COUNTIF({P}!M:M,"Sim")', "0.0%"); r += 1
    item(r, "Nota média no prazo", f'=AVERAGEIF({P}!M:M,"Não",{P}!N:N)', "0.00"); r += 1
    item(r, "Nota média com atraso", f'=AVERAGEIF({P}!M:M,"Sim",{P}!N:N)', "0.00"); r += 1
    item(r, "% insatisfeitos com 2+ vendedores",
         f'=COUNTIFS({P}!I:I,">1",{P}!O:O,"Sim")/COUNTIF({P}!I:I,">1")', "0.0%",
         "curiosidade: quase nunca atrasam, mas chegam em partes"); r += 1
    r += 1
    obs_modelo = "resultado do script src/mineracao.py (reports/resultados.json)"
    secao(r, "Modelos de mineração (valores gerados pelo código Python)"); r += 1
    c = res["classificacao"]
    item(r, "Random Forest – AUC", c["auc_modelo"], "0.000", obs_modelo); r += 1
    item(r, "Random Forest – recall dos insatisfeitos", c["recall_insatisfeitos"], "0.0%", obs_modelo); r += 1
    item(r, "Random Forest – precisão dos insatisfeitos", c["precisao_insatisfeitos"], "0.0%", obs_modelo); r += 1
    imp = c["importancia"]
    item(r, "Peso do tempo de entrega no modelo",
         imp["Atraso vs. prazo (dias)"] + imp["Dias até a entrega"], "0%",
         "atraso vs. prazo + dias até a entrega"); r += 1
    k = res["clusterizacao"]
    item(r, "K-Means – nº de grupos (k)", k["k_escolhido"], "0", "escolhido pelo índice de silhueta"); r += 1
    item(r, "K-Means – índice de silhueta", k["silhueta_por_k"][str(k["k_escolhido"])], "0.000", obs_modelo); r += 1
    item(r, "Comentários negativos que citam entrega", res["texto"]["neg_citam_entrega_pct"] / 100, "0.0%",
         "mineração de texto"); r += 1
    r += 1
    secao(r, "Os 3 V’s do dataset bruto"); r += 1
    item(r, "Volume – linhas", tres["volume"]["total_linhas"], "#,##0", "9 arquivos CSV"); r += 1
    item(r, "Volume – tamanho (MB)", tres["volume"]["total_mb"], "0.0"); r += 1
    item(r, "Variedade – tipos de dado", ", ".join(tres["variedade"]["formatos"][:4])); r += 1
    item(r, "Velocidade – pedidos por dia (média)", tres["velocidade"]["pedidos_por_dia_medio"], "0.0",
         f'{tres["velocidade"]["periodo_inicio"]} a {tres["velocidade"]["periodo_fim"]}'); r += 1
    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 52
    ws.sheet_view.showGridLines = False

    # ---------------- Insatisfação por atraso ----------------
    wf = wb.create_sheet("Insatisfacao por atraso")
    wf["A1"] = "Insatisfação por faixa de atraso na entrega"
    wf["A1"].font = F_TITULO
    wf["A2"] = "Dias de atraso = data de entrega − prazo prometido. Negativo = chegou adiantado. Calculado da aba Pedidos."
    wf["A2"].font = F_SUB
    cabecalho(wf, 4, ["Faixa", "De (dias, >)", "Até (dias, ≤)", "Pedidos", "Insatisfeitos",
                      "% insatisfeitos", "Nota média"])
    faixas = [("10+ dias adiantado", -1000, -10), ("3 a 10 dias adiantado", -10, -3),
              ("0 a 3 dias adiantado", -3, 0), ("1 a 3 dias atrasado", 0, 3),
              ("4 a 7 dias atrasado", 3, 7), ("8 a 14 dias atrasado", 7, 14),
              ("15+ dias atrasado", 14, 1000)]
    for i, (nome, de, ate) in enumerate(faixas, start=5):
        wf.cell(row=i, column=1, value=nome)
        wf.cell(row=i, column=2, value=de)
        wf.cell(row=i, column=3, value=ate)
        wf.cell(row=i, column=4, value=f'=COUNTIFS({P}!L:L,">"&B{i},{P}!L:L,"<="&C{i})').number_format = "#,##0"
        wf.cell(row=i, column=5, value=f'=COUNTIFS({P}!L:L,">"&B{i},{P}!L:L,"<="&C{i},{P}!O:O,"Sim")').number_format = "#,##0"
        wf.cell(row=i, column=6, value=f"=IFERROR(E{i}/D{i},0)").number_format = "0.0%"
        wf.cell(row=i, column=7, value=f'=IFERROR(AVERAGEIFS({P}!N:N,{P}!L:L,">"&B{i},{P}!L:L,"<="&C{i}),0)').number_format = "0.00"
        for col in range(1, 8):
            wf.cell(row=i, column=col).font = F_NORMAL
            wf.cell(row=i, column=col).border = LINHA
    t = 5 + len(faixas)
    wf.cell(row=t, column=1, value="Total").font = F_BOLD
    wf.cell(row=t, column=4, value=f"=SUM(D5:D{t-1})").number_format = "#,##0"
    wf.cell(row=t, column=5, value=f"=SUM(E5:E{t-1})").number_format = "#,##0"
    wf.cell(row=t, column=6, value=f"=IFERROR(E{t}/D{t},0)").number_format = "0.0%"
    for col in (4, 5, 6):
        wf.cell(row=t, column=col).font = F_BOLD
    wf.cell(row=t + 2, column=1, value="Os limites -1000 e 1000 apenas representam “sem limite”.").font = F_SUB
    for col, w in zip("ABCDEFG", (24, 12, 12, 11, 13, 15, 12)):
        wf.column_dimensions[col].width = w

    # ---------------- Dados ----------------
    print("Gravando aba Pedidos...")
    aba_tabela(wb, "Pedidos", p, COLUNAS_PEDIDOS, "TabelaPedidos")

    rfm = rfm.sort_values("valor_total", ascending=False).copy()
    rfm["nota_media"] = rfm["nota_media"].round(2)
    print("Gravando aba Clientes RFM...")
    aba_tabela(wb, "Clientes RFM", rfm, [
        ("customer_unique_id", "ID do cliente", "@", 34),
        ("estado", "Estado (UF)", "@", 11),
        ("recencia_dias", "Recência (dias desde a última compra)", "0", 18),
        ("frequencia", "Frequência (nº de pedidos)", "0", 14),
        ("valor_total", "Valor total gasto (R$)", "#,##0.00", 16),
        ("nota_media", "Nota média", "0.00", 11),
    ], "TabelaClientes")

    # ---------------- Governança ----------------
    wg = wb.create_sheet("Governanca")
    wg["A1"] = "Qualidade dos dados: o que foi encontrado e corrigido"
    wg["A1"].font = F_TITULO
    cabecalho(wg, 3, ["Problema encontrado", "Registros", "Tratamento"])
    linhas_gov = [
        ("Pedidos não entregues ou sem data de entrega", gov["pedidos_descartados"], "Descartados"),
        ("Avaliações duplicadas no mesmo pedido", gov["reviews_duplicadas_removidas"], "Mantida a mais recente"),
        ("Produtos sem categoria", gov["nulos_antes"]["produtos_sem_categoria"], "Rotulados como “sem_categoria”"),
        ("Entregas acima de 120 dias (ruído)", gov["outliers_entrega_removidos"], "Removidas"),
        ("Pagamento faltante", gov["pagamentos_faltantes_imputados"], "Preenchido com itens + frete"),
        ("Entrega registrada antes da compra", gov["entregas_antes_da_compra"], "Verificado: nenhuma"),
        ("Avaliações sem comentário escrito", gov["nulos_antes"]["reviews_sem_comentario"], "Mantidas (nota válida)"),
    ]
    for i, linha in enumerate(linhas_gov, start=4):
        for j, v in enumerate(linha, start=1):
            c = wg.cell(row=i, column=j, value=v)
            c.font, c.border = F_NORMAL, LINHA
        wg.cell(row=i, column=2).number_format = "#,##0"
    fim = 4 + len(linhas_gov) + 1
    wg.cell(row=fim, column=1, value="Base final de pedidos").font = F_BOLD
    wg.cell(row=fim, column=2, value=gov["linhas_finais_pedidos"]).number_format = "#,##0"
    wg.cell(row=fim + 1, column=1, value="Clientes únicos").font = F_BOLD
    wg.cell(row=fim + 1, column=2, value=gov["clientes_unicos"]).number_format = "#,##0"
    wg.cell(row=fim + 3, column=1, value="Fonte: reports/governanca.json, gerado por src/tratamento.py").font = F_SUB
    for col, w in zip("ABC", (48, 12, 34)):
        wg.column_dimensions[col].width = w

    # ---------------- Dicionário ----------------
    wd = wb.create_sheet("Dicionario")
    wd["A1"] = "Dicionário de dados (aba Pedidos)"
    wd["A1"].font = F_TITULO
    cabecalho(wd, 3, ["Coluna", "Descrição"])
    descr = {
        "ID do pedido": "Identificador único do pedido na Olist",
        "Data da compra": "Data e hora em que o cliente fez o pedido",
        "Estado (UF)": "Estado do cliente",
        "Categoria do produto": "Categoria do primeiro item do pedido",
        "Valor dos itens (R$)": "Soma do preço dos itens",
        "Frete (R$)": "Soma do frete cobrado",
        "Valor pago (R$)": "Total pago pelo cliente",
        "Qtd. itens": "Número de itens no pedido",
        "Qtd. vendedores": "Número de lojas diferentes no pedido",
        "Prazo prometido (dias)": "Dias entre a compra e a data estimada de entrega",
        "Dias até a entrega": "Dias entre a compra e a entrega real",
        "Dias de atraso (negativo = adiantado)": "Entrega real − data estimada",
        "Atrasou?": "Sim se a entrega passou da data estimada",
        "Nota (1 a 5)": "Nota dada pelo cliente na avaliação",
        "Insatisfeito? (nota 1-2)": "Sim se a nota foi 1 ou 2 (alvo do modelo de classificação)",
        "Tipo de pagamento": "Cartão, boleto, voucher ou débito",
        "Parcelas": "Número máximo de parcelas",
        "Comentário do cliente": "Texto livre escrito na avaliação (vazio se não houver)",
    }
    for i, (k_, v) in enumerate(descr.items(), start=4):
        wd.cell(row=i, column=1, value=k_).font = F_BOLD
        wd.cell(row=i, column=2, value=v).font = F_NORMAL
    wd.column_dimensions["A"].width = 38
    wd.column_dimensions["B"].width = 70

    wb.calculation.fullCalcOnLoad = True
    print("Salvando...")
    wb.save(SAIDA)
    print(f"OK: {SAIDA.name} ({SAIDA.stat().st_size / 1_048_576:.1f} MB)")


if __name__ == "__main__":
    main()
