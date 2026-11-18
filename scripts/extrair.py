"""Extrai a tabela 'Outorgas Join' do Power BI publico e grava data/outorgas.csv.

Uso: python scripts/extrair.py
Variaveis opcionais: PAGINA (linhas por pagina, padrao 500), MIN_LINHAS (trava de seguranca, padrao 30000).
"""
import csv, datetime as dt, json, os, sys, time
import requests

URL = "https://wabi-brazil-south-b-primary-api.analysis.windows.net/public/reports/querydata?synchronous=true"
CHAVE = "2d09cc1b-8d9c-4a05-9ab9-37250382de09"
MODEL_ID = 6865363
ENTIDADE = "Outorgas Join"

# colunas que ja vimos na tabela do relatorio
BASE = ["cnpj", "Entidade", "UF", "Municipio", "Processo", "DescricaoRazao", "Data_DOU_Documento",
        "Servico", "Finalidade", "Status_state", "descricao_processos", "id"]
# colunas que existem na sua planilha organizada, mas nao aparecem na tabela visivel.
# O script tenta pedir; se o BI recusar alguma, ele avisa e segue sem ela.
OPCIONAIS = ["Fistel", "Ibge", "NumDocumento", "CodOrgao", "DescricaoTipoDocumento"]
COLUNAS_DATA = {"Data_DOU_Documento"}

PAGINA = int(os.environ.get("PAGINA", "500"))
MIN_LINHAS = int(os.environ.get("MIN_LINHAS", "30000"))
HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "Accept": "application/json, text/plain, */*",
    "X-PowerBI-ResourceKey": CHAVE,
    "Origin": "https://app.powerbi.com",
    "Referer": "https://app.powerbi.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
}


def ref(c, fonte="o"):
    return {"Column": {"Expression": {"SourceRef": {"Source": fonte}}, "Property": c}}


def montar_corpo(cols, restart=None, entidade=ENTIDADE, filtro=True, ordenar="UF"):
    q = {"Version": 2, "From": [{"Name": "o", "Entity": entidade, "Type": 0}],
         "Select": [dict(ref(c), Name=f"{entidade}.{c}", NativeReferenceName=c) for c in cols]}
    if filtro and "descricao_processos" in cols:
        q["Where"] = [{"Condition": {"Not": {"Expression": {"In": {
            "Expressions": [ref("descricao_processos")],
            "Values": [[{"Literal": {"Value": "null"}}]]}}}}}]
    if ordenar and ordenar in cols:
        q["OrderBy"] = [{"Direction": 1, "Expression": ref(ordenar)}]
    janela = {"Count": PAGINA}
    if restart:
        janela["RestartTokens"] = restart
    cmd = {"Query": q,
           "Binding": {"Primary": {"Groupings": [{"Projections": list(range(len(cols)))}]},
                       "DataReduction": {"DataVolume": 3, "Primary": {"Window": janela}},
                       "Version": 1},
           "ExecutionMetricsKind": 1}
    return {"version": "1.0.0",
            "queries": [{"Query": {"Commands": [{"SemanticQueryDataShapeCommand": cmd}]}, "QueryId": ""}],
            "cancelQueries": [], "modelId": MODEL_ID}


def decodificar(ds, cols):
    """Decodifica o formato compacto (DSR) do Power BI para listas de valores."""
    n = len(cols)
    dicts = ds.get("ValueDicts", {})
    pH = ds.get("PH", [])
    if not pH:
        return []
    linhas_brutas = pH[0].get("DM0", [])
    esquema = None
    anterior = [None] * n
    saida = []
    for row in linhas_brutas:
        if "S" in row:
            esquema = row["S"]
        c = list(row.get("C", []))
        r = row.get("R", 0)
        nulo = row.get("\u00d8", 0)
        atual = []
        k = 0
        for i in range(n):
            if r & (1 << i):
                v = anterior[i]
            elif nulo & (1 << i):
                v = None
            else:
                v = c[k] if k < len(c) else None
                k += 1
                col = esquema[i] if esquema and i < len(esquema) else {}
                if "DN" in col and v is not None:
                    d = dicts.get(col["DN"], [])
                    # indice do dicionario (int); se vier texto/valor literal, mantem como esta
                    if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < len(d):
                        v = d[v]
            atual.append(v)
        anterior = atual
        saida.append(atual)
    return saida


def para_texto(nome, v):
    if v is None:
        return ""
    if nome in COLUNAS_DATA and isinstance(v, (int, float)):
        return (dt.datetime(1970, 1, 1) + dt.timedelta(milliseconds=v)).strftime("%Y-%m-%d")
    return str(v)


def token(nome, v):
    """Reconstroi o 'restart token' a partir da ultima linha, caso o BI nao devolva."""
    if v is None:
        return "null"
    if nome in COLUNAS_DATA:
        d = (dt.datetime(1970, 1, 1) + dt.timedelta(milliseconds=v)).strftime("%Y-%m-%dT00:00:00")
        return f"datetime'{d}'"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def pedir(corpo, tentativas=4):
    ultimo = None
    for t in range(tentativas):
        try:
            r = requests.post(URL, data=json.dumps(corpo), headers=HEADERS, timeout=120)
            if r.status_code == 200:
                return r.json()
            ultimo = f"HTTP {r.status_code}: {r.text[:400]}"
            if r.status_code in (400, 401, 403, 404):
                break
        except Exception as e:  # rede
            ultimo = repr(e)
        time.sleep(3 * (t + 1))
    raise RuntimeError(ultimo)


def ler_resposta(j, cols):
    res = j["results"][0]["result"]["data"]["dsr"]
    if "DataShapes" in res:
        raise RuntimeError("Erro do BI: " + json.dumps(res["DataShapes"])[:500])
    ds = res["DS"][0]
    if "odata.error" in ds:
        raise RuntimeError("Erro do BI: " + json.dumps(ds["odata.error"])[:500])
    return ds


def validar(cols, linhas):
    """Confere se a decodificacao alinhou as colunas (UF com 2 letras, data como numero)."""
    if not linhas:
        raise RuntimeError("O BI devolveu 0 linhas na primeira pagina.")
    erros = 0
    for l in linhas:
        d = dict(zip(cols, l))
        uf = d.get("UF")
        dou = d.get("Data_DOU_Documento")
        if not (isinstance(uf, str) and len(uf) == 2):
            erros += 1
        elif dou is not None and not isinstance(dou, (int, float)):
            erros += 1
    if erros > len(linhas) * 0.05:
        raise RuntimeError(f"Decodificacao desalinhada: {erros}/{len(linhas)} linhas fora do formato. Veja a amostra acima.")


def baixar(cols):
    linhas, restart, vistos = [], None, set()
    for pagina in range(1, 400):
        ds = ler_resposta(pedir(montar_corpo(cols, restart)), cols)
        novas = decodificar(ds, cols)
        if pagina == 1:
            print("  amostra:", novas[:2], flush=True)
            validar(cols, novas)
        linhas.extend(novas)
        print(f"  pagina {pagina}: +{len(novas)} (total {len(linhas)})", flush=True)
        rt = ds.get("RT")
        if not rt and len(novas) >= PAGINA:
            rt = [[token(c, v) for c, v in zip(cols, novas[-1])]]
        if not rt or not novas or (ds.get("IC") and len(novas) < PAGINA):
            break
        chave = json.dumps(rt)
        if chave in vistos:
            print("  aviso: paginacao repetiu, encerrando")
            break
        vistos.add(chave)
        restart = rt
    return linhas


def main():
    os.makedirs("data", exist_ok=True)
    cols = BASE + OPCIONAIS
    try:
        linhas = baixar(cols)
    except RuntimeError as e:
        print("Falhou com colunas opcionais:", e)
        print("Tentando de novo so com as colunas basicas (sem Fistel/Ibge).")
        cols = BASE
        linhas = baixar(cols)
    if len(linhas) < MIN_LINHAS:
        sys.exit(f"Poucas linhas ({len(linhas)} < {MIN_LINHAS}). Nada foi gravado para nao sobrescrever os dados bons.")
    tmp = "data/outorgas.csv.tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for l in linhas:
            w.writerow([para_texto(c, v) for c, v in zip(cols, l)])
    os.replace(tmp, "data/outorgas.csv")
    print(f"OK: {len(linhas)} linhas, colunas: {cols}")
    # data de atualizacao do painel (opcional)
    try:
        ds = ler_resposta(pedir(montar_corpo(["Data Atualização"], entidade="Data Atualização",
                                             filtro=False, ordenar=None)), ["Data Atualização"])
        v = decodificar(ds, ["Data Atualização"])[0][0]
        open("data/data_bi.txt", "w").write(para_texto("Data_DOU_Documento", v))
        print("Data de atualizacao do BI:", open("data/data_bi.txt").read())
    except Exception as e:
        print("Sem data de atualizacao do BI (usando a data da execucao):", str(e)[:150])


if __name__ == "__main__":
    main()
