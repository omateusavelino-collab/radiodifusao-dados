# Radiodifusão em Números – dados

Atualização diária (6h de Brasília) por GitHub Actions.

- `scripts/extrair.py` baixa a tabela "Outorgas Join" do Power BI público.
- `scripts/gerar_json.py` gera `data/muns.json`, `data/prod.json` e `data/meta.json`.
- `data/fixos/` guarda tabelas que não vêm do BI (rádios comunitárias e migrações). Atualize esses CSVs na mão quando mudarem.
- `scripts/descobrir_esquema.py` lista tabelas e colunas do modelo do BI (use só se uma coluna falhar).
