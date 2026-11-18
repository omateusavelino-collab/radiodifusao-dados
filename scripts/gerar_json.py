"""Le data/outorgas.csv (+ data/fixos/*.csv) e gera data/muns.json, data/prod.json e data/meta.json."""
import datetime as dt, json, os, sys
import pandas as pd

HOJE = pd.Timestamp(os.environ.get("HOJE") or dt.date.today().isoformat())
ANO_INI = 2019
SV = {"RADCOM": 0, "RTVD": 1, "RTRFM": 2, "GTVD": 3, "FM": 4, "OM": 4}          # servico -> coluna do mapa
FN = {"Comercial": 0, "Educativo": 1, "Educativo Público": 1, "Público": 2, "Comunitária": 3}
FLAGS = {  # descricao_processos -> indicador
    "novas_rtv": "Nova Outorga de RTV", "dig": "Digitalização TVD", "rtr": "Nova Outorga de RTR",
    "tv": "Nova Outorga de TV", "radio": "Nova Outorga de Rádio", "prim": "Primarização de Outorga",
    "transf": "Transferência", "renov": "Renovação"}


def ler(caminho, **kw):
    return pd.read_csv(caminho, dtype=str, keep_default_na=False, na_values=[""], **kw) if os.path.exists(caminho) else None


def main():
    d = ler("data/outorgas.csv")
    if d is None:
        sys.exit("data/outorgas.csv nao existe. Rode extrair.py antes.")
    for obrigatoria in ("Fistel", "Ibge"):
        if obrigatoria not in d.columns:
            sys.exit(f"A coluna {obrigatoria} nao veio do BI. Sem ela nao da para contar estacoes por municipio.")
    d = d.drop_duplicates()
    d["dt"] = pd.to_datetime(d["Data_DOU_Documento"], errors="coerce")
    d = d[d.dt.isna() | (d.dt <= HOJE)]
    # Regra da planilha: Status_Valido = Nao quando o estado do canal termina em C0, C5 ou CE-01
    d["valido"] = ~d["Status_state"].fillna("").str.contains(r"-(?:C0|C5|CE-01)$", regex=True)
    for k, v in FLAGS.items():
        d[k] = d["descricao_processos"] == v

    ano_atual = HOJE.year
    anos = list(range(ANO_INI, ano_atual + 1))

    # ---------------- estacoes (mapa) ----------------
    primeira = d.groupby("Fistel").dt.min()
    v = d[d.valido].sort_values(["dt", "id"], kind="stable").groupby("Fistel").tail(1).copy()
    v["ano"] = v.Fistel.map(primeira).dt.year
    partes = [v[["Ibge", "UF", "Municipio", "Servico", "Finalidade", "ano"]]]

    rc = ler("data/fixos/radcom.csv")
    if rc is not None:
        rc = rc.rename(columns={"Município": "Municipio"})
        rc["Servico"] = "RADCOM"
        rc["Finalidade"] = "Comunitária"
        rc["ano"] = pd.to_datetime(rc["Data_DOU_Documento"], errors="coerce").dt.year
        partes.append(rc[["Ibge", "UF", "Municipio", "Servico", "Finalidade", "ano"]])
    else:
        print("AVISO: data/fixos/radcom.csv nao encontrado; rádios comunitárias ficam fora do mapa.")

    a = pd.concat(partes, ignore_index=True)
    a = a[a.Servico.isin(SV)].copy()
    a["s"] = a.Servico.map(SV)
    a["f"] = a.Finalidade.map(FN).fillna(0).astype(int)
    a["y"] = a.ano.fillna(1900).astype(int).clip(lower=ANO_INI - 1) - (ANO_INI - 1)   # 0 = ate 2018
    a["Ibge"] = a.Ibge.astype(str).str.replace(r"\.0$", "", regex=True).str[:7]
    muns = []
    for ib, g in a.groupby("Ibge"):
        nome = g.Municipio.dropna().mode()
        nome = nome.iloc[0] if len(nome) else ib
        if nome.isupper():
            nome = nome.title()
        cont = g.groupby(["s", "f", "y"]).size()
        muns.append([ib, g.UF.iloc[0], nome, [[int(s), int(f), int(y), int(n)] for (s, f, y), n in cont.items()]])
    muns.sort(key=lambda m: m[0])

    # ---------------- producao (evolucao e producao da SERAD) ----------------
    def serie(mask):
        s = d[mask].groupby(d.dt.dt.year).size()
        return [int(s.get(y, 0)) for y in anos]

    def mensal(x):
        g = x.groupby([x.dt.dt.year, x.dt.dt.month]).size()
        return {str(y): [int(g.get((y, m), 0)) for m in range(1, 13)] for y in anos}

    def dtfix(nome):
        t = ler(f"data/fixos/{nome}.csv")
        if t is None:
            return d.iloc[0:0]
        t["dt"] = pd.to_datetime(t["Data_DOU_Documento"], errors="coerce")
        return t[t.dt <= HOJE]

    rad = dtfix("radcom")
    mig = pd.concat([dtfix("migracao_am_fm"), dtfix("migracao_oc_ot_fm")], ignore_index=True)
    P = {"novas": [["Novos canais (RTV)", mensal(d[d.novas_rtv])], ["Digitalizações (RTV e GTV)", mensal(d[d.dig])],
                   ["RTR", mensal(d[d.rtr])], ["Rádios comunitárias", mensal(rad) if len(rad) else {}],
                   ["Rádios", mensal(d[d.radio])], ["TVs (geradoras)", mensal(d[d.tv])]],
         "pos": [["Renovações", mensal(d[d.renov])], ["Transferências", mensal(d[d.transf])],
                 ["Migrações AM-FM", mensal(mig) if len(mig) else {}], ["Primarizações", mensal(d[d.prim])]]}
    ultimo_mes = int(d[d.dt.dt.year == ano_atual].dt.dt.month.max() or 0)
    prod = {"anos": anos, "nov": serie(d.novas_rtv), "dig": serie(d.dig), "P": P,
            "parcial": {"ano": ano_atual, "ate_mes": ultimo_mes}}

    ref_bi = open("data/data_bi.txt").read().strip() if os.path.exists("data/data_bi.txt") else HOJE.strftime("%Y-%m-%d")
    meta = {"data_referencia": ref_bi, "gerado_em": HOJE.strftime("%Y-%m-%d"), "linhas_bi": int(len(d)),
            "estacoes": int(len(a)), "municipios": len(muns), "anos_mapa": ["Até 2018"] + [str(y) for y in anos],
            "rtv_estacoes": int(((a.s == 1)).sum()), "com_estacoes": int(((a.s == 0)).sum())}
    for nome, obj in (("muns", muns), ("prod", prod), ("meta", meta)):
        with open(f"data/{nome}.json", "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    print("OK", meta)


if __name__ == "__main__":
    main()
