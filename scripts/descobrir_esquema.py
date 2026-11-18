"""Lista tabelas e colunas do modelo do relatorio (rode so quando precisar descobrir nomes)."""
import json, requests
from extrair import CHAVE, MODEL_ID, HEADERS
url = "https://wabi-brazil-south-b-primary-api.analysis.windows.net/public/reports/conceptualschema"
r = requests.post(url, data=json.dumps({"modelIds": [MODEL_ID], "userPreferredLocale": "pt-BR"}), headers=HEADERS, timeout=60)
print("HTTP", r.status_code)
try:
    j = r.json()
    for s in j.get("schemas", []):
        for e in s["schema"].get("Entities", []):
            print("\nTABELA:", e["Name"])
            for p in e.get("Properties", []):
                print("   ", p["Name"])
except Exception:
    print(r.text[:3000])
